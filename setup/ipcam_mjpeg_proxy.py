#!/usr/bin/env python3
# ════════════════════════════════════════════════════════════════════
# IP카메라 (ZY-CAMHIPTZ-A-2M) RTSP HEVC → MJPEG 변환 프록시.
# 카메라가 HEVC(H.265)라 브라우저 직접 재생 불가. ffmpeg 으로 디코딩 후 JPEG
# 시퀀스로 multipart/x-mixed-replace 스트림 출력. 단일 ffmpeg + 다중 클라이언트
# fan-out (메모리 공유 buffer) 으로 자원 절약.
#
# 카메라 접근: jayeondeule.iptime.org 외부 포트 5540(RTSP) / 5040(HTTP CGI).
# RPi 5101/5103/5199 와 동일한 외부 포트포워딩 패턴.
#
# 입력 : rtsp://...@jayeondeule.iptime.org:5540/11  (IPCAM_RTSP env 로 주입)
# 출력 : http://127.0.0.1:5046/stream   (multipart MJPEG)
#        http://127.0.0.1:5046/snapshot (단일 JPEG, 가장 최근 프레임)
#        http://127.0.0.1:5046/health   (OK / STALE)
# ════════════════════════════════════════════════════════════════════
import base64
import os
import subprocess
import threading
import time
import urllib.request

from flask import Flask, Response

app = Flask(__name__)

RTSP   = os.getenv('IPCAM_RTSP', 'rtsp://admin:Wkdusemfdp1%40@jayeondeule.iptime.org:5540/11')
WIDTH  = int(os.getenv('IPCAM_WIDTH',  '1280'))
HEIGHT = int(os.getenv('IPCAM_HEIGHT', '720'))
FPS    = int(os.getenv('IPCAM_FPS',    '15'))
QUAL   = int(os.getenv('IPCAM_JPEG_QUALITY', '5'))   # ffmpeg q:v (낮을수록 고화질)
PORT   = int(os.getenv('IPCAM_PROXY_PORT', '5046'))

CAM_HTTP = os.getenv('IPCAM_HTTP', 'http://jayeondeule.iptime.org:5040')
CAM_AUTH = os.getenv('IPCAM_AUTH', 'admin:Wkdusemfdp1@')


# ────────────────────────────────────────────────────────────────────
# 카메라 HTTP CGI 호출 (Basic Auth 자동 부착).
# Hipcam V24 펌웨어는 일정시간 후 audio encoding 을 자동 OFF 시키므로
# /audio 진입 시마다 setaencattr=1 을 다시 켜줘야 한다.
# ────────────────────────────────────────────────────────────────────
def _cam_cgi(query, timeout=5):
    try:
        url = f"{CAM_HTTP}/cgi-bin/hi3510/param.cgi?{query}"
        req = urllib.request.Request(url)
        token = base64.b64encode(CAM_AUTH.encode()).decode()
        req.add_header('Authorization', f'Basic {token}')
        urllib.request.urlopen(req, timeout=timeout).read()
    except Exception:
        pass

_lock = threading.Lock()
_last_frame = None
_last_ts = 0.0


# ────────────────────────────────────────────────────────────────────
# ffmpeg subprocess 무한 루프 — RTSP 끊기면 자동 재시도.
# stdout 으로 mjpeg byte stream 읽고 SOI/EOI(JPEG marker)로 프레임 분리해
# 공유 버퍼에 저장.
# ────────────────────────────────────────────────────────────────────
def _ffmpeg_loop():
    """ffmpeg subprocess 무한 루프 + watchdog.
       프레임 5초 이상 못 받으면 RTSP 스트림 stall 로 간주 → ffmpeg kill 후 재시작."""
    global _last_frame, _last_ts
    while True:
        proc = None
        try:
            proc = subprocess.Popen(
                ['ffmpeg',
                 '-rtsp_transport', 'tcp',
                 '-i', RTSP,
                 '-an',
                 '-vf', f'scale={WIDTH}:{HEIGHT},fps={FPS}',
                 '-q:v', str(QUAL),
                 '-f', 'mjpeg',
                 '-'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=10**6,
            )
            buf = b''
            last_chunk_ts = time.time()
            # 별도 워치독 — 워밍업 15초 후, 5초간 프레임 0 이면 ffmpeg 강제 kill.
            # 워밍업: ffmpeg 가 RTSP 연결 + 첫 프레임 받기까지 시간 필요.
            def _watchdog(p):
                started = time.time()
                while p.poll() is None:
                    time.sleep(1.0)
                    if time.time() - started < 15.0:
                        continue
                    with _lock:
                        ts = _last_ts
                    age = time.time() - ts if ts else 999
                    if age > 5.0:
                        try: p.kill()
                        except Exception: pass
                        return
            wd = threading.Thread(target=_watchdog, args=(proc,), daemon=True)
            wd.start()

            while True:
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                last_chunk_ts = time.time()
                buf += chunk
                while True:
                    soi = buf.find(b'\xff\xd8')
                    if soi < 0:
                        buf = b''
                        break
                    eoi = buf.find(b'\xff\xd9', soi + 2)
                    if eoi < 0:
                        if soi > 0:
                            buf = buf[soi:]
                        break
                    frame = buf[soi:eoi + 2]
                    buf = buf[eoi + 2:]
                    with _lock:
                        _last_frame = frame
                        _last_ts = time.time()
        except Exception:
            pass
        finally:
            try:
                if proc and proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        time.sleep(2)


# ────────────────────────────────────────────────────────────────────
# /stream — multipart MJPEG 라이브 스트림.
# ────────────────────────────────────────────────────────────────────
@app.route('/stream')
def stream():
    def gen():
        last_seen_ts = 0.0
        while True:
            with _lock:
                f = _last_frame
                ts = _last_ts
            if f and ts != last_seen_ts:
                last_seen_ts = ts
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + f + b'\r\n')
            time.sleep(1.0 / max(FPS, 1))
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')


# ────────────────────────────────────────────────────────────────────
# /snapshot — 가장 최근 프레임 JPEG 단일 응답.
# ────────────────────────────────────────────────────────────────────
@app.route('/snapshot')
def snapshot():
    with _lock:
        f = _last_frame
    if not f:
        return Response('no frame yet', status=503)
    return Response(f, mimetype='image/jpeg')


# ────────────────────────────────────────────────────────────────────
# /health — 5초 이내 프레임 들어왔는지.
# ────────────────────────────────────────────────────────────────────
@app.route('/health')
def health():
    with _lock:
        ts = _last_ts
    age = time.time() - ts if ts else 9999
    return ('OK' if age < 5 else 'STALE'), 200


# ────────────────────────────────────────────────────────────────────
# /audio — RTSP 트랙의 PCM A-law 오디오를 추출해 MP3 스트림으로 출력.
# 카메라 자체가 HTTP CGI 마이크 토글을 노출 안 하므로, 클라이언트에서
# <audio> 태그 play/pause + volume 으로 듣기/음량을 제어한다.
# 클라이언트 1명당 ffmpeg 1개 — 동시 재생 시 카메라 RTSP 동시연결.
# ────────────────────────────────────────────────────────────────────
@app.route('/audio')
def audio():
    # 카메라가 audio encoding 을 자동 OFF 로 돌리므로 ffmpeg 시작 전 매번 ON 명령.
    # -aeswitch 는 'on'/'off' 가 아닌 1/0 을 요구함 (V24 펌웨어 검증 완료).
    _cam_cgi('cmd=setaencattr&-chn=11&-aeswitch=1')
    time.sleep(0.6)  # 카메라 내부에서 audio track 이 RTSP 에 합류할 시간

    def gen():
        proc = subprocess.Popen(
            ['ffmpeg',
             '-rtsp_transport', 'tcp',
             '-i', RTSP,
             '-vn',                        # 영상 제거
             '-acodec', 'libmp3lame',
             '-ab', '64k',
             '-ar', '22050',
             '-ac', '1',
             '-f', 'mp3',
             '-'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=10**6,
        )
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            try: proc.kill()
            except Exception: pass
    return Response(gen(), mimetype='audio/mpeg')


if __name__ == '__main__':
    threading.Thread(target=_ffmpeg_loop, daemon=True).start()
    app.run(host='127.0.0.1', port=PORT, threaded=True)
