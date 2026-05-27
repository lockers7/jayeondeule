# ══════════════════════════════════════════════════════════════════════════════
# test_tools_service — 서버 관리 도구 (3단계, 2026-07-17)
#
# ⛔ 최대 위험 = LLM 이 농장을 무제어 상태로 만드는 것.
#   stop 을 **구현하지 않는 것** 이 그 방어다. 이 테스트가 그걸 못 박는다.
#
# 파일 시작 함수 목록:
#   test_stop_not_implemented    : stop/disable 함수가 아예 없음
#   test_whitelist_only          : 화이트리스트 밖 서비스 거부
#   test_postgres_chroma_excluded: PostgreSQL/ChromaDB 는 대상 제외
#   test_status_and_list         : 조회는 전체(_REGISTRY), 재기동은 좁게(_ALLOWED)
#   test_registry_covers_user_system_package : 사용자/시스템/패키지 전부 포함
#   test_registry_marks_restartable_correctly : restartable 플래그 정합성
#   test_no_sudo_password_path   : sudo -S/DB비밀번호 경로 없음 (root 경로 부활 방지)
#   test_systemd_units_use_restart_only : systemd 는 restart 직접 (stop 미사용)
#   test_restart_health_retry    : 헬스 실패 시 2회 시도 후 사유 반환
#   test_registered_in_5_places  : 5중 등록
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch

from agri_ai_core.src.ai import tools_service as tsv


def test_stop_not_implemented():
    # ⛔ stop 이 생기는 순간 LLM 이 농장 제어를 멈출 수 있다. 코드에 없어야 한다.
    for banned in ("stop_service", "disable_service", "kill_service", "shutdown"):
        assert not hasattr(tsv, banned), f"{banned} 가 구현됨 — 농장 무제어 위험"


def test_whitelist_only():
    for no in (2, 3, 18, 99, 0, -1):
        r = tsv.restart_service(no, reason="pytest")
        assert r["success"] is False, f"화이트리스트 우회: {no}"
    assert tsv.restart_service("abc")["success"] is False


def test_postgres_chroma_excluded():
    # 재기동 시 전 서비스 연쇄 영향 → 대상에서 뺀다
    assert 2 not in tsv._ALLOWED, "PostgreSQL 이 재기동 대상에 포함됨"
    assert 3 not in tsv._ALLOWED, "ChromaDB 가 재기동 대상에 포함됨"


def test_status_and_list():
    # ⛔ 조회는 agriAiCore 등록 **전체**(_REGISTRY), 재기동은 좁은 화이트리스트(_ALLOWED).
    #   2026-07-17: 처음엔 조회에도 _ALLOWED 를 써서 6개만 보였고, 농장주가
    #   "각 서비스란 llm·ollama·chromadb·schedule 등 등록된 전체"라고 지적했다.
    with patch.object(tsv, "_health", lambda spec: True):
        r = tsv.list_services()
        assert r["success"] is True
        assert r["count"] == len(tsv._REGISTRY)
        assert r["count"] > len(tsv._ALLOWED), "조회가 재기동 목록으로 좁혀짐"
        assert all(s["healthy"] for s in r["services"])
        r = tsv.service_status(5)
        assert r["success"] is True and r["name"] == "FastAPI"
    assert tsv.service_status(99)["success"] is False


def test_registry_covers_user_system_package():
    # 농장주 정의: 사용자 / 시스템 / 패키지 서비스 전부
    names = {c["name"] for c in tsv._REGISTRY}
    for must in ("Ollama", "PostgreSQL", "ChromaDB", "Scheduler", "FastAPI",
                 "SearXNG", "Nginx", "Web Backend", "Shop Backend"):
        assert must in names, f"{must} 가 조회 목록에 없음"
    cats = {c["category"] for c in tsv._REGISTRY}
    assert cats == {"사용자", "시스템", "패키지"}, f"분류 누락: {cats}"


def test_registry_marks_restartable_correctly():
    # 조회 목록의 restartable 은 _ALLOWED 와 정확히 일치해야 한다 —
    # 어긋나면 LLM 이 재기동 불가한 서비스를 시도한다.
    r = tsv.list_services()
    for s_ in r["services"]:
        assert s_["restartable"] == (s_["service_no"] in tsv._ALLOWED)
    # PostgreSQL/Nginx 는 조회는 되지만 재기동은 불가
    by_no = {s_["service_no"]: s_ for s_ in r["services"]}
    assert by_no[2]["restartable"] is False, "PostgreSQL 재기동 허용됨 — 연쇄영향"
    assert by_no[9]["restartable"] is False, "Nginx 재기동 허용됨"


def test_no_sudo_password_path():
    # ⛔ 2026-07-17 비-root 전환. 서비스 본체는 jayeondeule 로 돈다.
    #   systemd 유닛만 `sudo -n systemctl restart <unit>` 을 쓰는데, 이는
    #   /etc/sudoers.d/agri_llm 의 NOPASSWD 화이트리스트(restart 전용)에 의존한다.
    #   ⛔ 비밀번호를 코드가 다루면(sudo -S + DB 조회) LLM 이 root 를 얻는다 — 금지.
    import inspect
    src = inspect.getsource(tsv.restart_service)
    assert "sudo -S" not in src and "-S" not in src.split("sudo")[1][:20], \
        "sudo -S(비밀번호 주입) 사용 — root 경로 부활"
    assert not hasattr(tsv, "_sudo_password"), "_sudo_password 잔존 — root 경로 부활"
    assert "sudo_passwd" not in inspect.getsource(tsv), "DB 비밀번호 조회 잔존"


def test_systemd_units_use_restart_only():
    # agriAiCore 의 restart 는 내부적으로 systemctl stop 을 호출한다.
    # stop 을 sudoers 에 넣으면 LLM 이 서비스를 정지시킬 수 있어 3단계 방어가 무너진다.
    # → systemd 유닛은 systemctl restart 를 직접 쓴다.
    import inspect
    src = inspect.getsource(tsv.restart_service)
    assert '"restart", unit' in src or '"systemctl", "restart"' in src, \
        "systemd 유닛이 restart 직접 경로를 쓰지 않음"
    assert '"stop"' not in src, "restart_service 가 stop 을 호출함 — 정지 위험"
    # 유닛명이 화이트리스트에 고정돼 있어야 임의 유닛 조작이 불가하다
    units = {c.get("unit") for c in tsv._ALLOWED.values() if c.get("unit")}
    assert units == {"agent_monitor", "agent_pending_worker", "agent_event_listener"}


def test_restart_health_retry():
    calls = {"n": 0}

    def _run(*a, **k):
        calls["n"] += 1
        class _R:
            stdout, stderr, returncode = "", "", 0
        return _R()

    with patch.object(tsv, "_health", lambda spec: False), \
         patch.object(tsv.subprocess, "run", _run), \
         patch.object(tsv.time, "sleep", lambda s: None):
        r = tsv.restart_service(5, reason="pytest")
    assert r["success"] is False
    assert calls["n"] == 2, "헬스 실패 시 1회 자동 재시도해야 함"
    assert "search_logs" in r["error"], "LLM 이 다음에 뭘 할지 안내해야 함"


def test_registered_in_5_places():
    from agri_ai_core.src.ai.tools_definition import get_available_tools
    from agri_ai_core.src.ai.pipeline.question_analyzer import _VALID_TOOLS
    names = [t["function"]["name"] for t in get_available_tools()]
    for tool in ("restart_service", "service_status", "list_services"):
        assert tool in names, f"{tool} LLM 미노출"
        assert tool in _VALID_TOOLS, f"{tool} ANALYZER 누락"


# ⛔ 회귀 방지 (2026-07-17): 헬스 판정을 실체와 맞추지 않으면 LLM 이 오보한다.
#   ① Camera Archive 는 독립 프로세스가 아니라 Scheduler 내부 작업 —
#      ("proc","camera_archive") 로 찾아 "다운"으로 오보했다.
#   ② RPi Camera 는 5199 원격 보드 SSH wrapper — 농장주가 보드를 교체하며
#      setup 검증 중이라 미가동이 곧 장애가 아니다(optional).
def test_camera_archive_not_proc_based():
    cfg = next(c for c in tsv._REGISTRY if c["no"] == 14)
    kind, _ = cfg["health"]
    assert kind != "proc", "Camera Archive 는 전용 프로세스가 없다 — proc 판정 시 상시 '다운' 오보"


def test_rpi_camera_is_optional():
    cfg = next(c for c in tsv._REGISTRY if c["no"] == 13)
    assert cfg.get("optional") is True, "RPi Camera(원격 5199)는 미가동이 장애가 아니다"


def test_optional_excluded_from_down():
    # optional 서비스가 down 목록에 들어가면 농장주가 불필요한 경보를 받는다
    def _h(spec):
        return False
    with patch.object(tsv, "_health", _h):
        r = tsv.list_services()
    opt_names = {c["name"] for c in tsv._REGISTRY if c.get("optional")}
    assert not (set(r["down"]) & opt_names), f"optional 이 장애로 집계됨: {r['down']}"
