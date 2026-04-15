import { useState, useRef } from 'react';
import { Button } from 'react-bootstrap';
import { ImageFill, XCircleFill, PlayBtnFill } from 'react-bootstrap-icons';
import api from '../../api/client';

function isVideo(url) {
  return /\.(mp4|webm|ogg|mov)$/i.test(url);
}

export default function ImageUploader({ images = [], onChange, postId, commentId }) {
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  const handleUpload = async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    setUploading(true);
    try {
      const formData = new FormData();
      for (const file of files) formData.append('files', file);
      if (postId) formData.append('postId', postId);
      if (commentId) formData.append('commentId', commentId);

      const { data } = await api.post('/board/images/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (data.success) {
        onChange([...images, ...data.data]);
      }
    } catch { /* ignore */ }
    setUploading(false);
    e.target.value = '';
  };

  const handleRemove = (idx) => {
    onChange(images.filter((_, i) => i !== idx));
  };

  return (
    <div>
      <div className="d-flex flex-wrap gap-2 mb-2">
        {images.map((url, i) => (
          <div key={i} style={{ position: 'relative', display: 'inline-block' }}>
            {isVideo(url) ? (
              <div style={{
                width: '100px', height: '100px', borderRadius: '8px',
                border: '1px solid var(--shop-border)', background: '#222',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <PlayBtnFill size={28} style={{ color: '#fff' }} />
              </div>
            ) : (
              <img src={url} alt="" style={{
                width: '100px', height: '100px', objectFit: 'cover',
                borderRadius: '8px', border: '1px solid var(--shop-border)',
              }} />
            )}
            <XCircleFill
              size={18}
              style={{ position: 'absolute', top: -6, right: -6, cursor: 'pointer', color: '#dc3545', background: '#fff', borderRadius: '50%' }}
              onClick={() => handleRemove(i)}
            />
          </div>
        ))}
      </div>
      <input type="file" ref={fileRef} accept="image/*,video/mp4,video/webm,video/ogg,video/quicktime" multiple
        style={{ display: 'none' }} onChange={handleUpload} />
      <Button size="sm" variant="outline-secondary" onClick={() => fileRef.current?.click()}
        disabled={uploading}>
        <ImageFill className="me-1" /> {uploading ? '업로드 중...' : '이미지/동영상 첨부'}
      </Button>
    </div>
  );
}
