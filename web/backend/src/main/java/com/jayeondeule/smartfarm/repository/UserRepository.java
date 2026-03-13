package com.jayeondeule.smartfarm.repository;

import com.jayeondeule.smartfarm.entity.user.User;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.List;

@Repository
public interface UserRepository extends JpaRepository<User, String> {
    User findByUserId(String userId);

    List<User> findByUserIdIn(Collection<String> userIds);

    boolean existsByUserId(String userId);

    Page<User> findAllByFarmId(long farmId, Pageable pageable);

    // dlteYn 조건 추가 메서드
    Page<User> findAllByDlteYn(String dlteYn, Pageable pageable);

    Page<User> findAllByFarmIdAndDlteYn(long farmId, String dlteYn, Pageable pageable);
}
