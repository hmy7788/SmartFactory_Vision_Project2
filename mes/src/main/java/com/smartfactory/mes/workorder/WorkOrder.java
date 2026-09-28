package com.smartfactory.mes.workorder;

import java.time.Instant;

import com.smartfactory.mes.recipe.Recipe;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.Version;

/**
 * 작업지시: 어느 검사대에서, 어떤 레시피(버전까지)로, 몇 개.
 * 상태 전이는 이 클래스의 메서드로만 — 서비스가 status 를 직접 바꾸지 않는다.
 */
@Entity
@Table(name = "work_order")
public class WorkOrder {

    @Id
    @Column(name = "work_order_id", length = 40)
    private String workOrderId;

    @Column(name = "station_id", nullable = false, length = 40)
    private String stationId;

    @ManyToOne(fetch = FetchType.EAGER, optional = false)
    @JoinColumn(name = "recipe_pk", nullable = false)
    private Recipe recipe;

    @Column(nullable = false)
    private int quantity;

    @Column(name = "done_qty", nullable = false)
    private int doneQty;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private WorkOrderStatus status;

    @Column(name = "released_at", nullable = false)
    private Instant releasedAt;

    @Column(name = "started_at")
    private Instant startedAt;

    @Column(name = "finished_at")
    private Instant finishedAt;

    @Column(length = 300)
    private String reason;

    /**
     * 낙관적 잠금 — REST 취소와 MQTT 결과가 동시에 같은 작업지시를 바꿀 때 한쪽이 덮어쓰지 않게.
     * Long(null) 이어야 한다: id 를 직접 정하는 엔티티라 Spring Data 는 "version 이 null 인가" 로 새 것인지 판단한다.
     * primitive long(0) 이면 새 작업지시를 merge 로 저장하려다 Hibernate 6.6 에서 OptimisticLockException 이 난다.
     */
    @Version
    private Long lockVersion;

    protected WorkOrder() {
    }

    public WorkOrder(String workOrderId, String stationId, Recipe recipe, int quantity) {
        this(workOrderId, stationId, recipe, quantity, WorkOrderStatus.RELEASED);
    }

    private WorkOrder(String workOrderId, String stationId, Recipe recipe, int quantity, WorkOrderStatus status) {
        this.workOrderId = workOrderId;
        this.stationId = stationId;
        this.recipe = recipe;
        this.quantity = quantity;
        this.status = status;
        this.releasedAt = Instant.now();            // QUEUED 면 '등록 시각', 발행될 때 다시 찍는다
    }

    /** 앞 작업지시가 끝나기를 기다리는 작업지시 (검사대에는 아직 안 보낸다). */
    public static WorkOrder queued(String workOrderId, String stationId, Recipe recipe, int quantity) {
        return new WorkOrder(workOrderId, stationId, recipe, quantity, WorkOrderStatus.QUEUED);
    }

    /** 대기열 맨 앞 → 발행. 발행 시각을 지금으로. */
    public void dispatch() {
        if (status == WorkOrderStatus.QUEUED) {
            status = WorkOrderStatus.RELEASED;
            releasedAt = Instant.now();
        }
    }

    public boolean isActive() {
        return status.isActive();
    }

    /** 검사대가 ACCEPTED. */
    public void accept() {
        if (status == WorkOrderStatus.RELEASED) {
            status = WorkOrderStatus.IN_PROGRESS;
            startedAt = Instant.now();
        }
    }

    /** 제품 1개 (중복 제거된 result). 셌으면 true. */
    public boolean countResult() {
        if (!isActive()) {
            return false;
        }
        accept();                                   // ACCEPTED 가 늦게 와도 결과가 오면 진행 중
        doneQty++;
        if (doneQty >= quantity) {
            status = WorkOrderStatus.COMPLETED;
            finishedAt = Instant.now();
        }
        return true;
    }

    public void reject(String why) {
        if (status == WorkOrderStatus.RELEASED) {
            status = WorkOrderStatus.REJECTED;
            reason = why;
            finishedAt = Instant.now();
        }
    }

    public void cancel(String why) {
        if (status.isOpen()) {                      // 대기 중인 것도 취소할 수 있다
            status = WorkOrderStatus.CANCELLED;
            reason = why;
            finishedAt = Instant.now();
        }
    }

    public String getWorkOrderId() {
        return workOrderId;
    }

    public String getStationId() {
        return stationId;
    }

    public Recipe getRecipe() {
        return recipe;
    }

    public int getQuantity() {
        return quantity;
    }

    public int getDoneQty() {
        return doneQty;
    }

    public WorkOrderStatus getStatus() {
        return status;
    }

    public Instant getReleasedAt() {
        return releasedAt;
    }

    public Instant getStartedAt() {
        return startedAt;
    }

    public Instant getFinishedAt() {
        return finishedAt;
    }

    public String getReason() {
        return reason;
    }
}
