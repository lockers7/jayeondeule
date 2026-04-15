from datetime import datetime
from dataclasses import dataclass

# 자동 기록 데이터 형식 클래스
@dataclass
class AutoRecdFormat:
    farm_id:           str   = ''
    recd_date:         str   = ''
    htemp_val:         float = 0.0
    humi_val:          float = 0.0
    co2_val:           float = 0.0
    wtemp_val:         float = 0.0
    outdoor_temp_val:  float = 0.0
    outdoor_humi_val:  float = 0.0

# 릴레이 상태 형식 클래스
class BaseRelayFlagFormat:
    def __init__(self, *relay_status):
        for i in range(15):
            setattr(self, f'relay_{i+1}_st', False)
        
        for i, status in enumerate(relay_status):
            setattr(self, f'relay_{i+1}_st', status)

# 온도, 습도, CO2 기준 설정 클래스
class BaseSetFormat:
    def __init__(self, htemp_min, htemp_max, humi_min, humi_max, co2_min, co2_max, wtemp_min, wtemp_max):
        self.htemp_min = htemp_min
        self.htemp_max = htemp_max
        self.humi_min  = humi_min
        self.humi_max  = humi_max
        self.co2_min   = co2_min
        self.co2_max   = co2_max
        self.wtemp_min = wtemp_min
        self.wtemp_max = wtemp_max

# 외부 온도, 습도 클래스
class OutdoorSensor:
    def __init__(self, outdoor_temp_val, outdoor_humi_val):
        self.outdoor_temp_val = outdoor_temp_val
        self.outdoor_humi_val = outdoor_humi_val

# 조명 설정 시간대 형식 클래스
class LghtSetFormat:
    def __init__(self, fr_time, to_time):
        self.fr_time = fr_time
        self.to_time = to_time

# 급수 설정 시간대 형식 클래스
class WatrSetFormat:
    def __init__(self, fr_time, to_time):
        self.fr_time = fr_time
        self.to_time = to_time
