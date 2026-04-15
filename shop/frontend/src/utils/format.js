/** 날짜 포맷 (날짜만) */
export function formatDate(dt) {
  if (!dt) return '-';
  return new Date(dt).toLocaleDateString('ko-KR');
}

/** 날짜+시간 포맷 */
export function formatDateTime(dt) {
  if (!dt) return '';
  const d = new Date(dt);
  return d.toLocaleDateString('ko-KR') + ' ' + d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}

/** 금액 포맷 */
export function formatCurrency(n) {
  return (n || 0).toLocaleString() + '원';
}

/** 동영상 URL 여부 */
export function isVideo(url) {
  return /\.(mp4|webm|ogg|mov)$/i.test(url);
}

/** 빈 문자열 → '-' */
export function displayOrDash(v) {
  return (v && v.trim()) ? v : '-';
}
