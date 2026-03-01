# Web 코드 안정화 계획서

> 작성일: 2026-03-01
> 대상: Spring Boot 백엔드 + React 프론트엔드
> 원칙: **기능 변경 0%, 코드 안정화만 수행**
> 이전 계획서: `CodeOptimizing.md` (1차), `CodeOptimizing_2nd.md` (2차), `CodeOptimizing_3rd.md` (3차, 시스템 통합)

---

## 1. 분석 범위

| 영역 | 경로 | 파일 수 |
|------|------|--------|
| Spring Boot 백엔드 | `web/backend/src/main/java/com/jayeondeule/smartfarm/` | 76개 |
| React 프론트엔드 | `web/frontend/src/` | 약 40개 |

---

## 2. 발견 항목 요약

| 우선순위 | 건수 | 설명 |
|---------|------|------|
| **P0 (긴급)** | **2건** | API URL 오류, @IdClass 오류 |
| **P1 (중요)** | **10건** | 콘솔 로그 제거, 중복 설정 통합, DI 패턴 개선, JWT 로깅 |
| **P2 (개선)** | **10건** | 미사용 import 정리, 주석 코드 제거, 코드 스타일 통일 |
| **합계** | **22건** | - |

---

## 3. Spring Boot 백엔드

### 3.1 [P0] @IdClass 오류 — RelayRecording 엔티티

**파일**: `web/backend/.../entity/relay/RelayRecording.java`

```
현재: @IdClass(RelayRecording.class)   ← 자기 자신을 참조 (오류)
수정: @IdClass(RelayRecordingId.class) ← 올바른 ID 클래스 참조
```

**위험도**: 높음 — 현재 동작하고 있다면 JPA 구현체가 우회하는 것이며, 업그레이드 시 장애 가능

---

### 3.2 [P1] SecurityConfig @Autowired + 생성자 주입 혼합

**파일**: `web/backend/.../config/SecurityConfig.java` (28~35행)

```
현재:
  @Autowired                       ← 필드 주입
  private final SwaggerBeanUtil swaggerBeanUtility;
  private final JwtUtil jwtUtil;
  public SecurityConfig(...) { ... }  ← 생성자 주입

수정:
  @Autowired 제거 (생성자 주입만 유지, 또는 @RequiredArgsConstructor 사용)
```

**이유**: final 필드에 @Autowired는 모순, 생성자 주입이 이미 존재하므로 불필요

---

### 3.3 [P1] CORS 설정 이중 정의

**파일**: `SecurityConfig.java` (62~70행) + `WebConfig.java` (14~19행)

```
현재: 동일한 CORS 원본(origins)이 두 곳에서 하드코딩
  - SecurityConfig: List.of("http://localhost:5173", "https://lockers7.iptime.org", ...)
  - WebConfig: "http://localhost:5173", "https://lockers7.iptime.org", ...

수정: CORS 원본을 application.properties에 정의하고, 한 곳에서만 CORS 설정
  app.cors.allowed-origins=http://localhost:5173,https://lockers7.iptime.org,http://lockers7.iptime.org
```

---

### 3.4 [P1] ObjectMapper 초기화 패턴 불일치 (6개 Service)

**파일**: AuthService, FarmService, HouseService, SettingService, SensorService, MemoService

```
현재:
  - AuthService: 메서드 내부에서 매번 new ObjectMapper() 생성
  - 나머지: 필드 선언 + @PostConstruct로 JavaTimeModule 등록

수정: ObjectMapper를 @Bean으로 등록하고, 모든 Service에서 주입받아 사용
  @Configuration
  public class JacksonConfig {
      @Bean
      public ObjectMapper objectMapper() {
          ObjectMapper mapper = new ObjectMapper();
          mapper.registerModule(new JavaTimeModule());
          return mapper;
      }
  }
```

---

### 3.5 [P1] JwtAuthFilter 예외 처리 — 로깅 부재

**파일**: `web/backend/.../filter/JwtAuthFilter.java` (63~67행)

```
현재:
  catch (Exception e) {
      response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
      return;
  }

수정:
  catch (Exception e) {
      log.warn("JWT 인증 실패: {}", e.getMessage());
      response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
      return;
  }
```

**이유**: JWT 에러 원인 추적 불가 (만료, 서명 오류, 형식 오류 구분 불가)

---

### 3.6 [P1] ID 클래스 equals/hashCode → @EqualsAndHashCode

**파일**: SensorRecordingId, RelayRecordingId, FarmHouseCropsId, LightIrrigationSettingId

```
현재: 수동 equals/hashCode 구현 (약 15줄씩, 4개 파일 = 60줄)
수정: Lombok @EqualsAndHashCode 적용 (4줄로 축소)

  @Getter @Setter
  @EqualsAndHashCode
  public class SensorRecordingId implements Serializable { ... }
```

---

### 3.7 [P1] JwtUtil 주석 코드 정리

**파일**: `web/backend/.../util/JwtUtil.java` (20~22행)

```
현재:
  //    private final long accessTokenValidity = 1000L * 60 * 60 * 2; // 2시간
  private final long accessTokenValidity = 1000L * 60 * 60 * 24 * 7; // 7일(임시)
  //    private final long refreshTokenValidity = 1000L * 60 * 60 * 24 * 7; // 7일

수정:
  // 토큰 유효기간 — 운영 시 application.properties로 이관 검토
  private final long accessTokenValidity = 1000L * 60 * 60 * 24 * 7; // 7일
```

---

### 3.8 [P2] FarmController 주석 처리된 기능 코드

**파일**: `web/backend/.../controller/FarmController.java` (79~80행)

```
현재:
  } else if (...) {
      //  farmService.patchFarmByFarmId(farmId, modifiedInfo);
  }

수정: 빈 분기 제거 또는 TODO 명시
```

---

### 3.9 [P2] MemoService N+1 쿼리

**파일**: `web/backend/.../service/MemoService.java` (47~54행)

```
현재:
  result.forEach(item ->
      item.setAthrName(userRepository.findByUserId(item.getAthr()).getUserName())
  );
  // ↑ 메모 N건 × userRepository 쿼리 1회 = N+1 문제

수정: 사용자 ID를 배치로 조회
  Set<String> authorIds = memoList.map(FarmHouseCrops::getAthr).collect(toSet());
  Map<String, String> nameMap = userRepository.findByUserIdIn(authorIds)
      .stream().collect(toMap(User::getUserId, User::getUserName));
  result.forEach(item -> item.setAthrName(nameMap.get(item.getAthr())));
```

---

## 4. React 프론트엔드

### 4.1 [P0] apiRoutes.js URL 문법 오류

**파일**: `web/frontend/src/utils/apiRoutes.js` (114행)

```
현재: url: `${BASE_URL}/farms/me}`   ← 닫는 중괄호 잔류
수정: url: `${BASE_URL}/farms/me`
```

**위험도**: 높음 — "내 농장 조회" API 호출 실패 가능

---

### 4.2 [P1] console.log 제거 (3건)

| 파일 | 줄 | 내용 |
|------|---|------|
| `utils/memoUtil.js` | 15 | `console.log(content)` |
| `pages/house/HouseRegisterPage.jsx` | 23 | `console.log(form)` |
| `components/memo/MemoDashboard.jsx` | 113 | `console.log(memoId)` |

```
수정: 3개 console.log 라인 제거
```

---

### 4.3 [P1] 미사용 import 정리 (3건)

| 파일 | 줄 | 미사용 항목 |
|------|---|------------|
| `pages/common/Header.jsx` | 1, 8 | `useEffect`, `useState`, `getUser` |
| `pages/farm/FarmMonitoringPage.jsx` | 23 | `LatestSensorItem` |

```
수정: 미사용 import 문 제거
```

---

### 4.4 [P1] ChatInput.jsx 주석 처리된 코드 제거

**파일**: `web/frontend/src/components/ai/ChatInput.jsx` (37~41행)

```
현재:
  {/* 자전거 애니메이션 숨김
  <div style={{height: "32px", ...}}>
      {isLoading && <span className="chat-running-bicycle">🚴</span>}
  </div>
  */}

수정: 주석 블록 완전 제거
```

---

### 4.5 [P1] useEffect 의존성 배열 보완 (3건)

| 파일 | 줄 | 누락된 의존성 |
|------|---|-------------|
| `pages/farm/FarmMonitoringPage.jsx` | 90~94 | `farmId`, `navigate` |
| `components/memo/MemoDashboard.jsx` | 58~62 | `farmId` |
| `components/relay/RelayDashboard.jsx` | 17~51 | `farmId` |

```
주의: 의존성 추가 시 무한 루프 발생 가능성 검토 필요
방안: 각 useEffect 내부에서 조건 분기로 불필요한 재실행 방지 확인 후 적용
```

---

### 4.6 [P2] ChatMessageList.jsx key prop 개선

**파일**: `web/frontend/src/components/ai/ChatMessageList.jsx` (30~31행)

```
현재: key={index}   ← 배열 인덱스를 key로 사용
수정: key={msg.timestamp || `msg-${index}`}
      또는 메시지 객체에 고유 ID 부여
```

---

### 4.7 [P2] .catch(console.error) 패턴 (2건)

**파일**: `components/ai/ChatSidebar.jsx` (26, 40행)

```
현재: .catch(console.error)
수정: .catch(err => { console.error(err); })
      — 향후 사용자 피드백 추가 용이하도록 화살표 함수로 통일
```

---

## 5. 제외 항목 (기능 변경 위험)

| 항목 | 이유 |
|------|------|
| RelayRecording boolean 16개 → 배열 전환 | DB 스키마 변경 필요, 기능 변경 |
| AuthService RuntimeException → 커스텀 예외 | 에러 응답 형식 변경, 프론트엔드 영향 |
| HouseService null 반환 → 예외 전환 | API 계약 변경, 프론트엔드 영향 |
| SensorService 형변환 최적화 | DB 반환 타입에 따라 ClassCastException 위험 |
| 릴레이 라벨 하드코딩 → 설정 분리 | 설정 체계 변경, UI 동작 변경 가능 |
| 인라인 스타일 → CSS 분리 | 렌더링 차이 가능, 대규모 리팩토링 |
| Relay polling 간격 조정 | 실시간성 변경, 운영 정책 결정 필요 |

---

## 6. 권장 실행 순서

```
Phase 1 — P0 긴급 수정 (2건, 즉시)
  ├─ WEB-01: @IdClass 오류 수정 (RelayRecording.java)
  └─ WEB-02: apiRoutes.js URL 문법 오류 수정

Phase 2 — P1 안정화 (10건)
  ├─ WEB-03: SecurityConfig @Autowired 제거
  ├─ WEB-04: CORS 설정 통합
  ├─ WEB-05: ObjectMapper @Bean 등록 + Service 주입 통일
  ├─ WEB-06: JwtAuthFilter JWT 에러 로깅 추가
  ├─ WEB-07: ID 클래스 @EqualsAndHashCode 적용 (4개 파일)
  ├─ WEB-08: JwtUtil 주석 코드 정리
  ├─ WEB-09: console.log 제거 (3건)
  ├─ WEB-10: 미사용 import 정리 (3건)
  ├─ WEB-11: ChatInput 주석 코드 제거
  └─ WEB-12: useEffect 의존성 보완 (3건, 신중히)

Phase 3 — P2 코드 정리 (4건)
  ├─ WEB-13: FarmController 주석 분기 정리
  ├─ WEB-14: MemoService N+1 쿼리 개선
  ├─ WEB-15: ChatMessageList key prop 개선
  └─ WEB-16: .catch(console.error) 통일
```
