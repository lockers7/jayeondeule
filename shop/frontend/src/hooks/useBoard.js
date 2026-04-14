import { useState, useCallback } from 'react';
import api from '../api/client';
import { isVideo as isVideoUrl } from '../utils/format';

/** 게시글 상세 + 이미지 로딩 훅 */
export function usePostDetail() {
  const [post, setPost] = useState(null);
  const [images, setImages] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (postId) => {
    setLoading(true);
    try {
      const [postRes, imgRes] = await Promise.all([
        api.get(`/board/posts/${postId}`),
        api.get(`/board/posts/${postId}/images`),
      ]);
      setPost(postRes.data.data);
      setImages(imgRes.data.data || []);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  return { post, setPost, images, loading, load };
}

/** 첨부파일 관리 훅 (작성 페이지용) */
export function useAttachments(maxImageMB = 300, maxVideoMB = 700) {
  const [attachments, setAttachments] = useState([]);
  const [error, setError] = useState('');

  const addFiles = (fileList) => {
    const files = Array.from(fileList);
    for (const file of files) {
      const isVid = file.type.startsWith('video/');
      const maxMB = isVid ? maxVideoMB : maxImageMB;
      if (file.size > maxMB * 1024 * 1024) {
        setError(`${isVid ? '동영상' : '이미지'} 최대 크기는 ${maxMB}MB입니다. (${file.name})`);
        return false;
      }
    }
    setError('');
    const newItems = files.map(file => ({
      file,
      previewUrl: URL.createObjectURL(file),
      type: file.type.startsWith('video/') ? 'video' : 'image',
      caption: '',
    }));
    setAttachments(prev => [...prev, ...newItems]);
    return true;
  };

  const remove = (idx) => {
    setAttachments(prev => {
      if (!prev[idx].existing) URL.revokeObjectURL(prev[idx].previewUrl);
      return prev.filter((_, i) => i !== idx);
    });
  };

  const setCaption = (idx, caption) => {
    setAttachments(prev => prev.map((att, i) => i === idx ? { ...att, caption } : att));
  };

  const loadExisting = (imageList) => {
    setAttachments(imageList.map(img => ({
      previewUrl: img.imageUrl,
      type: isVideoUrl(img.imageUrl) ? 'video' : 'image',
      caption: img.caption || '',
      existing: true,
    })));
  };

  /** 새 파일만 서버에 업로드 (캡션 포함) */
  const uploadNew = async (postId) => {
    const newFiles = attachments.filter(a => !a.existing && a.file);
    if (newFiles.length === 0) return;
    const formData = new FormData();
    for (const att of newFiles) {
      formData.append('files', att.file);
      formData.append('captions', att.caption || '');
    }
    formData.append('postId', postId);
    await api.post('/board/images/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  };

  return { attachments, error, setError, addFiles, remove, setCaption, loadExisting, uploadNew };
}
