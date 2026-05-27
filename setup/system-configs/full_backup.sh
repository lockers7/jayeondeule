#!/bin/bash
# =========================================================================
# AgriAI Core 완전 이식 백업 (sudo 불필요 · 오프라인 실사용모델 포함)
# =========================================================================
#  · 목적: E:\ 경유 → 동일 HW 신규서버에서 `RESTORE.sh` 1개로 즉시 현재상태 복원
#  · 제외(실행 무관/임시): .git · backups · logs · download · 캐시 · .claude · .github
#  · 포함(실행 필수/데이터): source(venv·web·external·.mcp·docs·upload) ·
#    configs · PostgreSQL 덤프 · ChromaDB 데이터 · requirements ·
#    Ollama 실사용 모델 blob(gemma3:27b + bge-m3)
#  · 압축: 용량 목적 압축 안 함. 다수 소파일→단일 tar 는 이송/복원 용이 목적만.
# =========================================================================
set -u
PROJECT_DIR="/workspace/jayeondeule"
B="$PROJECT_DIR/.backup"
LOG="$PROJECT_DIR/logs/full_backup.log"
mkdir -p "$PROJECT_DIR/logs"
: > "$LOG"
say(){ echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

say "===== 완전 백업 시작 → $B ====="
rm -rf "$B"; mkdir -p "$B"/{configs,data,source,python,ollama}

# ── .env DB 접속 ──
PGP=$(grep '^PGDB_PASSWORD=' "$PROJECT_DIR/.env" | cut -d= -f2)
PGDB=$(grep '^PGDB_DATABASE=' "$PROJECT_DIR/.env" | cut -d= -f2)
PGU=$(grep '^PGDB_USER='   "$PROJECT_DIR/.env" | cut -d= -f2)
PGH=$(grep '^PGDB_HOST='   "$PROJECT_DIR/.env" | cut -d= -f2)
PGPORT=$(grep '^PGDB_PORT=' "$PROJECT_DIR/.env" | cut -d= -f2)

# ── [1] 설정 파일(커밋본 사용 — sudo 불필요) ──
say "[1/8] configs (nginx·systemd·postgresql)"
cp -a "$PROJECT_DIR/setup/system-configs/nginx"       "$B/configs/nginx"
cp -a "$PROJECT_DIR/setup/system-configs/systemd"     "$B/configs/systemd"
cp -a "$PROJECT_DIR/setup/system-configs/postgresql"  "$B/configs/postgresql"
say "     systemd 유닛: $(ls "$B/configs/systemd" | wc -l)개"

# ── [2] 소스(실행 필수 + 데이터 · 실행무관/임시 제외) ──
say "[2/8] source rsync (venv 포함, .git/backups/logs 제외)"
rsync -a \
  --exclude='.git/' --exclude='.ollama/' --exclude='chromadb/' \
  --exclude='logs/' --exclude='backups/' --exclude='backup/' \
  --exclude='.backup/' --exclude='download/' --exclude='.pytest_cache/' \
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='.claude/' \
  --exclude='.github/' --exclude='.states/' \
  "$PROJECT_DIR/" "$B/source/" 2>>"$LOG"
say "     source 크기: $(du -sh "$B/source" | awk '{print $1}')"

# ── [3] PostgreSQL 전체 덤프(인증만, sudo 불필요) ──
say "[3/8] PostgreSQL dump ($PGDB)"
PGPASSWORD="$PGP" pg_dump -h "$PGH" -p "$PGPORT" -U "$PGU" -d "$PGDB" \
  --no-owner --no-privileges -f "$B/data/postgresql_dump.sql" 2>>"$LOG" \
  && say "     dump: $(du -sh "$B/data/postgresql_dump.sql" | awk '{print $1}')" \
  || say "     [ERROR] pg_dump 실패 — 로그 확인"

# ── [4] ChromaDB 데이터(persist 디렉토리) ──
say "[4/8] ChromaDB database rsync"
mkdir -p "$B/data/chromadb"
rsync -a "$PROJECT_DIR/chromadb/database" "$B/data/chromadb/" 2>>"$LOG"
cp -a "$PROJECT_DIR/chromadb/chromadb_config.yaml" "$B/data/chromadb/" 2>/dev/null || true
say "     chromadb: $(du -sh "$B/data/chromadb" | awk '{print $1}')"

# ── [5] Python requirements ──
say "[5/8] python requirements"
cp -a "$PROJECT_DIR/requirements.txt" "$B/python/requirements.txt"
"$PROJECT_DIR/venv/bin/pip" freeze > "$B/python/requirements.frozen.txt" 2>/dev/null || true

# ── [6] Ollama 실사용 모델 blob 선별 복사(gemma3:27b + bge-m3) ──
say "[6/8] Ollama 실사용 모델 blob 선별(gemma3:27b + bge-m3)"
mkdir -p "$B/ollama/models/blobs"
python3 - "$PROJECT_DIR/.ollama/models" "$B/ollama/models" <<'PY' 2>>"$LOG"
import json, os, shutil, sys
src, dst = sys.argv[1], sys.argv[2]
models = [("gemma3","27b"), ("bge-m3","latest")]
os.makedirs(os.path.join(dst,"blobs"), exist_ok=True)
digests=set()
for name, tag in models:
    mf = os.path.join(src,"manifests/registry.ollama.ai/library",name,tag)
    if not os.path.isfile(mf):
        print("  [WARN] manifest 없음:", mf); continue
    d = json.load(open(mf))
    digests.add(d["config"]["digest"])
    for l in d["layers"]: digests.add(l["digest"])
    # manifest 보존(원 경로 구조)
    mdst = os.path.join(dst,"manifests/registry.ollama.ai/library",name,tag)
    os.makedirs(os.path.dirname(mdst), exist_ok=True)
    shutil.copy2(mf, mdst)
    print("  manifest:", name, tag)
tot=0
for dg in digests:
    fn = "sha256-"+dg.split(":")[1]
    s = os.path.join(src,"blobs",fn); t = os.path.join(dst,"blobs",fn)
    if os.path.isfile(s):
        shutil.copy2(s,t); sz=os.path.getsize(t); tot+=sz
print(f"  blob {len(digests)}개, 합계 {tot//(1024*1024)}MB")
PY
say "     ollama models: $(du -sh "$B/ollama/models" | awk '{print $1}')"
# 모델 목록(복원 pull 대상 = 실사용 2종만)
printf "NAME\tID\tSIZE\tMODIFIED\ngemma3:27b\t-\t17GB\t-\nbge-m3:latest\t-\t1.2GB\t-\n" > "$B/ollama/models.txt"

# ── [7] 복원 스크립트 + 오프라인 원클릭 래퍼 ──
say "[7/8] restore_local.sh + RESTORE.sh"
cp -a "$PROJECT_DIR/setup/system-configs/restore_local.sh" "$B/restore_local.sh"
cat > "$B/RESTORE.sh" <<'RS'
#!/bin/bash
# =====================================================================
# 원클릭 오프라인 복원 — 동일 HW 신규서버에서 이것 1개만 실행
#   sudo bash /workspace/jayeondeule/.backup/RESTORE.sh
# 실사용 Ollama 모델(gemma3:27b+bge-m3)을 선배치해 재다운로드 없이 복원.
# =====================================================================
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="/workspace/jayeondeule"; OWNER="jayeondeule"
[ "$(id -u)" -eq 0 ] || { echo "sudo 필요: sudo bash $0"; exit 1; }
# 1) 오프라인 모델 선배치(services 단계의 ollama pull 을 '이미 설치됨'으로 건너뛰게)
if [ -d "$HERE/ollama/models/blobs" ]; then
  mkdir -p "$PROJECT_DIR/.ollama/models"
  rsync -a "$HERE/ollama/models/" "$PROJECT_DIR/.ollama/models/"
  id "$OWNER" &>/dev/null && chown -R "$OWNER:$OWNER" "$PROJECT_DIR/.ollama" 2>/dev/null || true
  echo "[RESTORE] 오프라인 Ollama 모델 배치(gemma3:27b, bge-m3)"
fi
# 2) 기존 검증 복원 파이프라인 실행(설치→소스→설정→데이터→빌드→서비스)
bash "$HERE/restore_local.sh" all
echo "[RESTORE] 완료 → sudo ./agriAiCore start"
RS
chmod +x "$B/RESTORE.sh" "$B/restore_local.sh"

# ── [8] 매니페스트 ──
say "[8/8] BACKUP_INFO.txt"
{
  echo "AgriAI Core 완전 이식 백업"
  echo "생성: $(date '+%Y-%m-%d %H:%M:%S')  호스트: $(hostname)"
  echo "원본: $PROJECT_DIR"
  echo ""
  echo "[복원 방법 — 동일 HW 신규서버]"
  echo "  1) 이 .backup/ (또는 전송용 tar 해제분)을 신규서버 $PROJECT_DIR/.backup/ 에 배치"
  echo "  2) sudo bash $PROJECT_DIR/.backup/RESTORE.sh    ← 명령어 1개"
  echo ""
  echo "[포함]"
  echo "  configs/    nginx·systemd(7)·postgresql 설정"
  echo "  source/     프로젝트 소스 + venv + web(dist/jar) + external + .mcp + docs + upload"
  echo "  data/       postgresql_dump.sql(전체DB) + chromadb/database(VectorDB)"
  echo "  python/     requirements.txt(+frozen)"
  echo "  ollama/     실사용 모델 blob(gemma3:27b, bge-m3) + models.txt"
  echo "  restore_local.sh · RESTORE.sh(오프라인 원클릭)"
  echo ""
  echo "[제외 — 실행 무관/임시] .git · backups · logs · download · 캐시 · .claude · .github · 미사용모델(qwen3·gemma4·mistral)"
  echo ""
  echo "[구성 크기]"
  du -sh "$B"/* 2>/dev/null | sed 's/^/  /'
  echo "  ----"
  echo "  총계: $(du -sh "$B" | awk '{print $1}')"
} > "$B/BACKUP_INFO.txt"
cat "$B/BACKUP_INFO.txt" | tee -a "$LOG"

say "===== 백업 완료. 총 $(du -sh "$B" | awk '{print $1}') ====="
echo "[[DONE]]" | tee -a "$LOG"
