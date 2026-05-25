#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# 자연들에 농장 — 새 라즈베리파이 셋업 스크립트 (raspi/#99 표준 템플릿)
#
# 사용법:
#   sudo ./setup.sh
#
# 전제:
#   · Debian 13 (trixie) RPi OS 64-bit 갓 설치 완료
#   · 사용자명 'jayeondeule' 생성됨
#   · 네트워크 + iptime 공유기 포트포워딩 5199 → 22 (호기별 다름) 설정됨
#   · USB UVC 카메라 1대 + I2C 센서 (SHT4x 0x44, BME280 0x76) + UART CO2 (MH-Z19B) 연결
#
# 작업:
#   1. apt 의존성 설치 (python3, i2c-tools, v4l2-utils, autossh, libcamera 미사용)
#   2. 사용자 그룹 추가 (i2c, gpio, dialout, video, spi)
#   3. raspi-config 인터페이스 (i2c, spi, serial) 활성화
#   4. /home/jayeondeule/ + FarmUnits/ + camera_stream.py 복사
#   5. /etc/systemd/system/ 안 unit 3개 복사
#   6. Python venv (~/jayeondeule) 생성 + 패키지 설치
#   7. SSH 키 등록 안내 (camera_tunnel 용)
#   8. systemctl enable + start
#   9. 검증 (snapshot capture, 데몬 상태)
# ═══════════════════════════════════════════════════════════════════════════
set -e

if [ "$EUID" -ne 0 ]; then
  echo "sudo 권한 필요: sudo ./setup.sh"
  exit 1
fi

USER_NAME="jayeondeule"
USER_HOME="/home/$USER_NAME"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 호기 번호 — IP D Class 마지막 2자리에서 자동 산출
HOUSE_ID=$(hostname -I | awk '{print $1}' | awk -F. '{print $4}')
echo "═══ 자연들에 농장 셋업 시작 (호기 ID 자동 인식: $HOUSE_ID) ═══"

# ─── ① apt 의존성 ─────────────────────────────────────────────────────────
echo "[1/9] apt 패키지 설치..."
apt update -qq
apt install -y -qq \
  python3 python3-venv python3-pip python3-dev \
  i2c-tools v4l-utils \
  autossh openssh-client \
  git curl wget

# libcamera 의존성 제거 (USB UVC 카메라 사용 — picamera2 불필요)
# (필요 시) apt purge -y python3-libcamera python3-picamera2

# ─── ② 사용자 그룹 ────────────────────────────────────────────────────────
echo "[2/9] $USER_NAME 그룹 추가 (i2c, gpio, dialout, video, spi)..."
for grp in i2c gpio dialout video spi; do
  getent group $grp > /dev/null || groupadd $grp
  usermod -aG $grp $USER_NAME
done

# ─── ③ raspi-config 인터페이스 활성화 ─────────────────────────────────────
echo "[3/9] I2C / SPI / Serial 인터페이스 활성화..."
raspi-config nonint do_i2c 0       # I2C ON
raspi-config nonint do_spi 0       # SPI ON
raspi-config nonint do_serial_hw 0 # Serial HW ON
raspi-config nonint do_serial_cons 1  # Serial console OFF (UART CO2 센서 사용)

# ─── ④ 파일 복사 ──────────────────────────────────────────────────────────
echo "[4/9] FarmUnits / camera_stream.py 복사..."
cp -r "$SCRIPT_DIR/home/FarmUnits" "$USER_HOME/"
cp "$SCRIPT_DIR/home/camera_stream.py" "$USER_HOME/"
chown -R $USER_NAME:$USER_NAME "$USER_HOME/FarmUnits" "$USER_HOME/camera_stream.py"
chmod +x "$USER_HOME/camera_stream.py" 2>/dev/null || true

# ─── ⑤ systemd unit 복사 ─────────────────────────────────────────────────
echo "[5/9] systemd unit 3개 배치..."
cp "$SCRIPT_DIR/etc/systemd/system/"*.service /etc/systemd/system/

# camera_tunnel.service 의 reverse 포트를 호기 ID 에 맞게 자동 수정
#   1 → 8092 / 2 → 8093 / 3 → 8094 / 99 → 8095 / 그 외 → 8090+호기
case "$HOUSE_ID" in
  1)  TUNNEL_PORT=8092 ;;
  2)  TUNNEL_PORT=8093 ;;
  3)  TUNNEL_PORT=8094 ;;
  99) TUNNEL_PORT=8095 ;;
  *)  TUNNEL_PORT=$((8090 + HOUSE_ID)) ;;
esac
echo "  호기 $HOUSE_ID → reverse tunnel 포트 $TUNNEL_PORT"
sed -i "s|-R [0-9]\+:localhost:8090|-R $TUNNEL_PORT:localhost:8090|" /etc/systemd/system/camera_tunnel.service

systemctl daemon-reload

# ─── ⑥ Python venv ───────────────────────────────────────────────────────
echo "[6/9] Python venv 생성 ($USER_HOME/jayeondeule)..."
if [ ! -d "$USER_HOME/jayeondeule" ]; then
  sudo -u $USER_NAME python3 -m venv "$USER_HOME/jayeondeule"
fi
sudo -u $USER_NAME "$USER_HOME/jayeondeule/bin/pip" install --quiet --upgrade pip
sudo -u $USER_NAME "$USER_HOME/jayeondeule/bin/pip" install --quiet \
  flask pillow \
  pyserial smbus2 \
  adafruit-circuitpython-sht4x adafruit-circuitpython-bme280 \
  adafruit-blinka \
  psycopg2-binary python-dotenv \
  lgpio rpi-lgpio RPLCD

# ─── ⑦ SSH 키 안내 (camera_tunnel 용) ─────────────────────────────────────
echo "[7/9] SSH 키 확인..."
if [ ! -f "$USER_HOME/.ssh/id_rsa" ]; then
  echo "  ⚠ $USER_HOME/.ssh/id_rsa 가 없습니다."
  echo "  다음 명령으로 키 생성 + 운영서버 등록 필요:"
  echo "    sudo -u $USER_NAME ssh-keygen -t rsa -b 4096 -f $USER_HOME/.ssh/id_rsa -N ''"
  echo "    sudo -u $USER_NAME ssh-copy-id jayeondeule@222.112.126.152"
fi

# ─── ⑧ 서비스 활성화 + 시작 ──────────────────────────────────────────────
echo "[8/9] systemd 서비스 활성화..."
for svc in camera_stream camera_tunnel jayeondeule_ctrl; do
  systemctl enable $svc.service
  systemctl restart $svc.service
done

# ─── ⑨ 검증 ──────────────────────────────────────────────────────────────
echo "[9/9] 검증..."
sleep 5
echo "--- 서비스 상태 ---"
for svc in camera_stream camera_tunnel jayeondeule_ctrl; do
  state=$(systemctl is-active $svc.service)
  echo "  $svc: $state"
done

echo "--- 카메라 snapshot 직접 호출 (8090) ---"
SIZE=$(curl -s -o /tmp/_setup_cam.jpg -w '%{size_download}' http://127.0.0.1:8090/snapshot --max-time 8 || echo 0)
if [ "$SIZE" -gt 50000 ]; then
  echo "  ✅ 실 카메라 캡처 ($SIZE B)"
else
  echo "  ⚠ fallback 이미지 또는 실패 ($SIZE B) — USB 카메라 연결 확인"
fi

echo "--- I2C 장치 스캔 ---"
i2cdetect -y 1 2>/dev/null | tail -9

echo ""
echo "═══ 셋업 완료 ═══"
echo "  호기 ID: $HOUSE_ID"
echo "  reverse tunnel 포트: $TUNNEL_PORT"
echo "  재로그인 후 그룹 권한 반영됨 (또는 reboot 권장)"
echo "  운영서버 .env 의 FARM_RPI_CAM_URL_<farm>_<house> 등록 확인 필요"
