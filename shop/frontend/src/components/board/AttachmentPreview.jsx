import { useRef } from 'react';
import { Button, Form } from 'react-bootstrap';
import { ImageFill, XCircleFill } from 'react-bootstrap-icons';

/** 작성 페이지용 첨부 미리보기 + 캡션 입력 + 파일 선택 버튼 */
export default function AttachmentPreview({ attachments, onAdd, onRemove, onCaptionChange, count }) {
  const fileRef = useRef(null);

  return (
    <>
      {attachments.length > 0 && (
        <div style={{
          border: '2px solid #90A4AE', borderTop: 'none', borderRadius: '0 0 8px 8px',
          padding: '12px', background: '#fafffe',
        }}>
          {attachments.map((att, i) => (
            <div key={i} style={{ marginBottom: i < attachments.length - 1 ? 16 : 0 }}>
              <div style={{ position: 'relative' }}>
                {att.type === 'video' ? (
                  <video controls style={{ width: '100%', aspectRatio: '16/9', borderRadius: '8px', background: '#000', objectFit: 'contain' }}>
                    <source src={att.previewUrl} type={att.file?.type} />
                  </video>
                ) : (
                  <img src={att.previewUrl} alt=""
                    style={{ width: '100%', borderRadius: '8px', maxHeight: '400px', objectFit: 'contain' }} />
                )}
                <XCircleFill size={24} style={{
                  position: 'absolute', top: 8, right: 8, cursor: 'pointer',
                  color: '#dc3545', background: '#fff', borderRadius: '50%',
                }} onClick={() => onRemove(i)} />
              </div>
              {/* 캡션 입력 */}
              <Form.Control
                size="sm"
                type="text"
                placeholder="이미지 설명을 입력하세요 (선택사항)"
                value={att.caption || ''}
                onChange={(e) => onCaptionChange && onCaptionChange(i, e.target.value)}
                style={{ marginTop: '6px', fontSize: '0.88rem', borderColor: '#B2DFDB' }}
              />
            </div>
          ))}
        </div>
      )}
      <div className="mt-2">
        <input type="file" ref={fileRef} accept="image/*,video/mp4,video/webm,video/ogg,video/quicktime"
          multiple style={{ display: 'none' }} onChange={(e) => { onAdd(e.target.files); e.target.value = ''; }} />
        <Button size="sm" variant="outline-secondary" onClick={() => fileRef.current?.click()}>
          <ImageFill className="me-1" /> 이미지/동영상 첨부
        </Button>
        {(count || attachments.length) > 0 && (
          <span className="ms-2 text-muted" style={{ fontSize: '0.85rem' }}>
            {count || attachments.length}개 첨부됨
          </span>
        )}
      </div>
    </>
  );
}
