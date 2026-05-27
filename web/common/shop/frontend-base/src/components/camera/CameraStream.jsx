import { useState, useEffect, useRef } from 'react';
import { CameraVideo } from 'react-bootstrap-icons';

export default function CameraStream({ farmId, houseId, label }) {
  const [errored, setErrored] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const imgRef = useRef(null);
  const src = `/camera/${farmId}/${houseId}/stream`;

  // multipart MJPEG 은 onLoad 가 일관되지 않아 두 가지 신호로 placeholder 해제:
  //   1) <img> naturalWidth > 0 (첫 프레임 디코딩 완료) — 200ms 폴링
  //   2) 5초 안전 timeout (오래 안 떠도 강제 표시 — 사용자가 멈춘 상태로 오해 안 하게)
  // 3호처럼 TTFB 가 800ms+ 인 카메라도 폴링이 잡아냄.
  useEffect(() => {
    setLoaded(false);
    const poll = setInterval(() => {
      const w = imgRef.current && imgRef.current.naturalWidth;
      if (w && w > 0) { setLoaded(true); clearInterval(poll); }
    }, 200);
    const safety = setTimeout(() => setLoaded(true), 5000);
    return () => { clearInterval(poll); clearTimeout(safety); };
  }, [src]);

  if (errored) {
    return (
      <div className="camera-container">
        <div className="camera-placeholder">
          <CameraVideo size={40} />
          <span>카메라 점검 중입니다</span>
        </div>
      </div>
    );
  }

  return (
    <div className="camera-container" style={{ position: 'relative' }}>
      <div className="camera-label">
        <span className="camera-live-dot" />
        {label || 'LIVE'}
      </div>
      {!loaded && (
        <div
          className="camera-placeholder"
          style={{
            position: 'absolute', inset: 0, zIndex: 1,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: '#1a1a1a', color: '#888',
          }}
        >
          <CameraVideo size={32} />
          <span style={{ marginLeft: 8 }}>연결 중…</span>
        </div>
      )}
      <img
        ref={imgRef}
        className="camera-stream"
        src={src}
        alt={label || '실시간 스트리밍'}
        onError={() => setErrored(true)}
        onLoad={() => setLoaded(true)}
      />
    </div>
  );
}
