package com.smartfactory.mes.common;

import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/**
 * DB 커밋이 끝난 뒤에 실행한다 (트랜잭션이 없으면 바로).
 * MQTT 발행을 커밋 전에 하면, 롤백됐는데 설비는 작업지시를 받은 상태가 된다 — 그래서 발행은 항상 커밋 뒤.
 */
public final class AfterCommit {
    private AfterCommit() {
    }

    public static void run(Runnable action) {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    action.run();
                }
            });
        } else {
            action.run();
        }
    }
}
