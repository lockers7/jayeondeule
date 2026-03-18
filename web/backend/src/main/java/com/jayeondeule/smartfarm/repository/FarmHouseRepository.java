package com.jayeondeule.smartfarm.repository;

import com.jayeondeule.smartfarm.entity.house.FarmHouse;
import com.jayeondeule.smartfarm.entity.house.FarmHouseId;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface FarmHouseRepository extends JpaRepository<FarmHouse, FarmHouseId> {
    List<FarmHouse> findAllByFarmId(long farmId);

    List<FarmHouse> findAllByFarmIdOrderByHousIdAsc(long farmId);

    // dlteYn 조건 추가 메서드
    List<FarmHouse> findAllByFarmIdAndDlteYnOrderByHousIdAsc(long farmId, String dlteYn);

    // 농장 내 최대 housId 조회 (신규 등록 시 ID 채번)
    @Query("SELECT COALESCE(MAX(f.housId), 0) FROM FarmHouse f WHERE f.farmId = :farmId")
    long findMaxHousIdByFarmId(@Param("farmId") long farmId);

    // 관리자 전용: 재배사 번호(PK) 변경 — 네이티브 SQL 필요
    @Modifying
    @Query(value = "UPDATE farmhouse_m_info SET hous_id = :newHousId WHERE farm_id = :farmId AND hous_id = :oldHousId", nativeQuery = true)
    void updateHousId(@Param("farmId") long farmId, @Param("oldHousId") long oldHousId, @Param("newHousId") long newHousId);
}
