package com.smartfactory.mes.result;

import java.time.Instant;
import java.time.OffsetDateTime;

import com.smartfactory.mes.message.ResultMessage;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

/** 제품 1개의 검사 실적. event_id unique = 같은 보고가 두 번 와도 한 줄 (멱등의 마지막 방어선). */
@Entity
@Table(name = "product_result",
        uniqueConstraints = @UniqueConstraint(name = "uk_product_result_event", columnNames = "event_id"),
        indexes = @Index(name = "ix_product_result_wo", columnList = "work_order_id"))
public class ProductResult {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "event_id", nullable = false, length = 64)
    private String eventId;

    @Column(name = "work_order_id", length = 40)
    private String workOrderId;

    @Column(name = "station_id", nullable = false, length = 40)
    private String stationId;

    @Column(name = "product_seq")
    private int productSeq;

    @Column(name = "local_product_id")
    private Long localProductId;

    @Column(name = "recipe_id", length = 50)
    private String recipeId;

    @Column(name = "recipe_version")
    private int recipeVersion;

    @Column(name = "first_pass")
    private boolean firstPass;

    @Column(name = "ng_count")
    private int ngCount;

    @Column(name = "material_ng_count")
    private int materialNgCount;

    @Column(name = "hold_count")
    private int holdCount;

    @Column(name = "ng_codes", length = 500)
    private String ngCodes;

    @Column(name = "cycle_ms")
    private Long cycleMs;

    @Column(name = "materials_ms")
    private Long materialsMs;

    @Column(name = "assembly_ms")
    private Long assemblyMs;

    @Column(name = "occurred_at")
    private OffsetDateTime occurredAt;

    @Column(name = "received_at", nullable = false)
    private Instant receivedAt;

    protected ProductResult() {
    }

    public static ProductResult of(String stationId, ResultMessage m) {
        ProductResult r = new ProductResult();
        r.eventId = m.eventId();
        r.workOrderId = m.workOrderId();
        r.stationId = stationId;
        r.productSeq = m.productSeq();
        r.localProductId = m.localProductId();
        r.recipeId = m.recipeId();
        r.recipeVersion = m.recipeVersion();
        r.firstPass = m.firstPass();
        r.ngCount = m.ngCount();
        r.materialNgCount = m.materialNgCount();
        r.holdCount = m.holdCount();
        r.ngCodes = m.ngCodes() == null ? "" : String.join(",", m.ngCodes());
        r.cycleMs = m.cycleMs();
        r.materialsMs = m.materialsMs();
        r.assemblyMs = m.assemblyMs();
        r.occurredAt = m.occurredAt();
        r.receivedAt = Instant.now();
        return r;
    }

    public String getEventId() {
        return eventId;
    }

    public String getWorkOrderId() {
        return workOrderId;
    }

    public String getStationId() {
        return stationId;
    }

    public int getProductSeq() {
        return productSeq;
    }

    public String getRecipeId() {
        return recipeId;
    }

    public int getRecipeVersion() {
        return recipeVersion;
    }

    public boolean isFirstPass() {
        return firstPass;
    }

    public int getNgCount() {
        return ngCount;
    }

    public String getNgCodes() {
        return ngCodes;
    }

    public Long getCycleMs() {
        return cycleMs;
    }

    public OffsetDateTime getOccurredAt() {
        return occurredAt;
    }
}
