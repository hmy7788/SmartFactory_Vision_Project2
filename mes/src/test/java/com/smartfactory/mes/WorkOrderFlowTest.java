package com.smartfactory.mes;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartfactory.mes.common.ApiException;
import com.smartfactory.mes.message.Placement;
import com.smartfactory.mes.mqtt.StationMessageHandler;
import com.smartfactory.mes.recipe.RecipeService;
import com.smartfactory.mes.result.ProductResultRepository;
import com.smartfactory.mes.station.StationRepository;
import com.smartfactory.mes.workorder.WorkOrder;
import com.smartfactory.mes.workorder.WorkOrderService;
import com.smartfactory.mes.workorder.WorkOrderStatus;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

/**
 * 작업지시 한 바퀴: 발행(retained) → 검사대 ACCEPTED → 결과(중복 포함) → 수량 채움 → retained 비움.
 * 검사대 메시지는 web/mes_link.py 가 실제로 만드는 모양 그대로 (docs/mes_mqtt.md).
 */
@SpringBootTest(properties = {
        "mes.mqtt.enabled=false",
        "spring.datasource.url=jdbc:h2:mem:mestest;DB_CLOSE_DELAY=-1"})
class WorkOrderFlowTest {

    @TestConfiguration
    static class Config {
        @Bean
        @Primary
        RecordingGateway recordingGateway() {
            return new RecordingGateway();
        }
    }

    @Autowired
    WorkOrderService service;
    @Autowired
    RecipeService recipes;
    @Autowired
    StationMessageHandler handler;
    @Autowired
    RecordingGateway gateway;
    @Autowired
    ObjectMapper json;
    @Autowired
    ProductResultRepository results;
    @Autowired
    StationRepository stations;

    @Test
    void releasePublishesRetainedWorkOrderWithRecipeAndQueuesASecondOne() throws Exception {
        WorkOrder wo = service.release("T-1", "recipe_1", null, 3);
        RecordingGateway.Msg msg = gateway.last("factory/T-1/workorder");
        assertThat(msg.retained()).isTrue();
        assertThat(msg.qos()).isEqualTo(1);
        JsonNode m = json.readTree(msg.payload());
        assertThat(m.get("schema").asText()).isEqualTo("pokayoke/1");
        assertThat(m.get("work_order_id").asText()).isEqualTo(wo.getWorkOrderId()).startsWith("WO-");
        assertThat(m.get("quantity").asInt()).isEqualTo(3);
        assertThat(m.get("recipe").get("recipe_id").asText()).isEqualTo("recipe_1");
        assertThat(m.get("recipe").get("version").asInt()).isEqualTo(1);
        assertThat(m.get("recipe").get("placements").get(0).get("mother_hole").asInt()).isEqualTo(1);

        WorkOrder second = service.release("T-1", "recipe_2", null, 1);          // 진행 중이면 막지 않고 대기열로
        assertThat(second.getStatus()).isEqualTo(WorkOrderStatus.QUEUED);
        JsonNode again = json.readTree(gateway.last("factory/T-1/workorder").payload());
        assertThat(again.get("work_order_id").asText()).isEqualTo(wo.getWorkOrderId());   // 검사대에는 여전히 첫 것
        assertThat(again.get("next").get(0).get("work_order_id").asText()).isEqualTo(second.getWorkOrderId());
    }

    @Test
    void batchRunsLinesInOrderAndAdvancesWhenQuantityIsReached() throws Exception {
        List<WorkOrder> wos = service.releaseAll("T-6", List.of(
                new WorkOrderService.Line("recipe_1", null, 2), new WorkOrderService.Line("recipe_2", null, 3)));
        WorkOrder a = wos.get(0), b = wos.get(1);
        assertThat(service.get(a.getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.RELEASED);
        assertThat(service.get(b.getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.QUEUED);
        JsonNode m = json.readTree(gateway.last("factory/T-6/workorder").payload());
        assertThat(m.get("work_order_id").asText()).isEqualTo(a.getWorkOrderId());
        assertThat(m.get("next").get(0).get("recipe_id").asText()).isEqualTo("recipe_2");
        assertThat(m.get("next").get(0).get("quantity").asInt()).isEqualTo(3);

        handler.handle("factory/T-6/ack", ack(a, "ACCEPTED", null));
        handler.handle("factory/T-6/result", result(a, 1, List.of()));
        assertThat(service.get(b.getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.QUEUED);   // 아직 1/2
        handler.handle("factory/T-6/result", result(a, 2, List.of()));
        assertThat(service.get(a.getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.COMPLETED);
        assertThat(service.get(b.getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.RELEASED); // 다음 줄 자동 발행
        JsonNode m2 = json.readTree(gateway.last("factory/T-6/workorder").payload());
        assertThat(m2.get("work_order_id").asText()).isEqualTo(b.getWorkOrderId());
        assertThat(m2.get("recipe").get("recipe_id").asText()).isEqualTo("recipe_2");
        assertThat(m2.get("next").size()).isEqualTo(0);

        handler.handle("factory/T-6/ack", ack(b, "ACCEPTED", null));
        for (int i = 1; i <= 3; i++) {
            handler.handle("factory/T-6/result", result(b, i, List.of()));
        }
        assertThat(service.get(b.getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.COMPLETED);
        assertThat(gateway.last("factory/T-6/workorder").payload()).isEmpty();      // 대기열 끝 — retained 비움
    }

    @Test
    void batchWithAnUnknownRecipeRegistersNothing() {
        assertThatThrownBy(() -> service.releaseAll("T-7", List.of(
                new WorkOrderService.Line("recipe_1", null, 1), new WorkOrderService.Line("no_such_recipe", null, 1))))
                .isInstanceOf(ApiException.class);
        assertThat(service.list("T-7").size()).isEqualTo(0);
    }

    @Test
    void cancellingTheRunningOrderStartsTheNextOneAndCancellingAQueuedOneDoesNot() {
        List<WorkOrder> wos = service.releaseAll("T-8", List.of(new WorkOrderService.Line("recipe_1", null, 1),
                new WorkOrderService.Line("recipe_2", null, 1), new WorkOrderService.Line("recipe_3", null, 1)));
        service.cancel(wos.get(2).getWorkOrderId(), null);                          // 대기 중인 것 취소
        assertThat(service.get(wos.get(2).getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.CANCELLED);
        assertThat(service.get(wos.get(0).getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.RELEASED);
        service.cancel(wos.get(0).getWorkOrderId(), null);                          // 진행 중인 것 취소 → 다음 줄
        assertThat(service.get(wos.get(1).getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.RELEASED);
        assertThat(gateway.last("factory/T-8/workorder").payload()).contains(wos.get(1).getWorkOrderId());
    }

    @Test
    void rejectionMovesOnButBusyDoesNot() {
        List<WorkOrder> wos = service.releaseAll("T-9", List.of(new WorkOrderService.Line("recipe_1", null, 1),
                new WorkOrderService.Line("recipe_2", null, 1), new WorkOrderService.Line("recipe_3", null, 1)));
        handler.handle("factory/T-9/ack", ack(wos.get(0), "REJECTED", "INVALID_RECIPE: test"));
        assertThat(service.get(wos.get(1).getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.RELEASED);
        handler.handle("factory/T-9/ack", ack(wos.get(1), "REJECTED", "BUSY: WO-OLD 진행 중 (1/3)"));
        assertThat(service.get(wos.get(2).getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.QUEUED);   // 사람이 볼 때까지 멈춤
    }

    @Test
    void resultsAreCountedOnceAndCompletionClearsRetained() {
        WorkOrder wo = service.release("T-2", "recipe_2", null, 2);
        String id = wo.getWorkOrderId();
        handler.handle("factory/T-2/ack", ack(wo, "ACCEPTED", null));
        assertThat(service.get(id).getStatus()).isEqualTo(WorkOrderStatus.IN_PROGRESS);

        String first = result(wo, 1, List.of("WRONG_BOLT:H1"));
        handler.handle("factory/T-2/result", first);
        handler.handle("factory/T-2/result", first);                 // QoS 1 재전송 — 두 번 세면 안 된다
        assertThat(service.get(id).getDoneQty()).isEqualTo(1);

        handler.handle("factory/T-2/result", result(wo, 2, List.of()));
        WorkOrder done = service.get(id);
        assertThat(done.getStatus()).isEqualTo(WorkOrderStatus.COMPLETED);
        assertThat(done.getDoneQty()).isEqualTo(2);
        assertThat(results.countByWorkOrderId(id)).isEqualTo(2);
        assertThat(service.results(id).get(0).getNgCodes()).isEqualTo("WRONG_BOLT:H1");
        assertThat(service.results(id).get(0).isFirstPass()).isFalse();
        assertThat(gateway.last("factory/T-2/workorder").payload()).isEmpty();   // retained 비움

        handler.handle("factory/T-2/result", result(wo, 3, List.of()));          // 다 찬 뒤에 온 것 — 기록만, 수량 그대로
        assertThat(service.get(id).getDoneQty()).isEqualTo(2);
    }

    @Test
    void cancelClearsRetainedAndNextReleaseIsAllowed() {
        WorkOrder wo = service.release("T-3", "recipe_3", null, 5);
        service.cancel(wo.getWorkOrderId(), null);
        assertThat(service.get(wo.getWorkOrderId()).getStatus()).isEqualTo(WorkOrderStatus.CANCELLED);
        assertThat(gateway.last("factory/T-3/workorder").payload()).isEmpty();
        WorkOrder next = service.release("T-3", "recipe_3", null, 1);
        assertThat(gateway.last("factory/T-3/workorder").payload()).contains(next.getWorkOrderId());
    }

    @Test
    void rejectedByStationIsWithdrawn() {
        WorkOrder wo = service.release("T-5", "recipe_1", null, 1);
        handler.handle("factory/T-5/ack", ack(wo, "REJECTED", "INVALID_RECIPE: test"));
        WorkOrder after = service.get(wo.getWorkOrderId());
        assertThat(after.getStatus()).isEqualTo(WorkOrderStatus.REJECTED);
        assertThat(after.getReason()).contains("INVALID_RECIPE");
        assertThat(gateway.last("factory/T-5/workorder").payload()).isEmpty();
    }

    @Test
    void recipeRulesMatchTheStation() {
        assertThatThrownBy(() -> recipes.create("bad", List.of(new Placement(5, "bolt_1", "part_2hole"))))
                .hasMessageContaining("H5");
        assertThatThrownBy(() -> recipes.create("bad", List.of(new Placement(1, "bolt_1", "part_2hole"),
                new Placement(1, "bolt_2", "part_3hole")))).hasMessageContaining("두 번");
        recipes.create("recipe_x", List.of(new Placement(1, "bolt_1", "part_2hole")));
        int v = recipes.create("recipe_x", List.of(new Placement(2, "bolt_2", "part_3hole"))).getVersion();
        assertThat(v).isEqualTo(2);                                  // 고치지 않고 버전을 올린다
        assertThat(recipes.resolve("recipe_x", 1).getVersion()).isEqualTo(1);
        assertThat(recipes.resolve("recipe_x", null).getVersion()).isEqualTo(2);
    }

    @Test
    void stationStateFollowsStatusTopicIncludingLwt() {
        handler.handle("factory/T-4/status", "{\"schema\":\"pokayoke/1\",\"station_id\":\"T-4\",\"state\":\"online\","
                + "\"occurred_at\":\"2026-09-28T09:00:00+09:00\"}");
        assertThat(stations.findById("T-4").orElseThrow().getState()).isEqualTo("online");
        handler.handle("factory/T-4/status", "{\"schema\":\"pokayoke/1\",\"station_id\":\"T-4\",\"state\":\"offline\"}");
        assertThat(stations.findById("T-4").orElseThrow().getState()).isEqualTo("offline");
        handler.handle("factory/T-4/status", "not json");            // 깨진 메시지 — 예외 없이 무시
        handler.handle("factory/T-4/status", "");                    // retained 비움
    }

    private String ack(WorkOrder wo, String type, String reason) {
        return """
                {"schema": "pokayoke/1", "event_id": "%s", "station_id": "%s", "type": "%s",
                 "work_order_id": "%s", "done": 0, "quantity": %d, "reason": %s,
                 "occurred_at": "2026-09-28T09:00:02+09:00"}
                """.formatted(UUID.randomUUID(), wo.getStationId(), type, wo.getWorkOrderId(), wo.getQuantity(),
                reason == null ? "null" : "\"" + reason + "\"");
    }

    /** web/mes_link.py product_completed() 가 만드는 모양 그대로 (null 필드 포함). */
    private String result(WorkOrder wo, int seq, List<String> ngCodes) {
        String codes = ngCodes.isEmpty() ? "[]" : "[\"" + String.join("\", \"", ngCodes) + "\"]";
        return """
                {"schema": "pokayoke/1", "event_id": "%s", "station_id": "%s",
                 "work_order_id": "%s", "product_seq": %d, "local_product_id": %d,
                 "recipe_id": "%s", "recipe_version": %d,
                 "first_pass": %s, "ng_count": %d, "material_ng_count": 0, "hold_count": 2,
                 "ng_codes": %s, "cycle_ms": 42100, "materials_ms": null, "assembly_ms": 32300,
                 "occurred_at": "2026-09-28T09:12:03+09:00"}
                """.formatted(UUID.randomUUID(), wo.getStationId(), wo.getWorkOrderId(), seq, 100 + seq,
                wo.getRecipe().getRecipeId(), wo.getRecipe().getVersion(), ngCodes.isEmpty(), ngCodes.size(), codes);
    }
}
