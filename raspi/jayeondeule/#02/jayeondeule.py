import sys
import os
import subprocess
import time

from dotenv   import load_dotenv
from datetime import datetime, timedelta, timezone

import config          as cfg

from sensor   import sensor_control
from sql      import sql_control, sql_format, sql_config
from gpio     import gpio_control, gpio_config

from log_handler import setup_logger
logger = setup_logger("jayeondeule")

#---------------------------------------------------------
# 하위 디렉토의 파일 참조
#---------------------------------------------------------
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

#---------------------------------------------------------------------
# 팜 정보 읽어 옴옴
#---------------------------------------------------------------------
load_dotenv('.env')
farm_id  = os.getenv('FARM_ID')
house_id = cfg.is_myHouseId() # os.getenv('FARM_HOUSE_ID')
db       = None

chiller_start_time = None  # 칠러가 True로 변경된 시작 시간
CHILLER_MAX_RUNTIME = 40 * 60  # 40분 (초 단위)

#---------------------------------------------------------
# 시스템 service restart 
#---------------------------------------------------------
def system_restart_for_error():
    time.sleep(3)
    subprocess.call(["sudo", "/bin/systemctl", "restart", os.getenv("SYSTEM_SERVICE_NAME")])

#---------------------------------------------------------------------
# 아래 함수에 db instant를 파라메터로 주어야 해서 여기서 실행한다.
#---------------------------------------------------------------------
for attempt in range(sql_config.RETRY_ATTEMPTS):
    try:
        db = sql_control.SQLControl(farm_id, house_id)
        logger.info(f" 데이터 베이스 연결 완료 !!!")
        break
    except Exception as e:
        logger.error(f" 데이터 베이스 연결 오류 !!! 재시도회수: {attempt}, 오류: {e}")
        time.sleep(sql_config.RETRY_DELAY)
else:
    system_restart_for_error()

#---------------------------------------------------------------------
# 외부 클래스 정의
#---------------------------------------------------------------------
logger.info(f" 릴에이 초기화 시작 !!!")
gpio   = gpio_control.GPIOControl()
logger.info(f" GPIO 클래스 초기화 완료 !!!")

sensor = sensor_control.SENSControl(farm_id, house_id, gpio)
try:
    sensor_status = sensor.check_sensor_connections()
    for device, status in sensor_status.items():
        logger.info(f" 센서 연결 상태: {device} - {'연결됨' if status else '연결 안됨'}")
except Exception as e:
    logger.error(f" 센서 연결 상태 확인 중 오류 발생: {str(e)}")
logger.info(f" 센스 클래스 초기화 및 각 센서 연결 초기화 완료 !!!")


#----------------------------------------------
# 칠러 보호 기능 - 40분 연속 가동 시 강제 OFF
#----------------------------------------------
def check_chiller_protection():
    global chiller_start_time
    
    current_chiller_status = getattr(gpio.relay_status, f'relay_{gpio_config.CHILLER_GPIO+1}st_flag', False)
    
    if current_chiller_status:
        current_time = datetime.now()
        
        if chiller_start_time is None:
            chiller_start_time = current_time
            logger.info(f"칠러 가동 시작: {chiller_start_time}")
        else:
            runtime_seconds = (current_time - chiller_start_time).total_seconds()
            
            if runtime_seconds >= CHILLER_MAX_RUNTIME:
                logger.warning(f"칠러 40분 연속 가동으로 인한 강제 OFF - 가동시간: {runtime_seconds/60:.1f}분")
                gpio.relay_control(gpio_config.CHILLER_GPIO, False)
                chiller_start_time = None
                return True
            else:
                remaining_seconds = CHILLER_MAX_RUNTIME - runtime_seconds
                if int(runtime_seconds) % 300 == 0: 
                    logger.info(f"칠러 연속 가동 중 - 경과시간: {runtime_seconds/60:.1f}분, 남은시간: {remaining_seconds/60:.1f}분")
    else:
        if chiller_start_time is not None:
            runtime_seconds = (datetime.now() - chiller_start_time).total_seconds()
            logger.info(f"칠러 가동 종료 - 총 가동시간: {runtime_seconds/60:.1f}분")
            chiller_start_time = None
    return False

#------------------------
# 센서값 데이터 형식 정의
#------------------------
auto_record_data           = sql_format.AutoRecdFormat
auto_record_data.farm_id   = farm_id
auto_record_data.hous_id   = house_id

#------------------------------------------
# 센서 측정 값 읽기 
#------------------------------------------
def get_each_sensor_value():
    KST = timezone(timedelta(hours=9))
    readings = sensor.get_all_sensor_value()
    if readings:
        auto_record_data.indr_tprt_valu  = round(readings['indr_tprt_valu'], 3)
        auto_record_data.indr_hmdt_valu  = round(readings['indr_hmdt_valu'], 3)
        auto_record_data.oudr_tprt_valu  = round(readings['oudr_tprt_valu'], 3)
        auto_record_data.oudr_hmdt_valu  = round(readings['oudr_hmdt_valu'], 3)
        auto_record_data.co2_valu        = round(readings['co2_valu'], 3)
        auto_record_data.watr_tprt_valu  = round(readings['watr_tprt_valu'], 3)
        auto_record_data.ligt_level_valu = round(readings['ligt_level_valu'], 3)
        auto_record_data.watr_level_valu = round(readings['watr_level_valu'], 3)
    else:
        auto_record_data.indr_tprt_valu  = 0.0
        auto_record_data.indr_hmdt_valu  = 0.0
        auto_record_data.oudr_tprt_valu  = 0.0
        auto_record_data.oudr_hmdt_valu  = 0.0
        auto_record_data.co2_valu        = 0.0
        auto_record_data.watr_tprt_valu  = 0.0
        auto_record_data.ligt_level_valu = 0.0
        auto_record_data.watr_level_valu = 0.0

    auto_record_data.recd_dttm = datetime.now(KST).isoformat()
    logger.info(f" {auto_record_data.farm_id} - {auto_record_data.hous_id} - {auto_record_data.recd_dttm} 센서상태 -> 내부온도: {auto_record_data.indr_tprt_valu} / 내부습도: {auto_record_data.indr_hmdt_valu} / 외부온도:  {auto_record_data.oudr_tprt_valu} / 외부습드:  {auto_record_data.oudr_hmdt_valu} / CO2: {auto_record_data.co2_valu} / 수온:  {auto_record_data.watr_tprt_valu} / 조도: {auto_record_data.ligt_level_valu} / 수위: {auto_record_data.watr_level_valu}")

#------------------------------------------
# 릴레이값 로깅
#------------------------------------------
def logging_relay_status():
    try:
        relay_status_parts = []
        for i in range(1, 14):
            relay_attr = f"relay_{i}st_flag"
            if hasattr(gpio.relay_status, relay_attr):
                relay_value = getattr(gpio.relay_status, relay_attr)
                relay_name = gpio_config.RELAY_NAMES[relay_attr]
                relay_status_parts.append(f"{relay_name}: {relay_value}")
        relay_status_str = " / ".join(relay_status_parts)
        logger.info(f"       릴레이상태 -> {relay_status_str}")
    except Exception as e:
        logger.error(f"릴레이 상태 로깅 중 오류 발생: {str(e)}")

#========================================================================================================
# 메인 프로그램 시작 
#========================================================================================================
def main_loop():
    #----------------------------------------------
    # DataBase 연결 확인
    #----------------------------------------------
    if db is None or not db.check_base_available():
        system_restart_for_error()
        logger.info(f" Database 재 연결 완료 !!!")
        return
    
    #----------------------------------------------
    # 릴레이 값 초기화 - 모두 False 처리
    #----------------------------------------------
    for i in range(len(gpio_config.RELAY_GPIO)):
        time.sleep(0.3)
        gpio.relay_control(i, cfg.RELAY_ON) 
        time.sleep(0.3)
        gpio.relay_control(i, cfg.RELAY_OFF)
    logger.info(f" 각 GPIO 릴레이 초기화 완료 !!!")

    #----------------------------------------------
    # 센서 값 읽어오는 Interval 계산위한 시간 셋팅
    #----------------------------------------------
    sense_get_time = datetime.now()

    #----------------------------------------------
    # 무한 반복 수행
    #----------------------------------------------
    while True:
        try:
            if (datetime.now() - sense_get_time >= timedelta(seconds=float(db.get_sensor_refresh_interval())) or db.get_refresh_flag()):
                #--------------------
                # 센서 값을 읽고 기록 
                #--------------------
                get_each_sensor_value()
                db.set_auto_recd(auto_record_data)

                #------------------------------------
                # 센서 값을 분석하고 릴레이 값을 셋팅 
                #------------------------------------
                # if not db.get_base_relay_manual_control_flag() and sensor:
                #     gpio.relay_status = ansAct.analysis_action(auto_record_data)
                # else:
                base_relay_status, base_relay_len = db.get_base_relay_status()
                for i in range(base_relay_len):
                    single_relay_status = getattr(base_relay_status, f'relay_{i+1}st_flag')
                    gpio.relay_control(i, single_relay_status)

                chiller_forced_off = check_chiller_protection()
                if chiller_forced_off:
                    setattr(gpio.relay_status, f'relay_{gpio_config.CHILLER_GPIO+1}st_flag', False)

                db.set_base_relay_status(gpio.relay_status, auto_record_data.recd_dttm)

                #--------------------------------------
                # 홈페이지 Refresh Flag를 False로 셋팅 
                #--------------------------------------
                db.set_refresh_flag(False)

                sense_get_time = datetime.now()

        except KeyboardInterrupt:
            gpio.cleanup_gpio()
            logger.error(f" Program interrupted by user.")
            break
        except Exception as e:
            gpio.cleanup_gpio()
            logger.error(f" Error occurred Main: {e}")
            system_restart_for_error()

if __name__ == "__main__":

    main_loop()

