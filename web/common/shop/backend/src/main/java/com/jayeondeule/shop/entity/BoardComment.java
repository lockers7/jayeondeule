package com.jayeondeule.shop.entity;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;
import java.util.List;

@Entity
@Table(name = "shop_board_comment")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class BoardComment {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "comment_id")
    private Integer commentId;

    @Column(name = "post_id", nullable = false)
    private Integer postId;

    @Column(name = "parent_id")
    private Integer parentId;

    @Column(columnDefinition = "TEXT", nullable = false)
    private String content;

    @Column(name = "writer_id", nullable = false)
    private String writerId;

    @Column(name = "writer_name", nullable = false)
    private String writerName;

    @Column(name = "del_yn", nullable = false)
    private String delYn;

    @Column(name = "rgst_dt")
    private LocalDateTime rgstDt;

    @Column(name = "updt_dt")
    private LocalDateTime updtDt;

    @Transient
    private List<BoardComment> children;

    @Transient
    private List<BoardImage> images;

    @PrePersist
    public void prePersist() {
        if (rgstDt == null) rgstDt = LocalDateTime.now();
        if (delYn == null) delYn = "N";
    }

    @PreUpdate
    public void preUpdate() {
        updtDt = LocalDateTime.now();
    }
}
