#!/usr/bin/env python3
# ════════════════════════════════════════════════════════════════════
# RPi USB 카메라(UVC, V4L2) MJPEG 스트림 서버 — port 8090
# 메인 서버의 camera_tunnel.service(autossh -R 8095:localhost:8090)와 짝.
# 이전: picamera2/libcamera 의존 (RPi 카메라 모듈 IMX708 전용)
# 변경: v4l2-ctl subprocess 사용 (UVC 표준 USB 카메라). picamera 의존 제거.
# --->
# create_no_camera_jpeg : 카메라 부재 시 "Camera not installed" placeholder
# check_camera          : v4l2-ctl --info 로 디바이스 인식 확인
# capture_jpeg          : v4l2-ctl 단일 프레임 MJPG 캡처 (실패 시 placeholder)
# generate_frames       : multipart MJPEG 무한 generator (INTERVAL 간격)
# /stream               : MJPEG 라이브 스트림
# /snapshot             : 단일 JPEG 응답
# /health               : OK / NO_CAMERA 200 응답
#
# 환경변수 (기본값):
#   CAMERA_DEVICE          : /dev/video0
#   CAMERA_WIDTH           : 1280
#   CAMERA_HEIGHT          : 720
#   CAMERA_FRAME_INTERVAL  : 0.5  (초)
#   CAMERA_JPEG_QUALITY    : 85   (placeholder 만 적용 — UVC MJPG 는 카메라 직출)
# ════════════════════════════════════════════════════════════════════
import io
import os
import logging
import subprocess
import time

from flask import Flask, Response

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

DEVICE       = os.getenv('CAMERA_DEVICE',         '/dev/video0')
WIDTH        = int(os.getenv('CAMERA_WIDTH',      '1280'))
HEIGHT       = int(os.getenv('CAMERA_HEIGHT',     '720'))
INTERVAL     = float(os.getenv('CAMERA_FRAME_INTERVAL', '0.5'))
JPEG_QUALITY = int(os.getenv('CAMERA_JPEG_QUALITY', '85'))
# 소프트웨어 화이트밸런스 보정 — USB 카메라별 색감 변질(파란색 편향 등) 자동 보정.
#   CAM_WB_CORRECT=0 으로 끌 수 있다. CAM_WB_SKEW=채널편차 임계(이하면 정상으로 보고 스킵).
CAM_WB_CORRECT = os.getenv('CAM_WB_CORRECT', '1') == '1'
CAM_WB_SKEW    = int(os.getenv('CAM_WB_SKEW', '20'))


# ────────────────────────────────────────────────────────────────────
# gray-world 화이트밸런스 보정 — 채널 평균을 균등화해 색 편향(파란색 등) 제거.
#   ⛔ 카메라 색감 변질(2/3호 파란색 포화)을 소프트웨어로 잡는다. 정상 카메라(1호)는
#      채널 편차가 작아(<CAM_WB_SKEW) 스킵 → 무해. ImageStat 로 평균은 C레벨(빠름).
#   보드 교체 시 이 보정도 함께 배포되도록 스트리머(camera_stream.py)에 둔다.
# ────────────────────────────────────────────────────────────────────
def _correct_white_balance(jpeg_bytes):
    if not CAM_WB_CORRECT or not jpeg_bytes:
        return jpeg_bytes
    try:
        from PIL import Image, ImageStat
        img = Image.open(io.BytesIO(jpeg_bytes)).convert('RGB')
        r, g, b = ImageStat.Stat(img).mean
        if (max(r, g, b) - min(r, g, b)) < CAM_WB_SKEW:
            return jpeg_bytes            # 이미 균형 — 정상 카메라, 보정 불필요
        gray = (r + g + b) / 3.0
        kr, kg, kb = gray / max(r, 1.0), gray / max(g, 1.0), gray / max(b, 1.0)
        R, G, B = img.split()
        R = R.point(lambda v: min(255, int(v * kr)))
        G = G.point(lambda v: min(255, int(v * kg)))
        B = B.point(lambda v: min(255, int(v * kb)))
        buf = io.BytesIO()
        Image.merge('RGB', (R, G, B)).save(buf, format='JPEG', quality=JPEG_QUALITY)
        return buf.getvalue()
    except Exception as e:
        logger.warning(f'화이트밸런스 보정 실패(원본 반환): {e}')
        return jpeg_bytes


# ────────────────────────────────────────────────────────────────────
# 카메라 부재 시 안내 placeholder JPEG 생성 (640x360 검은 배경 + 안내 문구).
# ────────────────────────────────────────────────────────────────────
def create_no_camera_jpeg():
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (640, 360), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 639, 359], outline=(80, 80, 80), width=2)
    draw.text((240, 155), '카메라 없음', fill=(180, 180, 180))
    draw.text((210, 185), 'Camera not installed', fill=(120, 120, 120))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=JPEG_QUALITY)
    return buf.getvalue()


# ────────────────────────────────────────────────────────────────────
# v4l2-ctl --info 로 디바이스 인식 확인. 응답에 'Driver name' 포함 시 정상.
# ────────────────────────────────────────────────────────────────────
def check_camera():
    try:
        r = subprocess.run(
            ['v4l2-ctl', '-d', DEVICE, '--info'],
            capture_output=True, timeout=3,
        )
        return r.returncode == 0 and b'Driver name' in r.stdout
    except Exception as e:
        logger.warning(f'v4l2-ctl 검사 실패: {e}')
        return False


# ────────────────────────────────────────────────────────────────────
# 단일 MJPG 프레임 캡처 (v4l2-ctl --stream-mmap --stream-count=1).
# 실패 시 직전 성공 프레임 캐시 반환 — 화면 깜빡임 방지.
# 캐시도 없는 초기 단계에서만 placeholder 반환.
# [2026-05-01] _last_good_frame 캐시 추가: USB 일시 실패 시 정지 화면처럼
# 보이도록 하여 검은 placeholder 와 정상 프레임이 번갈아 나타나는 깜빡임 제거.
# ────────────────────────────────────────────────────────────────────
_last_good_frame = None
_consecutive_fail = 0


def capture_jpeg():
    global _last_good_frame, _consecutive_fail
    cmd = [
        'v4l2-ctl', '-d', DEVICE,
        f'--set-fmt-video=width={WIDTH},height={HEIGHT},pixelformat=MJPG',
        '--stream-mmap', '--stream-count=1', '--stream-to=-',
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        if r.returncode == 0 and r.stdout:
            frame = _correct_white_balance(r.stdout)   # 색감 변질 자동 보정
            _last_good_frame = frame
            _consecutive_fail = 0
            return frame
        _consecutive_fail += 1
        # 5초당 1회만 경고 로그 (rc=255 폭주 시 로그 부피 제어)
        if _consecutive_fail % 10 == 1:
            logger.warning(
                f'v4l2-ctl rc={r.returncode} 연속실패={_consecutive_fail} '
                f'stderr={(r.stderr or b"")[:120].decode("utf-8", errors="replace")}'
            )
    except subprocess.TimeoutExpired:
        _consecutive_fail += 1
        if _consecutive_fail % 10 == 1:
            logger.warning(f'v4l2-ctl 타임아웃(5s) 연속실패={_consecutive_fail}')
    except Exception as e:
        _consecutive_fail += 1
        if _consecutive_fail % 10 == 1:
            logger.warning(f'v4l2-ctl 예외: {e}')
    # 캐시된 직전 프레임 반환 (정지 화면처럼) — 캐시 없을 때만 placeholder
    if _last_good_frame is not None:
        return _last_good_frame
    return create_no_camera_jpeg()


# ────────────────────────────────────────────────────────────────────
# multipart MJPEG generator — INTERVAL 간격으로 새 프레임 push.
# ────────────────────────────────────────────────────────────────────
def generate_frames():
    while True:
        frame = capture_jpeg()
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(INTERVAL)


# ────────────────────────────────────────────────────────────────────
# /stream — MJPEG 라이브 스트림 (multipart/x-mixed-replace).
# ────────────────────────────────────────────────────────────────────
@app.route('/stream')
def stream():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


# ────────────────────────────────────────────────────────────────────
# /snapshot — 단일 JPEG 응답.
# ────────────────────────────────────────────────────────────────────
@app.route('/snapshot')
def snapshot():
    return Response(capture_jpeg(), mimetype='image/jpeg')


# ────────────────────────────────────────────────────────────────────
# /health — 카메라 인식 OK / NO_CAMERA 200 응답.
# ────────────────────────────────────────────────────────────────────
@app.route('/health')
def health():
    return ('OK' if check_camera() else 'NO_CAMERA'), 200


if __name__ == '__main__':
    ok = check_camera()
    logger.info(f'USB 카메라 {DEVICE} 인식: {ok}')
    logger.info(f'카메라 스트리밍 서버 시작: http://0.0.0.0:8090 (해상도 {WIDTH}x{HEIGHT}, interval {INTERVAL}s)')
    app.run(host='0.0.0.0', port=8090, threaded=True)
