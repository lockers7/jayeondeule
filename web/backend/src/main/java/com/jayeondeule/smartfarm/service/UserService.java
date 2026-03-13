package com.jayeondeule.smartfarm.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.jayeondeule.smartfarm.dto.user.*;
import com.jayeondeule.smartfarm.entity.user.User;
import com.jayeondeule.smartfarm.repository.UserRepository;
import lombok.RequiredArgsConstructor;

import java.util.Objects;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class UserService {
    //사용자 비즈니스 로직 및 인증 처리

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final ObjectMapper mapper;

    //회원가입
    public boolean insertUser(UserInsertDTO signupInfo) {
        String hashed = passwordEncoder.encode(signupInfo.getPasswd());
        signupInfo.setPasswd(hashed);

        userRepository.save(Objects.requireNonNull(mapper.convertValue(signupInfo, User.class)));

        return true;
    }

    //아이디 중복 확인
    public boolean idDuplicationCheck(String idInfo) {
        return userRepository.existsByUserId(idInfo);
    }

    //유저 리스트 조회(관리자용) — dlteYn='N'만 조회
    public Page<UserDTO> getUsers(int page, int size) {
        Pageable pageable = PageRequest.of(page, size, Sort.by("rgstDttm").descending());

        Page<User> userList = userRepository.findAllByDlteYn("N", pageable);

        return userList.map(user -> mapper.convertValue(user, UserDTO.class));
    }

    //농장별 유저 리스트 조회 — dlteYn='N'만 조회
    public Page<UserDTO> getUsers(int page, int size, long searchQuery) {
        Pageable pageable = PageRequest.of(page, size, Sort.by("rgstDttm").descending());

        Page<User> userList = userRepository.findAllByFarmIdAndDlteYn(searchQuery, "N", pageable);

        return userList.map(user -> mapper.convertValue(user, UserDTO.class));
    }

    //유저 전체 리스트 조회(관리자용) — 삭제 포함
    public Page<UserDTO> getUsersAll(int page, int size) {
        Pageable pageable = PageRequest.of(page, size, Sort.by("rgstDttm").descending());

        Page<User> userList = userRepository.findAll(pageable);

        return userList.map(user -> mapper.convertValue(user, UserDTO.class));
    }

    //농장별 유저 전체 리스트 조회(관리자용) — 삭제 포함
    public Page<UserDTO> getUsersAll(int page, int size, long searchQuery) {
        Pageable pageable = PageRequest.of(page, size, Sort.by("rgstDttm").descending());

        Page<User> userList = userRepository.findAllByFarmId(searchQuery, pageable);

        return userList.map(user -> mapper.convertValue(user, UserDTO.class));
    }

    //사용자 복원 (soft delete 취소 — dlteYn='N')
    public void restoreUser(String userId) {
        User target = userRepository.findByUserId(userId);
        if (target != null) {
            target.setDlteYn("N");
            userRepository.save(target);
        }
    }

    //사용자 정보 조회
    public UserDTO getUser(String userId) {
        return mapper.convertValue(userRepository.findByUserId(userId), UserDTO.class);
    }

    //비밀번호 변경
    public boolean patchUserPassword(UserPasswordPatchDTO passwordInfo, String userId) {
        User target = userRepository.findByUserId(userId);

        if(passwordEncoder.matches(passwordInfo.getOldPassword(), target.getPasswd())) {
            String hashedNew = passwordEncoder.encode(passwordInfo.getNewPassword());
            target.changePassword(hashedNew);
            userRepository.save(target);
            return true;
        }

        return false;
    }

    //사용자 정보 수정
    public void patchUser(UserPatchDTO modifiedInfo, String userId) {
        User target = userRepository.findByUserId(userId);

        if (modifiedInfo.getUserName() != null) target.changeUserName(modifiedInfo.getUserName());
        if (modifiedInfo.getPstn() != null) target.changeUserPstn(modifiedInfo.getPstn());
        if (modifiedInfo.getHpNo() != null) target.changeUserHpNo(modifiedInfo.getHpNo());
        if (modifiedInfo.getAuthLvel() != null) target.changeUserAuthLvel(modifiedInfo.getAuthLvel());
        if (modifiedInfo.getFarmId() != null) target.setFarmId(modifiedInfo.getFarmId());
        if (modifiedInfo.getPasswd() != null && !modifiedInfo.getPasswd().isBlank()) {
            target.changePassword(passwordEncoder.encode(modifiedInfo.getPasswd()));
        }

        userRepository.save(Objects.requireNonNull(target));
    }

    //사용자에게 농장 접근 권한 부여
    public void patchUserFarmId(UserFarmIdPatchDTO modifiedInfo, String userId) {
        User target = userRepository.findByUserId(userId);

        target.setFarmId(modifiedInfo.getFarmId());

        userRepository.save(target);
    }

    //사용자에게 부여된 농장ID 조회
    public long getUserOwnedFarmId(String userId) {
        return userRepository.findByUserId(userId).getFarmId();
    }

    //사용자 삭제 (soft delete — dlteYn='Y')
    public void deleteUser(String userId) {
        User target = userRepository.findByUserId(userId);
        if (target != null) {
            target.setDlteYn("Y");
            userRepository.save(target);
        }
    }

    //사용자 완전 삭제 (hard delete — 레코드 삭제)
    public void hardDeleteUser(String userId) {
        User target = userRepository.findByUserId(userId);
        if (target != null) {
            userRepository.delete(Objects.requireNonNull(target));
        }
    }
}
