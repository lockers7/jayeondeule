-- =========================================================================
-- 재배사 카메라 이미지 이력 테이블
-- 매시간 정각에 RPi 측 USB 카메라 캡처 → 메타데이터 저장.
-- 이미지 본체는 파일시스템 (/workspace/jayeondeule/upload/camera/<farm>/<house>/)
-- vision_summary 는 ChromaDB farm_knowledge 컬렉션에도 임베딩 (RAG/학습).
-- =========================================================================

CREATE TABLE IF NOT EXISTS farmhouse_image_history (
    image_id        BIGSERIAL    PRIMARY KEY,
    farm_id         INTEGER      NOT NULL,
    hous_id         INTEGER      NOT NULL,
    captured_at     TIMESTAMP    NOT NULL,
    file_path       TEXT         NOT NULL,
    file_size       INTEGER,
    width           INTEGER,
    height          INTEGER,
    -- Pillow 휴리스틱 분석 결과
    brightness      REAL,
    saturation      REAL,
    dark_ratio      REAL,
    bright_ratio    REAL,
    -- Vision LLM 분석 (옵션 — VISION_MODEL 설정 시 채워짐)
    vision_summary  TEXT,
    vision_model    TEXT,
    -- ChromaDB 임베딩 추적 (성공 시 청크 ID)
    rag_chunk_id    TEXT,
    created_at      TIMESTAMP    DEFAULT NOW()
);

-- 호기별 시계열 조회 인덱스 (24시간 이력 / 추세 분석용)
CREATE INDEX IF NOT EXISTS idx_farmhouse_image_history_farm_house_time
    ON farmhouse_image_history (farm_id, hous_id, captured_at DESC);

-- 보존 정책 정리(cron)에 사용
CREATE INDEX IF NOT EXISTS idx_farmhouse_image_history_captured_at
    ON farmhouse_image_history (captured_at);

COMMENT ON TABLE  farmhouse_image_history IS '재배사 카메라 시간별 캡처 이력 (메타+휴리스틱+Vision LLM 분석)';
COMMENT ON COLUMN farmhouse_image_history.file_path IS '이미지 파일 절대경로 (UPLOAD_PATH/camera/<farm>/<house>/YYYYMMDD_HH.jpg)';
COMMENT ON COLUMN farmhouse_image_history.vision_summary IS 'Vision LLM 의 한국어 묘사 (자실체 형성·곰팡이·결로·조명 등)';
COMMENT ON COLUMN farmhouse_image_history.rag_chunk_id IS 'ChromaDB farm_knowledge 컬렉션의 청크 ID (RAG 검색용)';
