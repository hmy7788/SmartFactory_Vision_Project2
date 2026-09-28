package com.smartfactory.mes.workorder;

import java.time.ZoneId;
import java.util.Set;
import java.util.TreeSet;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartfactory.mes.message.WorkOrderMessage;
import com.smartfactory.mes.mqtt.MqttGateway;
import com.smartfactory.mes.mqtt.MqttProperties;
import com.smartfactory.mes.recipe.RecipeService;
import com.smartfactory.mes.station.StationRepository;

import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * 검사대의 workorder 토픽(retained) 을 DB 와 같게 맞춘다 — "지금 이 검사대가 할 일" 을 통째로 다시 싣는 방식.
 * 한 번 발행을 놓쳐도(브로커 끊김) 다음 맞추기(재연결·다음 변경) 에서 바로잡힌다.
 */
@Component
public class WorkOrderPublisher {

    private final MqttGateway gateway;
    private final ObjectMapper json;
    private final MqttProperties props;
    private final RecipeService recipes;
    private final WorkOrderRepository orders;
    private final StationRepository stations;

    public WorkOrderPublisher(MqttGateway gateway, ObjectMapper json, MqttProperties props, RecipeService recipes,
                              WorkOrderRepository orders, StationRepository stations) {
        this.gateway = gateway;
        this.json = json;
        this.props = props;
        this.recipes = recipes;
        this.orders = orders;
        this.stations = stations;
    }

    /** 이 검사대의 진행 중 작업지시를 싣거나, 없으면 retained 를 비운다. 커밋 뒤에 불리므로 새 트랜잭션에서 읽는다. */
    @Transactional(propagation = Propagation.REQUIRES_NEW, readOnly = true)
    public void syncStation(String stationId) {
        String topic = props.topic(stationId, "workorder");
        orders.findFirstByStationIdAndStatusIn(stationId, WorkOrderStatus.active())
                .ifPresentOrElse(wo -> gateway.publish(topic, toJson(message(wo)), 1, true),
                        () -> gateway.publish(topic, "", 1, true));
    }

    /** MQTT 연결(재연결) 때 — 아는 검사대 전부. */
    @Transactional(propagation = Propagation.REQUIRES_NEW, readOnly = true)
    public void syncAll() {
        Set<String> ids = new TreeSet<>(orders.findStationIds());
        stations.findAll().forEach(s -> ids.add(s.getStationId()));
        ids.forEach(this::syncStationInCurrentTx);
    }

    private void syncStationInCurrentTx(String stationId) {
        String topic = props.topic(stationId, "workorder");
        orders.findFirstByStationIdAndStatusIn(stationId, WorkOrderStatus.active())
                .ifPresentOrElse(wo -> gateway.publish(topic, toJson(message(wo)), 1, true),
                        () -> gateway.publish(topic, "", 1, true));
    }

    public WorkOrderMessage message(WorkOrder wo) {
        var next = orders.findByStationIdAndStatusOrderByWorkOrderIdAsc(wo.getStationId(), WorkOrderStatus.QUEUED).stream()
                .map(q -> new WorkOrderMessage.Next(q.getWorkOrderId(), q.getRecipe().getRecipeId(), q.getQuantity()))
                .toList();
        return new WorkOrderMessage(WorkOrderMessage.SCHEMA, wo.getWorkOrderId(), wo.getStationId(),
                recipes.payload(wo.getRecipe()), wo.getQuantity(),
                wo.getReleasedAt().atZone(ZoneId.systemDefault()).toOffsetDateTime(), next);
    }

    private String toJson(Object value) {
        try {
            return json.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }
}
