# ══════════════════════════════════════════════════════════════════════════════
# 시스템관리 SSH 명령 지식 시드 — 원격(Windows/Linux/RaspberryPi) 유지보수 RAG
#
# 농장주 지시(2026-07-24): 로컬 LLM이 SSH로 원격 서버(특히 라즈베리파이의 농장관리
#   센서·릴레이 프로그램)를 스스로 파악·유지보수하도록, OS별 SSH 시스템관리 명령
#   사용법을 RAG로 저장해 즉시 사용 가능하게. remote_status/remote_run 과 결합.
#   저장은 system_knowledge(document_collection, category='sysadmin'). 각 320자 내 핵심.
#
# 파일 시작 함수 목록:
#   seed_sysadmin_knowledge : 시스템관리 명령 문서 일괄 upsert(멱등)
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# (key, text) — 각 320자 내 핵심. remote_run(host, command) 로 실행할 실제 명령 포함.
SYSADMIN_DOCS = [
    # ── 원격 유지보수 워크플로우 ──
    ("sa_workflow",
     "[원격 유지보수 절차] ①remote_status(host)로 리소스·서비스·failed 파악 →②remote_run 으로 "
     "로그·설정·코드 조사(read-only 즉시) →③원인 진단 →④수정안 마련 →⑤변경성 명령(재시작·파일수정·"
     "설치)은 remote_run 하면 승인요청됨 → 관리자 승인(approve_remote_command) 후 집행 →⑥재조회로 "
     "검증. 추측 금지 — 실제 로그·파일·상태를 remote_run 으로 확인 후 판단."),
    ("sa_ssh_basics",
     "[SSH 사용] 원격 조사는 remote_status(host)·remote_run(host, command). host 는 등록이름"
     "(manage_remote_host) 또는 'user@host:port'. 키 인증만(비번 불가). 파일 본문은 remote_run "
     "host cmd='cat 파일', 목록은 'ls -al 경로', 검색은 'grep -rn 패턴 경로'."),

    # ── Linux 일반 ──
    ("sa_linux_service",
     "[Linux 서비스] 상태: systemctl status <svc> / systemctl is-active <svc> / 목록 "
     "systemctl list-units --type=service --state=running|failed. 로그 journalctl -u <svc> -n 100 "
     "--no-pager. ⚠️변경성(승인필요): systemctl restart|start|stop <svc>, systemctl enable <svc>."),
    ("sa_linux_process",
     "[Linux 프로세스] ps -eo pid,pcpu,pmem,comm --sort=-pcpu | head / pgrep -af <이름> / "
     "특정 포트 점유 ss -tlnp | grep :<포트> 또는 lsof -i:<포트>. ⚠️종료 kill -9 <pid>(승인필요)."),
    ("sa_linux_resource",
     "[Linux 리소스] CPU/부하 uptime, cat /proc/loadavg, top -bn1 | head. 메모리 free -m. "
     "디스크 df -h / 디렉토리 용량 du -sh <경로>/* | sort -h. 코어 nproc. GPU nvidia-smi. "
     "온도 sensors(lm-sensors)."),
    ("sa_linux_log",
     "[Linux 로그] journalctl -u <svc> -n 200 --no-pager / journalctl --since '1 hour ago' / "
     "부팅오류 dmesg -T | tail. 텍스트 로그 tail -n 200 /var/log/<파일> · grep -n ERROR "
     "/var/log/<파일>. 실시간은 원격에선 tail 스냅샷으로(무한 -f 금지)."),
    ("sa_linux_pkg",
     "[Linux 패키지] 설치확인 dpkg -l | grep <pkg> / which <cmd> / <cmd> --version. python "
     "패키지 pip show <pkg> 또는 python -c 'import <m>; print(<m>.__version__)'. ⚠️설치 apt install / "
     "pip install(승인필요)."),
    ("sa_linux_file",
     "[Linux 파일·권한] 보기 cat/less/head/tail, 검색 grep -rn '패턴' <경로>, 찾기 find <경로> "
     "-name '*.py'. 권한 ls -al, 소유 stat <파일>. ⚠️변경(승인): 수정은 편집 대신 원격 파일이면 "
     "sed -i·tee·리다이렉트(>)가 필요 — 전부 승인 대상. 백업 후 변경 권장."),
    ("sa_linux_net",
     "[Linux 네트워크] 리스닝 포트 ss -tlnp, 연결 ss -tnp, IP ip a, 라우팅 ip r, 헬스 "
     "curl -sS -m5 http://host:port/path 또는 ping -c3 host. DNS getent hosts <도메인>."),
    ("sa_linux_cron",
     "[Linux 예약작업] 사용자 크론 crontab -l, 시스템 ls /etc/cron.d /etc/cron.*. systemd 타이머 "
     "systemctl list-timers --no-pager. ⚠️변경 crontab -e/설치(승인필요)."),

    # ── RaspberryPi (농장관리 핵심) ──
    ("sa_rpi_overview",
     "[RaspberryPi 개요] 모델·펌웨어 cat /proc/device-tree/model, vcgencmd version. 설정 "
     "/boot/config.txt·/boot/cmdline.txt, raspi-config(대화형→비대화 raspi-config nonint). "
     "OS cat /etc/os-release. 사용자 보통 pi. 농장 프로그램은 systemd 서비스 또는 python 스크립트."),
    ("sa_rpi_temp_power",
     "[RPi 온도·전원] CPU온도 vcgencmd measure_temp, 클럭 vcgencmd measure_clock arm, 전압 "
     "vcgencmd measure_volts. ⚠️저전압/스로틀 vcgencmd get_throttled (0x0=정상, 비0=전원·과열 문제). "
     "SD 상태·용량 df -h /."),
    ("sa_rpi_gpio",
     "[RPi GPIO 릴레이제어] 핀맵 pinout(gpiozero), 상태 raspi-gpio get 또는 gpio readall(wiringpi). "
     "python: from gpiozero import OutputDevice; r=OutputDevice(17, active_high=False, initial_value=False); "
     "r.on()/r.off(). ⚠️릴레이 보드는 대개 active-low(LOW=ON) — active_high=False 주의. 실제제어는 승인."),
    ("sa_rpi_i2c",
     "[RPi I2C 센서] 활성화 raspi-config nonint do_i2c 0. 장치 스캔 i2cdetect -y 1(주소 목록). "
     "레지스터 읽기 i2cget -y 1 0x<addr> 0x<reg>. python: import smbus2; bus=smbus2.SMBus(1); "
     "bus.read_i2c_block_data(addr,reg,n). SHT/BME 등 온습도·CO2 센서에 사용."),
    ("sa_rpi_1wire",
     "[RPi 1-Wire 수온(DS18B20)] 활성화 raspi-config nonint do_onewire 0(+/boot/config.txt dtoverlay="
     "w1-gpio). 값 cat /sys/bus/w1/devices/28-*/w1_slave (t= 뒤 밀리℃). 센서 목록 ls "
     "/sys/bus/w1/devices/. 수온계 관리에 사용."),
    ("sa_rpi_spi",
     "[RPi SPI] 활성화 raspi-config nonint do_spi 0. 장치 ls /dev/spidev*. python spidev 로 "
     "ADC(MCP3008 등) 아날로그 센서 읽기. 조도·수위 등 아날로그 센서에."),
    ("sa_rpi_service",
     "[RPi 농장 프로그램 관리] 서비스 확인 systemctl status <farm_svc> / 로그 journalctl -u "
     "<farm_svc> -n 200 --no-pager. 자동시작 systemctl is-enabled. 유닛파일 위치 "
     "systemctl cat <farm_svc> 또는 /etc/systemd/system/*.service. ⚠️재시작·enable·데몬리로드"
     "(systemctl daemon-reload)는 승인필요."),
    ("sa_rpi_code",
     "[RPi 코드 유지보수] 프로그램 위치 파악: systemctl cat <svc> 의 ExecStart 경로, 또는 "
     "find /home/pi /opt -name '*.py' | grep -i 'sensor\\|relay\\|farm'. 본문 cat, 검색 "
     "grep -rn '함수명' <경로>. python 버전·패키지 python3 --version / pip list. venv 있으면 "
     "그 python 사용. 수정은 백업(cp) 후 편집·재시작(승인)."),
    ("sa_rpi_python",
     "[RPi python 개발] 센서/릴레이 라이브러리: gpiozero·RPi.GPIO(GPIO), smbus2(I2C), spidev(SPI), "
     "adafruit-circuitpython-*(센서 드라이버), w1thermsensor(DS18B20). 설치확인 pip show <pkg>. "
     "테스트는 짧은 python -c 로 센서 1회 읽기부터. 서비스 코드는 venv python 경로 확인."),
    ("sa_rpi_debug",
     "[RPi 디버깅 흐름] ①systemctl status <svc>로 실패여부·최근 종료코드 →②journalctl -u <svc> "
     "-n 200 로 traceback 확인 →③원인(센서 미인식 i2cdetect·1wire 없음, 권한, 패키지, 배선) 격리 "
     "→④수정 →⑤systemctl restart 후 journalctl -f 스냅샷으로 정상 재기동 확인. 센서 미인식은 "
     "먼저 raspi-config 인터페이스 활성화·배선·주소 확인."),

    # ── Windows (SSH → PowerShell/cmd) ──
    ("sa_win_service",
     "[Windows 서비스] PowerShell: Get-Service <name> / Get-Service | Where Status -eq 'Running'. "
     "cmd: sc query <name>. ⚠️변경 Restart-Service <name> / sc start|stop(승인필요, 관리자권한)."),
    ("sa_win_process",
     "[Windows 프로세스] Get-Process | Sort CPU -desc | Select -First 10 / tasklist. 포트 "
     "netstat -ano | findstr :<포트>. ⚠️종료 Stop-Process -Id <pid> / taskkill /PID <pid> /F(승인)."),
    ("sa_win_resource",
     "[Windows 리소스] 개요 systeminfo. CPU/메모리 Get-CimInstance Win32_OperatingSystem | "
     "Select FreePhysicalMemory,TotalVisibleMemorySize. 디스크 Get-PSDrive -PSProvider FileSystem "
     "또는 wmic logicaldisk get size,freespace,caption. GPU nvidia-smi(설치시)."),
    ("sa_win_log",
     "[Windows 로그·파일] 이벤트 Get-WinEvent -LogName System -MaxEvents 50 / Get-EventLog "
     "-LogName Application -Newest 50. 파일 Get-Content <path> -Tail 200, 검색 Select-String "
     "'패턴' <path>, 목록 Get-ChildItem <path>. SSH 기본셸이 cmd면 powershell -c \"…\" 로 감싼다."),

    # ── 안전·주의 ──
    ("sa_safety",
     "[원격 작업 안전] ⛔변경성 명령(rm·mv·systemctl restart·설치·파일수정 리다이렉트·재부팅)은 "
     "remote_run 하면 자동 승인보류→관리자 승인 후에만 집행된다. 조회로 충분히 파악한 뒤 최소 변경. "
     "파일 수정 전 cp 백업. 라즈베리파이 재부팅(sudo reboot)은 농장 제어 중단 위험 — 꼭 필요시만 승인 요청."),
]


def seed_sysadmin_knowledge():
    from agri_ai_core.src.ai.system_knowledge import save_system_knowledge
    n = 0
    for key, text in SYSADMIN_DOCS:
        if save_system_knowledge(text, category="sysadmin", source="seed", key=key).get("success"):
            n += 1
    logger.info(f"[시스템관리지식] 시드 완료: {n}/{len(SYSADMIN_DOCS)}건")
    return {"success": True, "seeded": n, "total": len(SYSADMIN_DOCS)}
