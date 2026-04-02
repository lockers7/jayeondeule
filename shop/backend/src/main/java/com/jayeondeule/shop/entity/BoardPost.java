package com.jayeondeule.shop.entity;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "shop_board_post")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class BoardPost {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "post_id")
    private Integer postId;

    @Column(name = "farm_id", nullable = false)
    private Long farmId;

    @Column(name = "board_type", nullable = false)
    private String boardType;

    @Column(name = "product_id")
    private Integer productId;

    @Column(nullable = false)
    private String title;

    @Column(columnDefinition = "TEXT", nullable = false)
    private String content;

    @Column(name = "writer_id", nullable = false)
    private String writerId;

    @Column(name = "writer_name", nullable = false)
    private String writerName;

    @Column(name = "view_count")
    private Integer viewCount;

    @Column(name = "del_yn", nullable = false)
    private String delYn;

    @Column(name = "resolve_yn", nullable = false)
    private String resolveYn;

    @Column(name = "rgst_dt")
    private LocalDateTime rgstDt;

    @Column(name = "updt_dt")
    private LocalDateTime updtDt;

    @Transient
    private Integer commentCount;

    @Transient
    private String productName;

    @PrePersist
    public void prePersist() {
        if (rgstDt == null) rgstDt = LocalDateTime.now();
        if (delYn == null) delYn = "N";
        if (resolveYn == null) resolveYn = "N";
        if (viewCount == null) viewCount = 0;
    }

    @PreUpdate
    public void preUpdate() {
        updtDt = LocalDateTime.now();
    }
}
