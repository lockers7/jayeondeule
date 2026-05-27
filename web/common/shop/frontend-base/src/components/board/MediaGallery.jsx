import { isVideo } from '../../utils/format';

/** 게시글 상세에서 이미지/동영상 + 캡션 표시 */
export default function MediaGallery({ images = [] }) {
  if (images.length === 0) return null;
  return (
    <div className="mb-4">
      {images.map((img, i) => (
        <div key={i} style={{ marginBottom: '16px' }}>
          {isVideo(img.imageUrl) ? (
            <video controls style={{ width: '100%', aspectRatio: '16/9', borderRadius: '12px', background: '#000', objectFit: 'contain' }}>
              <source src={img.imageUrl} />
            </video>
          ) : (
            <img src={img.imageUrl} alt={img.caption || ''}
              style={{ maxWidth: '100%', borderRadius: '12px' }} />
          )}
          {img.caption && (
            <p style={{
              fontSize: '0.9rem', color: 'var(--shop-text-light)', marginTop: '6px',
              paddingLeft: '4px', fontStyle: 'italic',
            }}>
              {img.caption}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
