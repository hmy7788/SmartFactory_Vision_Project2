package com.smartfactory.mes.message;

import java.time.OffsetDateTime;

import com.fasterxml.jackson.annotation.JsonProperty;

/** 검사대 → MES (retained): online / offline(LWT — 브로커가 대신 보냄) */
public record StatusMessage(
        @JsonProperty("schema") String schema,
        @JsonProperty("station_id") String stationId,
        @JsonProperty("state") String state,
        @JsonProperty("occurred_at") OffsetDateTime occurredAt) {
}
