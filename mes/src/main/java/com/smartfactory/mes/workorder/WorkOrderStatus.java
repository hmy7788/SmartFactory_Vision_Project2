package com.smartfactory.mes.workorder;

import java.util.EnumSet;
import java.util.Set;

/**
 * QUEUED(대기열 — 앞 작업지시가 끝나면 MES 가 자동 발행)
 *   → RELEASED(발행, 검사대 아직 못 받음) → IN_PROGRESS(검사대가 ACCEPTED) → COMPLETED(수량 채움)
 *                                        ↘ CANCELLED(MES 가 취소)     REJECTED(검사대가 거절)
 */
public enum WorkOrderStatus {
    QUEUED, RELEASED, IN_PROGRESS, COMPLETED, CANCELLED, REJECTED;

    /** 한 검사대에 이 상태인 작업지시는 하나만 (= 검사대에 실려 있는 것). */
    public static Set<WorkOrderStatus> active() {
        return EnumSet.of(RELEASED, IN_PROGRESS);
    }

    public boolean isActive() {
        return this == RELEASED || this == IN_PROGRESS;
    }

    /** 아직 끝나지 않음 (대기 포함) — 취소할 수 있다. */
    public boolean isOpen() {
        return this == QUEUED || isActive();
    }
}
