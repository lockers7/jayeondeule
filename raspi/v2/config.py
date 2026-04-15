import socket

RELAY_ON  = True
RELAY_OFF = False

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

def is_myFarmId():
    return os.getenv('FARM_ID')

def is_myHouseId():
    local_ip = ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    finally:
        s.close()

    house_id = int(local_ip.strip().split('.')[-1]) - 100
    return int(local_ip.strip().split('.')[-1]) - 100
