package com.smartfactory.mes.message;

import java.time.OffsetDateTime;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * MES → 검사대, 토픽 {prefix}/{station}/workorder (retained, QoS 1)
 * next: 이 검사대의 대기열 (보여 주기용 — 검사대는 지금 것만 한다. 다음 것은 MES 가 이 토픽으로 다시 싣는다)
 */
public record WorkOrderMessage(
        @JsonProperty("schema") String schema,
        @JsonProperty("work_order_id") String workOrderId,
        @JsonProperty("station_id") String stationId,
        @JsonProperty("recipe") RecipePayload recipe,
        @JsonProperty("quantity") int quantity,
        @JsonProperty("released_at") OffsetDateTime releasedAt,
        @JsonProperty("next") List<Next> next) {

    public static final String SCHEMA = "pokayoke/1";

    public record Next(
            @JsonProperty("work_order_id") String workOrderId,
            @JsonProperty("recipe_id") String recipeId,
            @JsonProperty("quantity") int quantity) {
    }
}
