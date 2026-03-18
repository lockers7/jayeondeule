package com.jayeondeule.smartfarm.repository;

import com.jayeondeule.smartfarm.entity.memo.FarmHouseCrops;
import com.jayeondeule.smartfarm.entity.memo.FarmHouseCropsId;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

@Repository
public interface FarmHouseCropsRepository extends JpaRepository<FarmHouseCrops, FarmHouseCropsId> {
    Page<FarmHouseCrops> findAllByFarmIdAndHousId(long farmId, long housId, Pageable pageable);

    @Modifying
    @Query("DELETE FROM FarmHouseCrops f WHERE f.farmId = :farmId AND f.housId = :housId")
    void deleteAllByFarmIdAndHousId(@Param("farmId") long farmId, @Param("housId") long housId);

    @Modifying
    @Query(value = "UPDATE farmhouse_l_crops SET hous_id = :newHousId WHERE farm_id = :farmId AND hous_id = :oldHousId", nativeQuery = true)
    void updateHousId(@Param("farmId") long farmId, @Param("oldHousId") long oldHousId, @Param("newHousId") long newHousId);
}
