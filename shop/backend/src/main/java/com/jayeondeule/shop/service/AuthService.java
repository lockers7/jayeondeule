package com.jayeondeule.shop.service;

import com.jayeondeule.shop.dto.*;
import com.jayeondeule.shop.entity.FarmUser;
import com.jayeondeule.shop.entity.ShopUser;
import com.jayeondeule.shop.repository.FarmUserRepository;
import com.jayeondeule.shop.repository.ShopUserRepository;
import com.jayeondeule.shop.util.JwtUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Service
@RequiredArgsConstructor
public class AuthService {
    private final ShopUserRepository userRepo;
    private final FarmUserRepository farmUserRepo;
    private final PasswordEncoder passwordEncoder;
    private final JwtUtil jwtUtil;

    public Map<String, Object> login(LoginRequest req) {
        log.info("[로그인 시도] userId={}", req.getShopUsrId());

        // 1순위: shop_user 테이블 (일반회원)
        Optional<ShopUser> shopUserOpt = userRepo.findById(req.getShopUsrId());
        if (shopUserOpt.isPresent()) {
            return loginAsShopUser(shopUserOpt.get(), req.getPasswd());
        }

        // 2순위: user_m_info 테이블 (농장관리자 = ADMIN/FARM_ADMIN)
        Optional<FarmUser> farmUserOpt = farmUserRepo.findByUserIdAndDlteYn(req.getShopUsrId(), "N");
        if (farmUserOpt.isPresent()) {
            return loginAsFarmUser(farmUserOpt.get(), req.getPasswd());
        }

        log.warn("[로그인 실패] 존재하지 않는 아이디: {}", req.getShopUsrId());
        throw new RuntimeException("아이디 또는 비밀번호가 일치하지 않습니다.");
    }

    private Map<String, Object> loginAsShopUser(ShopUser user, String rawPassword) {
        if (!"ACTIVE".equals(user.getUsrStatus())) {
            log.warn("[로그인 실패] 탈퇴 회원: {}", user.getShopUsrId());
            throw new RuntimeException("탈퇴한 회원입니다.");
        }
        if (!passwordEncoder.matches(rawPassword, user.getPasswd())) {
            log.warn("[로그인 실패] 비밀번호 불일치 (shop_user): {}", user.getShopUsrId());
            throw new RuntimeException("아이디 또는 비밀번호가 일치하지 않습니다.");
        }

        user.setLastLoginDt(LocalDateTime.now());
        userRepo.save(user);
        log.info("[로그인 성공] userId={}, grade={}, farmId={}, source=shop_user", user.getShopUsrId(), user.getUsrGrade(), user.getFarmId());

        return buildLoginResult(user.getShopUsrId(), user.getUsrName(), user.getUsrGrade(),
                user.getFarmId(), user.getPhone(), user.getEmail(),
                user.getZipcode(), user.getAddress(), user.getAddressDetail());
    }

    private Map<String, Object> loginAsFarmUser(FarmUser farmUser, String rawPassword) {
        String shopGrade = farmUser.toShopGrade();
        if (shopGrade == null) {
            log.warn("[로그인 실패] 알 수 없는 권한: {} (authLvel={})", farmUser.getUserId(), farmUser.getAuthLvel());
            throw new RuntimeException("아이디 또는 비밀번호가 일치하지 않습니다.");
        }
        if (!passwordEncoder.matches(rawPassword, farmUser.getPasswd())) {
            log.warn("[로그인 실패] 비밀번호 불일치 (user_m_info): {}", farmUser.getUserId());
            throw new RuntimeException("아이디 또는 비밀번호가 일치하지 않습니다.");
        }

        Long farmId = farmUser.getFarmId() != null ? farmUser.getFarmId() : 1L;
        log.info("[로그인 성공] userId={}, grade={}, farmId={}, source=user_m_info", farmUser.getUserId(), shopGrade, farmId);

        return buildLoginResult(farmUser.getUserId(), farmUser.getUserName(), shopGrade,
                farmId, farmUser.getHpNo(), null);
    }

    private Map<String, Object> buildLoginResult(String userId, String name, String grade, Long farmId, String phone, String email) {
        return buildLoginResult(userId, name, grade, farmId, phone, email, null, null, null);
    }

    private Map<String, Object> buildLoginResult(String userId, String name, String grade, Long farmId,
                                                  String phone, String email, String zipcode, String address, String addressDetail) {
        Map<String, Object> claims = new HashMap<>();
        claims.put("userId", userId);
        claims.put("usrName", name);
        claims.put("usrGrade", grade);
        claims.put("farmId", farmId);

        Map<String, Object> userInfo = new HashMap<>();
        userInfo.put("shopUsrId", userId);
        userInfo.put("usrName", name);
        userInfo.put("usrGrade", grade);
        userInfo.put("farmId", farmId);
        userInfo.put("phone", phone != null ? phone : "");
        userInfo.put("email", email != null ? email : "");
        userInfo.put("zipcode", zipcode != null ? zipcode : "");
        userInfo.put("address", address != null ? address : "");
        userInfo.put("addressDetail", addressDetail != null ? addressDetail : "");

        Map<String, Object> result = new HashMap<>();
        result.put("token", jwtUtil.generateToken(claims));
        result.put("userInfo", userInfo);
        return result;
    }

    @Transactional
    public ShopUser register(RegisterRequest req) {
        log.info("[회원가입 시도] userId={}, name={}", req.getShopUsrId(), req.getUsrName());
        if (userRepo.existsByShopUsrId(req.getShopUsrId())) {
            log.warn("[회원가입 실패] shop_user 중복: {}", req.getShopUsrId());
            throw new RuntimeException("이미 사용 중인 아이디입니다.");
        }
        if (farmUserRepo.findByUserIdAndDlteYn(req.getShopUsrId(), "N").isPresent()) {
            log.warn("[회원가입 실패] user_m_info 중복: {}", req.getShopUsrId());
            throw new RuntimeException("이미 사용 중인 아이디입니다.");
        }

        ShopUser user = ShopUser.builder()
                .shopUsrId(req.getShopUsrId())
                .farmId(1L)
                .passwd(passwordEncoder.encode(req.getPasswd()))
                .usrName(req.getUsrName())
                .usrGrade("MEMBER")
                .usrStatus("ACTIVE")
                .phone(req.getPhone())
                .email(req.getEmail())
                .zipcode(req.getZipcode())
                .address(req.getAddress())
                .addressDetail(req.getAddressDetail())
                .build();
        ShopUser saved = userRepo.save(user);
        log.info("[회원가입 성공] userId={}, grade={}", saved.getShopUsrId(), saved.getUsrGrade());
        return saved;
    }

    public boolean checkIdAvailable(String id) {
        if (userRepo.existsByShopUsrId(id)) return false;
        if (farmUserRepo.findByUserIdAndDlteYn(id, "N").isPresent()) return false;
        return true;
    }

    @Transactional
    public void changePassword(String userId, String currentPassword, String newPassword) {
        // ShopUser 먼저 확인
        Optional<ShopUser> shopUserOpt = userRepo.findById(userId);
        if (shopUserOpt.isPresent()) {
            ShopUser user = shopUserOpt.get();
            if (!passwordEncoder.matches(currentPassword, user.getPasswd())) {
                throw new RuntimeException("현재 비밀번호가 일치하지 않습니다.");
            }
            user.setPasswd(passwordEncoder.encode(newPassword));
            userRepo.save(user);
            log.info("[비밀번호 변경] userId={} (shop_user)", userId);
            return;
        }
        // FarmUser 확인
        Optional<FarmUser> farmUserOpt = farmUserRepo.findByUserIdAndDlteYn(userId, "N");
        if (farmUserOpt.isPresent()) {
            FarmUser farmUser = farmUserOpt.get();
            if (!passwordEncoder.matches(currentPassword, farmUser.getPasswd())) {
                throw new RuntimeException("현재 비밀번호가 일치하지 않습니다.");
            }
            farmUser.setPasswd(passwordEncoder.encode(newPassword));
            farmUserRepo.save(farmUser);
            log.info("[비밀번호 변경] userId={} (user_m_info)", userId);
            return;
        }
        throw new RuntimeException("회원 정보를 찾을 수 없습니다.");
    }
}
