package com.jayeondeule.smartfarm.repository;

import com.jayeondeule.smartfarm.entity.house.FarmHouse;
import com.jayeondeule.smartfarm.entity.house.FarmHouseId;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface FarmHouseRepository extends JpaRepository<FarmHouse, FarmHouseId> {
    List<FarmHouse> findAllByFarmId(long farmId);

    List<FarmHouse> findAllByFarmIdOrderByHousNameAsc(long farmId);

    // dlteYn 조건 추가 메서드
    List<FarmHouse> findAllByFarmIdAndDlteYnOrderByHousNameAsc(long farmId, String dlteYn);

    // 농장 내 최대 housId 조회 (신규 등록 시 ID 채번)
    @Query("SELECT COALESCE(MAX(f.housId), 0) FROM FarmHouse f WHERE f.farmId = :farmId")
    long findMaxHousIdByFarmId(@Param("farmId") long farmId);
    //재배사 관련 데이터 CRUD 인터페이스
}
