package com.jayeondeule.smartfarm.repository;

import com.jayeondeule.smartfarm.entity.setting.SensorSetting;
import com.jayeondeule.smartfarm.entity.setting.SensorSettingId;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

@Repository
public interface SensorSettingRepository extends JpaRepository<SensorSetting, SensorSettingId> {
    SensorSetting findTopByFarmIdAndHousIdOrderBySetnDttmDesc(long farmId, long houseId);

    @Modifying
    @Query("DELETE FROM SensorSetting s WHERE s.farmId = :farmId AND s.housId = :housId")
    void deleteAllByFarmIdAndHousId(@Param("farmId") long farmId, @Param("housId") long housId);

    @Modifying
    @Query(value = "UPDATE sensor_m_setting SET hous_id = :newHousId WHERE farm_id = :farmId AND hous_id = :oldHousId", nativeQuery = true)
    void updateHousId(@Param("farmId") long farmId, @Param("oldHousId") long oldHousId, @Param("newHousId") long newHousId);
}
