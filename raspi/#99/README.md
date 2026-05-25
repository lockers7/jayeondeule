# raspi/#99 — 자연들에 농장 RPi 표준 템플릿

새 라즈베리파이를 농장 호기로 셋업할 때 그대로 적용하는 기본 구조입니다.
2026-05-23 부터 `#99` 가 마스터, 다른 호기(`#01` ~ `#03`) 는 본 구조를 따라 동기화됩니다.

## 디렉토리 구조

```
raspi/#99/
├── home/                              ← RPi 의 /home/jayeondeule/ 에 그대로 복사
│   ├── camera_stream.py               ← v4l2 기반 USB UVC 카메라 MJPEG 서버
│   └── FarmUnits/                     ← /home/jayeondeule/FarmUnits/
│       ├── .env                       ← 농장/DB 환경변수 (FARM_ID, HOST, USER, ...)
│       ├── FarmUnits.code-workspace
│       ├── config.py                  ← FarmUnits 자체 설정
│       ├── jayeondeule.py             ← 농장 IoT 메인 데몬 (센서·릴레이·DB)
│       ├── log_handler.py
│       ├── display/lcd_control.py     ← (옵션) LCD 표시
│       ├── gpio/                      ← gpio_config.py (16 릴레이 핀 매핑), gpio_control.py
│       ├── sensor/                    ← sensor_config.py, sensor_control.py
│       └── sql/                       ← DB 스키마·쿼리·포맷
├── etc/                               ← RPi 의 /etc/ 에 복사
│   └── systemd/system/
│       ├── camera_stream.service      ← MJPEG 8090 서버
│       ├── camera_tunnel.service      ← 운영서버로 reverse SSH 터널 (호기별 포트)
│       └── jayeondeule_ctrl.service   ← 농장 메인 데몬 자동 시작
└── setup.sh                           ← 새 RPi 자동 셋업 스크립트
```

## 새 라즈베리파이 셋업 절차 (간단)

```bash
# 1. RPi OS 64-bit (Debian 13 trixie) 설치 + 사용자 jayeondeule 생성
# 2. 네트워크 설정 + iptime 공유기 포트포워딩 (호기별 SSH 포트 → 22)
# 3. USB UVC 카메라 + I2C 센서 + UART CO2 센서 연결

# 4. 표준 템플릿 복사 (운영서버 또는 git 에서)
scp -r raspi/#99 jayeondeule@<신규-RPi>:/tmp/

# 5. 자동 셋업
ssh jayeondeule@<신규-RPi>
sudo bash /tmp/#99/setup.sh

# 6. SSH 키 안내 따라 운영서버 ssh-copy-id

# 7. 재부팅 (그룹 권한 반영)
sudo reboot
```

## 호기 ID 자동 산출

`setup.sh` 가 RPi 의 IP 주소 마지막 옥텟을 호기 ID 로 사용합니다.
예: `192.168.0.199` → `HOUSE_ID=99` → reverse tunnel 포트 `8095`.

| HOUSE_ID | reverse port (운영서버 측 listen) |
|---|---|
| 1 | 8092 |
| 2 | 8093 |
| 3 | 8094 |
| 99 (개발용) | 8095 |
| 그 외 | 8090 + HOUSE_ID |

## 핵심 의존성 (apt + pip)

**apt**: `python3 python3-venv i2c-tools v4l-utils autossh openssh-client`

**pip** (venv `~/jayeondeule`):
- `flask pillow` — 카메라 MJPEG 서버
- `pyserial smbus2` — CO2 시리얼 + I2C
- `adafruit-circuitpython-sht4x` (실내 온습도 SHT45)
- `adafruit-circuitpython-bme280` (실외 온습도/기압)
- `adafruit-blinka` — Adafruit board layer
- `psycopg2-binary python-dotenv` — DB
- `lgpio` — 신형 GPIO API (raspi-config 활성)
- `rpi-lgpio` — RPi.GPIO 호환 레이어 (Debian 13 trixie + RPi5 필수)
- `RPLCD` — LCD 표시 (선택, LCD 패널 연결 시)

## 호기별 차이 (수동 조정 필요)

`setup.sh` 가 자동 산출하지 못하는 항목 — 운영서버 측에서 수동 등록:

1. **`/workspace/jayeondeule/.env` 의 `FARM_RPI_CAM_URL_<farm>_<house>`**
   - 예: `FARM_RPI_CAM_URL_0_99=http://127.0.0.1:8095/snapshot`
2. **iptime 공유기 포트포워딩** (외부 SSH 접근용)
   - 예: `5199` 외부 → `22` 내부 (IP `192.168.0.199`)
3. **DB `farmhouse_m_info` 테이블에 행 추가** (`farm_id`, `hous_id`, `hous_name`)

## sync 정책

- **마스터** = `raspi/#99` (이 디렉토리)
- 다른 호기 (`#01`, `#02`, `#03`) 도 본 디렉토리를 따라 정렬 권장
- 새 RPi 셋업 후 운영 코드가 안정화되면 변경사항은 `raspi/#99` 에 commit, 다른 호기에 sync

## 최근 변경 이력

- **2026-05-23** — 마스터 템플릿 신설
  - `home/camera_stream.py` 추가 (v4l2 기반 신버전, md5 `bbb6e32acdc1`)
  - `home/FarmUnits/sensor/sensor_control.py` 최신본 반영 (md5 `e1765143`)
  - `etc/systemd/system/` 3개 unit 추가
  - `setup.sh` 자동 셋업 스크립트 작성
  - 5199 동기화 검증 (SD 초기화 직후 raspi/#99 → 5199 일괄 배포 + venv 재생성 → 센서 정상화)
  - `setup.sh` pip 목록 보강: `rpi-lgpio` (RPi.GPIO 호환), `RPLCD` (LCD)
