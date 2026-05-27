import { useState, useEffect, useRef } from 'react';
import {
  CameraVideo, ArrowUp, ArrowDown, ArrowLeft, ArrowRight,
  ZoomIn, ZoomOut, Mic, MicMute, VolumeUp, VolumeMute, House,
} from 'react-bootstrap-icons';

// IP 카메라 메인 view + PTZ + 오디오 컨트롤.
// 스트림: multipart MJPEG (서버 ffmpeg 가 RTSP HEVC → JPEG 시퀀스로 변환).
// PTZ:    Hi3510 ptzctrl.cgi — 단일 명령(시작 1회 / 정지 1회).
// 오디오: 모바일 앱과 동일한 반-듀플렉스 패턴.
//   • 스피커 ON  → 농장 환경음 듣기 (페이지 로드 시 자동 ON, 음량 슬라이더 표시)
//   • 마이크 ON  → 노트북 마이크 → 농장 (말하기). 카메라 펌웨어가 표준 backchannel 미지원이라
//                  서버 게이트웨이가 갖춰질 때까지 안내만 표시.
//   • 두 버튼은 상호 배타 (스피커 ON 시 마이크 OFF, 그 반대도)
// 사용: <IpCamView base="/camera/main" label="농장 메인 LIVE" />
export default function IpCamView({ base = '/camera/main', label = '농장 메인 LIVE' }) {
  const [errored, setErrored] = useState(false);
  const [streamKey, setStreamKey] = useState(0);
  const step = 1;  // ptzctrl.cgi -step 유효값은 0/1 둘 뿐 — 실제 속도는 setmotorattr panspeed/tiltspeed 로 결정
  const [speakerOn, setSpeakerOn] = useState(true);   // 농장 → 노트북 듣기 (기본 ON)
  const [talkOn, setTalkOn] = useState(false);        // 노트북 → 농장 말하기 (백엔드 미구현)
  const [volume, setVolume] = useState(0.7);
  const [talkUnsupportedAt, setTalkUnsupportedAt] = useState(0);
  const audioRef = useRef(null);

  useEffect(() => {
    if (errored) {
      const id = setTimeout(() => { setErrored(false); setStreamKey(k => k + 1); }, 5000);
      return () => clearTimeout(id);
    }
  }, [errored]);

  // [2026-05-01] 카메라 CGI (Hipcam V24 검증):
  //   setaencattr     : 환경음 인코딩 ON(=1)/OFF(=0). 일정 시간 후 카메라가 자동 OFF 시키므로
  //                     서버 /audio 진입 시에도 한 번 더 켬.
  //   setaudioinvolume: 카메라 마이크 감도 1~100
  //   setmotorattr    : PTZ 모터 속도 (panspeed/tiltspeed). 유효값 0/1/2, 2 가 max.
  const camCgi = (q) => fetch(`${base}/cgi-bin/hi3510/param.cgi?${q}`).catch(() => {});

  // 마운트 시 PTZ 속도 max 설정 (panspeed=2, tiltspeed=2).
  useEffect(() => { camCgi('cmd=setmotorattr&-panspeed=2&-tiltspeed=2'); }, []);

  // 스피커(듣기) ON/OFF — audio.src 부여 후 play(), OFF 시 pause + src 제거.
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    if (speakerOn) {
      camCgi('cmd=setaencattr&-chn=11&-aeswitch=1');
      a.muted = false;
      a.volume = volume;
      a.src = `${base}/audio?t=${Date.now()}`;
      const p = a.play();
      if (p && p.catch) {
        p.catch(err => console.warn('[IpCam] speaker autoplay blocked:', err && err.name));
      }
    } else {
      a.pause();
      a.removeAttribute('src');
      a.load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speakerOn, base]);

  // 자동재생 정책 — 첫 사용자 제스처(클릭/터치) 발생 시 paused 면 재시도.
  useEffect(() => {
    const retry = () => {
      const a = audioRef.current;
      if (a && speakerOn && a.paused) a.play().catch(() => {});
    };
    document.addEventListener('click', retry, { once: true });
    document.addEventListener('touchstart', retry, { once: true });
    return () => {
      document.removeEventListener('click', retry);
      document.removeEventListener('touchstart', retry);
    };
  }, [speakerOn]);

  // 볼륨 슬라이더 — 즉시 audio.volume 반영, 카메라 마이크 감도도 동기화.
  useEffect(() => {
    const a = audioRef.current;
    if (a) a.volume = volume;
  }, [volume]);
  const onVolumeChange = (v) => {
    setVolume(v);
    camCgi(`cmd=setaudioinvolume&-volume=${Math.max(1, Math.round(v * 100))}`);
  };

  // 모바일 패턴: 스피커/마이크 상호 배타.
  const toggleSpeaker = () => {
    if (talkOn) setTalkOn(false);
    setSpeakerOn(s => !s);
  };
  const toggleTalk = () => {
    // 백엔드 게이트웨이(go2rtc 등) 가 준비되기 전까지는 안내만.
    if (!talkOn) {
      if (speakerOn) setSpeakerOn(false);
      setTalkUnsupportedAt(Date.now());
      setTimeout(() => setTalkUnsupportedAt(0), 3500);
    }
  };

  const ptzUrl = (act) => `${base}/cgi-bin/hi3510/ptzctrl.cgi?-step=${step}&-act=${encodeURIComponent(act)}`;
  const startMove = (act) => { fetch(ptzUrl(act)).catch(() => {}); };
  const stopMove  = ()    => { fetch(ptzUrl('stop')).catch(() => {}); };

  if (errored) {
    return (
      <div className="camera-container">
        <div className="camera-placeholder">
          <CameraVideo size={40} />
          <span>메인 카메라 점검 중입니다 (자동 재연결 대기)</span>
        </div>
      </div>
    );
  }

  // 토글 버튼은 클릭 순간 짧게 flash — 카메라 응답이 늦어도 클릭이 됐음을 즉시 표시.
  const flashOnce = (el) => {
    if (!el) return;
    el.classList.remove('ipcam-flash');
    void el.offsetWidth;  // reflow 강제 → animation 재시작
    el.classList.add('ipcam-flash');
  };

  // 통일된 작은 버튼 (현재의 약 1/4 면적). 패드 한 변 약 36px.
  const btn = (onPress, IconCmp, title, isToggle = false, active = false) => (
    <button
      title={title}
      className="ipcam-ctrl-btn"
      onMouseDown={isToggle ? undefined : (() => onPress())}
      onMouseUp={isToggle ? undefined : stopMove}
      onMouseLeave={isToggle ? undefined : stopMove}
      onTouchStart={isToggle ? undefined : ((e) => { e.preventDefault(); onPress(); })}
      onTouchEnd={isToggle ? undefined : ((e) => { e.preventDefault(); stopMove(); })}
      onClick={isToggle ? (e) => { flashOnce(e.currentTarget); onPress(); } : undefined}
      style={{
        width: '36px', height: '36px',
        background: 'rgba(255,255,255,0.95)',
        color: '#333',
        border: '1px solid var(--shop-border, #ddd)',
        borderRadius: '6px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        cursor: 'pointer', userSelect: 'none', WebkitUserSelect: 'none',
        padding: 0,
      }}
    >
      <IconCmp size={16} />
    </button>
  );

  return (
    <div className="camera-container" style={{ position: 'relative' }}>
      <style>{`
        .ipcam-ctrl-btn { transition: background 0.08s, color 0.08s, transform 0.08s; }
        .ipcam-ctrl-btn:active {
          background: var(--shop-accent, #2d6a4f) !important;
          color: #fff !important;
          transform: scale(0.9);
        }
        .ipcam-ctrl-btn.ipcam-flash {
          animation: ipcamFlash 280ms ease-out;
        }
        @keyframes ipcamFlash {
          0%   { background: var(--shop-accent, #2d6a4f); color: #fff; transform: scale(0.9); }
          100% { transform: scale(1); }
        }
      `}</style>
      <div className="camera-label">
        <span className="camera-live-dot" />
        {label}
      </div>
      <img
        key={streamKey}
        className="camera-stream"
        src={`${base}/stream`}
        alt={label}
        onError={() => setErrored(true)}
        style={{ width: '100%', height: 'auto', display: 'block' }}
      />

      {/* hidden audio element — 마이크 토글로 play/pause, 볼륨/음소거 제어 */}
      <audio ref={audioRef} preload="none" />

      {/* 컨트롤 패널 — 콤팩트 (이전의 약 1/4 사이즈) — 좌우 중앙 정렬 */}
      <div style={{
        marginTop: '10px',
        display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start',
        justifyContent: 'center',
        gap: '14px',
        fontSize: '11px',
      }}>
        {/* 4방향 + 정지 (3x3에서 대각선 제외) */}
        <div>
          <div style={{ marginBottom: '4px', color: 'var(--shop-text-muted, #888)' }}>이동</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 36px)', gap: '4px' }}>
            <span />
            {btn(() => startMove('up'), ArrowUp, '위')}
            <span />
            {btn(() => startMove('left'), ArrowLeft, '왼쪽')}
            {btn(() => { fetch(`${base}/cgi-bin/hi3510/preset.cgi?-act=goto&-number=0`).catch(() => {}); }, House, '홈', true)}
            {btn(() => startMove('right'), ArrowRight, '오른쪽')}
            <span />
            {btn(() => startMove('down'), ArrowDown, '아래')}
            <span />
          </div>
        </div>

        {/* 줌 + 오디오 (오디오는 줌 아래) */}
        <div>
          <div style={{ marginBottom: '4px', color: 'var(--shop-text-muted, #888)' }}>줌</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 36px)', gap: '4px' }}>
            {btn(() => startMove('zoomin'), ZoomIn, 'ZOOM IN')}
            {btn(() => startMove('zoomout'), ZoomOut, 'ZOOM OUT')}
          </div>
          <div style={{ marginTop: '8px', marginBottom: '4px', color: 'var(--shop-text-muted, #888)' }}>오디오</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 36px)', gap: '4px' }}>
            {/* 스피커 = 듣기 (농장 → 노트북) */}
            {btn(toggleSpeaker, speakerOn ? VolumeUp : VolumeMute, speakerOn ? '듣기 끄기' : '듣기 시작', true, speakerOn)}
            {/* 마이크 = 말하기 (노트북 → 농장) — 백엔드 게이트웨이 미구현 */}
            {btn(toggleTalk, talkOn ? Mic : MicMute, talkOn ? '말하기 끄기' : '말하기 시작 (준비 중)', true, talkOn)}
          </div>
          {/* 볼륨 슬라이더 — 스피커(듣기) ON 일 때만 노출 */}
          {speakerOn && (
            <div style={{ marginTop: '6px' }}>
              <input
                type="range"
                min={0} max={100} step={1}
                value={Math.round(volume * 100)}
                onChange={(e) => onVolumeChange(Number(e.target.value) / 100)}
                title={`볼륨 ${Math.round(volume * 100)}%`}
                style={{ width: '76px', height: '20px' }}
              />
            </div>
          )}
          {talkUnsupportedAt > 0 && (
            <div style={{ marginTop: '6px', fontSize: '10px', color: '#c0392b', maxWidth: '160px', lineHeight: 1.3 }}>
              말하기 기능은 카메라 펌웨어 한계로 게이트웨이 작업 중입니다.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
