# raspi/v1 히터밸브 OFF 로직 분석 결과

## 분석 일시
2025-12-17 23:00

## 분석 대상
`./raspi/v1` 디렉토리 하위 Python 코드에서 히터밸브(relay_15st_flag)를 OFF로 설정하는 로직 여부 확인

---

## 결론

**히터밸브를 직접 OFF로 설정하는 로직은 발견되지 않음**

---

## 상세 분석

### 1. 2호 재배사 전용 코드

`raspi/v1`은 **2호 재배사 전용** 코드입니다:
- `hous_id=2`가 모든 쿼리에 하드코딩되어 있음
- 1호, 3호 재배사와는 별도로 동작

### 2. 릴레이 구성

**[raspi/v1/gpio/gpio_config.py:2](raspi/v1/gpio/gpio_config.py#L2)**
```python
RELAY_GPIO = [0, 5, 6, 13, 19, 26, 23, 24, 25, 16, 20, 21, 17, 27, 22]  # 15개
USING_RELAY_CNT = 15
```

**2호 재배사 릴레이 매핑:**
- relay_1st: 수온히터1
- relay_2st: 물순환모터
- relay_3st: 라디에이터
- relay_4st: 수온히터2
- relay_5st: **조명** (1호/3호와 다름, 1호/3호는 relay_7st)
- relay_6st: **관수** (1호/3호와 다름, 1호/3호는 relay_8st)
- relay_7st: 흡입환풍모터
- relay_8st: 배출환풍모터
- relay_9st: 공기순환밸브
- relay_10st: 공기흡입밸브
- relay_11st: 공기배출밸브
- relay_12st: 배수모터
- relay_13st~15st: **미사용**
- relay_16st: **미사용** (데이터베이스에만 존재, GPIO 없음)

### 3. 릴레이 제어 흐름

**[raspi/v1/main.py:185-190](raspi/v1/main.py#L185-L190)**
```python
# 1. 데이터베이스에서 릴레이 상태 읽기
base_relay_st, base_relay_len = db.get_base_relay_st()

# 2. 읽은 상태대로 GPIO 제어
for i in range(base_relay_len):
    single_relay_status = getattr(base_relay_st, f'relay_{i+1}_st')
    gpio.relay_control(i, single_relay_status)

# 3. 현재 GPIO 상태를 데이터베이스에 저장
db.set_base_relay_st(gpio.relay_st, auto_record_data.recd_date)
```

**흐름:**
1. `RELAY_L_RECORDING` 테이블에서 최신 릴레이 상태 조회
2. 조회한 값대로 실제 GPIO 핀 제어
3. 제어 후 현재 상태를 다시 데이터베이스에 저장

### 4. 발견된 문제 및 수정

**문제:**
**[raspi/v1/sql/sql_query.py:6](raspi/v1/sql/sql_query.py#L6)** (수정 전)
```python
INSERT_RELAY_STATUS_SQL = "INSERT INTO RELAY_L_RECORDING (..., relay_15st_flag, relay_16st_flag, ...)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, False, %s, 2, %s);"
#                                                                                                    ↑
#                                                                                              relay_16st_flag가 False로 하드코딩
```

- relay_16st_flag가 `False`로 하드코딩되어 있었음
- **relay_15st_flag는 정상적으로 파라미터(%s) 전달됨**
- 15개 릴레이 값만 전달하고 16번째는 하드코딩 사용

**수정 내용:**

1. **[raspi/v1/sql/sql_query.py:7](raspi/v1/sql/sql_query.py#L7)** (수정 후)
   ```python
   # relay_16st_flag를 %s로 변경하여 파라미터로 받도록 수정
   INSERT_RELAY_STATUS_SQL = "... VALUES (%s, %s, ..., %s, %s, %s, 2, %s);"
   #                                                       ↑
   #                                                  relay_16st_flag도 파라미터로
   ```

2. **[raspi/v1/sql/sql_control.py:36-41](raspi/v1/sql/sql_control.py#L36-L41)** (수정 후)
   ```python
   def set_base_relay_st(self, relay_st: sql_format.BaseRelayFlagFormat, recd_date: str):
       # 15개 릴레이 데이터 수집
       relay_data = [getattr(relay_st, f'relay_{i+1}_st') for i in range(gpioCfg.USING_RELAY_CNT)]
       # relay_16st_flag 추가 (항상 False)
       relay_data.append(False)
       # farm_id, recd_date 추가
       self.cursor.execute(sql_query.INSERT_RELAY_STATUS_SQL, relay_data + [self.farm_id, recd_date])
   ```

### 5. relay_15st_flag 처리

**2호 재배사에서 relay_15st_flag:**
- GPIO 핀에 연결되어 있음 (15번째 릴레이)
- "미사용"으로 표시되어 있지만 물리적으로 존재
- 데이터베이스에서 읽은 값대로 제어됨
- **직접 OFF로 설정하는 로직 없음**

**데이터 흐름:**
```
데이터베이스(RELAY_L_RECORDING)
    ↓ (SELECT 쿼리로 읽기)
라즈베리파이 메모리
    ↓ (GPIO 제어)
실제 하드웨어
    ↓ (현재 상태 저장)
데이터베이스(RELAY_L_RECORDING)
```

라즈베리파이는 **수동적으로** 데이터베이스 값을 따르므로:
- 데이터베이스에서 relay_15st_flag = True → GPIO ON
- 데이터베이스에서 relay_15st_flag = False → GPIO OFF

---

## 1호 재배사 vs 2호 재배사 차이점

| 항목 | 1호 재배사 | 2호 재배사 |
|------|-----------|-----------|
| 조명 릴레이 | relay_7st_flag | relay_5st_flag |
| 관수 릴레이 | relay_8st_flag | relay_6st_flag |
| 히터밸브 | relay_15st_flag (항상 ON 유지 필요) | relay_15st_flag (미사용) |
| 라디에이터 | 없음 | relay_3st_flag |
| 릴레이 개수 | 16개 (DB) | 15개 (GPIO) + 1개 (DB only) |
| 제어 코드 | `agri_ai_core/*` | `raspi/v1/*` |

---

## 검증 결과

### 검색 패턴
1. `relay.*15` - relay_15 관련 모든 참조
2. `히터밸브` - 한글 키워드
3. `heater.*valve` - 영문 키워드
4. `relay_15st_flag.*False` - relay_15를 False로 설정하는 로직

### 발견된 파일
1. `raspi/v1/gpio/gpio_config.py:34` - "미사용" 정의
2. `raspi/v1/sql/sql_query.py:7` - INSERT 쿼리
3. `raspi/v1/sql/sql_query.py:39` - SELECT 쿼리
4. `raspi/v1/sql/db_layout.py:188` - 스키마 정의 (True 기본값)

**모든 파일에서 relay_15st_flag를 직접 False로 설정하는 로직 없음**

---

## 결론 및 권장사항

### 현재 상태
✓ **raspi/v1 코드에서 히터밸브를 OFF로 설정하는 로직 없음**
✓ **데이터베이스 값을 그대로 따름**
✓ **relay_16st_flag 하드코딩 문제 수정 완료**

### 1호 재배사 히터밸브 보호
1호 재배사 히터밸브는 `agri_ai_core/control/relay/relay_manager.py`에서 보호됨:
```python
# 1호 재배사 히터밸브 항상 ON
if str(house_id) == "1":
    relay_values["relay_15st_flag"] = True
```

### 2호 재배사
- relay_15st는 미사용 릴레이
- 특별한 보호 로직 불필요
- 데이터베이스 값에 따라 제어됨

---

**분석 완료 시간:** 2025-12-17 23:10
**상태:** ✓ 히터밸브 OFF 로직 없음 확인 완료
**추가 조치:** 없음
