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
    """로컬 IP의 마지막 옥텟 - 100 으로 재배사 ID 계산.
    [2026-04-22 수정] 재부팅 직후 네트워크 미준비 상태에서 local_ip=''/'0.0.0.0'
    으로 잡혀 hous_id=-100 이 나와 DB FK 위반으로 트랜잭션 abort 되던 버그 방지.
    최대 10회(~30초) 유효 IP 획득 재시도 후에도 실패하면 예외 발생.
    """
    import socket as _socket
    import time as _time
    for _attempt in range(10):
        local_ip = ""
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
        try:
            last_octet = int(local_ip.strip().split('.')[-1])
            if last_octet >= 100:    # 자연들에 재배사 IP 체계: 100 이상
                return last_octet - 100
        except (ValueError, AttributeError, IndexError):
            pass
        _time.sleep(3)
    raise RuntimeError(f"유효한 로컬 IP 획득 실패 (마지막 local_ip={local_ip!r})")

