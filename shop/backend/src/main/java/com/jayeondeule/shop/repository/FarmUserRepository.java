package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.FarmUser;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface FarmUserRepository extends JpaRepository<FarmUser, String> {
    Optional<FarmUser> findByUserIdAndDlteYn(String userId, String dlteYn);
}
