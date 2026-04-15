package com.jayeondeule.smartfarm.repository;

import com.jayeondeule.smartfarm.entity.relay.RelayRecording;
import com.jayeondeule.smartfarm.entity.relay.RelayRecordingId;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

@Repository
public interface RelayRecordingRepository extends JpaRepository<RelayRecording, RelayRecordingId> {
    RelayRecording findTopByFarmIdAndHousIdOrderByRecdDttmDesc(long farmId, long housId);

    @Modifying
    @Query("DELETE FROM RelayRecording r WHERE r.farmId = :farmId AND r.housId = :housId")
    void deleteAllByFarmIdAndHousId(@Param("farmId") long farmId, @Param("housId") long housId);

    @Modifying
    @Query(value = "UPDATE relay_l_recording SET hous_id = :newHousId WHERE farm_id = :farmId AND hous_id = :oldHousId", nativeQuery = true)
    void updateHousId(@Param("farmId") long farmId, @Param("oldHousId") long oldHousId, @Param("newHousId") long newHousId);
}
