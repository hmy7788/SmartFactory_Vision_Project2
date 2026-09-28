package com.smartfactory.mes.message;

import java.time.OffsetDateTime;

import com.fasterxml.jackson.annotation.JsonProperty;

/** 검사대 → MES: ACCEPTED / REJECTED / COMPLETED / CANCELLED */
public record AckMessage(
        @JsonProperty("schema") String schema,
        @JsonProperty("event_id") String eventId,
        @JsonProperty("station_id") String stationId,
        @JsonProperty("type") String type,
        @JsonProperty("work_order_id") String workOrderId,
        @JsonProperty("done") Integer done,
        @JsonProperty("quantity") Integer quantity,
        @JsonProperty("reason") String reason,
        @JsonProperty("occurred_at") OffsetDateTime occurredAt) {
}
