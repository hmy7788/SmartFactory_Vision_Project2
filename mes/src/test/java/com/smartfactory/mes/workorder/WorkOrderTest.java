package com.smartfactory.mes.workorder;

import static org.assertj.core.api.Assertions.assertThat;

import com.smartfactory.mes.recipe.Recipe;

import org.junit.jupiter.api.Test;

/** 상태 전이 규칙만 (스프링 없이). */
class WorkOrderTest {

    private WorkOrder order(int qty) {
        return new WorkOrder("WO-TEST-001", "VIS-01", new Recipe("recipe_1", 1, "[]"), qty);
    }

    @Test
    void resultWithoutAcceptStillStartsAndCompletesAtQuantity() {
        WorkOrder wo = order(2);
        assertThat(wo.countResult()).isTrue();
        assertThat(wo.getStatus()).isEqualTo(WorkOrderStatus.IN_PROGRESS);
        assertThat(wo.getStartedAt()).isNotNull();
        assertThat(wo.countResult()).isTrue();
        assertThat(wo.getStatus()).isEqualTo(WorkOrderStatus.COMPLETED);
        assertThat(wo.countResult()).isFalse();                       // 끝난 뒤엔 세지 않는다
        assertThat(wo.getDoneQty()).isEqualTo(2);
    }

    @Test
    void queuedWaitsUntilDispatchedAndCanBeCancelled() {
        WorkOrder wo = WorkOrder.queued("WO-TEST-002", "VIS-01", new Recipe("recipe_2", 1, "[]"), 3);
        assertThat(wo.getStatus()).isEqualTo(WorkOrderStatus.QUEUED);
        assertThat(wo.isActive()).isFalse();
        assertThat(wo.countResult()).isFalse();                       // 대기 중에 온 결과는 세지 않는다
        wo.dispatch();
        assertThat(wo.getStatus()).isEqualTo(WorkOrderStatus.RELEASED);
        WorkOrder other = WorkOrder.queued("WO-TEST-003", "VIS-01", new Recipe("recipe_3", 1, "[]"), 1);
        other.cancel("필요 없어짐");
        assertThat(other.getStatus()).isEqualTo(WorkOrderStatus.CANCELLED);
        other.dispatch();                                             // 취소된 것은 발행되지 않는다
        assertThat(other.getStatus()).isEqualTo(WorkOrderStatus.CANCELLED);
    }

    @Test
    void rejectOnlyBeforeAcceptAndCancelOnlyWhileActive() {
        WorkOrder wo = order(1);
        wo.accept();
        wo.reject("late");
        assertThat(wo.getStatus()).isEqualTo(WorkOrderStatus.IN_PROGRESS);
        wo.cancel("stop");
        assertThat(wo.getStatus()).isEqualTo(WorkOrderStatus.CANCELLED);
        wo.cancel("again");
        assertThat(wo.getReason()).isEqualTo("stop");
    }
}
