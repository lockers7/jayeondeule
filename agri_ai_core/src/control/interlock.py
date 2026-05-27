# ═══════════════════════════════════════════════════════════════════════
# 밸브-팬 인터록 모듈.
# AI/알고리즘/수동 모든 모드의 set_relay_value 가 통과해야 하는 단일 게이트.
# 위험 전이 5종(팬 OFF→ON 2개, 밸브 ON→OFF 3개) 만 검사하며 그 외는 본질 안전.
#
# Rule 1: 흡입팬 ON  → 흡입밸브 ON OR 순환밸브 ON ≥ N초 경과 후 가능
# Rule 2: 배출팬 ON  → 배출밸브 ON OR 순환밸브 ON ≥ N초 경과 후 가능
# Rule 3: 흡입밸브 OFF → 흡입팬 OFF OR (순환밸브 ON AND 배출팬 ON)
# Rule 4: 배출밸브 OFF → 배출팬 OFF OR (순환밸브 ON AND 흡입팬 ON)
# Rule 5: 순환밸브 OFF → (흡입팬 OFF OR 흡입밸브 ON) AND (배출팬 OFF OR 배출밸브 ON)
#         (Rule 1/2 invariant 보존 — 각 ON 팬은 자기 측 비순환 밸브 ON 필수)
# --->
# record_valve_transitions: 릴레이 쓰기 직후 OFF→ON 전이 시각 latch 갱신
# get_valve_dwell_sec: 특정 밸브가 ON 상태로 머문 시간(초)
# bootstrap_valve_state: DB 의 가장 최근 RELAY_L_RECORDING 으로 latch 복원
# evaluate_interlock: target_relay 를 Rule 1~5 로 검사해 위반 시 보정 + 위반 사유
# get_interlock_status: 흡입팬/배출팬 잔여 가동가능 시간(초) — UI 표시용
# clear_state: 테스트용 latch 초기화
# ═══════════════════════════════════════════════════════════════════════
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.control.control_common import get_pin_map, SEMANTIC_LABELS

logger = setup_logger(__name__)


# ══════════════════
# 인터록 임계값 (초)
# ══════════════════
VALVE_FAN_INTERLOCK_SEC = int(os.environ.get("VALVE_FAN_INTERLOCK_SEC", "10"))


# ══════════════════════════════════════════════════════════════════════════
# 팬 → 선행 밸브 매핑 (둘 중 하나가 임계 이상 ON 이면 팬 ON 허용)
#
# ⛔⛔ 절대 제거 금지 — 사용자(농장주) 명시 지시 ⛔⛔
#   "운용모드에 관계없이 제어 마지막 부분에 아래 2개의 비상제어 코드가
#    반드시 있어야 한다:
#      · 흡입팬 ON 은 반드시 흡입밸브 ON 혹은 순환밸브 ON 이어야 함
#      · 배출팬 ON 은 반드시 배출밸브 ON 혹은 순환밸브 ON 이어야 함"
#   밸브가 닫힌 채 팬이 돌면 모터 소손(물리 파손). 이 매핑과 아래
#   evaluate_interlock (전이 게이트 + 최종 불변식 강제) 은 그 지시의 구현이며,
#   어떤 리팩토링/최적화에서도 삭제·우회(skip 플래그 추가 포함) 금지.
#   호출 위치: relay_manager.set_relay_value — 모든 제어 경로(LLM/agent/스케줄/
#   수동/비상가드)의 최종 관문.
# ══════════════════════════════════════════════════════════════════════════
FAN_VALVE_GATE = {
    'intake_fan_flag':  ('air_intake_valve_flag',  'air_circulation_valve_flag'),
    'exhaust_fan_flag': ('air_exhaust_valve_flag', 'air_circulation_valve_flag'),
}

# OFF 인터록: 밸브 OFF 시 함께 강제 OFF 해야 할 팬
VALVE_DEPENDENT_FANS = {
    'air_intake_valve_flag':      ('intake_fan_flag',),
    'air_exhaust_valve_flag':     ('exhaust_fan_flag',),
    'air_circulation_valve_flag': ('intake_fan_flag', 'exhaust_fan_flag'),
}


# ══════════════════════════════════════════════════════════════════════════
# 밸브 ON 전이 시각 latch
# key: (str(farm_id), int(house_id), valve_flag) → datetime (가장 최근 OFF→ON 전이 시각)
# 값이 없으면 "현재 OFF 또는 미상" 으로 간주 (게이트가 차단 측으로 결정)
# ══════════════════════════════════════════════════════════════════════════
_valve_on_since: Dict[Tuple[str, int, str], datetime] = {}
_valve_lock = threading.Lock()


# ────────────────────────────────────────────────────────────────────
# 밸브 latch dict 의 키 튜플 생성 — (str(farm), int(house), valve_flag).
# ────────────────────────────────────────────────────────────────────
def _key(farm_id, house_id, valve_flag):
    return (str(farm_id), int(house_id), valve_flag)


# ────────────────────────────────────────────────────────────────────
# relay_*st_flag → semantic flag 역매핑 (pin_map 의 역).
# ────────────────────────────────────────────────────────────────────
def _pin_to_flag(house_id, pin_key):
    pin_map = get_pin_map(house_id)
    for flag, pin in pin_map.items():
        if pin == pin_key:
            return flag
    return None


# ────────────────────────────────────────────────────────────────────
# semantic flag → relay_*st_flag 정매핑.
# ────────────────────────────────────────────────────────────────────
def _flag_to_pin(house_id, flag):
    return get_pin_map(house_id).get(flag)


# ══════════════════════════════════════════════════════════════════════════
# OFF→ON 전이 latch 갱신
# prev/new 는 relay_*st_flag dict (이미 게이트 통과한 최종 쓰기 값 기준).
# OFF→ON: latch 에 now() 기록 / ON→OFF: latch 에서 제거
# ══════════════════════════════════════════════════════════════════════════
def record_valve_transitions(farm_id, house_id, prev: Optional[Dict], new: Dict, now: Optional[datetime] = None):
    if not new:
        return
    now = now or datetime.now()
    prev = prev or {}
    with _valve_lock:
        for flag in FAN_VALVE_GATE.values():
            pass   # noop — flag iter 는 valve 키를 직접 사용
        for valve_flag in VALVE_DEPENDENT_FANS.keys():
            pin = _flag_to_pin(house_id, valve_flag)
            if not pin:
                continue
            prev_on = bool(prev.get(pin, False))
            new_on = bool(new.get(pin, False))
            k = _key(farm_id, house_id, valve_flag)
            if not prev_on and new_on:
                _valve_on_since[k] = now
            elif prev_on and not new_on:
                _valve_on_since.pop(k, None)


# ══════════════════════════════════════════════════════════════════════════
# 밸브가 현재 ON 상태로 머문 시간(초). OFF 또는 미상이면 None.
# ══════════════════════════════════════════════════════════════════════════
def get_valve_dwell_sec(farm_id, house_id, valve_flag, now: Optional[datetime] = None) -> Optional[float]:
    now = now or datetime.now()
    with _valve_lock:
        ts = _valve_on_since.get(_key(farm_id, house_id, valve_flag))
    if ts is None:
        return None
    return (now - ts).total_seconds()


# ══════════════════════════════════════════════════════════════════════════
# DB 의 가장 최근 RELAY_L_RECORDING 한 건으로 latch 초기화 (서비스 부팅 시 호출).
# 어느 시점에 ON 되었는지는 알 수 없으므로 "ON 인 상태이면 충분히 오래됨" 으로
# 가정하여 매우 과거 시각을 latch (= 인터록 즉시 통과). 안전 측면에서 보수적
# 선택지는 "now()" 로 두고 다시 10초 대기인데, 이는 자동 재시작 시 정상
# 가동중이던 시스템에 부당 차단을 일으키므로 과거 시각을 택함.
# ══════════════════════════════════════════════════════════════════════════
def bootstrap_valve_state(farm_id, house_id, latest_relay: Optional[Dict] = None):
    if latest_relay is None:
        try:
            from agri_ai_core.src.postgresql.reader import read_latest_relay_info
            latest_relay = read_latest_relay_info(farm_id, house_id) or {}
        except Exception as e:
            logger.warning(f"[interlock] bootstrap 실패 farm={farm_id} house={house_id}: {e}")
            return
    long_ago = datetime.now() - timedelta(hours=24)
    with _valve_lock:
        for valve_flag in VALVE_DEPENDENT_FANS.keys():
            pin = _flag_to_pin(house_id, valve_flag)
            if not pin:
                continue
            if bool(latest_relay.get(pin, False)):
                _valve_on_since[_key(farm_id, house_id, valve_flag)] = long_ago
            else:
                _valve_on_since.pop(_key(farm_id, house_id, valve_flag), None)


# ══════════════════════════════════════════════════════════════════════════
# 게이트: target_relay 를 검사해 위반 시 보정. current/target 모두 relay_*st_flag dict.
# 반환: (corrected_target, violations).  violations: [{flag, action, remaining_sec, reason}, ...]
#
# ON 인터록: 팬 OFF→ON 전이일 때만 적용. 이미 ON 인 팬은 통과 (현행 유지).
# OFF 인터록: 밸브 ON→OFF 전이일 때, 의존 팬을 같이 OFF 로 강제 (자동 보정).
# ══════════════════════════════════════════════════════════════════════════
def evaluate_interlock(farm_id, house_id, current: Optional[Dict], target: Dict,
                       now: Optional[datetime] = None,
                       valve_dwell_sec: Optional[Dict[str, Optional[float]]] = None
                       ) -> Tuple[Dict, List[Dict]]:
    now = now or datetime.now()
    current = current or {}
    corrected = dict(target)
    violations: List[Dict] = []

    # ───── ON 인터록: 흡입팬/배출팬 ─────
    for fan_flag, gate_valves in FAN_VALVE_GATE.items():
        fan_pin = _flag_to_pin(house_id, fan_flag)
        if not fan_pin or fan_pin not in corrected:
            continue
        prev_on = bool(current.get(fan_pin, False))
        new_on = bool(corrected.get(fan_pin, False))
        if not (new_on and not prev_on):
            continue   # OFF→ON 전이가 아니면 통과 (이미 ON 이거나 OFF 유지)

        # 밸브 dwell — target 도 함께 보아 "이번 쓰기로 함께 ON 되는 밸브" 도 0초로 인식
        max_dwell = -1.0
        ok_via = None
        for v in gate_valves:
            v_pin = _flag_to_pin(house_id, v)
            if not v_pin:
                continue
            target_v_on = bool(corrected.get(v_pin, current.get(v_pin, False)))
            if not target_v_on:
                continue
            if valve_dwell_sec is not None and v in valve_dwell_sec:
                d = valve_dwell_sec[v]
            else:
                d = get_valve_dwell_sec(farm_id, house_id, v, now=now)
                # 이번 쓰기로 새로 ON 되는 경우(직전엔 OFF) — dwell=0
                if d is None and bool(corrected.get(v_pin, False)) and not bool(current.get(v_pin, False)):
                    d = 0.0
            if d is None:
                continue
            if d > max_dwell:
                max_dwell = d
                ok_via = v

        if max_dwell >= VALVE_FAN_INTERLOCK_SEC:
            continue   # 통과
        # 위반 — 팬 ON 차단 (현재 상태로 되돌림)
        corrected[fan_pin] = prev_on
        remain = max(0, int(VALVE_FAN_INTERLOCK_SEC - max(0.0, max_dwell)))
        if max_dwell < 0:
            reason = f"{SEMANTIC_LABELS.get(fan_flag, fan_flag)} ON 차단 — 선행 밸브({'/'.join(SEMANTIC_LABELS.get(v, v) for v in gate_valves)}) 가 ON 이 아닙니다"
        else:
            reason = f"{SEMANTIC_LABELS.get(fan_flag, fan_flag)} ON 차단 — {SEMANTIC_LABELS.get(ok_via, ok_via)} ON 후 {VALVE_FAN_INTERLOCK_SEC}초 미경과 (잔여 {remain}초)"
        violations.append({
            'flag': fan_flag, 'action': 'on_blocked',
            'remaining_sec': remain, 'reason': reason,
        })

    # ───── OFF 인터록: 차단 + 사유 안내 ─────
    # 밸브가 닫힌 상태에서 팬이 가동되면 모터 손상 위험.
    # Rule 3: 흡입밸브 OFF — 흡입팬 OFF OR (순환밸브 ON AND 배출팬 ON)
    # Rule 4: 배출밸브 OFF — 배출팬 OFF OR (순환밸브 ON AND 흡입팬 ON)
    # Rule 5: 순환밸브 OFF — (흡입팬 OFF OR 흡입밸브 ON) AND (배출팬 OFF OR 배출밸브 ON)
    #         Rule 1/2 invariant 보존 — OFF 후 각 ON 팬에 자기 측 비순환 밸브 ON
    for valve_flag, dependent_fans in VALVE_DEPENDENT_FANS.items():
        v_pin = _flag_to_pin(house_id, valve_flag)
        if not v_pin or v_pin not in corrected:
            continue
        prev_on = bool(current.get(v_pin, False))
        new_on = bool(corrected.get(v_pin, False))
        if not (prev_on and not new_on):
            continue   # ON→OFF 전이가 아니면 통과

        blocking_fans = []
        for fan_flag in dependent_fans:
            fan_pin = _flag_to_pin(house_id, fan_flag)
            if not fan_pin:
                continue
            fan_target_on = bool(corrected.get(fan_pin, current.get(fan_pin, False)))
            if fan_target_on:
                blocking_fans.append(fan_flag)

        if not blocking_fans:
            continue   # 의존 팬 모두 OFF → 밸브 OFF 허용

        # Rule 3, 4 — 흡입/배출 밸브 OFF 예외 (순환경로 확보 + 반대측 팬 가동 필수)
        # 순환밸브가 열려있더라도 반대측 팬이 OFF 면 dead loop 이라 흡입팬 출구
        # 보장 안 됨 → 반대측 팬 ON 까지 함께 만족해야 통과.
        if valve_flag in ('air_intake_valve_flag', 'air_exhaust_valve_flag'):
            circ_pin = _flag_to_pin(house_id, 'air_circulation_valve_flag')
            circ_on = bool(circ_pin and corrected.get(circ_pin, current.get(circ_pin, False)))
            if valve_flag == 'air_intake_valve_flag':
                opposite_fan_flag = 'exhaust_fan_flag'
            else:
                opposite_fan_flag = 'intake_fan_flag'
            opp_pin = _flag_to_pin(house_id, opposite_fan_flag)
            opp_on = bool(opp_pin and corrected.get(opp_pin, current.get(opp_pin, False)))
            if circ_on and opp_on:
                continue   # 순환밸브 ON + 반대측 팬 ON → 순환경로 살아있음 → OFF 허용

        # 순환밸브 예외 — Rule 1/2 invariant 보존 AND 식:
        # 통과 = (흡입팬 OFF OR 흡입밸브 ON) AND (배출팬 OFF OR 배출밸브 ON)
        # 순환밸브 OFF 후 ON 인 팬마다 자기 측 비순환 밸브가 ON 이어야 ON 조건
        # 만족 — 한 쪽이라도 dead end 면 차단.
        unsafe_fans = list(blocking_fans)
        if valve_flag == 'air_circulation_valve_flag':
            iv_pin = _flag_to_pin(house_id, 'air_intake_valve_flag')
            if_pin = _flag_to_pin(house_id, 'intake_fan_flag')
            ev_pin = _flag_to_pin(house_id, 'air_exhaust_valve_flag')
            ef_pin = _flag_to_pin(house_id, 'exhaust_fan_flag')

            def _on(pin):
                return bool(pin and corrected.get(pin, current.get(pin, False)))

            intake_fan_on  = _on(if_pin)
            intake_v_on    = _on(iv_pin)
            exhaust_fan_on = _on(ef_pin)
            exhaust_v_on   = _on(ev_pin)

            intake_safe  = (not intake_fan_on)  or intake_v_on
            exhaust_safe = (not exhaust_fan_on) or exhaust_v_on
            if intake_safe and exhaust_safe:
                continue   # 양쪽 측 모두 안전 (각 ON 팬에 자기 측 밸브 보장)
            # 차단 — 자기 측 밸브 미열림 ON 팬을 안내 메시지에
            unsafe_fans = []
            if intake_fan_on and not intake_v_on:
                unsafe_fans.append('intake_fan_flag')
            if exhaust_fan_on and not exhaust_v_on:
                unsafe_fans.append('exhaust_fan_flag')

        # 차단 — 밸브를 ON 으로 되돌림
        corrected[v_pin] = True
        fan_labels = ', '.join(SEMANTIC_LABELS.get(f, f) for f in unsafe_fans)
        valve_label = SEMANTIC_LABELS.get(valve_flag, valve_flag)
        # 흡입/배출 밸브는 "순환밸브 ON + 반대측 팬 ON" 예외도 안내
        if valve_flag == 'air_intake_valve_flag':
            reason = (f"{valve_label} OFF 차단 — 흡입팬을 먼저 OFF 시키거나, "
                      f"순환밸브와 배출팬을 함께 ON 한 뒤 다시 시도하세요")
        elif valve_flag == 'air_exhaust_valve_flag':
            reason = (f"{valve_label} OFF 차단 — 배출팬을 먼저 OFF 시키거나, "
                      f"순환밸브와 흡입팬을 함께 ON 한 뒤 다시 시도하세요")
        else:
            reason = (f"{valve_label} OFF 차단 — {fan_labels} 을(를) OFF 시키거나, "
                      f"흡입측 또는 배출측 (밸브+팬) 풀가동 후 다시 시도하세요")
        violations.append({
            'flag': valve_flag,
            'action': 'off_blocked',
            'remaining_sec': 0,
            'blocking_fans': list(unsafe_fans),
            'reason': reason,
        })

    # ══════════════════════════════════════════════════════════════════════
    # ⛔ 절대 불변식 최종 강제 — 절대 제거 금지 (사용자 명시 지시) ⛔
    #   "흡입팬 ON 은 반드시 흡입밸브 ON 혹은 순환밸브 ON /
    #    배출팬 ON 은 반드시 배출밸브 ON 혹은 순환밸브 ON"
    #   위의 전이 게이트(OFF→ON / ON→OFF)는 '변경 순간' 만 검사하므로, 이미
    #   위반 상태로 존재하는 경우(외부 요인·부팅 직후·과거 잔존 등)는 걸러지지
    #   않는다. 본 블록은 최종 결과(corrected)를 무조건 검사해 "밸브가 모두
    #   OFF 인데 팬이 ON" 이면 팬을 강제 OFF — 어떤 경로로도 이 불변식을
    #   위반한 채 릴레이가 기록될 수 없게 하는 최후 안전망이다(모터 소손 방지).
    # ══════════════════════════════════════════════════════════════════════
    for fan_flag, gate_valves in FAN_VALVE_GATE.items():
        fan_pin = _flag_to_pin(house_id, fan_flag)
        if not fan_pin or not bool(corrected.get(fan_pin, False)):
            continue   # 팬 OFF 면 불변식 자동 충족
        any_valve_on = False
        for v in gate_valves:
            v_pin = _flag_to_pin(house_id, v)
            if v_pin and bool(corrected.get(v_pin, False)):
                any_valve_on = True
                break
        if not any_valve_on:
            corrected[fan_pin] = False
            fan_label = SEMANTIC_LABELS.get(fan_flag, fan_flag)
            valve_labels = '/'.join(SEMANTIC_LABELS.get(v, v) for v in gate_valves)
            violations.append({
                'flag': fan_flag,
                'action': 'invariant_forced_off',
                'remaining_sec': 0,
                'reason': (f"[절대불변식] {fan_label} 강제 OFF — 선행 밸브({valve_labels}) "
                           f"가 모두 OFF 상태 (모터 소손 방지, 상시 강제)"),
            })

    return corrected, violations


# ══════════════════════════════════════════════════════════════════════════
# UI 표시용 — 흡입팬/배출팬의 현재 ON 가능 여부와 잔여 초
# 반환: { 'intake_fan_flag': {can_on, remaining_sec, gate_via}, 'exhaust_fan_flag': {...} }
# ══════════════════════════════════════════════════════════════════════════
def get_interlock_status(farm_id, house_id, current: Optional[Dict] = None,
                         now: Optional[datetime] = None) -> Dict[str, Dict]:
    now = now or datetime.now()
    current = current or {}
    out: Dict[str, Dict] = {}
    for fan_flag, gate_valves in FAN_VALVE_GATE.items():
        max_dwell = -1.0
        gate_via = None
        for v in gate_valves:
            v_pin = _flag_to_pin(house_id, v)
            if not v_pin or not bool(current.get(v_pin, False)):
                continue
            d = get_valve_dwell_sec(farm_id, house_id, v, now=now)
            if d is None:
                continue
            if d > max_dwell:
                max_dwell = d
                gate_via = v
        can_on = max_dwell >= VALVE_FAN_INTERLOCK_SEC
        remain = 0 if can_on else max(0, int(VALVE_FAN_INTERLOCK_SEC - max(0.0, max_dwell)))
        if max_dwell < 0:
            remain = VALVE_FAN_INTERLOCK_SEC
        out[fan_flag] = {
            'can_on': can_on,
            'remaining_sec': remain,
            'gate_via': gate_via,
            'gate_threshold_sec': VALVE_FAN_INTERLOCK_SEC,
        }
    return out


# ══════════════════
# 테스트용 latch 초기화
# ══════════════════
def clear_state():
    with _valve_lock:
        _valve_on_since.clear()
