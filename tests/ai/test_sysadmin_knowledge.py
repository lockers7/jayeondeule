# 시스템관리 SSH 지식 시드 검증 — 원격 유지보수 RAG.
import inspect
from agri_ai_core.src.ai import sysadmin_knowledge as sa


def test_docs_cover_os_and_rpi():
    keys = {k for k, _ in sa.SYSADMIN_DOCS}
    # RPi 농장관리 핵심 + OS별
    for k in ("sa_workflow", "sa_rpi_gpio", "sa_rpi_1wire", "sa_rpi_i2c",
              "sa_rpi_service", "sa_rpi_debug", "sa_linux_service", "sa_win_service", "sa_safety"):
        assert k in keys, k


def test_rpi_relay_and_sensor_commands():
    docs = {k: v for k, v in sa.SYSADMIN_DOCS}
    assert "gpiozero" in docs["sa_rpi_gpio"] and "active" in docs["sa_rpi_gpio"]
    assert "w1_slave" in docs["sa_rpi_1wire"]        # DS18B20 수온
    assert "i2cdetect" in docs["sa_rpi_i2c"]


def test_seed_wired_into_system_knowledge():
    from agri_ai_core.src.ai import system_knowledge as sk
    src = inspect.getsource(sk.seed_system_knowledge)
    assert "seed_sysadmin_knowledge" in src           # 재시드에도 영속
