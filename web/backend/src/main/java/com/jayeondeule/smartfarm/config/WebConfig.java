package com.jayeondeule.smartfarm.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

// CORS 설정은 SecurityConfig.corsConfigurationSource()에서 통합 관리
@Configuration
public class WebConfig implements WebMvcConfigurer {
}
