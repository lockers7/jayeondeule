# ══════════════════════════════════════════════════════════════════════════════
# test_log_cleanup_filename — delete_old_daily_logs 파일명 파싱 버그 회귀
#   shop_goheung_YYYY-MM-DD.log(농장명 삽입)·shop_backend.log(날짜없음) 대응 검증.
#   버그: split("_",1)[1] 이 'goheung_2026-07-20' 를 날짜로 파싱 시도 → 매일 오류.
# ══════════════════════════════════════════════════════════════════════════════
import io, os, sys
from contextlib import redirect_stderr
from datetime import datetime


def _touch(d, name):
    p = os.path.join(d, name)
    open(p, "w").close()
    return p


def test_cleanup_handles_farmname_and_undated(tmp_path):
    from agri_ai_core.logs import delete_old_daily_logs
    d = str(tmp_path)
    today = datetime.now().strftime("%Y-%m-%d")
    old = "2020-01-01"
    # 오래된(삭제 대상)
    _touch(d, f"ai_{old}.log")
    _touch(d, f"web_{old}.log")
    _touch(d, f"shop_goheung_{old}.log")   # ← 예전엔 파싱오류 나던 파일
    _touch(d, f"shop_{old}.log")
    # 날짜 없는(스킵 대상 — 오류 아님)
    _touch(d, "shop_backend.log")
    # 최근(보존)
    _touch(d, f"ai_{today}.log")

    err = io.StringIO()
    with redirect_stderr(err):
        deleted = delete_old_daily_logs(d, days=100)
    stderr_out = err.getvalue()

    # 1) 어떤 파일에서도 '삭제 오류'(파싱실패) 가 없어야 함
    assert "삭제 오류" not in stderr_out, f"파싱 오류 발생: {stderr_out}"
    assert "does not match format" not in stderr_out
    # 2) 오래된 파일(농장명 삽입 포함) 전부 삭제됨
    for n in (f"ai_{old}.log", f"web_{old}.log", f"shop_goheung_{old}.log", f"shop_{old}.log"):
        assert not os.path.exists(os.path.join(d, n)), f"미삭제: {n}"
    # 3) 날짜 없는 파일은 보존(정리 대상 아님)
    assert os.path.exists(os.path.join(d, "shop_backend.log"))
    # 4) 최근 파일 보존
    assert os.path.exists(os.path.join(d, f"ai_{today}.log"))
    assert deleted == 4
