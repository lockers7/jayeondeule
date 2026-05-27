# ══════════════════════════════════════════════════════════════════════════════
# test_kakao_notify — 카카오 '나에게 보내기' 알림 검증 (HTTP mock)
#
# 파일 시작 함수 목록:
#   test_noop_without_key        : REST 키 미설정 → push_alert 완전 no-op
#   test_auth_url                : 인증 URL 생성 (scope=talk_message)
#   test_exchange_and_send       : code 교환 → 토큰 저장 → 발송 payload 검증
#   test_text_truncation         : 200자 초과 본문 분할 발송
#   test_level_filter            : KAKAO_PUSH_MIN_LEVEL 필터 동작
#   test_refresh_rotation        : 갱신 응답의 새 refresh_token 교체 저장
# ══════════════════════════════════════════════════════════════════════════════
import json
import pytest

import agri_ai_core.src.ai.kakao_notify as K


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # 실 DB 토큰 행 보호: 테스트 전후 kakao_token_m 정리 (id=1 단일행 스왑)
    from agri_ai_core.src.postgresql.connection import db_session
    K.ensure_table()
    with db_session() as d:
        backup = d.fetch_one("SELECT * FROM kakao_token_m WHERE id=1", ())
        d.execute_query("DELETE FROM kakao_token_m WHERE id=1", ())
    yield
    with db_session() as d:
        d.execute_query("DELETE FROM kakao_token_m WHERE id=1", ())
        if backup:
            d.execute_query(
                "INSERT INTO kakao_token_m (id, access_token, refresh_token, "
                "access_expires_at, refresh_expires_at) VALUES (1,%s,%s,%s,%s)",
                (backup["access_token"], backup["refresh_token"],
                 backup["access_expires_at"], backup["refresh_expires_at"]))


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)
    def json(self):
        return self._body


def test_noop_without_key(monkeypatch):
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    called = []
    monkeypatch.setattr(K, "send_to_me", lambda *a, **kw: called.append(1))
    K.push_alert("critical", "t", "b")
    assert called == []  # 키 없으면 스레드 생성 전에 종료


def test_auth_url(monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "testkey")
    r = K.build_auth_url()
    assert r["success"] and "talk_message" in r["auth_url"] and "testkey" in r["auth_url"]


def test_exchange_and_send(monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "testkey")
    posts = []

    def fake_post(url, **kw):
        posts.append((url, kw))
        if "oauth/token" in url:
            return _Resp(200, {"access_token": "AT1", "expires_in": 21599,
                               "refresh_token": "RT1", "refresh_token_expires_in": 5184000})
        return _Resp(200, {"result_code": 0})

    monkeypatch.setattr("requests.post", fake_post)
    assert K.exchange_code("authcode")["success"] is True

    r = K.send_to_me("테스트 메시지")
    assert r["success"] is True
    url, kw = posts[-1]
    assert "memo/default/send" in url
    assert kw["headers"]["Authorization"] == "Bearer AT1"
    tpl = json.loads(kw["data"]["template_object"])
    assert tpl["object_type"] == "text" and tpl["text"] == "테스트 메시지"
    assert tpl["link"]["web_url"].startswith("https://")


def test_text_truncation(monkeypatch):
    # 200자 초과 본문은 분할 발송 — 긴 보고서도 전문 전달
    monkeypatch.setenv("KAKAO_REST_API_KEY", "testkey")
    K._save_tokens("AT", 21599, "RT", 5184000)
    captured = []

    def fake_post(url, **kw):
        if "memo" in url:
            captured.append(json.loads(kw["data"]["template_object"])["text"])
        return _Resp(200, {})

    monkeypatch.setattr("requests.post", fake_post)
    r = K.send_to_me("가" * 500)
    assert r["success"] is True and r["sent_parts"] == len(captured) >= 3
    assert all(len(t) <= 200 for t in captured)
    assert captured[0].startswith("(1/")   # 조각 표기
    # 원문 전체가 조각들에 보존됐는지 (표기 제거 후 결합)
    joined = "".join(t.split(") ", 1)[1] for t in captured)
    assert joined.replace("\n", "") == "가" * 500


def test_split_chunks_line_boundary():
    # 재배사별 보고(줄 단위) — 줄 경계 우선 분할, 각 조각 200자 이하
    body = "\n".join([f"- {h}호 재배사: 습도 95% 초과, 배출팬 ON 제어 중이며 상세 사유는 다음과 같습니다 " * 2 for h in (1, 2, 3)])
    parts = K._split_chunks(body)
    assert len(parts) >= 2
    assert all(len(p) <= 200 for p in parts)
    assert "3호" in "".join(parts)   # 마지막 재배사 내용 보존


def test_level_filter(monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "testkey")
    monkeypatch.setenv("KAKAO_PUSH_MIN_LEVEL", "warning")
    sent = []
    monkeypatch.setattr(K.threading, "Thread",
                        lambda target, daemon: type("T", (), {"start": lambda s: sent.append(1)})())
    K.push_alert("info", "t", "b")
    assert sent == []          # info < warning → 미발송
    K.push_alert("critical", "t", "b")
    assert sent == [1]         # critical ≥ warning → 발송


def test_refresh_rotation(monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "testkey")
    K._save_tokens("OLD_AT", -100, "OLD_RT", 5184000)  # access 만료 상태

    def fake_post(url, **kw):
        assert kw["data"]["refresh_token"] == "OLD_RT"
        return _Resp(200, {"access_token": "NEW_AT", "expires_in": 21599,
                           "refresh_token": "NEW_RT", "refresh_token_expires_in": 5184000})

    monkeypatch.setattr("requests.post", fake_post)
    token = K._get_valid_access_token()
    assert token == "NEW_AT"
    saved = K._load_tokens()
    assert saved["refresh_token"] == "NEW_RT"  # 회전된 refresh 교체 저장 확인
