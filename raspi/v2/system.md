# FarmUnits 시스템 구성 문서

## 1. 시스템 개요

스마트팜(재배사) 자동 제어 시스템.
라즈베리파이 4를 현장 컨트롤러로 사용하며, 환경 센서 값을 수집하고 16채널 릴레이를 통해 재배사 내 각종 장치를 제어한다.
수집된 데이터는 외부 PostgreSQL 서버에 실시간 저장된다.

---

## 2. 하드웨어 구성

| 항목 | 사양 |
|------|------|
| 컨트롤러 | Raspberry Pi 4 Model B Rev 1.5 |
| OS | Linux 6.12.47+rpt-rpi-v8 |
| RAM | 1.8GB |
| SWAP | 2.0GB |
| Python | 3.11 |

---

## 3. 소프트웨어 구조

```
FarmUnits/
├── jayeondeule.py          # 메인 진입점 / 메인 루프
├── config.py               # 전역 상수 및 farm_id/house_id 결정 로직
├── log_handler.py          # 일별 로그 파일 자동 생성/삭제 핸들러
├── main_control.py         # [미완성/삭제됨] MainControl 클래스 스텁
├── rcDecision.md           # rcDecision 클래스 설계 명세서
│
├── sensor/
│   ├── sensor_config.py    # 센서 I2C/Serial 주소 상수
│   └── sensor_control.py   # SENSControl 클래스 - 모든 센서 읽기
│
├── gpio/
│   ├── gpio_config.py      # GPIO 핀 번호 상수 / 릴레이 이름 맵
│   └── gpio_control.py     # GPIOControl 클래스 - 릴레이 On/Off 제어
│
├── sql/
│   ├── sql_config.py       # DB 접속 정보
│   ├── sql_format.py       # 데이터 포맷 클래스 (dataclass)
│   ├── sql_query.py        # SQL 쿼리 상수
│   ├── sql_control.py      # SQLControl 클래스 - DB 읽기/쓰기
│   └── db_layout.py        # DB 테이블 스키마 정의
│
├── logs/                   # 일별 로그 파일 (llm_YYYY_MM_DD.log)
└── .env                    # 환경 변수 (FARM_ID, SYSTEM_SERVICE_NAME 등)
```

---

## 4. 주요 모듈 상세

### 4.1 jayeondeule.py — 메인 진입점

- `.env` 에서 `FARM_ID` 읽음
- `house_id` = 현재 로컬 IP의 마지막 옥텟 − 100 (예: IP `.101` → house_id `1`)
- 시작 시 DB 연결 최대 5회 재시도, 실패 시 systemd 서비스 재시작
- `main_loop()` 내 무한 루프:
  1. DB에서 센서 갱신 주기(`snsr_rfrs_itvl`) 또는 갱신 플래그(`rfrs_flag`) 확인
  2. 조건 충족 시 → 전체 센서 읽기 → DB 저장
  3. DB에서 릴레이 설정값 읽어 GPIO에 적용
  4. 릴레이 상태 DB 저장
  5. 갱신 플래그 False로 초기화

> **현재 자동 제어 로직 비활성화 상태**
> `jayeondeule.py:162-163` 에서 `analysis_action` 호출부가 주석 처리되어 있음.
> DB에서 릴레이 값을 직접 읽어 적용하는 수동 제어 모드로 동작 중.

---

### 4.2 sensor/sensor_control.py — SENSControl

| 메서드 | 설명 |
|--------|------|
| `get_tprt_hmdt_now_val()` | 실내 온습도(SHT4x), 실외 온습도(BME280) |
| `get_co2_now_val()` | CO₂ 농도 ppm (MH-Z19B UART) |
| `get_water_temp_now_val()` | 수온 (DS18B20 1-Wire) |
| `get_all_sensor_value()` | 전체 센서 값 dict 반환 |
| `check_sensor_connections()` | 각 센서 연결 상태 확인 |

**센서 목록:**

| 센서 | 모델 | 인터페이스 | 측정 항목 |
|------|------|-----------|----------|
| 실내 온습도 | SHT4x | I2C (0x44) | 온도, 습도 |
| 실외 온습도/기압 | BME280 | I2C (0x76) | 온도, 습도 |
| CO₂ | MH-Z19B | UART `/dev/ttyAMA0` 9600bps | CO₂ ppm |
| 수온 | DS18B20 | 1-Wire `/sys/bus/w1/devices/28*` | 수온 |
| 조도 | 디지털 | GPIO 17 | 조도 레벨 (0/1) |
| 수위 | 디지털 | GPIO 27 | 수위 레벨 (0/1) |

---

### 4.3 gpio/gpio_control.py — GPIOControl

- `lgpio` 라이브러리 사용
- 릴레이 16채널 제어 (`RELAY_GPIO` 배열 기준)
- **릴레이 신호 반전**: GPIO `True` → 릴레이 `OFF`, GPIO `False` → 릴레이 `ON`
- 초기화 시 모든 릴레이 `True`(off) 설정

**릴레이 채널 맵:**

| 번호 | relay_flag | 장치명 | GPIO 핀 |
|------|-----------|--------|---------|
| 1 | relay_1st_flag | 수온히터 | 22 |
| 2 | relay_2st_flag | 물순환모터 | 23 |
| 3 | relay_3st_flag | 배수모터1 | 9 |
| 4 | relay_4st_flag | 미사용 | 25 |
| 5 | relay_5st_flag | 흡입환풍모터 | 11 |
| 6 | relay_6st_flag | 배출환풍모터 | 8 |
| 7 | relay_7st_flag | 조명 | 5 |
| 8 | relay_8st_flag | 관수 | 7 |
| 9 | relay_9st_flag | 실내히터 | 6 |
| 10 | relay_10st_flag | 공기순환밸브 | 12 |
| 11 | relay_11st_flag | 공기흡입밸브 | 20 |
| 12 | relay_12st_flag | 미사용 | 16 |
| 13 | relay_13st_flag | 미사용 | 19 |
| 14 | relay_14st_flag | 공기배출밸브 | 13 |
| 15 | relay_15st_flag | 실내히터밸브 | 26 |
| 16 | relay_16st_flag | 미사용 | 21 |

---

### 4.4 sql/ — 데이터베이스 계층

- **DB 엔진**: PostgreSQL
- **외부 호스트**: `lockers7.iptime.org:5432`
- **DB명**: `jayeondeule`

**테이블 구조:**

| 테이블 | 설명 | PK |
|--------|------|-----|
| `FARM_M_INFO` | 농장 기본 정보 | farm_id |
| `USER_M_INFO` | 농장 사용자 정보 | farm_id, user_id |
| `FARMHOUSE_M_INFO` | 재배사 설정 (갱신주기, 수동/자동 플래그) | farm_id, hous_id |
| `SENSOR_M_SETTING` | 온도/습도/CO₂/수온 기준값 설정 | farm_id, hous_id, setn_dttm |
| `SENSOR_L_RECORDING` | 센서 측정값 기록 원장 | farm_id, hous_id, recd_dttm |
| `RELAY_L_RECORDING` | 릴레이 상태 기록 원장 | farm_id, hous_id, recd_dttm |
| `FARMHOUSE_L_PRODUCT` | 재배사 재배 기록 | farm_id, hous_id, recd_dttm |
| `CODE_M_MASTER` | 공통 코드 마스터 | code_id, code_item |

---

### 4.5 log_handler.py — 로그 관리

- 일별 파일 자동 생성: `logs/llm_YYYY_MM_DD.log`
- 60일 초과 로그 자동 삭제
- 콘솔 + 파일 동시 출력
- LOG_LEVEL `.env` 환경변수로 제어 가능

---

### 4.6 config.py — 전역 설정

```python
RELAY_ON  = True
RELAY_OFF = False

WTEMP_MIN_GAP = 8   # 수온 하한 보정값
TEMP_MIN_GAP  = 1   # 온도 하한 보정값
```

- `is_myHouseId()`: 로컬 IP 마지막 옥텟 − 100 으로 재배사 ID 자동 결정
- `is_myFarmId()`: `.env`의 `FARM_ID` 반환

---

## 5. 시스템 서비스

| 항목 | 값 |
|------|-----|
| 서비스명 | `jayeondeule_ctrl` |
| 실행 파일 | `jayeondeule.py` |
| 오류 시 | systemd 서비스 자동 재시작 (`system_restart_for_error()`) |
| 버전 | v2 |

---

## 6. 제어 로직 현황

### 현재 동작 (수동 모드)
```
DB(RELAY_L_RECORDING) → 릴레이 설정값 읽기 → GPIO 적용
```
웹/외부 앱에서 DB 릴레이 값을 변경하면, Pi가 주기적으로 읽어 적용.

### 계획 중 (자동 모드) — rcDecision.md 참조
- 온도 제어: 실내 ≤26℃ / ≥29℃ 기준 히터·팬·밸브 자동 연동
- 수온 안전: 수온 ≥45℃ 히터 강제 Off
- CO₂ 제어: ≥1500ppm 환기 On / ≤700ppm 환기 Off
- 10초 지연 동작 타임스탬프 관리 필요
- `rcDecision` 클래스 구현 후 `jayeondeule.py:162` 주석 해제

---

## 7. 미완성 / 이슈

| 항목 | 상태 | 비고 |
|------|------|------|
| `main_control.py` | 삭제됨 | git index에만 존재 (AD), 클래스 스텁만 있었음 |
| 자동 제어 로직 | 미구현 | `analysis_action` 호출 주석 처리 중 |
| `rcDecision.py` | 미생성 | rcDecision.md에 설계 명세 작성 완료 |
| 외부 BME280 | 비정상 | 최근 로그에서 외부온도 0.0 (센서 미연결 또는 오류) |
| 실내 습도 | 의심값 | 최근 로그에서 100% 고정 |

---

## 8. 의존 패키지

```
psycopg2          # PostgreSQL 연결
python-dotenv     # .env 로드
pyserial          # CO₂ 센서 UART
lgpio             # GPIO 제어 (lgpio 방식)
adafruit-blinka   # CircuitPython 호환
adafruit-circuitpython-sht31d / sht4x  # 실내 온습도 센서
adafruit-circuitpython-bme280          # 실외 온습도 센서
busio / board     # I2C 버스
```

---

## 9. 보안 주의사항

- `sql/sql_config.py` 와 `.env` 에 DB 패스워드가 평문으로 존재
- `.env` 를 `.gitignore` 에 추가하고, `sql_config.py`의 패스워드를 환경변수로 이전 권장
- `sql_config.py` 를 git에 커밋하지 않도록 주의
