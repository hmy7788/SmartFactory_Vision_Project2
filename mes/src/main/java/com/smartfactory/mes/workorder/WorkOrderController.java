package com.smartfactory.mes.workorder;

import java.time.Instant;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.smartfactory.mes.result.ProductResult;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/work-orders")
public class WorkOrderController {

    private final WorkOrderService service;

    public WorkOrderController(WorkOrderService service) {
        this.service = service;
    }

    @GetMapping
    public List<WorkOrderView> list(@RequestParam(name = "station", required = false) String station) {
        return service.list(station).stream().map(WorkOrderView::of).toList();
    }

    @GetMapping("/{id}")
    public WorkOrderDetail get(@PathVariable("id") String id) {
        return new WorkOrderDetail(WorkOrderView.of(service.get(id)),
                service.results(id).stream().map(ResultView::of).toList());
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public WorkOrderView release(@Valid @RequestBody ReleaseRequest request) {
        return WorkOrderView.of(service.release(request.stationId(), request.recipeId(), request.recipeVersion(),
                request.quantity()));
    }

    /** 여러 줄을 순서대로: 첫 줄 발행, 나머지 대기열 — 앞 줄 수량이 다 차면 MES 가 다음 줄을 자동 발행. */
    @PostMapping("/batch")
    @ResponseStatus(HttpStatus.CREATED)
    public List<WorkOrderView> releaseAll(@Valid @RequestBody BatchRequest request) {
        return service.releaseAll(request.stationId(), request.lines().stream()
                        .map(l -> new WorkOrderService.Line(l.recipeId(), l.recipeVersion(), l.quantity())).toList())
                .stream().map(WorkOrderView::of).toList();
    }

    @PostMapping("/{id}/cancel")
    public WorkOrderView cancel(@PathVariable("id") String id) {
        return WorkOrderView.of(service.cancel(id, null));
    }

    public record ReleaseRequest(
            @NotBlank @JsonProperty("station_id") String stationId,
            @NotBlank @JsonProperty("recipe_id") String recipeId,
            @JsonProperty("recipe_version") Integer recipeVersion,
            @Min(1) @JsonProperty("quantity") int quantity) {
    }

    public record BatchRequest(
            @NotBlank @JsonProperty("station_id") String stationId,
            @NotEmpty @Valid @JsonProperty("lines") List<LineRequest> lines) {
    }

    public record LineRequest(
            @NotBlank @JsonProperty("recipe_id") String recipeId,
            @JsonProperty("recipe_version") Integer recipeVersion,
            @Min(1) @JsonProperty("quantity") int quantity) {
    }

    public record WorkOrderView(
            @JsonProperty("work_order_id") String workOrderId,
            @JsonProperty("station_id") String stationId,
            @JsonProperty("recipe_id") String recipeId,
            @JsonProperty("recipe_version") int recipeVersion,
            @JsonProperty("quantity") int quantity,
            @JsonProperty("done_qty") int doneQty,
            @JsonProperty("status") WorkOrderStatus status,
            @JsonProperty("released_at") Instant releasedAt,
            @JsonProperty("started_at") Instant startedAt,
            @JsonProperty("finished_at") Instant finishedAt,
            @JsonProperty("reason") String reason) {

        static WorkOrderView of(WorkOrder w) {
            return new WorkOrderView(w.getWorkOrderId(), w.getStationId(), w.getRecipe().getRecipeId(),
                    w.getRecipe().getVersion(), w.getQuantity(), w.getDoneQty(), w.getStatus(), w.getReleasedAt(),
                    w.getStartedAt(), w.getFinishedAt(), w.getReason());
        }
    }

    public record ResultView(
            @JsonProperty("product_seq") int productSeq,
            @JsonProperty("first_pass") boolean firstPass,
            @JsonProperty("ng_count") int ngCount,
            @JsonProperty("ng_codes") String ngCodes,
            @JsonProperty("cycle_ms") Long cycleMs,
            @JsonProperty("occurred_at") java.time.OffsetDateTime occurredAt,
            @JsonProperty("event_id") String eventId) {

        static ResultView of(ProductResult r) {
            return new ResultView(r.getProductSeq(), r.isFirstPass(), r.getNgCount(), r.getNgCodes(), r.getCycleMs(),
                    r.getOccurredAt(), r.getEventId());
        }
    }

    public record WorkOrderDetail(
            @JsonProperty("work_order") WorkOrderView workOrder,
            @JsonProperty("results") List<ResultView> results) {
    }
}
