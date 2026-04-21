# ════════════════════════════════════════════════════════════════════
# 매핑 모듈 - 센서/릴레이 한글-영문 필드 매핑 및 house_id별 매핑 반환.
# --->
# get_relay_mapping       : house_id 별 릴레이 매핑 dict 반환 (STANDARD/E 분기)
# relay_def_by_sem        : 시멘틱 영문기능명 → RelayDef 양방향 조회
# relay_def_by_col        : DB 컬럼명 → RelayDef 양방향 조회
# standard_pin_map        : STANDARD 시멘틱 → 컬럼 dict 자동 생성
# e_pin_map               : E타입 시멘틱 → 컬럼 dict 자동 생성
# standard_semantic_keys  : STANDARD 시멘틱 영문기능명 set
# e_semantic_keys         : E타입 시멘틱 영문기능명 set
# _flags                  : sem 별 메타 태그 frozenset 자동 도출 (PROTECTED 등)
# _rd                     : RelayDef 생성 헬퍼 — desc/flags 를 sem 으로부터 자동 채움
# protected_semantic_keys : flags 에 'PROTECTED' 가 설정된 시멘틱 키 set
# all_semantic_keys       : STANDARD ∪ E 의 모든 시멘틱 영문기능명 set
# all_relay_defs          : STANDARD ∪ E 의 모든 RelayDef (sem 중복은 STANDARD 우선)
# semantic_labels         : sem → 한글 기능명 dict — STANDARD/E 머지
# device_aliases          : 한글기능명/별칭 → sem dict — STANDARD/E + _EXTRA_DEVICE_ALIASES 머지
# device_mapping_text     : LLM 시스템 프롬프트용 장치명 매핑 한 줄 요약 텍스트
# device_detail_text      : LLM 제어 판단용 장치 상세 설명 (sem·kor_func·kor_relay·desc 결합)
# circulation_modes_text  : 5종 순환 모드 표 텍스트 (CIRCULATION_MODES 자동 생성)
# circulation_mode_enum   : 순환 모드 enum 리스트 (LLM 도구 정의용)
# growth_stages_enum      : 생육 단계 enum 리스트 (LLM 도구 정의용)
# control_modes_enum      : 제어 모드 enum 리스트 (LLM 도구 정의용)
# --->
# 도메인 상수 (SSOT):
# GROWTH_STAGES           : 생육 단계 4종 — '발아기'/'생육기'/'수확기'/'휴지기'
# CONTROL_MODES           : 재배사 제어 모드 3종 — 'manual'/'algorithm'/'ai'
# ════════════════════════════════════════════════════════════════════
# [변경3 · 2026-04-19] 전 재배사의 릴레이 기능명을 웹 UI(RelayDashboard) 라벨 기준으로 통일.
#   STANDARD(1·3호): 수온히터/포그생성/배수밸브/흡입팬/배출팬/조명/관수/실내히터/
#                   순환밸브/배출밸브(11)/흡입밸브(14)/히터밸브(15)
#   E타입(2호):      수온히터/포그생성/관수/흡입팬/배출팬/
#                   순환밸브(10)/흡입밸브(11)/배출밸브(12)/배수밸브(13)
#   원복: .changeBak_3 백업 참조
# ════════════════════════════════════════════════════════════════════
# [변경4 · 2026-04-30] STANDARD 매핑(RELAY_FIELD_MAPPING) 5-tuple 단일 구조로 재편.
#   키:   relay_Nst_flag (DB 컬럼명)
#   값:   RelayDef(col, kor_relay, sem, kor_func, desc)
#         - col       : DB 컬럼명 (relay_Nst_flag) — 키와 동일
#         - kor_relay : 릴레이 한글명 ("릴레이1" 등 — UI 라벨)
#         - sem       : 시멘틱 영문기능명 (water_heater_flag 등 — 비즈니스 로직 키)
#         - kor_func  : 한글 기능명 ("수온히터" 등 — 표시·로그)
#         - desc      : 기능 상세 설명
#   효과: 시멘틱/컬럼명 별도 dict 항목 → 단일 항목, 양방향 조회 헬퍼로 통합.
#         RELAY_FIELD_MAPPING_E 는 2차 작업 시 동일 구조로 변환 예정.
# ════════════════════════════════════════════════════════════════════
from collections import namedtuple

# 센서 필드 매핑 - 키: 센서 필드명, 값: (한글명, 단위)
SENSOR_FIELD_MAPPING = {
    "indoor_temperature_value":  ("내부온도",    "℃"),
    "indoor_humidity_value":     ("내부습도",    "%"),
    "outdoor_temperature_value": ("외부온도",    "℃"),
    "outdoor_humidity_value":    ("외부습도",    "%"),
    "co2_concentration_value":   ("co2",         "ppm"),
    "water_temperature_value":   ("수온",        "℃"),
    "light_level_value":         ("광량",        "lux"),
    "water_level_value":         ("수위",        ""),
    "is_manual":                 ("수동설정여부", ""),
}

# 릴레이 정의 6-tuple — STANDARD/E 매핑 단일 구조
#   col       : DB 컬럼명 (relay_Nst_flag) — dict 키와 동일
#   kor_relay : 릴레이 한글명 ("릴레이1" 등 — UI 라벨)
#   sem       : 시멘틱 영문기능명 (water_heater_flag — 비즈니스 로직 키)
#   kor_func  : 한글 기능명 ("수온히터" — 표시·로그)
#   desc      : 기능 상세 설명 (LLM 제어 판단 시 참고)
#   flags     : 메타 태그 frozenset — 'PROTECTED' 등. 기본값 frozenset().
RelayDef = namedtuple(
    'RelayDef',
    ['col', 'kor_relay', 'sem', 'kor_func', 'desc', 'flags'],
    defaults=(frozenset(),),
)


# ════════════════════════════════════════════════════════════════════
# 시멘틱별 단일 진실 원천 — desc / 메타 태그
#   ※ desc 본문은 사용자 추가 검토 대상 (베이스라인). 본 dict 한 곳만 수정하면
#      STANDARD/E 매핑에서 sem 일치 항목이 모두 자동 반영됨.
# ════════════════════════════════════════════════════════════════════
_RELAY_DESCRIPTIONS = {
    'water_heater_flag': (
        '【가열 대상】 재배사 공기가 아니라 "재배사관리장치(외부 설비) 내부 지하수 탱크의 물". '
        '【동작】 ON: 탱크 물을 가열 → 탱크 수온(water_temperature_value) 상승. OFF: 가열 정지. '
        '【재배사에 미치는 직접 효과】 없음 — 탱크 물 자체는 재배사로 흐르지 않음. '
        '【재배사에 미치는 간접 효과】 가열된 탱크 물이 fog_occurs_flag(포그)로 분사될 때 '
        '재배사 내부 온도(indoor_temperature_value)와 습도(indoor_humidity_value)가 함께 상승. '
        '【의존성 (필수)】 drainage_motor_flag 와 상호배타. 배수밸브가 ON 이면 새 차가운 지하수가 계속 유입되어 가열 불가. '
        '수온을 올리려면 반드시 [drainage_motor_flag = OFF + water_heater_flag = ON] 조합. '
        '【가열 효율 룰 (사용자 정의·중요)】 '
        '포그가 ON 인 상태에서 가열하면 분사 손실로 가열이 매우 더디다. 신속한 수온 회복을 위해 다음 시퀀스를 따른다: '
        '(1) 수온이 적정범위 - 5℃ 이하 (예: 적정 35℃ 기준 30℃ 이하) → fog_occurs_flag = OFF 로 가열 집중. '
        '(2) 수온이 적정범위(water_temp_low) 도달 → fog_occurs_flag = ON 으로 재배사 가습·가온 전달. '
        '(3) 수온이 적정범위 안에서 유지되는 동안은 fog ON 유지. '
        '이 -5℃ 히스테리시스는 단순 임계 ON/OFF 진동(채터링)을 막고 가열 효율을 극대화하는 핵심 룰. '
        '【목표 수온대】 SENSOR_M_SETTING DB 테이블의 호기별 water_temp_low~water_temp_high 범위 (예: 40~55℃). '
        '임계값 자체는 하드코딩 금지 — DB 조회.'
    ),
    'fog_occurs_flag': (
        '【대상】 재배사관리장치(외부 설비) 지하수 탱크의 물을 미세 입자(미스트)로 만들어 재배사 내부 공기 중에 분사. '
        '【포그 vs 관수 차이】 포그=공기 중 안개(습도·온도 동시 영향). 관수=배지에 떨어지는 물줄기(배지 수분). '
        '【동작】 ON: 미스트 분사. OFF: 정지. '
        '【재배사에 미치는 효과】 '
        '· 습도(indoor_humidity_value): 항상 상승. '
        '· 온도(indoor_temperature_value): 분사되는 미스트 온도 = 탱크 수온이므로 — '
        '탱크가 따뜻하면 재배사 온도 상승, 차가우면 하강. '
        '【필수 안전 가드 (시스템 자동 강제)】 탱크 수온이 비상 하한(SENSOR_M_SETTING.water_temp_critical_low) 미만이면 '
        '시스템이 강제 OFF — 차가운 미스트로 재배사가 급랭되는 사고 방지. '
        '【가열 시퀀스 룰 (사용자 정의·중요)】 '
        '실내 저온이라 수온히터 가열 중일 때, 포그가 동시 ON 이면 미스트 분사로 탱크 수온이 잘 안 오른다. '
        '따라서 가열 페이즈는 다음 히스테리시스 시퀀스로 관리: '
        '(1) 수온 < 적정범위 - 5℃ → fog OFF (가열 집중). '
        '(2) 수온 ≥ 적정범위(water_temp_low) → fog ON (가습·가온 재배사 전달). '
        '(3) 적정범위 안에서는 ON 유지, 적정범위 - 5℃ 미만으로 떨어질 때만 다시 OFF. '
        '단순 임계 ON/OFF 진동(채터링) 방지 + 가열 효율 극대화. '
        '【용도 시나리오】 '
        '· 가열+가습: 수온히터로 탱크를 데운 뒤(배수밸브 OFF + 수온히터 ON) 위 시퀀스 따라 fog 결정. '
        '· 냉방+가습: 배수밸브 ON 으로 탱크가 자연 지하수 온도일 때 포그 ON (여름철).'
    ),
    'drainage_motor_flag': (
        '【대상】 재배사관리장치 지하수 탱크의 입출수 흐름 제어 밸브 (탱크 자체의 수위 유지·교체). '
        '【동작】 '
        'ON: 탱크 물이 계속 흘러나가고 새 자연 지하수가 유입 → 탱크 수온이 자연 지하수 본래 온도(연중 거의 일정·차가움)로 유지. '
        'OFF: 탱크 물 정체 → 수온히터로 가열 가능 또는 분사·증발로 천천히 변화. '
        '【재배사에 미치는 효과】 직접 효과 없음. 포그 가동 시 미스트 온도를 결정하는 사전 조건. '
        '【의존성】 water_heater_flag 와 상호배타 — 동시 ON 은 가열 효과 무효 (새 물이 계속 들어오므로). '
        '【용도 시나리오】 '
        '· 여름철 냉방: drainage_motor_flag = ON → 탱크가 차가워짐 → 포그 ON 시 차가운 미스트로 재배사 온도 하강. '
        '· 겨울철 가열: drainage_motor_flag = OFF → 수온히터 ON 으로 탱크 가열 → 포그 ON 시 따뜻한 미스트로 재배사 온도 상승. '
        '【LLM 제어 권한 (2026-05-01 변경)】 LLM 직접 결정 가능. 수온히터·배수밸브 상호배타 룰을 LLM 이 직접 적용한다. '
        '· 수온히터 ON ↔ 배수밸브 OFF (가온 위해 물 가둠). '
        '· 수온히터 OFF ↔ 배수밸브 ON (자연 흐름 유지·냉방).'
    ),
    'intake_fan_flag': (
        '【대상】 공기를 한 방향으로 밀어내는 송풍 팬. '
        '【중요 원리】 팬 자체로는 흐름 방향(외부→내부 / 내부→내부)을 결정하지 못함. '
        '동시에 어떤 댐퍼 밸브가 열려있느냐에 따라 동작이 결정됨. '
        '【동작 시나리오 — 함께 열린 밸브 조합 별】 '
        '· [air_intake_valve_flag=ON, air_circulation_valve_flag=OFF] → 외기 도입(외부 공기 → 재배사 내부). '
        '· [air_intake_valve_flag=OFF, air_circulation_valve_flag=ON] → 내부 순환(재배사 내부 공기를 내부에서만 회전). '
        '· [둘 다 ON] → 일부는 외기 도입, 일부는 내부 순환 (혼합 환기). '
        '【인터록 (interlock.py 가 자동 차단)】 '
        '· 흡입팬 ON 명령은 air_intake_valve_flag 또는 air_circulation_valve_flag 가 '
        '최소 10초(VALVE_FAN_INTERLOCK_SEC) 이상 미리 ON 상태였을 때만 허용. '
        '· 모든 밸브 OFF 상태에서 흡입팬 ON 명령은 시스템이 자동 거부 (밸브 없이 팬 가동 = 댐퍼 손상·소음·무흐름). '
        '· 흡입팬이 ON 인 동안에는 짝 밸브의 OFF 도 차단 (팬 먼저 OFF 후 밸브 OFF).'
    ),
    'exhaust_fan_flag': (
        '【대상】 공기를 한 방향으로 밀어내는 배기 팬 (흡입팬과 대칭 구조). '
        '【중요 원리】 팬 자체로는 흐름 방향을 결정하지 못함 — 동시에 열린 댐퍼 밸브가 결정. '
        '【동작 시나리오 — 함께 열린 밸브 조합 별】 '
        '· [air_exhaust_valve_flag=ON, air_circulation_valve_flag=OFF] → 내부 배출(재배사 내부 공기 → 외부). '
        '· [air_exhaust_valve_flag=OFF, air_circulation_valve_flag=ON] → 내부 순환(재배사 내부 공기를 내부에서만 회전). '
        '· [둘 다 ON] → 일부는 외부 배출, 일부는 내부 순환. '
        '【인터록 (interlock.py 가 자동 차단)】 '
        '· 배출팬 ON 명령은 air_exhaust_valve_flag 또는 air_circulation_valve_flag 가 '
        '최소 10초(VALVE_FAN_INTERLOCK_SEC) 이상 미리 ON 상태였을 때만 허용. '
        '· 모든 밸브 OFF 상태의 배출팬 ON 명령은 시스템 자동 거부. '
        '· 배출팬 ON 중에는 짝 밸브의 OFF 차단.'
    ),
    'lighting_flag': (
        '【대상】 재배사 내부 LED 조명. '
        '【동작】 ON: 점등, OFF: 소등. '
        '【효과】 광량(light_level_value, 단위 lux) 상승. '
        '【LLM 제어 권한】 PROTECTED — light_on_time / light_off_time 시간 스케줄에 따라 자동 점·소등됨(schedule_control.py). '
        'LLM 자율 변경 금지. 사용자가 명시 ON/OFF 명령한 경우에만 즉시 실행.'
    ),
    'irrigation_flag': (
        '【대상】 재배사 내부 천장의 스프링쿨러로 버섯 배지(재배 매질)에 물줄기를 직접 분사. '
        '【포그 vs 관수 차이】 관수=배지에 떨어지는 물줄기(배지 수분 공급). 포그=공기 중 미세 입자(공기 습도). '
        '【효과】 '
        '· 주 효과: 배지 수분 공급. '
        '· 부수 효과: 일시적으로 재배사 습도/온도 변화. '
        '【LLM 제어 권한】 PROTECTED — water_on_time + interval_min 듀티 사이클 스케줄로 자동 제어(schedule_control.py). '
        'LLM 자율 변경 금지. 사용자 명시 명령 시만 실행.'
    ),
    'air_circulation_valve_flag': (
        '【대상】 재배사 내부 공기 순환 경로의 댐퍼. "내부공기를 내부에서만 도는 경로" 의 개폐. '
        '【중요 원리】 단독 ON 으로는 공기 흐름 발생 안 함 (차단되진 않음 — 단지 흐름 없음). '
        '반드시 흡입팬 또는 배출팬과 함께 가동되어야 효과. '
        '【인터록상 특수 역할】 순환밸브가 ON 상태이면 흡입밸브·배출밸브가 OFF 여도 '
        '흡입팬·배출팬의 ON 게이트로 작동(둘 중 하나만 있으면 팬 ON 허용). '
        '【5장치(흡입팬·배출팬·흡입밸브·배출밸브·순환밸브) 유효 환기 5모드】 — circulation_modes_text() 자동 생성 표 참조.'
    ),
    'air_exhaust_valve_flag': (
        '【대상】 재배사 내부 공기를 외부로 내보내는 통로의 댐퍼. '
        '【중요 원리】 단독 ON 으로는 공기 흐름 없음 — 배출팬(exhaust_fan_flag) 가동과 짝지어야 흐름 발생. '
        '【동작】 [배출팬=ON + 배출밸브=ON] 조합 시 [재배사 내부 → 외부] 배기 흐름 형성. '
        '【인터록 (밸브 먼저 → 팬 나중 순서)】 '
        '· 배출팬을 켜기 위한 사전 조건: 배출밸브를 먼저 ON 한 뒤 '
        '10초(VALVE_FAN_INTERLOCK_SEC) 이상 dwell 후에야 배출팬 ON 가능. '
        '· 배출팬 ON 상태인 동안에는 배출밸브 OFF 명령이 차단됨 (반드시 팬 먼저 OFF → 밸브 OFF).'
    ),
    'air_intake_valve_flag': (
        '【대상】 재배사 외부 공기를 내부로 들이는 통로의 댐퍼. '
        '【중요 원리】 단독 ON 으로는 공기 흐름 없음 — 흡입팬(intake_fan_flag) 가동과 짝지어야 흐름 발생. '
        '【동작】 [흡입팬=ON + 흡입밸브=ON] 조합 시 [외부 → 재배사 내부] 흡기 흐름 형성. '
        '【인터록 (밸브 먼저 → 팬 나중 순서)】 '
        '· 흡입팬을 켜기 위한 사전 조건: 흡입밸브를 먼저 ON 한 뒤 '
        '10초(VALVE_FAN_INTERLOCK_SEC) 이상 dwell 후에야 흡입팬 ON 가능. '
        '· 흡입팬 ON 상태인 동안에는 흡입밸브 OFF 명령이 차단됨.'
    ),
    # [2026-04-30] radiator_flag 제거 — E타입 2호의 relay_3 (라디에이터)·relay_4 (칠러Ⅱ)
    # 모두 미사용으로 결정 (1·3호의 relay_9/15 와 동일한 disable 패턴).
    # 매핑에서 제외되어 핀맵·라벨·별칭·LLM 프롬프트에서 자동 누락되며, 백엔드의
    # force_off_unmapped_relays() 가 어떤 모드에서도 ON 을 차단함.
}

# PROTECTED — LLM 자율 변경 금지 (별도 스케줄·환경 로직이 관리)
_PROTECTED_SEMS = frozenset({'lighting_flag', 'irrigation_flag', 'drainage_motor_flag'})


# ────────────────────────────────────────────────────────────────────
# [변경6 · 2026-04-30] sem 별 메타 태그 frozenset 자동 도출 헬퍼.
# _PROTECTED_SEMS 에 포함된 sem 은 'PROTECTED' 태그가 자동 부여됨.
# ────────────────────────────────────────────────────────────────────
def _flags(sem):
    tags = set()
    if sem in _PROTECTED_SEMS:
        tags.add('PROTECTED')
    return frozenset(tags)


# ────────────────────────────────────────────────────────────────────
# [변경6 · 2026-04-30] RelayDef 생성 헬퍼 — desc/flags 자동 도출.
# 매핑 정의에서 col/kor_relay/sem/kor_func 4개만 명시하면 desc/flags 가 자동
# 채워짐 → 신규 릴레이 추가 시 _RELAY_DESCRIPTIONS / _PROTECTED_SEMS 만 갱신.
# ────────────────────────────────────────────────────────────────────
def _rd(col, kor_relay, sem, kor_func):
    return RelayDef(col, kor_relay, sem, kor_func, _RELAY_DESCRIPTIONS.get(sem, ''), _flags(sem))


# ════════════════════════════════════════════════════════════════════
# STANDARD (1·3호) — desc/flags 는 sem 기반 자동 도출
# ════════════════════════════════════════════════════════════════════
RELAY_FIELD_MAPPING = {
    'relay_1st_flag':  _rd('relay_1st_flag',  '릴레이1',  'water_heater_flag',          '수온히터'),
    'relay_2st_flag':  _rd('relay_2st_flag',  '릴레이2',  'fog_occurs_flag',            '포그생성'),
    'relay_3st_flag':  _rd('relay_3st_flag',  '릴레이3',  'drainage_motor_flag',        '배수밸브'),
    'relay_5st_flag':  _rd('relay_5st_flag',  '릴레이5',  'intake_fan_flag',            '흡입팬'),
    'relay_6st_flag':  _rd('relay_6st_flag',  '릴레이6',  'exhaust_fan_flag',           '배출팬'),
    'relay_7st_flag':  _rd('relay_7st_flag',  '릴레이7',  'lighting_flag',              '조명'),
    'relay_8st_flag':  _rd('relay_8st_flag',  '릴레이8',  'irrigation_flag',            '관수'),
    'relay_10st_flag': _rd('relay_10st_flag', '릴레이10', 'air_circulation_valve_flag', '순환밸브'),
    'relay_11st_flag': _rd('relay_11st_flag', '릴레이11', 'air_exhaust_valve_flag',     '배출밸브'),
    'relay_14st_flag': _rd('relay_14st_flag', '릴레이14', 'air_intake_valve_flag',      '흡입밸브'),
}

# ════════════════════════════════════════════════════════════════════
# E타입 (2호 전용) — STANDARD 와 동일한 6-tuple 구조, sem 매칭 시 desc 자동 공유
# ════════════════════════════════════════════════════════════════════
RELAY_FIELD_MAPPING_E = {
    'relay_1st_flag':  _rd('relay_1st_flag',  '릴레이1',  'water_heater_flag',          '수온히터'),
    'relay_2st_flag':  _rd('relay_2st_flag',  '릴레이2',  'fog_occurs_flag',            '포그생성'),
    'relay_5st_flag':  _rd('relay_5st_flag',  '릴레이5',  'lighting_flag',              '조명'),
    'relay_6st_flag':  _rd('relay_6st_flag',  '릴레이6',  'irrigation_flag',            '관수'),
    'relay_7st_flag':  _rd('relay_7st_flag',  '릴레이7',  'intake_fan_flag',            '흡입팬'),
    'relay_8st_flag':  _rd('relay_8st_flag',  '릴레이8',  'exhaust_fan_flag',           '배출팬'),
    'relay_10st_flag': _rd('relay_10st_flag', '릴레이10', 'air_circulation_valve_flag', '순환밸브'),
    'relay_11st_flag': _rd('relay_11st_flag', '릴레이11', 'air_intake_valve_flag',      '흡입밸브'),
    'relay_12st_flag': _rd('relay_12st_flag', '릴레이12', 'air_exhaust_valve_flag',     '배출밸브'),
    'relay_13st_flag': _rd('relay_13st_flag', '릴레이13', 'drainage_motor_flag',        '배수밸브'),
}


# ════════════════════════════════════════════════════════════════════
# 시스템 어휘·환기 모드 상수 — LLM 시스템 프롬프트에 1회만 노출
# ════════════════════════════════════════════════════════════════════
SYSTEM_GLOSSARY_TEXT = """\
시스템 어휘 정의 (장치 desc 해석에 필수):
- 재배사: 버섯이 자라는 실내 공간 — 모든 제어 대상.
- 재배사관리장치: 재배사 외부에 설치된 별도 설비. 지하수 탱크와 펌프·히터를 포함하며 포그·관수 분사용 물 공급원.
- 지하수 탱크: 재배사관리장치 내 물 저장조. 자연 지하수가 유입되며 수온히터로 가열 가능.
- 댐퍼: 공기 통로의 개폐 밸브 (열림=ON, 닫힘=OFF) — 그 자체로는 흐름을 만들지 않고 통로만 열고 닫음.
- 인터록: 안전 잠금 — 특정 순서·시간 조건을 어긴 ON/OFF 명령을 시스템이 자동 거부 (interlock.py).
- VALVE_FAN_INTERLOCK_SEC: 밸브 ON 후 팬 ON 까지의 최소 대기 시간(기본 10초).
- 듀티 사이클: 정해진 시간 간격으로 반복 ON/OFF 하는 스케줄 (관수의 interval_min 등).
- PROTECTED: 별도 자동 제어 로직이 관리하는 장치 태그 — LLM 자율 변경 금지. 사용자 명시 명령 시만 실행.
- SENSOR_M_SETTING: 호기별 센서 임계값(적정·비상 상하한) DB 테이블. 모든 임계값은 본 테이블 동적 조회 (코드 하드코딩 금지)."""

# ────────────────────────────────────────────────────────────────────
# [변경7 · 2026-04-30] 5종 순환 모드 표 텍스트 자동 생성.
# control_common.CIRCULATION_MODES (실제 시스템 사용 모드 정의) 를 SSOT 로 사용.
# CIRCULATION_MODES 의 mode 추가/변경/effect 수정 시 본 헬퍼 호출 결과가 자동 갱신됨.
# 순환 의존성 회피 위해 lazy import 사용.
# ────────────────────────────────────────────────────────────────────
# ════════════════════════════════════════════════════════════════════
# [변경7 · 2026-04-30] 도메인 enum SSOT — LLM 도구·프롬프트 enum 자동 생성용.
# prompts.py / tools_definition.py 에 흩어져 있던 enum 하드코딩을 본 상수 +
# 헬퍼로 통합. 신규 단계/모드 추가 시 본 파일만 수정 → 전 코드 자동 반영.
# ════════════════════════════════════════════════════════════════════
GROWTH_STAGES = ('발아기', '생육기', '수확기', '휴지기')
CONTROL_MODES = ('manual', 'algorithm', 'ai')


# ────────────────────────────────────────────────────────────────────
# 순환 모드 enum 리스트 (LLM 도구 set_circulation_mode 의 mode 검증용).
# control_common.CIRCULATION_MODES.keys() 를 SSOT 로 사용 — 새 모드 추가 시
# 자동 반영. lazy import 로 순환 의존 회피.
# ────────────────────────────────────────────────────────────────────
def circulation_mode_enum():
    from agri_ai_core.src.control.control_common import CIRCULATION_MODES
    return list(CIRCULATION_MODES.keys())


# ────────────────────────────────────────────────────────────────────
# 생육 단계 enum 리스트 (LLM 도구 set_growth_stage 의 stage 검증용).
# ────────────────────────────────────────────────────────────────────
def growth_stages_enum():
    return list(GROWTH_STAGES)


# ────────────────────────────────────────────────────────────────────
# 제어 모드 enum 리스트 (LLM 도구 set_house_control_mode 의 mode 검증용).
# ────────────────────────────────────────────────────────────────────
def control_modes_enum():
    return list(CONTROL_MODES)


def circulation_modes_text():
    from agri_ai_core.src.control.control_common import CIRCULATION_MODES

    def _onoff(v):
        return 'ON ' if v else 'OFF'

    lines = [
        '순환 모드 (밸브 → 15초 후 → 팬, control_common.CIRCULATION_MODES 자동 생성):',
    ]
    for mode, cfg in CIRCULATION_MODES.items():
        damp = cfg.get('dampers', {})
        fans = cfg.get('fans', {})
        effect = cfg.get('effect', '')
        line = (
            f"- {mode}: "
            f"순환밸브 {_onoff(damp.get('air_circulation_valve_flag'))}, "
            f"흡입밸브 {_onoff(damp.get('air_intake_valve_flag'))}, "
            f"배출밸브 {_onoff(damp.get('air_exhaust_valve_flag'))} → "
            f"흡입팬 {_onoff(fans.get('intake_fan_flag'))}, "
            f"배출팬 {_onoff(fans.get('exhaust_fan_flag'))}"
        )
        if effect:
            line += f" ({effect})"
        lines.append(line)
    lines.append('※ 팬 ON 시 해당 밸브가 최소 VALVE_FAN_INTERLOCK_SEC(기본 10초) 선행 ON 필수.')
    return '\n'.join(lines)


# ────────────────────────────────────────────────────────────────────
# [변경4·5 · 2026-04-30] house_id 별 릴레이 매핑 dict 반환 — 2호는 E타입,
# 그 외는 STANDARD. 모든 매핑 헬퍼의 진입점 역할.
# [버그수정 · 2026-05-01] house_id가 string('2') / int(2) 양쪽으로 들어오는데
#   기존 'house_id == 2' 는 string 비교 시 항상 False → 2호에도 STANDARD 적용되어
#   라벨이 뒤섞이는 환각의 진짜 근본 원인이었음. int 정규화 후 비교로 수정.
# ────────────────────────────────────────────────────────────────────
def get_relay_mapping(house_id=None):
    try:
        if house_id is not None and int(house_id) == 2:
            return RELAY_FIELD_MAPPING_E
    except (ValueError, TypeError):
        pass
    return RELAY_FIELD_MAPPING


# ════════════════════════════════════════════════════════════════════
# 매핑 조회 헬퍼 (RELAY_FIELD_MAPPING / RELAY_FIELD_MAPPING_E 공용)
# ════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# [변경5 · 2026-04-30] 시멘틱 영문기능명 → RelayDef 양방향 조회.
# house_id 미지정 시 STANDARD 우선, E 폴백. 없으면 None.
# ────────────────────────────────────────────────────────────────────
def relay_def_by_sem(sem, house_id=None):
    for d in (get_relay_mapping(house_id),) if house_id is not None else (RELAY_FIELD_MAPPING, RELAY_FIELD_MAPPING_E):
        for r in d.values():
            if r.sem == sem:
                return r
    return None


# ────────────────────────────────────────────────────────────────────
# [변경5 · 2026-04-30] DB 컬럼명(relay_Nst_flag) → RelayDef 양방향 조회.
# house_id 미지정 시 STANDARD 우선, E 폴백. 없으면 None.
# ────────────────────────────────────────────────────────────────────
def relay_def_by_col(col, house_id=None):
    if house_id is not None:
        return get_relay_mapping(house_id).get(col)
    return RELAY_FIELD_MAPPING.get(col) or RELAY_FIELD_MAPPING_E.get(col)


# ────────────────────────────────────────────────────────────────────
# [변경4 · 2026-04-30] STANDARD 시멘틱 → 컬럼 dict 자동 생성.
# control_common.RELAY_PIN_MAP_STANDARD 가 본 헬퍼 결과로 채워짐.
# ────────────────────────────────────────────────────────────────────
def standard_pin_map():
    return {r.sem: r.col for r in RELAY_FIELD_MAPPING.values()}


# ────────────────────────────────────────────────────────────────────
# [변경5 · 2026-04-30] E타입 시멘틱 → 컬럼 dict 자동 생성.
# control_common.RELAY_PIN_MAP_E 가 본 헬퍼 결과로 채워짐.
# ────────────────────────────────────────────────────────────────────
def e_pin_map():
    return {r.sem: r.col for r in RELAY_FIELD_MAPPING_E.values()}


# ────────────────────────────────────────────────────────────────────
# [변경4 · 2026-04-30] STANDARD 시멘틱 영문기능명 set — conversion.py 등에서
# DB row 키 매칭용으로 사용.
# ────────────────────────────────────────────────────────────────────
def standard_semantic_keys():
    return {r.sem for r in RELAY_FIELD_MAPPING.values()}


# ────────────────────────────────────────────────────────────────────
# [변경5 · 2026-04-30] E타입 시멘틱 영문기능명 set.
# ────────────────────────────────────────────────────────────────────
def e_semantic_keys():
    return {r.sem for r in RELAY_FIELD_MAPPING_E.values()}


# ────────────────────────────────────────────────────────────────────
# [변경5 · 2026-04-30] STANDARD + E 머지 헬퍼 — control_common 의 SEMANTIC_LABELS /
# DEVICE_ALIASES, LLM 프롬프트의 장치명 매핑 텍스트가 본 헬퍼로 자동 생성됨.
# ────────────────────────────────────────────────────────────────────
# 매핑 테이블에 없는 추가 한글 별칭 / 영문 별칭 (LLM 입력 다양성 흡수용).
# kor_func 와 중복되어도 무해 — DEVICE_ALIASES 머지 시 setdefault 로 보존.
_EXTRA_DEVICE_ALIASES = {
    '칠러':       'water_heater_flag',
    '칠러1':      'water_heater_flag',
    '포그':       'fog_occurs_flag',
    '배수':       'drainage_motor_flag',
    '흡입':       'intake_fan_flag',
    '배출':       'exhaust_fan_flag',
    'light':      'lighting_flag',
    'lighting':   'lighting_flag',
    'irrigation': 'irrigation_flag',
}


# ────────────────────────────────────────────────────────────────────
# [변경5 · 2026-04-30] sem → 한글 기능명 dict — STANDARD/E 머지.
# control_common.SEMANTIC_LABELS 가 본 헬퍼 결과로 채워짐. sem 중복은 STANDARD 우선.
# ────────────────────────────────────────────────────────────────────
def semantic_labels():
    labels = {}
    for d in (RELAY_FIELD_MAPPING, RELAY_FIELD_MAPPING_E):
        for r in d.values():
            labels.setdefault(r.sem, r.kor_func)
    return labels


# ────────────────────────────────────────────────────────────────────
# [변경5 · 2026-04-30] 한글기능명/별칭 → sem dict — STANDARD/E 매핑의 kor_func +
# _EXTRA_DEVICE_ALIASES 머지. control_common.DEVICE_ALIASES 가 본 헬퍼 결과로 채워짐.
# 사용자/LLM 자연어 입력의 다양한 표기를 시멘틱 키로 정규화하는데 사용.
# ────────────────────────────────────────────────────────────────────
def device_aliases():
    aliases = {}
    for d in (RELAY_FIELD_MAPPING, RELAY_FIELD_MAPPING_E):
        for r in d.values():
            aliases.setdefault(r.kor_func, r.sem)
    for alias, sem in _EXTRA_DEVICE_ALIASES.items():
        aliases.setdefault(alias, sem)
    return aliases


# ────────────────────────────────────────────────────────────────────
# [변경6 · 2026-04-30] flags 에 'PROTECTED' 가 설정된 시멘틱 키 set 자동 도출.
# STANDARD/E 매핑 둘 다 순회 union — 신규 PROTECTED 릴레이 추가 시 자동 반영.
# ai_control.PROTECTED_DEVICES 가 본 헬퍼 결과로 채워짐.
# ────────────────────────────────────────────────────────────────────
def protected_semantic_keys():
    out = set()
    for d in (RELAY_FIELD_MAPPING, RELAY_FIELD_MAPPING_E):
        for r in d.values():
            if 'PROTECTED' in r.flags:
                out.add(r.sem)
    return out


# ────────────────────────────────────────────────────────────────────
# [변경6 · 2026-04-30] STANDARD ∪ E 의 모든 시멘틱 영문기능명 set.
# ────────────────────────────────────────────────────────────────────
def all_semantic_keys():
    return standard_semantic_keys() | e_semantic_keys()


# ────────────────────────────────────────────────────────────────────
# [변경6 · 2026-04-30] STANDARD ∪ E 의 모든 RelayDef — sem 중복은 STANDARD 우선.
# LLM 프롬프트·문서 자동 생성 등 sem 단위 일괄 처리 시 사용.
# ────────────────────────────────────────────────────────────────────
def all_relay_defs():
    seen = {}
    for d in (RELAY_FIELD_MAPPING, RELAY_FIELD_MAPPING_E):
        for r in d.values():
            seen.setdefault(r.sem, r)
    return list(seen.values())


# ────────────────────────────────────────────────────────────────────
# [변경6 · 2026-04-30] LLM 제어 판단용 장치 상세 설명 텍스트 자동 생성.
# 형식 (한 줄=한 장치): - <sem> — <kor_func> (<kor_relay>): <desc>
# STANDARD 우선 노출, E타입 전용 sem 만 별도 라인.
# [변경7 · 2026-04-30] desc 를 _RELAY_DESCRIPTIONS dict 에서 직접 조회 (호출 시점
# 평가) — RelayDef.desc 캐시를 우회하여 _RELAY_DESCRIPTIONS 변경 즉시 반영.
# 진정한 SSOT 보장: mappers.py 의 _RELAY_DESCRIPTIONS 수정만으로 LLM 프롬프트가
# 자동 갱신 (서비스 재시작 없이도 함수 호출 시점에 새 desc 반영).
# ────────────────────────────────────────────────────────────────────
def device_detail_text():
    seen = set()
    lines = []
    for r in RELAY_FIELD_MAPPING.values():
        seen.add(r.sem)
        desc = _RELAY_DESCRIPTIONS.get(r.sem, r.desc)
        lines.append(f"- {r.sem} — {r.kor_func} ({r.kor_relay}): {desc}")
    for r in RELAY_FIELD_MAPPING_E.values():
        if r.sem in seen:
            continue
        seen.add(r.sem)
        desc = _RELAY_DESCRIPTIONS.get(r.sem, r.desc)
        lines.append(f"- {r.sem} — {r.kor_func} (E타입 {r.kor_relay}): {desc}")
    return '\n'.join(lines)


# ────────────────────────────────────────────────────────────────────
# [변경5 · 2026-04-30] LLM 시스템 프롬프트용 장치명 매핑 한 줄 요약 텍스트.
# 형식: '한글기능명/별칭1/별칭2=시멘틱, ...' — sem 기준으로 한글 별칭 모음.
# 영문 별칭(light/lighting/irrigation) 은 sem 자체로 LLM 이 직접 사용하므로 제외.
# ────────────────────────────────────────────────────────────────────
def device_mapping_text():
    sem_kors = {}      # sem → [kor 목록] (입력 순서 보존)
    sem_order = []     # sem 첫 등장 순서
    for d in (RELAY_FIELD_MAPPING, RELAY_FIELD_MAPPING_E):
        for r in d.values():
            if r.sem not in sem_kors:
                sem_kors[r.sem] = [r.kor_func]
                sem_order.append(r.sem)
            elif r.kor_func not in sem_kors[r.sem]:
                sem_kors[r.sem].append(r.kor_func)
    for alias, sem in _EXTRA_DEVICE_ALIASES.items():
        # 한글 별칭만 포함 (한 글자라도 한글 포함 시)
        if not any('가' <= ch <= '힣' for ch in alias):
            continue
        if sem in sem_kors and alias not in sem_kors[sem]:
            sem_kors[sem].append(alias)
    return ', '.join(f"{'/'.join(sem_kors[s])}={s}" for s in sem_order)
