package com.smartfactory.mes.result;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

public interface ProductResultRepository extends JpaRepository<ProductResult, Long> {

    boolean existsByEventId(String eventId);

    List<ProductResult> findByWorkOrderIdOrderByProductSeqAsc(String workOrderId);

    long countByWorkOrderId(String workOrderId);
}
