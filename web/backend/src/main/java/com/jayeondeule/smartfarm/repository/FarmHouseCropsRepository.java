package com.jayeondeule.smartfarm.repository;

import com.jayeondeule.smartfarm.entity.memo.FarmHouseCrops;
import com.jayeondeule.smartfarm.entity.memo.FarmHouseCropsId;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface FarmHouseCropsRepository extends JpaRepository<FarmHouseCrops, FarmHouseCropsId> {
    Page<FarmHouseCrops> findAllByFarmIdAndHousId(long farmId, long housId, Pageable pageable);
}
