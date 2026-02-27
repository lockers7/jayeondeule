package com.jayeondeule.smartfarm.repository;

import com.jayeondeule.smartfarm.entity.farm.Farm;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface FarmRepository extends JpaRepository<Farm, Long> {
    Page<Farm> findAllBy(Pageable pageable);

    Farm findByFarmId(Long farmId);
}
