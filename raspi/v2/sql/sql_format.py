from dataclasses import dataclass

#==============================================================================================
# 데이터 기록 용 포멧 클래스 정의
#==============================================================================================
#--------------------------------
# 센서값 저장용 포멧
#--------------------------------
@dataclass
class AutoRecdFormat:
    farm_id        : str   = ''
    hous_id        : str   = ''
    recd_dttm      : str   = ''
    indr_tprt_valu : float = 0.0
    indr_hmdt_valu : float = 0.0
    oudr_tprt_valu : float = 0.0
    oudr_hmdt_valu : float = 0.0
    co2_valu       : float = 0.0
    watr_tprt_valu : float = 0.0
    ligt_level_valu: float = 0.0
    watr_level_valu: float = 0.0

#--------------------------------
# 릴레이 상태 값 저장용 포멧
#--------------------------------
class BaseRelayFlagFormat:
    def __init__(self, *relay_status):
        for i, status in enumerate(relay_status):
            setattr(self, f'relay_{i+1}st_flag', status)

#--------------------------------
# 온도, 습도, CO2 운용 기본 설정값 
#--------------------------------
class BaseSetFormat:
    def __init__(self, tprt_min, tprt_max, hmdt_min, hmdt_max, co2_min, co2_max, watr_tprt_min, watr_tprt_max, heat_tprt_min, heat_tprt_max):
        self.tprt_min      = tprt_min     
        self.tprt_max	   = tprt_max     
        self.hmdt_min	   = hmdt_min     
        self.hmdt_max	   = hmdt_max     
        self.co2_min	   = co2_min      
        self.co2_max	   = co2_max      
        self.watr_tprt_min = watr_tprt_min
        self.watr_tprt_max = watr_tprt_max
        self.heat_tprt_min = heat_tprt_min
        self.heat_tprt_max = heat_tprt_max

#--------------------------------
# 조명 On, Off 설정 기본 값 
#--------------------------------
class LghtSetFormat:
    def __init__(self, strt_time, fnsh_time):
        self.strt_time = strt_time
        self.fnsh_time = fnsh_time

#--------------------------------
# 관수 On, Off 설정 기본 값 
#--------------------------------
class WatrSetFormat:
    def __init__(self, strt_time, fnsh_time):
        self.strt_time = strt_time
        self.fnsh_time = fnsh_time

