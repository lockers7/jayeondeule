#!/bin/bash
#############################################################
# 디스크 마이그레이션 스크립트
#
# 목표:
#   nvme0n1 (3.6TB NVMe SSD) → /workspace
#   sda     (500GB Samsung SSD) → / (OS)
#   sdb     (238GB ADATA SSD)  → swap 또는 예비
#   sdc     (1.8TB HDD)       → /tmp 또는 임시
#
# 예상 소요: 약 50~60분
#############################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠️  $1${NC}"; }
err() { echo -e "${RED}[$(date '+%H:%M:%S')] ❌ $1${NC}"; exit 1; }

# root 확인
[ "$(id -u)" -eq 0 ] || err "root 권한이 필요합니다. sudo bash $0 으로 실행하세요."

echo ""
echo "==========================================="
echo "  디스크 마이그레이션 스크립트"
echo "==========================================="
echo ""
echo "  현재 구성:"
echo "    / (OS)       → nvme0n1 (3.6TB NVMe)"
echo "    /workspace   → sdc     (1.8TB HDD)"
echo ""
echo "  목표 구성:"
echo "    / (OS)       → sda     (500GB Samsung SSD)"
echo "    /workspace   → nvme0n1 (3.6TB NVMe SSD)"
echo "    임시작업     → sdc     (1.8TB HDD)"
echo ""
echo "  ⚠️  이 작업은 sda, nvme0n1의 데이터를 모두 삭제합니다."
echo "  ⚠️  실패 시 부팅 불가능할 수 있습니다."
echo ""
read -p "  계속하시겠습니까? (yes/no): " CONFIRM
[ "$CONFIRM" = "yes" ] || { echo "취소되었습니다."; exit 0; }

#############################################################
# 0단계: 서비스 중지
#############################################################
log "0단계: 서비스 중지"
cd /workspace/jayeondeule && ./agriAiCore stop 2>/dev/null || true
sleep 3
log "서비스 중지 완료"

#############################################################
# 1단계: sda 파티셔닝 + 포맷 (OS용)
#############################################################
log "1단계: sda (Samsung SSD 500GB) 파티셔닝"
umount /dev/sda1 2>/dev/null || true

# 현재 부트가 GPT인지 확인
BOOT_TABLE=$(blkid -o value -s PTTYPE /dev/nvme0n1 2>/dev/null || echo "gpt")
log "  현재 루트 파티션 테이블: $BOOT_TABLE"

parted -s /dev/sda mklabel gpt
parted -s /dev/sda mkpart primary ext4 1MiB 100%
partprobe /dev/sda
sleep 2
# 파티션 인식 대기
if [ ! -b /dev/sda1 ]; then
    warn "파티션 인식 대기 중..."
    sleep 3
    partprobe /dev/sda
    sleep 2
fi
[ -b /dev/sda1 ] || err "/dev/sda1이 생성되지 않았습니다. 수동 확인 필요."
mkfs.ext4 -F /dev/sda1
log "sda 파티셔닝 + 포맷 완료"

#############################################################
# 2단계: OS 복제 (nvme0n1 → sda)
#############################################################
log "2단계: OS 복제 시작 (nvme0n1 → sda, 약 12분)"
mkdir -p /mnt/newroot
mount /dev/sda1 /mnt/newroot

rsync -aAXv --info=progress2 / /mnt/newroot/ \
  --exclude=/workspace/ \
  --exclude=/media/ \
  --exclude=/proc/ \
  --exclude=/sys/ \
  --exclude=/dev/ \
  --exclude=/run/ \
  --exclude=/tmp/ \
  --exclude=/mnt/ \
  --exclude=/snap/ \
  --exclude=/swap.img \
  --exclude=/lost+found

# 필수 디렉토리 생성
mkdir -p /mnt/newroot/{proc,sys,dev,run,tmp,mnt,workspace,media,snap}
chmod 1777 /mnt/newroot/tmp
log "OS 복제 완료"

#############################################################
# 3단계: nvme0n1 재파티셔닝 (/workspace 용)
#############################################################
log "3단계: nvme0n1 재파티셔닝 (주의: 현재 루트 — 복제 완료 확인)"

# 복제 검증
if [ ! -f /mnt/newroot/etc/fstab ]; then
    err "OS 복제 검증 실패: /mnt/newroot/etc/fstab 없음. 중단합니다."
fi
if [ ! -d /mnt/newroot/usr/bin ]; then
    err "OS 복제 검증 실패: /mnt/newroot/usr/bin 없음. 중단합니다."
fi
log "  OS 복제 검증 통과"

# /workspace를 임시로 sda에 복제 (nvme0n1 포맷 전 안전장치)
log "  /workspace 임시 백업 중..."
mkdir -p /mnt/newroot/workspace_backup_flag
# workspace는 너무 크므로 nvme0n1 포맷 전에 직접 HDD→NVMe로 복사

#############################################################
# 4단계: /workspace 복제 (sdc HDD → nvme0n1 NVMe)
# ⚠️ 이 단계에서 nvme0n1을 포맷하므로 현재 OS가 불안정해질 수 있음
# → 재부팅 후 sda에서 부팅한 뒤 실행하는 것이 안전
#############################################################
warn "4단계는 재부팅 후 sda 부팅 상태에서 실행해야 안전합니다."
warn "지금 nvme0n1을 포맷하면 현재 실행 중인 OS가 파괴됩니다."
echo ""
echo "  [안전한 진행 방법]"
echo "  1. 먼저 GRUB을 sda에 설치하고 재부팅"
echo "  2. BIOS에서 sda로 부팅"
echo "  3. 그 후 nvme0n1 포맷 + /workspace 복제"
echo ""
read -p "  GRUB 설치 후 재부팅 방식으로 진행할까요? (yes/no): " SAFE_MODE
if [ "$SAFE_MODE" != "no" ]; then
    SAFE_MODE="yes"
fi

#############################################################
# 5단계: fstab 수정 (새 OS에)
#############################################################
log "5단계: fstab 수정"
SDA1_UUID=$(blkid -s UUID -o value /dev/sda1)
log "  sda1 UUID: $SDA1_UUID"

cat > /mnt/newroot/etc/fstab << EOF
# /etc/fstab — 디스크 마이그레이션 후 설정
# sda1 → / (OS, Samsung SSD 850 EVO)
UUID=$SDA1_UUID / ext4 defaults 0 1

# nvme0n1p1 → /workspace (마이그레이션 2단계에서 UUID 업데이트 필요)
# WORKSPACE_PLACEHOLDER /workspace ext4 defaults 0 2

/swap.img none swap sw 0 0
EOF
log "  fstab 작성 완료 (workspace는 2단계에서 추가)"

#############################################################
# 6단계: GRUB 설치 (sda에 부트로더)
#############################################################
log "6단계: GRUB 설치 (sda)"
mount --bind /dev /mnt/newroot/dev
mount --bind /proc /mnt/newroot/proc
mount --bind /sys /mnt/newroot/sys
mount --bind /run /mnt/newroot/run

chroot /mnt/newroot grub-install /dev/sda
chroot /mnt/newroot update-grub

umount /mnt/newroot/run
umount /mnt/newroot/sys
umount /mnt/newroot/proc
umount /mnt/newroot/dev

log "GRUB 설치 완료"

echo ""
echo "==========================================="
echo "  1단계 완료!"
echo "==========================================="
echo ""
echo "  다음 단계:"
echo "  1. 재부팅: sudo reboot"
echo "  2. BIOS에서 Samsung SSD 850 EVO를 1순위 부팅으로 설정"
echo "  3. sda에서 부팅 후, 2단계 스크립트 실행:"
echo "     sudo bash /root/disk_migration_step2.sh"
echo ""

# 2단계 스크립트 생성 (새 OS에)
cat > /mnt/newroot/root/disk_migration_step2.sh << 'STEP2'
#!/bin/bash
set -e
GREEN='\033[0;32m'
NC='\033[0m'
log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }

echo "==========================================="
echo "  디스크 마이그레이션 2단계"
echo "  nvme0n1 포맷 + /workspace 복제"
echo "==========================================="

# 현재 / 가 sda에서 부팅되었는지 확인
ROOT_DEV=$(df / | tail -1 | awk '{print $1}')
if [[ "$ROOT_DEV" == *"nvme"* ]]; then
    echo "❌ 아직 nvme0n1에서 부팅 중입니다. sda에서 부팅 후 실행하세요."
    exit 1
fi
log "sda 부팅 확인: $ROOT_DEV"

# nvme0n1 파티셔닝
log "nvme0n1 파티셔닝 시작"
parted -s /dev/nvme0n1 mklabel gpt
parted -s /dev/nvme0n1 mkpart primary ext4 1MiB 100%
mkfs.ext4 -F /dev/nvme0n1p1
log "nvme0n1 포맷 완료"

# /workspace 복제 (HDD → NVMe)
log "/workspace 복제 시작 (HDD → NVMe, 약 36분)"
mkdir -p /mnt/new_workspace
mount /dev/nvme0n1p1 /mnt/new_workspace
# sdc1이 /workspace에 마운트되어 있는지 확인
if ! mountpoint -q /workspace 2>/dev/null; then
    mount /dev/sdc1 /workspace
fi
rsync -aAXv --info=progress2 /workspace/ /mnt/new_workspace/
log "/workspace 복제 완료"

# fstab 업데이트
NVME_UUID=$(blkid -s UUID -o value /dev/nvme0n1p1)
log "nvme0n1p1 UUID: $NVME_UUID"

# fstab에 workspace 추가
sed -i '/WORKSPACE_PLACEHOLDER/d' /etc/fstab
echo "UUID=$NVME_UUID /workspace ext4 defaults 0 2" >> /etc/fstab
log "fstab 업데이트 완료"

# workspace를 새 디스크로 재마운트
umount /workspace 2>/dev/null || true
umount /mnt/new_workspace
mount /dev/nvme0n1p1 /workspace
log "/workspace 재마운트 완료 (NVMe)"

echo ""
echo "==========================================="
echo "  마이그레이션 완료!"
echo "==========================================="
echo ""
df -h / /workspace
echo ""
echo "  서비스 시작: cd /workspace/jayeondeule && sudo ./agriAiCore start"
echo ""
STEP2
chmod +x /mnt/newroot/root/disk_migration_step2.sh

umount /mnt/newroot
log "스크립트 완료. 위 안내대로 진행하세요."
