package com.smartfactory.mes.station;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** 설비(검사대) 의 연결 상태. status 토픽(retained, LWT) 으로만 바뀐다. */
@Entity
@Table(name = "station")
public class Station {

    @Id
    @Column(name = "station_id", length = 40)
    private String stationId;

    @Column(name = "conn_state", nullable = false, length = 20)
    private String state;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected Station() {
    }

    public Station(String stationId) {
        this.stationId = stationId;
        this.state = "unknown";
        this.updatedAt = Instant.now();
    }

    public void update(String newState) {
        this.state = newState;
        this.updatedAt = Instant.now();
    }

    public String getStationId() {
        return stationId;
    }

    public String getState() {
        return state;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
