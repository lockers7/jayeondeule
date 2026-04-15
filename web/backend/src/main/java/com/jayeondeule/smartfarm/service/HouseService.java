package com.jayeondeule.smartfarm.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.jayeondeule.smartfarm.dto.house.FarmHouseDTO;
import com.jayeondeule.smartfarm.dto.house.FarmHouseInsertDTO;
import com.jayeondeule.smartfarm.dto.house.FarmHousePatchDTO;
import com.jayeondeule.smartfarm.entity.house.FarmHouse;
import com.jayeondeule.smartfarm.entity.house.FarmHouseId;
import com.jayeondeule.smartfarm.repository.*;
import jakarta.annotation.PostConstruct;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import jakarta.transaction.Transactional;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Objects;
import java.util.Optional;

@Service
@RequiredArgsConstructor
//재배사 등록, 설정, 모니터링 로직
public class HouseService {
    private final FarmHouseRepository farmHouseRepository;
    private final SensorRecordingRepository sensorRecordingRepository;
    private final SensorSettingRepository sensorSettingRepository;
    private final LightIrrigationSettingRepository lightIrrigationSettingRepository;
    private final RelayRecordingRepository relayRecordingRepository;
    private final FarmHouseCropsRepository farmHouseCropsRepository;
    private final ObjectMapper mapper;

    @PersistenceContext
    private EntityManager entityManager;

    @PostConstruct
    public void init() {
        mapper.registerModule(new JavaTimeModule());
    }

    //재배사 목록 조회 — dlteYn='N'만 조회
    public List<FarmHouseDTO> getHouseList(long farmId) {
        List<FarmHouse> result = farmHouseRepository.findAllByFarmIdAndDlteYnOrderByHousIdAsc(farmId, "N");
        return result.stream().map(item -> mapper.convertValue(item, FarmHouseDTO.class)).toList();
    }

    //재배사 전체 목록 조회(관리자용) — 삭제 포함
    public List<FarmHouseDTO> getHouseListAll(long farmId) {
        List<FarmHouse> result = farmHouseRepository.findAllByFarmIdOrderByHousIdAsc(farmId);
        return result.stream().map(item -> mapper.convertValue(item, FarmHouseDTO.class)).toList();
    }

    //재배사 복원 (soft delete 취소 — dlteYn='N')
    public void restoreHouse(long farmId, long houseId) {
        FarmHouseId id = FarmHouseId.builder()
                .farmId(farmId)
                .housId(houseId)
                .build();

        Optional<FarmHouse> targetOpt = farmHouseRepository.findById(Objects.requireNonNull(id));

        if(targetOpt.isPresent()) {
            FarmHouse target = targetOpt.get();
            target.setDlteYn("N");
            farmHouseRepository.save(target);
        }
    }

    public FarmHouseDTO getHouse(long farmId, long houseId) {
        FarmHouseId id = FarmHouseId.builder()
                .farmId(farmId)
                .housId(houseId)
                .build();

        Optional<FarmHouse> targetOpt = farmHouseRepository.findById(Objects.requireNonNull(id));

        return targetOpt.map(farmHouse -> mapper.convertValue(farmHouse, FarmHouseDTO.class)).orElse(null);
    }

    public void insertHouse(FarmHouseInsertDTO insertInfo) {
        // housId가 음수이면 자동 채번 (MAX+1), 0 이상이면 지정한 값 사용
        if (insertInfo.getHousId() < 0) {
            insertInfo.setHousId(farmHouseRepository.findMaxHousIdByFarmId(insertInfo.getFarmId()) + 1);
        }
        farmHouseRepository.save(Objects.requireNonNull(mapper.convertValue(insertInfo, FarmHouse.class)));
    }

    // 다음 재배사 번호 조회 (프론트엔드 표시용)
    public long getNextHousId(long farmId) {
        return farmHouseRepository.findMaxHousIdByFarmId(farmId) + 1;
    }

    @Transactional
    public void patchHouse(FarmHousePatchDTO modifiedInfo, long farmId, long houseId) {
        FarmHouseId id = FarmHouseId.builder()
                .farmId(farmId)
                .housId(houseId)
                .build();

        Optional<FarmHouse> targetOpt = farmHouseRepository.findById(Objects.requireNonNull(id));

        if(targetOpt.isPresent()) {
            FarmHouse target = targetOpt.get();

            target.setHousName(modifiedInfo.getHousName());
            target.setCropKind(modifiedInfo.getCropKind());
            target.setLastGetDttm(modifiedInfo.getLastGetDttm());
            target.setRfrsFlag(modifiedInfo.isRfrsFlag());
            target.setSnsrRfrsItvl(modifiedInfo.getSnsrRfrsItvl());
            target.setMnulCtrlFlag(modifiedInfo.isMnulCtrlFlag());
            target.setCtrlType(modifiedInfo.getCtrlType());
            target.setCropLvel(modifiedInfo.getCropLvel());

            farmHouseRepository.saveAndFlush(target);

            // 관리자 전용: 재배사 번호(housId) 변경
            if (modifiedInfo.getNewHousId() != null && modifiedInfo.getNewHousId() != houseId) {
                // JPA 캐시 클리어 후 네이티브 SQL로 PK 변경 (JPA는 PK 변경 불가)
                entityManager.clear();
                changeHousId(farmId, houseId, modifiedInfo.getNewHousId());
            }
        }
    }

    // 관리자 전용: 재배사 번호(PK) 변경 — 연관 테이블 포함 일괄 UPDATE
    private void changeHousId(long farmId, long oldHousId, long newHousId) {
        // 연관 테이블 먼저 변경 (FK 정합성)
        sensorRecordingRepository.updateHousId(farmId, oldHousId, newHousId);
        sensorSettingRepository.updateHousId(farmId, oldHousId, newHousId);
        lightIrrigationSettingRepository.updateHousId(farmId, oldHousId, newHousId);
        relayRecordingRepository.updateHousId(farmId, oldHousId, newHousId);
        farmHouseCropsRepository.updateHousId(farmId, oldHousId, newHousId);
        // 메인 테이블 변경
        farmHouseRepository.updateHousId(farmId, oldHousId, newHousId);
    }

    //재배사 삭제 (soft delete — dlteYn='Y')
    public void deleteHouse(long farmId, long houseId) {
        FarmHouseId id = FarmHouseId.builder()
                .farmId(farmId)
                .housId(houseId)
                .build();

        Optional<FarmHouse> targetOpt = farmHouseRepository.findById(Objects.requireNonNull(id));

        if(targetOpt.isPresent()) {
            FarmHouse target = targetOpt.get();
            target.setDlteYn("Y");
            farmHouseRepository.save(target);
        }
    }

    //재배사 완전 삭제 (hard delete — 연관 데이터 포함 레코드 삭제)
    @Transactional
    public void hardDeleteHouse(long farmId, long houseId) {
        // 연관 데이터 먼저 삭제 (FK 제약조건)
        sensorRecordingRepository.deleteAllByFarmIdAndHousId(farmId, houseId);
        sensorSettingRepository.deleteAllByFarmIdAndHousId(farmId, houseId);
        lightIrrigationSettingRepository.deleteAllByFarmIdAndHousId(farmId, houseId);
        relayRecordingRepository.deleteAllByFarmIdAndHousId(farmId, houseId);
        farmHouseCropsRepository.deleteAllByFarmIdAndHousId(farmId, houseId);

        // 재배사 삭제
        FarmHouseId id = FarmHouseId.builder()
                .farmId(farmId)
                .housId(houseId)
                .build();
        farmHouseRepository.deleteById(Objects.requireNonNull(id));
    }
}
