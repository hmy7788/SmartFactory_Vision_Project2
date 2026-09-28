package com.smartfactory.mes.workorder;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface WorkOrderRepository extends JpaRepository<WorkOrder, String> {

    boolean existsByStationIdAndStatusIn(String stationId, Collection<WorkOrderStatus> statuses);

    Optional<WorkOrder> findFirstByStationIdAndStatusIn(String stationId, Collection<WorkOrderStatus> statuses);

    long countByWorkOrderIdStartingWith(String prefix);

    /** 대기열: 작업지시 번호 순(= 등록 순, WO-날짜-일련번호). */
    Optional<WorkOrder> findFirstByStationIdAndStatusOrderByWorkOrderIdAsc(String stationId, WorkOrderStatus status);

    List<WorkOrder> findByStationIdAndStatusOrderByWorkOrderIdAsc(String stationId, WorkOrderStatus status);

    List<WorkOrder> findAllByOrderByReleasedAtDesc();

    List<WorkOrder> findByStationIdOrderByReleasedAtDesc(String stationId);

    @Query("select distinct w.stationId from WorkOrder w")
    List<String> findStationIds();
}
