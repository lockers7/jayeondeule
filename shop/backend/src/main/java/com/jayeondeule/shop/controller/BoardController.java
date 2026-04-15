package com.jayeondeule.shop.controller;

import com.jayeondeule.shop.dto.ApiResponse;
import com.jayeondeule.shop.entity.BoardComment;
import com.jayeondeule.shop.entity.BoardPost;
import com.jayeondeule.shop.service.BoardService;
import com.jayeondeule.shop.util.JwtUtil;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.Map;
import java.util.Set;

@RestController
@RequestMapping("/api/shop/board")
@RequiredArgsConstructor
public class BoardController {
    private final BoardService boardService;
    private final JwtUtil jwtUtil;
    private final com.jayeondeule.shop.repository.ShopUserRepository userRepo;

    private static final Set<String> ADMIN_GRADES = Set.of("SYSTEM_ADMIN", "SHOP_ADMIN");

    // JWT에서 사용자 정보 추출
    private String getUserId(String authHeader) {
        return jwtUtil.getUserId(authHeader.substring(7));
    }

    private String getUserGrade(String authHeader) {
        return jwtUtil.getUserGrade(authHeader.substring(7));
    }

    private String getUserName(String authHeader) {
        String name = jwtUtil.getUserName(authHeader.substring(7));
        if (name != null && !name.isEmpty()) return name;
        // JWT에 usrName이 없으면 DB에서 조회 (구 토큰 호환)
        String userId = getUserId(authHeader);
        return userRepo.findById(userId)
                .map(u -> u.getUsrName())
                .orElse(userId);
    }

    private boolean isAdmin(String authHeader) {
        return ADMIN_GRADES.contains(getUserGrade(authHeader));
    }

    // ========== 게시글 ==========

    // 게시글 목록 (공개 - 농장 이야기)
    @GetMapping("/posts")
    public ResponseEntity<?> getPosts(
            @RequestParam String boardType,
            @RequestParam(required = false) Long farmId) {
        return ResponseEntity.ok(ApiResponse.ok(boardService.getPosts(boardType, farmId)));
    }

    // 내 문의 목록
    @GetMapping("/posts/my")
    public ResponseEntity<?> getMyPosts(
            @RequestHeader("Authorization") String authHeader,
            @RequestParam String boardType) {
        return ResponseEntity.ok(ApiResponse.ok(boardService.getMyInquiries(getUserId(authHeader))));
    }

    // 게시글 상세
    @GetMapping("/posts/{postId}")
    public ResponseEntity<?> getPost(
            @PathVariable Integer postId,
            @RequestHeader(value = "Authorization", required = false) String authHeader,
            jakarta.servlet.http.HttpServletRequest request) {
        try {
            // viewer_id: 로그인 사용자는 userId, 비로그인은 IP
            String viewerId = null;
            if (authHeader != null && authHeader.startsWith("Bearer ")) {
                try { viewerId = jwtUtil.getUserId(authHeader.substring(7)); } catch (Exception ignored) {}
            }
            if (viewerId == null || viewerId.isEmpty()) {
                String xff = request.getHeader("X-Forwarded-For");
                viewerId = (xff != null && !xff.isEmpty()) ? xff.split(",")[0].trim() : request.getRemoteAddr();
            }
            BoardPost post = boardService.getPost(postId, viewerId);
            return ResponseEntity.ok(ApiResponse.ok(post));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    // 게시글 작성
    @PostMapping("/posts")
    public ResponseEntity<?> createPost(
            @RequestHeader("Authorization") String authHeader,
            @RequestBody Map<String, Object> body) {
        try {
            BoardPost post = BoardPost.builder()
                    .farmId(Long.valueOf(body.getOrDefault("farmId", 1).toString()))
                    .boardType((String) body.get("boardType"))
                    .productId(body.get("productId") != null ? Integer.valueOf(body.get("productId").toString()) : null)
                    .title((String) body.get("title"))
                    .content((String) body.get("content"))
                    .writerId(getUserId(authHeader))
                    .writerName(getUserName(authHeader))
                    .build();
            BoardPost saved = boardService.createPost(post);
            return ResponseEntity.ok(ApiResponse.ok("게시글이 등록되었습니다.", saved));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    // 게시글 수정
    @PutMapping("/posts/{postId}")
    public ResponseEntity<?> updatePost(
            @PathVariable Integer postId,
            @RequestHeader("Authorization") String authHeader,
            @RequestBody Map<String, Object> body) {
        try {
            Integer productId = body.get("productId") != null ? Integer.valueOf(body.get("productId").toString()) : null;
            BoardPost updated = boardService.updatePost(
                    postId, (String) body.get("title"), (String) body.get("content"), productId, getUserId(authHeader));
            return ResponseEntity.ok(ApiResponse.ok("게시글이 수정되었습니다.", updated));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    // 게시글 삭제
    @DeleteMapping("/posts/{postId}")
    public ResponseEntity<?> deletePost(
            @PathVariable Integer postId,
            @RequestHeader("Authorization") String authHeader) {
        try {
            boardService.deletePost(postId, getUserId(authHeader), isAdmin(authHeader));
            return ResponseEntity.ok(ApiResponse.ok("게시글이 삭제되었습니다.", null));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    // 문의 완료/미완료 토글 (관리자 전용)
    @PatchMapping("/posts/{postId}/resolve")
    public ResponseEntity<?> resolvePost(
            @PathVariable Integer postId,
            @RequestHeader("Authorization") String authHeader,
            @RequestBody Map<String, Object> body) {
        if (!isAdmin(authHeader)) {
            return ResponseEntity.status(403).body(ApiResponse.error("권한이 없습니다."));
        }
        try {
            boolean resolve = Boolean.TRUE.equals(body.get("resolve"));
            boardService.resolvePost(postId, resolve);
            return ResponseEntity.ok(ApiResponse.ok(resolve ? "완료 처리되었습니다." : "미완료로 변경되었습니다.", null));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    // ========== 댓글 ==========

    // 댓글 목록 (트리 구조)
    @GetMapping("/posts/{postId}/comments")
    public ResponseEntity<?> getComments(@PathVariable Integer postId) {
        return ResponseEntity.ok(ApiResponse.ok(boardService.getComments(postId)));
    }

    // 댓글 작성
    @PostMapping("/posts/{postId}/comments")
    public ResponseEntity<?> createComment(
            @PathVariable Integer postId,
            @RequestHeader("Authorization") String authHeader,
            @RequestBody Map<String, Object> body) {
        try {
            BoardComment comment = BoardComment.builder()
                    .postId(postId)
                    .parentId(body.get("parentId") != null ? Integer.valueOf(body.get("parentId").toString()) : null)
                    .content((String) body.get("content"))
                    .writerId(getUserId(authHeader))
                    .writerName(getUserName(authHeader))
                    .build();
            BoardComment saved = boardService.createComment(comment);
            return ResponseEntity.ok(ApiResponse.ok("댓글이 등록되었습니다.", saved));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    // 댓글 삭제
    @DeleteMapping("/comments/{commentId}")
    public ResponseEntity<?> deleteComment(
            @PathVariable Integer commentId,
            @RequestHeader("Authorization") String authHeader) {
        try {
            boardService.deleteComment(commentId, getUserId(authHeader), isAdmin(authHeader));
            return ResponseEntity.ok(ApiResponse.ok("댓글이 삭제되었습니다.", null));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    // ========== 이미지 ==========

    // 게시글 이미지 목록
    @GetMapping("/posts/{postId}/images")
    public ResponseEntity<?> getPostImages(@PathVariable Integer postId) {
        return ResponseEntity.ok(ApiResponse.ok(boardService.getPostImages(postId)));
    }

    // 이미지 업로드
    @PostMapping("/images/upload")
    public ResponseEntity<?> uploadImages(
            @RequestParam("files") MultipartFile[] files,
            @RequestParam(required = false) Integer postId,
            @RequestParam(required = false) Integer commentId,
            @RequestParam(required = false) String[] captions) {
        try {
            return ResponseEntity.ok(ApiResponse.ok(boardService.uploadImages(files, postId, commentId, captions)));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }
}
