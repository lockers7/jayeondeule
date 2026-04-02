package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.BoardComment;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface BoardCommentRepository extends JpaRepository<BoardComment, Integer> {

    List<BoardComment> findByPostIdAndDelYnOrderByRgstDtAsc(Integer postId, String delYn);

    int countByPostIdAndDelYn(Integer postId, String delYn);
}
