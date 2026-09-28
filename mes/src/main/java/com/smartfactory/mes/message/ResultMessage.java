package com.smartfactory.mes.message;

import java.time.OffsetDateTime;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

/** 검사대 → MES: 제품 1개 완료 (작업자가 PASS 에서 [작업 완료]) */
public record ResultMessage(
        @JsonProperty("schema") String schema,
        @JsonProperty("event_id") String eventId,
        @JsonProperty("station_id") String stationId,
        @JsonProperty("work_order_id") String workOrderId,
        @JsonProperty("product_seq") int productSeq,
        @JsonProperty("local_product_id") Long localProductId,
        @JsonProperty("recipe_id") String recipeId,
        @JsonProperty("recipe_version") int recipeVersion,
        @JsonProperty("first_pass") boolean firstPass,
        @JsonProperty("ng_count") int ngCount,
        @JsonProperty("material_ng_count") int materialNgCount,
        @JsonProperty("hold_count") int holdCount,
        @JsonProperty("ng_codes") List<String> ngCodes,
        @JsonProperty("cycle_ms") Long cycleMs,
        @JsonProperty("materials_ms") Long materialsMs,
        @JsonProperty("assembly_ms") Long assemblyMs,
        @JsonProperty("occurred_at") OffsetDateTime occurredAt) {
}
