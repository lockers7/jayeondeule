package com.jayeondeule.smartfarm.repository;

import com.jayeondeule.smartfarm.entity.relay.RelayRecording;
import com.jayeondeule.smartfarm.entity.relay.RelayRecordingId;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface RelayRecordingRepository extends JpaRepository<RelayRecording, RelayRecordingId> {
    RelayRecording findTopByFarmIdAndHousIdOrderByRecdDttmDesc(long farmId, long housId);
}
