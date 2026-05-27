package com.jayeondeule.shop.config;

import com.jayeondeule.shop.filter.JwtAuthFilter;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import java.util.List;

@Configuration
@EnableWebSecurity
@RequiredArgsConstructor
public class SecurityConfig {
    private final JwtAuthFilter jwtAuthFilter;

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .cors(c -> c.configurationSource(corsSource()))
            .csrf(c -> c.disable())
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/api/shop/auth/**").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/shop/products/view-ranking").hasAnyRole("SYSTEM_ADMIN", "SHOP_ADMIN", "MONITOR")
                .requestMatchers(HttpMethod.GET, "/api/shop/products/**").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/shop/categories/**").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/shop/board/posts").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/shop/board/posts/{postId}").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/shop/board/posts/{postId}/comments").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/shop/board/posts/{postId}/images").permitAll()
                .requestMatchers("/api/shop/lotto/**").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/shop/admin/**").hasAnyRole("SYSTEM_ADMIN", "SHOP_ADMIN", "MONITOR")
                .requestMatchers("/api/shop/admin/**").hasAnyRole("SYSTEM_ADMIN", "SHOP_ADMIN")
                .requestMatchers("/api/shop/system/**").hasRole("SYSTEM_ADMIN")
                .anyRequest().authenticated()
            )
            .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    CorsConfigurationSource corsSource() {
        var config = new CorsConfiguration();
        config.setAllowedOrigins(List.of(
                "http://localhost:5173",
                "http://localhost:5174",
                "https://lockers7.iptime.org",
                "http://lockers7.iptime.org",
                "https://lockers7.iptime.org:5100",
                "http://lockers7.iptime.org:5100"
        ));
        config.setAllowedMethods(List.of("*"));
        config.setAllowedHeaders(List.of("*"));
        config.setAllowCredentials(true);
        var source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }
}
