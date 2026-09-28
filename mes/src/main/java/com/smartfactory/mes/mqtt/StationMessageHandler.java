package com.smartfactory.mes.mqtt;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartfactory.mes.message.AckMessage;
import com.smartfactory.mes.message.ResultMessage;
import com.smartfactory.mes.message.StatusMessage;
import com.smartfactory.mes.station.StationService;
import com.smartfactory.mes.workorder.WorkOrderPublisher;
import com.smartfactory.mes.workorder.WorkOrderService;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 설비가 보낸 메시지 → 서비스. 토픽 모양: {prefix}/{station}/{ack|result|status}
 * 설비 종류가 늘어도(SFaaS 등) 토픽 규칙이 같으면 여기에 case 만 늘린다.
 */
@Component
public class StationMessageHandler {

    private static final Logger log = LoggerFactory.getLogger(StationMessageHandler.class);

    private final ObjectMapper json;
    private final WorkOrderService workOrders;
    private final StationService stations;
    private final MqttProperties props;

    public StationMessageHandler(MqttGateway gateway, ObjectMapper json, WorkOrderService workOrders,
                                 StationService stations, WorkOrderPublisher publisher, MqttProperties props) {
        this.json = json;
        this.workOrders = workOrders;
        this.stations = stations;
        this.props = props;
        gateway.setInboundListener(this::handle);
        gateway.setConnectedListener(publisher::syncAll);
    }

    public void handle(String topic, String payload) {
        String[] parts = topic.split("/");
        if (parts.length != 3 || !parts[0].equals(props.topicPrefix())) {
            log.warn("모르는 토픽 {}", topic);
            return;
        }
        String station = parts[1];
        String kind = parts[2];
        if (payload == null || payload.isBlank()) {
            return;                                  // retained 비움 등
        }
        try {
            switch (kind) {
                case "ack" -> workOrders.onAck(station, json.readValue(payload, AckMessage.class));
                case "result" -> workOrders.onResult(station, json.readValue(payload, ResultMessage.class));
                case "status" -> stations.onStatus(station, json.readValue(payload, StatusMessage.class));
                default -> log.debug("무시 {}", topic);
            }
        } catch (JsonProcessingException e) {
            log.warn("잘못된 메시지 {} : {}", topic, e.getOriginalMessage());
        }
    }
}
