package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.ShopUser;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface ShopUserRepository extends JpaRepository<ShopUser, String> {
    List<ShopUser> findByFarmIdAndUsrStatusOrderByRgstDtDesc(Long farmId, String usrStatus);
    List<ShopUser> findByFarmIdAndUsrGradeAndUsrStatusOrderByRgstDtDesc(Long farmId, String usrGrade, String usrStatus);
    boolean existsByShopUsrId(String shopUsrId);
    long countByFarmIdAndUsrGradeAndUsrStatus(Long farmId, String usrGrade, String usrStatus);
}
