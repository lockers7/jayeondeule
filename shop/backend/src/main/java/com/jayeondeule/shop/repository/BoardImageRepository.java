package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.BoardImage;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface BoardImageRepository extends JpaRepository<BoardImage, Integer> {

    List<BoardImage> findByPostIdOrderBySortOrder(Integer postId);

    List<BoardImage> findByCommentIdOrderBySortOrder(Integer commentId);

    List<BoardImage> findByPostIdInOrderBySortOrder(List<Integer> postIds);

    List<BoardImage> findByCommentIdInOrderBySortOrder(List<Integer> commentIds);

    void deleteByPostId(Integer postId);

    void deleteByCommentId(Integer commentId);
}
