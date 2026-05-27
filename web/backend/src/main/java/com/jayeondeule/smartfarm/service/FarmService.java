package com.jayeondeule.smartfarm.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.jayeondeule.smartfarm.dto.farm.FarmDTO;
import com.jayeondeule.smartfarm.dto.farm.FarmInsertDTO;
import com.jayeondeule.smartfarm.dto.farm.FarmPatchDTO;
import com.jayeondeule.smartfarm.entity.farm.Farm;
import com.jayeondeule.smartfarm.entity.user.User;
import com.jayeondeule.smartfarm.repository.FarmRepository;
import com.jayeondeule.smartfarm.repository.UserRepository;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.*;

import java.util.Objects;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class FarmService {
    private final FarmRepository farmRepository;
    private final UserRepository userRepository;
    private final ObjectMapper mapper;

    @PostConstruct
    public void init() {
        mapper.registerModule(new JavaTimeModule());
    }

    public void insertFarm(FarmInsertDTO farmInfo) {
        farmRepository.save(Objects.requireNonNull(mapper.convertValue(farmInfo, Farm.class)));
    }

    //전체 농장 목록 조회 (관리자용 — 삭제 포함)
    public Page<FarmDTO> getAllFarmsAll(int page, int size) {
        Pageable pageable = PageRequest.of(page, size, Sort.by("farmId").ascending());
        Page<Farm> farmList = farmRepository.findAllBy(pageable);
        return farmList.map(farm -> mapper.convertValue(farm, FarmDTO.class));
    }

    //농장 목록 조회 — dlteYn='N'만 조회
    public Page<FarmDTO> getAllFarms(int page, int size) {
        Pageable pageable = PageRequest.of(page, size, Sort.by("farmId").ascending());
        Page<Farm> farmList = farmRepository.findAllByDlteYn("N", pageable);
        return farmList.map(farm -> mapper.convertValue(farm, FarmDTO.class));
    }

    public FarmDTO getFarmByUserId(String userId) {
        User owner = userRepository.findByUserId(userId);

        Farm userFarm = farmRepository.findByFarmId(owner.getFarmId());

        return mapper.convertValue(userFarm, FarmDTO.class);
    }

    public FarmDTO getFarmByFarmId(Long farmId) {
        Farm userFarm = farmRepository.findByFarmId(farmId);

        return mapper.convertValue(userFarm, FarmDTO.class);
    }

    //농장 삭제 (soft delete — dlteYn='Y')
    public void deleteFarmByFarmId(Long farmId) {
        Farm target = farmRepository.findByFarmId(farmId);
        if (target != null) {
            target.setDlteYn("Y");
            farmRepository.save(target);
        }
    }

    //농장 복원 (soft delete 취소 — dlteYn='N')
    public void restoreFarm(Long farmId) {
        Farm target = farmRepository.findByFarmId(farmId);
        if (target != null) {
            target.setDlteYn("N");
            farmRepository.save(target);
        }
    }

    //농장 완전 삭제 (hard delete — 레코드 삭제)
    public void hardDeleteFarm(Long farmId) {
        Farm target = farmRepository.findByFarmId(farmId);
        if (target != null) {
            farmRepository.delete(Objects.requireNonNull(target));
        }
    }

    public void patchFarmByFarmId(Long farmId, FarmPatchDTO modifiedInfo) {
        Farm target = farmRepository.findByFarmId(farmId);

        target.setFarmName(modifiedInfo.getFarmName());
        target.setFarmDomi(modifiedInfo.getFarmDomi());

        target.setOpenDate(modifiedInfo.getOpenDate());
        target.setCloseDate(modifiedInfo.getCloseDate());

        target.setTelNo(modifiedInfo.getTelNo());
        target.setHpNo(modifiedInfo.getHpNo());
        target.setMail(modifiedInfo.getMail());
        target.setIpAddr(modifiedInfo.getIpAddr());
        target.setPort(modifiedInfo.getPort());
        target.setAddr(modifiedInfo.getAddr());
        target.setMainPrdt(modifiedInfo.getMainPrdt());
        target.setRmks(modifiedInfo.getRmks());

        farmRepository.save(target);
    }
}
