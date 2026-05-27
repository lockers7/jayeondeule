package com.jayeondeule.shop.filter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.ContentCachingRequestWrapper;
import org.springframework.web.util.ContentCachingResponseWrapper;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

@Slf4j
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestLoggingFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
            FilterChain chain)
            throws ServletException, IOException {

        ContentCachingRequestWrapper reqWrapper = new ContentCachingRequestWrapper(request, 1024 * 1024);
        ContentCachingResponseWrapper resWrapper = new ContentCachingResponseWrapper(response);

        long startTime = System.currentTimeMillis();
        String clientIp = getClientIp(request);
        String method = request.getMethod();
        String uri = request.getRequestURI();
        String query = request.getQueryString();
        String userId = request.getHeader("Authorization") != null ? "(인증)" : "(비인증)";

        try {
            chain.doFilter(reqWrapper, resWrapper);
        } finally {
            long elapsed = System.currentTimeMillis() - startTime;
            int status = resWrapper.getStatus();

            // 요청 본문 (POST/PUT/PATCH만, 비밀번호 마스킹)
            String reqBody = "";
            if ("POST".equals(method) || "PUT".equals(method) || "PATCH".equals(method)) {
                reqBody = new String(reqWrapper.getContentAsByteArray(), StandardCharsets.UTF_8);
                reqBody = maskSensitive(reqBody);
                if (reqBody.length() > 500)
                    reqBody = reqBody.substring(0, 500) + "...(truncated)";
            }

            // 응답 본문 (오류 시만)
            String resBody = "";
            if (status >= 400) {
                resBody = new String(resWrapper.getContentAsByteArray(), StandardCharsets.UTF_8);
                if (resBody.length() > 500)
                    resBody = resBody.substring(0, 500) + "...(truncated)";
            }

            // 로그 출력
            if (status >= 500) {
                log.error("[{}] {} {} {} -> {} ({}ms) IP:{} Body:{} Response:{}",
                        userId, method, uri, query != null ? "?" + query : "", status, elapsed, clientIp, reqBody,
                        resBody);
            } else if (status >= 400) {
                log.warn("[{}] {} {} {} -> {} ({}ms) IP:{} Body:{} Response:{}",
                        userId, method, uri, query != null ? "?" + query : "", status, elapsed, clientIp, reqBody,
                        resBody);
            } else {
                log.info("[{}] {} {} {} -> {} ({}ms) IP:{}{}",
                        userId, method, uri, query != null ? "?" + query : "", status, elapsed, clientIp,
                        reqBody.isEmpty() ? "" : " Body:" + reqBody);
            }

            resWrapper.copyBodyToResponse();
        }
    }

    private String getClientIp(HttpServletRequest request) {
        String ip = request.getHeader("X-Forwarded-For");
        if (ip == null || ip.isEmpty())
            ip = request.getHeader("X-Real-IP");
        if (ip == null || ip.isEmpty())
            ip = request.getRemoteAddr();
        if (ip != null && ip.contains(","))
            ip = ip.split(",")[0].trim();
        return ip;
    }

    private String maskSensitive(String body) {
        return body.replaceAll("\"passwd\"\\s*:\\s*\"[^\"]*\"", "\"passwd\":\"****\"")
                .replaceAll("\"password\"\\s*:\\s*\"[^\"]*\"", "\"password\":\"****\"");
    }
}
