import sys
import os
import subprocess
import time

from dotenv   import load_dotenv
from datetime import datetime, timedelta, timezone

import config          as cfg

from sql      import sql_control, sql_format, sql_config
from gpio     import gpio_config

from log_handler import setup_logger
logger = setup_logger('jayeondeule')

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv('.env')
farm_id  = os.getenv('FARM_ID')
house_id = cfg.is_myHouseId()
db       = None
gpio     = None
sensor   = None

def system_restart_for_error():
    time.sleep(5)
    subprocess.call(['sudo', '/bin/systemctl', 'restart', os.getenv('SYSTEM_SERVICE_NAME')])

# DB 연결
for attempt in range(sql_config.RETRY_ATTEMPTS):
    try:
        db = sql_control.SQLControl(farm_id, house_id)
        logger.info('데이터베이스 연결 완료')
        break
    except Exception as e:
        logger.error(f'데이터베이스 연결 오류 (재시도 {attempt}): {e}')
        time.sleep(sql_config.RETRY_DELAY)
else:
    logger.error('데이터베이스 연결 실패, 재시작')
    system_restart_for_error()

# GPIO 초기화 — 실패해도 계속 진행
try:
    from gpio import gpio_control
    gpio = gpio_control.GPIOControl()
    logger.info('GPIO 초기화 완료')
except Exception as e:
    logger.warning(f'GPIO 초기화 실패 (계속 진행): {e}')

# 센서 초기화 — 실패해도 계속 진행
try:
    from sensor import sensor_control
    sensor = sensor_control.SENSControl(farm_id, house_id, gpio)
    try:
        sensor_status = sensor.check_sensor_connections()
        for device, status in sensor_status.items():
            conn_text = '확인 불가 (GPIO)' if status is None else ('연결됨' if status else '연결 안됨')
            logger.info(f'센서 연결 상태: {device} - {conn_text}')
    except Exception as e:
        logger.warning(f'센서 연결 상태 확인 오류 (계속 진행): {e}')
    logger.info('센서 초기화 완료')
except Exception as e:
    logger.warning(f'센서 초기화 실패 (계속 진행): {e}')

auto_record_data         = sql_format.AutoRecdFormat
auto_record_data.farm_id = farm_id
auto_record_data.hous_id = house_id

def get_each_sensor_value():
    KST = timezone(timedelta(hours=9))
    if sensor:
        readings = sensor.get_all_sensor_value()
    else:
        readings = None

    if readings:
        auto_record_data.indr_tprt_valu  = round(readings.get('indr_tprt_valu', 0), 3)
        auto_record_data.indr_hmdt_valu  = round(readings.get('indr_hmdt_valu', 0), 3)
        auto_record_data.oudr_tprt_valu  = round(readings.get('oudr_tprt_valu', 0), 3)
        auto_record_data.oudr_hmdt_valu  = round(readings.get('oudr_hmdt_valu', 0), 3)
        auto_record_data.co2_valu        = round(readings.get('co2_valu', 0), 3)
        auto_record_data.watr_tprt_valu  = round(readings.get('watr_tprt_valu', 0), 3)
        auto_record_data.ligt_level_valu = round(readings.get('ligt_level_valu', 0), 3)
        auto_record_data.watr_level_valu = round(readings.get('watr_level_valu', 0), 3)
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
    logger.info(
        f'{auto_record_data.farm_id}-{auto_record_data.hous_id} '
        f'센서: 내부온도={auto_record_data.indr_tprt_valu} 내부습도={auto_record_data.indr_hmdt_valu} '
        f'외부온도={auto_record_data.oudr_tprt_valu} 외부습도={auto_record_data.oudr_hmdt_valu} '
        f'CO2={auto_record_data.co2_valu} 수온={auto_record_data.watr_tprt_valu} '
        f'조도={auto_record_data.ligt_level_valu} 수위={auto_record_data.watr_level_valu}'
    )

def main_loop():
    if db is None:
        logger.error('DB 연결 없음, 재시작')
        system_restart_for_error()
        return

    try:
        if not db.check_base_available():
            logger.warning('DB 기본 데이터 없음 (계속 진행)')
    except Exception as e:
        logger.warning(f'DB 체크 오류 (계속 진행): {e}')

    # GPIO 릴레이 초기화
    if gpio:
        for i in range(len(gpio_config.RELAY_GPIO)):
            try:
                time.sleep(0.3)
                gpio.relay_control(i, cfg.RELAY_ON)
                time.sleep(0.3)
                gpio.relay_control(i, cfg.RELAY_OFF)
            except Exception as e:
                logger.warning(f'릴레이 {i} 초기화 오류 (계속 진행): {e}')
        logger.info('GPIO 릴레이 초기화 완료')
    else:
        logger.warning('GPIO 없음, 릴레이 초기화 건너뜀')

    sense_get_time = datetime.now()

    while True:
        try:
            interval = 3
            try:
                interval = float(db.get_sensor_refresh_interval())
            except Exception:
                pass

            refresh_flag = False
            try:
                refresh_flag = db.get_refresh_flag()
            except Exception:
                pass

            if datetime.now() - sense_get_time >= timedelta(seconds=interval) or refresh_flag:
                get_each_sensor_value()

                try:
                    db.set_auto_recd(auto_record_data)
                except Exception as e:
                    logger.error(f'센서 데이터 DB 기록 오류: {e}')

                if gpio:
                    try:
                        base_relay_status, base_relay_len = db.get_base_relay_status()
                        for i in range(base_relay_len):
                            single_relay_status = getattr(base_relay_status, f'relay_{i+1}st_flag')
                            gpio.relay_control(i, single_relay_status)
                        db.set_base_relay_status(gpio.relay_status, auto_record_data.recd_dttm)
                    except Exception as e:
                        logger.error(f'릴레이 제어 오류: {e}')

                try:
                    db.set_refresh_flag(False)
                except Exception:
                    pass

                sense_get_time = datetime.now()

        except KeyboardInterrupt:
            if gpio:
                gpio.cleanup_gpio()
            logger.info('사용자에 의해 종료')
            break
        except Exception as e:
            logger.error(f'메인루프 오류: {e}')
            time.sleep(3)

if __name__ == '__main__':
    main_loop()
