import { useState } from 'react';
import { CameraVideo } from 'react-bootstrap-icons';

export default function CameraStream({ farmId, houseId, label }) {
  const [errored, setErrored] = useState(false);
  const src = `/camera/${farmId}/${houseId}/stream`;

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
    <div className="camera-container">
      <div className="camera-label">
        <span className="camera-live-dot" />
        {label || 'LIVE'}
      </div>
      <img
        className="camera-stream"
        src={src}
        alt={label || '실시간 스트리밍'}
        onError={() => setErrored(true)}
      />
    </div>
  );
}
