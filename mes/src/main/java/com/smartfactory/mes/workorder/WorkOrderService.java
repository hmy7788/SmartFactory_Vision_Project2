package com.smartfactory.mes.workorder;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;

import com.smartfactory.mes.common.AfterCommit;
import com.smartfactory.mes.common.ApiException;
import com.smartfactory.mes.message.AckMessage;
import com.smartfactory.mes.message.ResultMessage;
import com.smartfactory.mes.recipe.Recipe;
import com.smartfactory.mes.recipe.RecipeService;
import com.smartfactory.mes.result.ProductResult;
import com.smartfactory.mes.result.ProductResultRepository;
import com.smartfactory.mes.station.StationEvent;
import com.smartfactory.mes.station.StationEventRepository;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 작업지시의 발행·취소(REST) 와 검사대 보고(MQTT) 를 처리한다.
 *
 * 판단 기준:
 *  - 수량의 정답은 MES: 중복 제거된 result 만 센다 (검사대 화면의 3/10 은 보여 주기용).
 *  - 같은 메시지가 두 번 와도(QoS 1) 한 번만 반영: event_id 로 거른다 (멱등).
 *  - MQTT 발행은 커밋 뒤에만 (AfterCommit) — 롤백됐는데 설비는 받은 상태를 막는다.
 *  - 한 검사대에 실리는 작업지시는 하나. 나머지는 대기열(QUEUED) 에서 순서대로 — 앞 것이 끝나면(완료·취소·거절)
 *    MES 가 다음 것을 자동 발행한다. 순서의 정답도 MES 이고, 검사대는 받은 것 하나만 한다.
 */
@Service
public class WorkOrderService {

    private static final Logger log = LoggerFactory.getLogger(WorkOrderService.class);
    private static final DateTimeFormatter DAY = DateTimeFormatter.ofPattern("yyyyMMdd");

    private final WorkOrderRepository orders;
    private final ProductResultRepository results;
    private final StationEventRepository events;
    private final RecipeService recipes;
    private final WorkOrderPublisher publisher;

    public WorkOrderService(WorkOrderRepository orders, ProductResultRepository results, StationEventRepository events,
                            RecipeService recipes, WorkOrderPublisher publisher) {
        this.orders = orders;
        this.results = results;
        this.events = events;
        this.recipes = recipes;
        this.publisher = publisher;
    }

    /** 여러 줄 작업지시의 한 줄: 레시피(버전 생략 = 최신) × 수량. */
    public record Line(String recipeId, Integer recipeVersion, int quantity) {
    }

    // ── REST ──
    /**
     * 작업지시 한 건. 검사대가 비어 있으면 바로 발행(RELEASED), 진행 중·대기 중인 것이 있으면 대기열 끝(QUEUED).
     */
    @Transactional
    public WorkOrder release(String stationId, String recipeId, Integer recipeVersion, int quantity) {
        if (quantity < 1) {
            throw ApiException.badRequest("수량은 1 이상");
        }
        Recipe recipe = recipes.resolve(recipeId, recipeVersion);
        boolean busy = orders.existsByStationIdAndStatusIn(stationId, WorkOrderStatus.active())
                || orders.existsByStationIdAndStatusIn(stationId, EnumSet.of(WorkOrderStatus.QUEUED));
        String prefix = "WO-" + LocalDate.now().format(DAY) + "-";
        String id = prefix + String.format("%03d", orders.countByWorkOrderIdStartingWith(prefix) + 1);
        WorkOrder wo = orders.save(busy ? WorkOrder.queued(id, stationId, recipe, quantity)
                : new WorkOrder(id, stationId, recipe, quantity));
        promoteNext(stationId);                      // 대기만 있고 진행 중이 없던 이상 상태도 여기서 바로잡힌다
        AfterCommit.run(() -> publisher.syncStation(stationId));   // 대기열이 바뀌어도 다시 싣는다 (next 목록)
        log.info("작업지시 {} {} → {} ({} v{} × {})", busy ? "대기열 등록" : "발행", id, stationId,
                recipe.getRecipeId(), recipe.getVersion(), quantity);
        return wo;
    }

    /**
     * 여러 줄을 순서대로 한 번에 (예: recipe_1 × 2 → recipe_2 × 3). 첫 줄이 발행되고 나머지는 대기열.
     * 레시피를 전부 먼저 확인한다 — 한 줄이라도 틀리면 아무것도 등록하지 않는다 (한 트랜잭션).
     */
    @Transactional
    public List<WorkOrder> releaseAll(String stationId, List<Line> lines) {
        if (lines == null || lines.isEmpty()) {
            throw ApiException.badRequest("작업 줄이 없습니다");
        }
        for (Line l : lines) {
            if (l.quantity() < 1) {
                throw ApiException.badRequest(l.recipeId() + " 수량은 1 이상");
            }
            recipes.resolve(l.recipeId(), l.recipeVersion());
        }
        List<WorkOrder> out = new ArrayList<>();
        for (Line l : lines) {
            out.add(release(stationId, l.recipeId(), l.recipeVersion(), l.quantity()));
        }
        return out;
    }

    @Transactional
    public WorkOrder cancel(String workOrderId, String reason) {
        WorkOrder wo = get(workOrderId);
        if (!wo.getStatus().isOpen()) {
            throw ApiException.conflict(workOrderId + " 는 이미 " + wo.getStatus());
        }
        boolean wasActive = wo.isActive();
        wo.cancel(reason == null || reason.isBlank() ? "MES 에서 취소" : reason);
        if (wasActive) {
            promoteNext(wo.getStationId());          // 진행 중이던 것을 취소 → 다음 줄로
        }
        AfterCommit.run(() -> publisher.syncStation(wo.getStationId()));
        return wo;
    }

    /** 검사대에 실린 것이 없으면 대기열 맨 앞을 발행 상태로. 검사대로 싣는 건 커밋 뒤 syncStation. */
    private void promoteNext(String stationId) {
        if (orders.existsByStationIdAndStatusIn(stationId, WorkOrderStatus.active())) {
            return;
        }
        orders.findFirstByStationIdAndStatusOrderByWorkOrderIdAsc(stationId, WorkOrderStatus.QUEUED).ifPresent(next -> {
            next.dispatch();
            log.info("대기열 → 발행 {} → {} ({} × {})", next.getWorkOrderId(), stationId,
                    next.getRecipe().getRecipeId(), next.getQuantity());
        });
    }

    @Transactional(readOnly = true)
    public WorkOrder get(String workOrderId) {
        return orders.findById(workOrderId).orElseThrow(() -> ApiException.notFound("작업지시 없음: " + workOrderId));
    }

    @Transactional(readOnly = true)
    public List<WorkOrder> list(String stationId) {
        return stationId == null || stationId.isBlank() ? orders.findAllByOrderByReleasedAtDesc()
                : orders.findByStationIdOrderByReleasedAtDesc(stationId);
    }

    @Transactional(readOnly = true)
    public List<ProductResult> results(String workOrderId) {
        return results.findByWorkOrderIdOrderByProductSeqAsc(workOrderId);
    }

    // ── MQTT (설비 보고) ──
    @Transactional
    public void onAck(String stationId, AckMessage ack) {
        if (ack.eventId() == null || events.existsById(ack.eventId())) {
            return;                                  // 중복 (QoS 1 재전송)
        }
        events.save(new StationEvent(ack.eventId(), stationId, ack.type(), ack.workOrderId(), ack.reason(), ack.occurredAt()));
        WorkOrder wo = orders.findById(ack.workOrderId() == null ? "" : ack.workOrderId()).orElse(null);
        if (wo == null) {
            log.warn("{} 의 {} — 모르는 작업지시 {} ({})", stationId, ack.type(), ack.workOrderId(), ack.reason());
            return;
        }
        switch (ack.type() == null ? "" : ack.type()) {
            case "ACCEPTED" -> wo.accept();
            case "REJECTED" -> {
                wo.reject(ack.reason());
                // BUSY = 검사대에 MES 가 모르는 작업이 남아 있다 — 다음 것도 똑같이 거절될 테니 넘기지 않고 사람이 본다
                if (ack.reason() == null || !ack.reason().startsWith("BUSY")) {
                    promoteNext(stationId);
                }
                AfterCommit.run(() -> publisher.syncStation(stationId));   // 거절된 것을 retained 에서 내린다
            }
            case "CANCELLED" -> wo.cancel("검사대에서 취소 확인");
            case "COMPLETED" -> {
                if (wo.isActive()) {                  // 검사대는 다 셌는데 MES 는 아직 — result 가 늦거나 빠졌다
                    log.warn("{} 검사대 완료 보고, MES 집계 {}/{}", wo.getWorkOrderId(), wo.getDoneQty(), wo.getQuantity());
                }
            }
            default -> log.warn("모르는 ack {}", ack.type());
        }
    }

    /** 새로 센 결과면 true, 중복이면 false. */
    @Transactional
    public boolean onResult(String stationId, ResultMessage r) {
        if (r.eventId() == null || results.existsByEventId(r.eventId())) {
            return false;                            // 중복 (QoS 1 재전송) — 수량을 두 번 세지 않는다
        }
        results.save(ProductResult.of(stationId, r));
        WorkOrder wo = orders.findById(r.workOrderId() == null ? "" : r.workOrderId()).orElse(null);
        if (wo == null) {
            log.warn("모르는 작업지시의 결과 {} (event {}) — 기록만", r.workOrderId(), r.eventId());
            return true;
        }
        if (wo.countResult() && wo.getStatus() == WorkOrderStatus.COMPLETED) {
            log.info("작업지시 완료 {} ({}/{})", wo.getWorkOrderId(), wo.getDoneQty(), wo.getQuantity());
            promoteNext(stationId);                                         // 대기열에 다음 줄이 있으면 바로 발행
            AfterCommit.run(() -> publisher.syncStation(stationId));       // 다음 작업지시를 싣거나, 없으면 retained 비움
        }
        return true;
    }
}
