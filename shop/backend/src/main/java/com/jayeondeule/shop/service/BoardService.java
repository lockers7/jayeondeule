package com.jayeondeule.shop.service;

import com.jayeondeule.shop.entity.BoardComment;
import com.jayeondeule.shop.entity.BoardImage;
import com.jayeondeule.shop.entity.BoardPost;
import com.jayeondeule.shop.repository.BoardCommentRepository;
import com.jayeondeule.shop.repository.BoardImageRepository;
import com.jayeondeule.shop.repository.BoardPostRepository;
import com.jayeondeule.shop.repository.ShopProductRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class BoardService {
    private final BoardPostRepository postRepo;
    private final BoardCommentRepository commentRepo;
    private final BoardImageRepository imageRepo;
    private final ShopProductRepository productRepo;
    private final JdbcTemplate jdbc;

    @Value("${board.upload.path:/workspace/jayeondeule/shop/frontend/dist/images/board}")
    private String uploadPath;

    // ========== 게시글 CRUD ==========

    public List<BoardPost> getPosts(String boardType, Long farmId) {
        List<BoardPost> posts = (farmId != null)
                ? postRepo.findByBoardTypeAndFarmIdAndDelYnOrderByRgstDtDesc(boardType, farmId, "N")
                : postRepo.findByBoardTypeAndDelYnOrderByRgstDtDesc(boardType, "N");

        // 댓글 수 세팅
        for (BoardPost post : posts) {
            post.setCommentCount(commentRepo.countByPostIdAndDelYn(post.getPostId(), "N"));
            if (post.getProductId() != null) {
                productRepo.findById(post.getProductId())
                        .ifPresent(p -> post.setProductName(p.getProductName()));
            }
        }
        return posts;
    }

    // 문의: 특정 사용자의 문의 목록
    public List<BoardPost> getMyInquiries(String writerId) {
        List<BoardPost> posts = postRepo.findByBoardTypeAndWriterIdAndDelYnOrderByRgstDtDesc("INQUIRY", writerId, "N");
        for (BoardPost post : posts) {
            post.setCommentCount(commentRepo.countByPostIdAndDelYn(post.getPostId(), "N"));
            if (post.getProductId() != null) {
                productRepo.findById(post.getProductId())
                        .ifPresent(p -> post.setProductName(p.getProductName()));
            }
        }
        return posts;
    }

    @Transactional
    public BoardPost getPost(Integer postId, String viewerId) {
        // 동일 사용자는 1회만 카운트 (viewerId = userId 또는 IP)
        if (viewerId != null && !viewerId.isEmpty()) {
            int inserted = jdbc.update(
                "INSERT INTO shop_board_post_view (post_id, viewer_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                postId, viewerId
            );
            if (inserted > 0) {
                postRepo.incrementViewCount(postId);
            }
        }
        return postRepo.findById(postId)
                .orElseThrow(() -> new RuntimeException("게시글을 찾을 수 없습니다."));
    }

    @Transactional
    public BoardPost createPost(BoardPost post) {
        return postRepo.save(post);
    }

    @Transactional
    public BoardPost updatePost(Integer postId, String title, String content, Integer productId, String userId) {
        BoardPost post = postRepo.findById(postId)
                .orElseThrow(() -> new RuntimeException("게시글을 찾을 수 없습니다."));
        if (!post.getWriterId().equals(userId)) {
            throw new RuntimeException("수정 권한이 없습니다.");
        }
        post.setTitle(title);
        post.setContent(content);
        if (productId != null) post.setProductId(productId);
        return postRepo.save(post);
    }

    @Transactional
    public void deletePost(Integer postId, String userId, boolean isAdmin) {
        BoardPost post = postRepo.findById(postId)
                .orElseThrow(() -> new RuntimeException("게시글을 찾을 수 없습니다."));
        if (!isAdmin && !post.getWriterId().equals(userId)) {
            throw new RuntimeException("삭제 권한이 없습니다.");
        }
        post.setDelYn("Y");
        postRepo.save(post);
    }

    // ========== 문의 완료 처리 ==========

    @Transactional
    public void resolvePost(Integer postId, boolean resolve) {
        BoardPost post = postRepo.findById(postId)
                .orElseThrow(() -> new RuntimeException("게시글을 찾을 수 없습니다."));
        post.setResolveYn(resolve ? "Y" : "N");
        postRepo.save(post);
    }

    // 대시보드: 문의 건수
    public Map<String, Integer> getInquiryStats() {
        int total = postRepo.countByBoardTypeAndDelYn("INQUIRY", "N");
        int pending = postRepo.countByBoardTypeAndDelYnAndResolveYn("INQUIRY", "N", "N");
        return Map.of("totalInquiries", total, "pendingInquiries", pending);
    }

    // ========== 댓글 CRUD ==========

    public List<BoardComment> getComments(Integer postId) {
        List<BoardComment> all = commentRepo.findByPostIdAndDelYnOrderByRgstDtAsc(postId, "N");

        // 댓글 이미지 일괄 조회
        List<Integer> commentIds = all.stream().map(BoardComment::getCommentId).toList();
        Map<Integer, List<BoardImage>> imageMap = new HashMap<>();
        if (!commentIds.isEmpty()) {
            List<BoardImage> allImages = imageRepo.findByCommentIdInOrderBySortOrder(commentIds);
            imageMap = allImages.stream().collect(Collectors.groupingBy(BoardImage::getCommentId));
        }

        // 트리 구조 구성
        Map<Integer, List<BoardComment>> childMap = new HashMap<>();
        List<BoardComment> roots = new ArrayList<>();

        for (BoardComment c : all) {
            c.setChildren(new ArrayList<>());
            c.setImages(imageMap.getOrDefault(c.getCommentId(), List.of()));
            if (c.getParentId() == null) {
                roots.add(c);
            } else {
                childMap.computeIfAbsent(c.getParentId(), k -> new ArrayList<>()).add(c);
            }
        }
        buildTree(roots, childMap);
        return roots;
    }

    private void buildTree(List<BoardComment> nodes, Map<Integer, List<BoardComment>> childMap) {
        for (BoardComment node : nodes) {
            List<BoardComment> children = childMap.getOrDefault(node.getCommentId(), List.of());
            node.setChildren(children);
            if (!children.isEmpty()) {
                buildTree(children, childMap);
            }
        }
    }

    @Transactional
    public BoardComment createComment(BoardComment comment) {
        return commentRepo.save(comment);
    }

    @Transactional
    public void deleteComment(Integer commentId, String userId, boolean isAdmin) {
        BoardComment comment = commentRepo.findById(commentId)
                .orElseThrow(() -> new RuntimeException("댓글을 찾을 수 없습니다."));
        if (!isAdmin && !comment.getWriterId().equals(userId)) {
            throw new RuntimeException("삭제 권한이 없습니다.");
        }
        comment.setDelYn("Y");
        commentRepo.save(comment);
    }

    // ========== 이미지 업로드 ==========

    public List<BoardImage> getPostImages(Integer postId) {
        return imageRepo.findByPostIdOrderBySortOrder(postId);
    }

    @Transactional
    public List<String> uploadImages(MultipartFile[] files, Integer postId, Integer commentId, String[] captions) {
        List<String> urls = new ArrayList<>();
        try {
            String subDir = postId != null ? "post/" + postId : "comment/" + commentId;
            Path dir = Paths.get(uploadPath, subDir);
            Files.createDirectories(dir);

            for (int i = 0; i < files.length; i++) {
                MultipartFile file = files[i];
                String ext = getExtension(file.getOriginalFilename());
                String fileName = UUID.randomUUID().toString().substring(0, 8) + ext;
                Path filePath = dir.resolve(fileName);
                file.transferTo(filePath.toFile());

                String url = "/uploads/board/" + subDir + "/" + fileName;

                String caption = (captions != null && i < captions.length) ? captions[i] : null;
                BoardImage image = BoardImage.builder()
                        .postId(postId)
                        .commentId(commentId)
                        .imageUrl(url)
                        .sortOrder(i)
                        .caption(caption)
                        .build();
                imageRepo.save(image);
                urls.add(url);
            }
        } catch (IOException e) {
            log.error("이미지 업로드 오류: {}", e.getMessage());
            throw new RuntimeException("이미지 업로드에 실패했습니다.");
        }
        return urls;
    }

    @Transactional
    public void deletePostImages(Integer postId) {
        imageRepo.deleteByPostId(postId);
    }

    private String getExtension(String filename) {
        if (filename == null) return ".jpg";
        int idx = filename.lastIndexOf('.');
        return idx >= 0 ? filename.substring(idx) : ".jpg";
    }
}
