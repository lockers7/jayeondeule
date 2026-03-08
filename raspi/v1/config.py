import os
import sys
import socket
import datetime

from dotenv   import load_dotenv

# 기본 재배동 ID 설정
FARM_ID = '2'

# 센서값 읽기 간격 설정 (10초)
SENSOR_READ_INTERVAL = datetime.timedelta(seconds=3)

# DB 테이터 저장하는 간격(30초)
DB_WRITE_INTERVAL = datetime.timedelta(seconds=30)

# 센서 사용 여부 설정
SENSOR_ENABLED = False

CHILLER_1_MIN_GAP = 0
CHILLER_1_MAX_GAP = 0

CHILLER_2_MIN_GAP = 0
CHILLER_2_MAX_GAP = 0

TEMP_MIN_GAP = 1
TEMP_MAX_GAP = 0

HUMI_MIN_GAP = 0
HUMI_MAX_GAP = 0

CO2_MIN_GAP = 0
CO2_MAX_GAP = 0

WTEMP_MIN_GAP = 8
WTEMP_MAX_GAP = 0

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv('.env')

FARM_ID = 1
def is_myFarmId():
    return str(os.getenv('FARM_ID', FARM_ID))

def is_myHouseId():
    local_ip = ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    finally:
        s.close()

    return int(local_ip.strip().split('.')[-1]) - 100 
