package com.jayeondeule.smartfarm.repository;

import com.jayeondeule.smartfarm.entity.setting.LightIrrigationSetting;
import com.jayeondeule.smartfarm.entity.setting.LightIrrigationSettingId;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface LightIrrigationSettingRepository extends JpaRepository<LightIrrigationSetting, LightIrrigationSettingId> {
    List<LightIrrigationSetting> findAllByFarmIdAndHousIdOrderByStrtTime(long farmId, long houseId);

    @Modifying
    @Query("DELETE FROM LightIrrigationSetting l WHERE l.farmId = :farmId AND l.housId = :housId")
    void deleteAllByFarmIdAndHousId(@Param("farmId") long farmId, @Param("housId") long housId);

    @Modifying
    @Query(value = "UPDATE light_irrigation_s_setting SET hous_id = :newHousId WHERE farm_id = :farmId AND hous_id = :oldHousId", nativeQuery = true)
    void updateHousId(@Param("farmId") long farmId, @Param("oldHousId") long oldHousId, @Param("newHousId") long newHousId);
}
