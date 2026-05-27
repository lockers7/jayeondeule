package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.BoardPost;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import java.util.List;

public interface BoardPostRepository extends JpaRepository<BoardPost, Integer> {

    List<BoardPost> findByBoardTypeAndDelYnOrderByRgstDtDesc(String boardType, String delYn);

    List<BoardPost> findByBoardTypeAndFarmIdAndDelYnOrderByRgstDtDesc(String boardType, Long farmId, String delYn);

    // 문의: 특정 사용자의 문의 목록
    List<BoardPost> findByBoardTypeAndWriterIdAndDelYnOrderByRgstDtDesc(String boardType, String writerId, String delYn);

    // 대시보드: 문의 건수
    int countByBoardTypeAndDelYn(String boardType, String delYn);
    int countByBoardTypeAndDelYnAndResolveYn(String boardType, String delYn, String resolveYn);

    @Modifying
    @Query("UPDATE BoardPost p SET p.viewCount = p.viewCount + 1 WHERE p.postId = :postId")
    void incrementViewCount(Integer postId);
}
