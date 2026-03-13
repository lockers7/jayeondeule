package com.jayeondeule.smartfarm.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.jayeondeule.smartfarm.dto.house.FarmHouseDTO;
import com.jayeondeule.smartfarm.dto.house.FarmHouseInsertDTO;
import com.jayeondeule.smartfarm.dto.house.FarmHousePatchDTO;
import com.jayeondeule.smartfarm.entity.house.FarmHouse;
import com.jayeondeule.smartfarm.entity.house.FarmHouseId;
import com.jayeondeule.smartfarm.repository.FarmHouseRepository;
import jakarta.annotation.PostConstruct;
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
    private final ObjectMapper mapper;

    @PostConstruct
    public void init() {
        mapper.registerModule(new JavaTimeModule());
    }

    //재배사 목록 조회 — dlteYn='N'만 조회
    public List<FarmHouseDTO> getHouseList(long farmId) {
        List<FarmHouse> result = farmHouseRepository.findAllByFarmIdAndDlteYnOrderByHousNameAsc(farmId, "N");
        return result.stream().map(item -> mapper.convertValue(item, FarmHouseDTO.class)).toList();
    }

    //재배사 전체 목록 조회(관리자용) — 삭제 포함
    public List<FarmHouseDTO> getHouseListAll(long farmId) {
        List<FarmHouse> result = farmHouseRepository.findAllByFarmIdOrderByHousNameAsc(farmId);
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
        // 해당 farm의 house갯수에 따라 hous_id 지정.
        insertInfo.setHousId(farmHouseRepository.findAllByFarmId(insertInfo.getFarmId()).size() + 1);
        farmHouseRepository.save(Objects.requireNonNull(mapper.convertValue(insertInfo, FarmHouse.class)));
    }

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

            farmHouseRepository.save(target);
        }
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
}
