# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 카메라 / 버섯 영상 분석 모듈 (M11)
# [2026-04-28 신규] 재배사 내부 영상을 캡처해 LLM 의 상황 판단에 활용.
#
# 영상 소스 (자동 우선순위 — 사용 가능한 첫 소스만 사용):
#   1) USB 카메라 (메인 서버 직결) — V4L2 디바이스 또는 OpenCV index
#        env: FARM_USB_CAM_<farm>_<house> = /dev/video0  또는  0
#   2) RPi 카메라 HTTP (권장) — RPi 측 camera_stream.service(port 8090) +
#        camera_tunnel.service(autossh -R 8095:localhost:8090) reverse tunnel.
#        메인 서버 127.0.0.1:8095 → RPi /dev/video0. nginx /camera/<f>/<h>/ 도 동일.
#        env: FARM_RPI_CAM_URL_<farm>_<house> = http://127.0.0.1:8095/snapshot
#   3) SSH 직접 캡처 (백업 fallback) — reverse tunnel 미동작 시 메인에서 직접 v4l2-ctl
#        env: FARM_SSH_CAM_<farm>_<house> = user@host:port[:device][:WIDTHxHEIGHT]
#        선택: SSH_CAM_IDENTITY (권장) / SSH_CAM_PASSWORD (sshpass 폴백)
#   4) 정적 이미지 경로 — 운영 점검/테스트용
#        env: FARM_STATIC_IMG_<farm>_<house> = /path/to.jpg
#
# 분석 (선택적 · 모두 옵션):
#   A) 휴리스틱 통계 — Pillow 만 있어도 동작 (밝기 평균 / 채도 / 어두운픽셀비율)
#      → 버섯 갓 형성도(어두운 객체 점유율) / 조명 적정성 가늠.
#   B) Vision LLM (옵션) — Ollama 멀티모달 모델 (예: llava, llama3.2-vision 등)
#      env: VISION_MODEL = llava   (미설정 시 비활성)
#      env: VISION_URL   = http://localhost:11434  (Ollama 기본)
#
# 호출 룰:
#   • control_ai_environment 에서만 import.
#   • 동급 control 모듈 import 금지.
#   • utils.http_client / config / logs 만 의존.
#   • 카메라/모델/Pillow 부재 시 graceful skip → 기존 LLM 흐름 보존.
# --->
# _env_int             : 환경변수 → int 안전 변환
# _cache_get           : 캐시 조회 (TTL 만료 시 자동 제거)
# _cache_put           : 캐시 저장 (TTL 만료 시각 포함)
# _capture_usb         : USB 카메라(V4L2/OpenCV) 1프레임 캡처
# _capture_ssh         : RPi 측 USB 카메라 SSH 원격 캡처 (v4l2-ctl)
# _capture_rpi         : RPi HTTP 정지 이미지 fetch
# _capture_static      : 정적 이미지 파일 로드
# capture_image        : 영상 1프레임 bytes 확보 (4 소스 자동 우선순위)
# analyze_heuristics   : Pillow 통계 — 밝기/채도/어두운픽셀비율
# analyze_vision_llm   : Ollama 멀티모달 호출 → 텍스트 묘사
# get_camera_context   : capture + analyze 일괄 실행 → dict
# format_camera_block  : user prompt 한 블록 텍스트
# ══════════════════════════════════════════════════════════════════════════════
import base64
import io
import os
import time
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.http_client import http_json_request

logger = setup_logger(__name__)


_CACHE_TTL = 300  # 5분
_CACHE: Dict[tuple, tuple] = {}

# [2026-04-28 rev2] 영상 휴리스틱 임계 — 환경변수로 운영 조정 가능 (하드코딩 금지)
# ────────────────────────────────────────────────────────────────────
# 환경변수 값을 int 로 안전 변환. 미설정/실패 시 default.
# ────────────────────────────────────────────────────────────────────
def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default

_CAM_DARK_THRESHOLD   = _env_int("CAM_DARK_PIXEL_THRESHOLD",   60)   # 0~255
_CAM_BRIGHT_THRESHOLD = _env_int("CAM_BRIGHT_PIXEL_THRESHOLD", 200)  # 0~255


# ────────────────────────────────────────────────────────────────────
# 캐시 조회 — TTL 만료 시 자동 제거.
# ────────────────────────────────────────────────────────────────────
def _cache_get(key):
    e = _CACHE.get(key)
    if not e:
        return None
    if time.time() >= e[0]:
        _CACHE.pop(key, None)
        return None
    return e[1]


# ────────────────────────────────────────────────────────────────────
# 캐시 저장 — TTL 만료 시각과 함께 페이로드 보관.
# ────────────────────────────────────────────────────────────────────
def _cache_put(key, payload):
    _CACHE[key] = (time.time() + _CACHE_TTL, payload)


# ══════════════════════════════════════════════════════════════════════════════
# Source 1) USB 카메라 (V4L2 / OpenCV)
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# USB 카메라(V4L2/OpenCV) 1프레임 캡처 → JPEG bytes. 실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _capture_usb(device: str) -> Optional[bytes]:
    try:
        import cv2  # type: ignore
    except ImportError:
        logger.info("[AI카메라] OpenCV 미설치 — USB 카메라 캡처 스킵")
        return None
    try:
        idx = int(device) if device.isdigit() else device
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            logger.warning(f"[AI카메라] USB 디바이스 열기 실패 device={device}")
            return None
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            logger.warning(f"[AI카메라] USB 프레임 캡처 실패 device={device}")
            return None
        ok2, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok2:
            return None
        logger.info(f"[AI카메라] USB 캡처 성공 device={device} size={len(buf.tobytes())}B")
        return buf.tobytes()
    except Exception as e:
        logger.warning(f"[AI카메라] USB 캡처 예외 device={device}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Source 2) SSH 캡처 — RPi 측 USB 카메라를 메인 서버에서 SSH 통한 v4l2-ctl 캡처
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# [변경8 · 2026-04-30] RPi 의 USB 카메라(/dev/videoN) 를 SSH 로 원격 캡처.
# spec 형식: 'user@host:port[:device][:WxH]'  (device 기본 /dev/video0, 기본 1280x720)
# 메인 서버 ↔ RPi LAN 직접 접근 차단(client isolation) 환경에서도 외부 SSH 포트
# 포워딩만으로 카메라 영상 확보. 5분 캐시 적용으로 SSH 핸드셰이크 비용 무시 가능.
# 비밀번호: SSH_CAM_PASSWORD 환경변수 (sshpass) 또는 SSH 키 인증.
# ────────────────────────────────────────────────────────────────────
def _capture_ssh(spec: str) -> Optional[bytes]:
    import shutil
    import subprocess

    parts = spec.split(':')
    if len(parts) < 2 or '@' not in parts[0]:
        logger.warning(f"[AI카메라] SSH spec 형식 오류 spec={spec} (예: user@host:port)")
        return None
    user_host = parts[0]
    port = parts[1]
    device = parts[2] if len(parts) >= 3 and parts[2].startswith('/dev/') else '/dev/video0'
    res_idx = 3 if device != '/dev/video0' or (len(parts) >= 3 and parts[2].startswith('/dev/')) else 2
    res = parts[res_idx] if len(parts) > res_idx and 'x' in parts[res_idx] else '1280x720'
    try:
        width, height = res.split('x')
        int(width); int(height)
    except (ValueError, IndexError):
        width, height = '1280', '720'

    pw = os.getenv('SSH_CAM_PASSWORD', '').strip()
    identity = os.getenv('SSH_CAM_IDENTITY', '').strip()   # SSH 키 경로 (권장)
    cmd_remote = (
        f"v4l2-ctl -d {device} "
        f"--set-fmt-video=width={width},height={height},pixelformat=MJPG "
        f"--stream-mmap --stream-count=1 --stream-to=-"
    )
    ssh_opts = [
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'ConnectTimeout=8',
        '-o', 'BatchMode=' + ('no' if pw else 'yes'),
        '-p', port,
    ]
    if identity:
        ssh_opts += ['-i', identity]
    if pw:
        if not shutil.which('sshpass'):
            logger.warning("[AI카메라] sshpass 미설치 — SSH_CAM_PASSWORD 무시. SSH 키 인증으로 폴백.")
            ssh_cmd = ['ssh'] + ssh_opts + [user_host, cmd_remote]
        else:
            ssh_cmd = ['sshpass', '-p', pw, 'ssh'] + ssh_opts + [user_host, cmd_remote]
    else:
        ssh_cmd = ['ssh'] + ssh_opts + [user_host, cmd_remote]

    try:
        result = subprocess.run(ssh_cmd, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        logger.warning(f"[AI카메라] SSH 캡처 타임아웃(15s) spec={spec}")
        return None
    except Exception as e:
        logger.warning(f"[AI카메라] SSH 캡처 예외 spec={spec}: {e}")
        return None

    if result.returncode != 0:
        err_tail = (result.stderr or b'').decode('utf-8', errors='replace')[:200]
        logger.warning(f"[AI카메라] SSH 캡처 실패 spec={spec} rc={result.returncode} err={err_tail}")
        return None
    data = result.stdout or b''
    if not data:
        logger.warning(f"[AI카메라] SSH 캡처 빈 응답 spec={spec}")
        return None
    logger.info(f"[AI카메라] SSH 캡처 성공 spec={spec} size={len(data)}B (해상도 {width}x{height})")
    return data


# ══════════════════════════════════════════════════════════════════════════════
# Source 3) RPi 카메라 — HTTP 정지 이미지 fetch
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# RPi 카메라 HTTP 정지 이미지 fetch → bytes. 실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _capture_rpi(url: str) -> Optional[bytes]:
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'agri-ai/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
        if not data:
            return None
        logger.info(f"[AI카메라] RPi 캡처 성공 url={url} size={len(data)}B")
        return data
    except Exception as e:
        logger.warning(f"[AI카메라] RPi 캡처 실패 url={url}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Source 4) 정적 파일
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 정적 이미지 파일 로드 → bytes. 실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _capture_static(path: str) -> Optional[bytes]:
    try:
        with open(path, 'rb') as f:
            data = f.read()
        logger.info(f"[AI카메라] 정적 이미지 로드 path={path} size={len(data)}B")
        return data
    except Exception as e:
        logger.warning(f"[AI카메라] 정적 이미지 로드 실패 path={path}: {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# 4개 영상 소스(USB → RPi HTTP → SSH → 정적)를 순차 시도. 모두 실패 시 None.
# RPi reverse tunnel(nginx 통한 8095 fetch) 이 SSH 직접 캡처보다 빠르므로 우선.
# ────────────────────────────────────────────────────────────────────
def capture_image(farm_id, house_id) -> Optional[bytes]:
    usb = os.getenv(f"FARM_USB_CAM_{farm_id}_{house_id}") or os.getenv("FARM_USB_CAM_DEFAULT")
    if usb:
        b = _capture_usb(usb)
        if b:
            return b
    rpi = os.getenv(f"FARM_RPI_CAM_URL_{farm_id}_{house_id}")
    if rpi:
        b = _capture_rpi(rpi)
        if b:
            return b
    ssh = os.getenv(f"FARM_SSH_CAM_{farm_id}_{house_id}")
    if ssh:
        b = _capture_ssh(ssh)
        if b:
            return b
    static = os.getenv(f"FARM_STATIC_IMG_{farm_id}_{house_id}")
    if static:
        b = _capture_static(static)
        if b:
            return b
    logger.info(f"[AI카메라] 사용가능 영상 소스 없음 farm={farm_id} house={house_id}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# A) 휴리스틱 통계 (Pillow)
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# Pillow 휴리스틱 분석 — 밝기·채도·어두움/밝음 픽셀 비율 dict 반환.
# Pillow 미설치 시 빈 dict.
# ────────────────────────────────────────────────────────────────────
def analyze_heuristics(image_bytes: bytes) -> Dict[str, Any]:
    try:
        from PIL import Image, ImageStat  # type: ignore
    except ImportError:
        logger.info("[AI카메라] Pillow 미설치 — 휴리스틱 분석 스킵")
        return {}

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        # 다운샘플로 부담 줄이기
        img.thumbnail((320, 240))
        stat_rgb = ImageStat.Stat(img)
        r, g, b = stat_rgb.mean
        brightness = (r + g + b) / 3.0

        gray = img.convert("L")
        gray_pixels = list(gray.getdata())
        total = len(gray_pixels) or 1
        dark_ratio = sum(1 for p in gray_pixels if p < _CAM_DARK_THRESHOLD) / total
        bright_ratio = sum(1 for p in gray_pixels if p > _CAM_BRIGHT_THRESHOLD) / total

        # 단순 채도 추정 (HSV 변환)
        hsv = img.convert("HSV")
        sat_pixels = [p[1] for p in hsv.getdata()]
        sat_mean = sum(sat_pixels) / total

        result = {
            'width':         img.width,
            'height':        img.height,
            'brightness':    round(brightness, 1),
            'saturation':    round(sat_mean, 1),
            'dark_ratio':    round(dark_ratio, 3),
            'bright_ratio':  round(bright_ratio, 3),
            'rgb_mean':      [round(r, 1), round(g, 1), round(b, 1)],
        }
        logger.info(
            f"[AI카메라] 휴리스틱 분석 → 밝기 {result['brightness']:.0f} "
            f"채도 {result['saturation']:.0f} 어두움 {dark_ratio*100:.1f}% "
            f"밝음 {bright_ratio*100:.1f}%"
        )
        return result
    except Exception as e:
        logger.warning(f"[AI카메라] 휴리스틱 분석 실패: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# B) Vision LLM (Ollama 멀티모달)
# ══════════════════════════════════════════════════════════════════════════════
_VISION_PROMPT = (
    "이 사진은 상황버섯 재배사 내부의 종균 배지/자실체 모습입니다. "
    "다음 5가지를 한 문장씩 한국어로 간단히 답하세요. "
    "(1) 자실체 형성도(없음/초기/중기/후기), "
    "(2) 색상 이상(흰색·갈색·푸른색·검은색 곰팡이 또는 변색 여부), "
    "(3) 수분/결로 흔적, "
    "(4) 조명 적정성, "
    "(5) 즉시 조치가 필요한 이상 징후 요약. "
    "추측 없이 보이는 것만 서술하세요."
)


# ────────────────────────────────────────────────────────────────────
# Ollama 멀티모달 모델 호출 — 모델 미설정/실패 시 "" 반환.
# ────────────────────────────────────────────────────────────────────
def analyze_vision_llm(image_bytes: bytes, timeout: int = 60) -> str:
    # 메인 모델이 비전 지원하면 메인과 동일 모델 사용(swap 회피),
    # 미지원이면 VISION_MODEL fallback. 양쪽 다 비어 있으면 비전 스킵.
    from agri_ai_core.config import get_vision_model
    model = get_vision_model()
    if not model:
        logger.info("[AI카메라] 비전 모델 미설정(메인 비전 미지원 + VISION_MODEL 미설정) — Vision LLM 스킵")
        return ""
    base_url = os.getenv("VISION_URL", "http://localhost:11434").rstrip('/')

    try:
        b64 = base64.b64encode(image_bytes).decode('ascii')
    except Exception as e:
        logger.warning(f"[AI카메라] base64 인코딩 실패: {e}")
        return ""

    payload = {
        "model": model,
        "prompt": _VISION_PROMPT,
        "images": [b64],
        "stream": False,
        "options": {"temperature": 0, "num_predict": 220},
    }
    logger.info(f"[AI카메라] Vision LLM 호출 model={model} url={base_url}")
    t0 = time.time()
    try:
        status, data, err = http_json_request(
            "POST", f"{base_url}/api/generate",
            json_body=payload, timeout=timeout,
        )
    except Exception as e:
        logger.warning(f"[AI카메라] Vision LLM 예외: {e}")
        return ""

    elapsed = time.time() - t0
    if status != 200 or not data:
        logger.warning(f"[AI카메라] Vision LLM 실패 status={status} err={err} ({elapsed:.1f}s)")
        return ""
    text = (data.get("response", "") if isinstance(data, dict) else "").strip()
    logger.info(f"[AI카메라] Vision LLM 완료 ({elapsed:.1f}s, len={len(text)})")
    return text


# ══════════════════════════════════════════════════════════════════════════════
# 컨텍스트 빌더
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 캡처 → 휴리스틱 → Vision LLM 일괄 실행 후 dict 반환. 캐시 5분.
# ────────────────────────────────────────────────────────────────────
def get_camera_context(farm_id, house_id) -> Dict[str, Any]:
    cache_key = (int(farm_id), int(house_id))
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"[AI카메라] 캐시 hit farm={farm_id} house={house_id}")
        return cached

    image = capture_image(farm_id, house_id)
    if not image:
        return {}

    heur = analyze_heuristics(image)
    vision_text = analyze_vision_llm(image)

    payload = {
        'image_bytes_size': len(image),
        'heuristics':       heur,
        'vision_text':      vision_text,
    }
    _cache_put(cache_key, payload)
    return payload


# ────────────────────────────────────────────────────────────────────
# 카메라 컨텍스트 dict → user prompt 한 블록 텍스트.
# ────────────────────────────────────────────────────────────────────
def format_camera_block(ctx: Dict[str, Any]) -> str:
    if not ctx:
        return ""
    h = ctx.get('heuristics') or {}
    v = (ctx.get('vision_text') or '').strip()
    if not h and not v:
        return ""
    lines = [f"[재배사 영상 분석 (캡처 {ctx.get('image_bytes_size','-')}B)]"]
    if h:
        lines.append(
            f"  · 휴리스틱: 해상도 {h.get('width')}x{h.get('height')} · "
            f"밝기 {h.get('brightness')} · 채도 {h.get('saturation')} · "
            f"어두움비율 {h.get('dark_ratio')} · 밝음비율 {h.get('bright_ratio')}"
        )
    if v:
        # 줄바꿈은 user prompt 내에서 들여쓰기
        v_compact = v.replace('\n', ' ')[:480]
        lines.append(f"  · Vision LLM 묘사: {v_compact}")
    lines.append("  → 자실체 형성도·곰팡이·결로·조명 이상이 보이면 환경 결정에 반영.")
    return "\n".join(lines)
