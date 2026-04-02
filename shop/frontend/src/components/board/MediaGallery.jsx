import { isVideo } from '../../utils/format';

/** 게시글 상세에서 이미지/동영상 표시 */
export default function MediaGallery({ images = [] }) {
  if (images.length === 0) return null;
  return (
    <div className="mb-4">
      {images.map((img, i) => (
        isVideo(img.imageUrl) ? (
          <video key={i} controls style={{ width: '100%', aspectRatio: '16/9', borderRadius: '12px', marginBottom: '12px', background: '#000', objectFit: 'contain' }}>
            <source src={img.imageUrl} />
          </video>
        ) : (
          <img key={i} src={img.imageUrl} alt=""
            style={{ maxWidth: '100%', borderRadius: '12px', marginBottom: '12px' }} />
        )
      ))}
    </div>
  );
}
