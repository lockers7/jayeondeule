# ══════════════════════════════════════════════════════════════════════════════
# 제어 프롬프트 A/B 행동검증 하네스
# 같은 센서 시나리오에 현재/후보 프롬프트를 gemma3 로 태워 결정(action/devices/
# circulation)을 대조 → 프롬프트 단순화의 무퇴행을 수치로 확인.
# 사용: ./venv/bin/python tests/control/prompt_ab/harness.py <label>
#   label 결과를 tests/control/prompt_ab/decisions_<label>.json 에 저장.
#   golden 과 비교는 compare.py.
# ══════════════════════════════════════════════════════════════════════════════
import sys, json, os
sys.path.insert(0, "/workspace/jayeondeule")
from dotenv import load_dotenv; load_dotenv("/workspace/jayeondeule/.env")

from agri_ai_core.src.control.ai_control import (
    _build_system_prompt, _build_user_prompt, _call_llm, _parse_relay_response)
from agri_ai_core.src.control.ai_thresholds import get_thresholds
from agri_ai_core.src.postgresql.reader import read_optimal_condition, read_latest_relay_info

FARM, HOUSE = 1, 1
TS = get_thresholds(FARM, HOUSE)
OPT = read_optimal_condition(FARM, HOUSE) or {}
RELAY = {}   # fresh(전부 OFF) — LLM이 시나리오별로 결정하게 (현재상태 confound 제거)

# 대표 시나리오 (임계 기준: 온도 24~28/비상20~33, 습도72~94, CO2~2000/비상3000, 수온16~40/비상45)
def sensors(it, ih, co2, ot, oh, wt):
    return {'indoor_temperature': it, 'indoor_humidity': ih, 'co2': co2,
            'outdoor_temperature': ot, 'outdoor_humidity': oh, 'water_temperature': wt}
SCENARIOS = {
    "정상":     sensors(25, 80, 900, 22, 70, 20),
    "저온비상": sensors(18, 82, 700, 10, 65, 15),
    "고온_외기정상": sensors(34, 70, 800, 26, 60, 22),
    "고온_외기부적합": sensors(34, 70, 800, 33, 55, 22),
    "고CO2":    sensors(26, 80, 3200, 26, 60, 21),
    "고습":     sensors(26, 96, 900, 24, 80, 20),
}

def run(growth="생육기"):
    sp = _build_system_prompt(growth, TS)
    out = {"_meta": {"system_prompt_len": len(sp), "growth": growth}}
    for name, sd in SCENARIOS.items():
        up = _build_user_prompt(sd, RELAY, growth, OPT, "", HOUSE,
                                history_block="", rag_block="", extra_blocks=[], farm_id=None)  # 관리자지시 격리
        try:
            raw = _call_llm(sp, up)
            p = _parse_relay_response(raw) if raw else None
        except Exception as e:
            p = {"error": str(e)}
        dec = {}
        if isinstance(p, dict):
            dec = {"action": p.get("action"),
                   "devices": p.get("devices"),
                   "circulation": p.get("circulation"),
                   "reason": (p.get("reason") or "")[:80]}
        out[name] = {"user_prompt_len": len(up), "decision": dec}
        print(f"  [{name:14}] {dec.get('action')} · {dec.get('circulation')} · dev={dec.get('devices')}")
    return out

if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    print(f"═══ A/B 실행: {label} (system_prompt {len(_build_system_prompt('생육기', TS))}자) ═══")
    res = run("생육기")
    path = f"/workspace/jayeondeule/tests/control/prompt_ab/decisions_{label}.json"
    json.dump(res, open(path, "w"), ensure_ascii=False, indent=1, default=str)
    # 백업 디렉토리에도 golden 보존
    if label == "baseline":
        json.dump(res, open("/workspace/jayeondeule/backup/simplify_20260719/ab_baseline.json","w"),
                  ensure_ascii=False, indent=1, default=str)
    print(f"→ 저장: {path}")
