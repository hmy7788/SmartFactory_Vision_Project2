package com.smartfactory.mes.station;

import java.time.Instant;
import java.time.OffsetDateTime;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** 검사대 ack 기록 (ACCEPTED/REJECTED/COMPLETED/CANCELLED). event_id 가 PK — 두 번 오면 두 번째는 저장되지 않는다. */
@Entity
@Table(name = "station_event")
public class StationEvent {

    @Id
    @Column(name = "event_id", length = 64)
    private String eventId;

    @Column(name = "station_id", nullable = false, length = 40)
    private String stationId;

    @Column(name = "ack_type", length = 20)
    private String ackType;

    @Column(name = "work_order_id", length = 40)
    private String workOrderId;

    @Column(length = 300)
    private String reason;

    @Column(name = "occurred_at")
    private OffsetDateTime occurredAt;

    @Column(name = "received_at", nullable = false)
    private Instant receivedAt;

    protected StationEvent() {
    }

    public StationEvent(String eventId, String stationId, String ackType, String workOrderId, String reason,
                        OffsetDateTime occurredAt) {
        this.eventId = eventId;
        this.stationId = stationId;
        this.ackType = ackType;
        this.workOrderId = workOrderId;
        this.reason = reason;
        this.occurredAt = occurredAt;
        this.receivedAt = Instant.now();
    }

    public String getEventId() {
        return eventId;
    }

    public String getAckType() {
        return ackType;
    }

    public String getWorkOrderId() {
        return workOrderId;
    }

    public String getReason() {
        return reason;
    }
}
