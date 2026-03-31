import sys
import os
import subprocess
import time
import config   as cfg

from datetime import datetime, timedelta
from sensor   import sensor_control
from sql      import sql_control, sql_format, sql_config
from gpio     import gpio_control, gpio_config

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from log_handler import setup_logger
logger = setup_logger("main")

#---------------------------------------------------------------------
# 팜 정보 읽어 옴옴
#---------------------------------------------------------------------
farm_id  = cfg.is_myFarmId()
house_id = cfg.is_myHouseId()
db       = None

def system_restart_for_error():
    time.sleep(5)
    subprocess.call(["sudo", "/bin/systemctl", "restart", "jayeondeule_ctrl"])

for attempt in range(sql_config.RETRY_ATTEMPTS):
    try:
        db = sql_control.SQLControl(farm_id)
        print("Database connected successfully.")
        break
    except Exception as e:
        print(f"Database connection failed: {attempt} / {e}")
        time.sleep(sql_config.RETRY_DELAY)
else:
    print("데이터베이스 연결 실패로 재시작")
    system_restart_for_error()

# 센서 초기화 - 실패해도 계속 진행
try:
    sensor = sensor_control.SENSControl(farm_id)
    logger.info("센서 초기화 완료")
except Exception as e:
    logger.error(f"센서 초기화 중 오류 발생 (계속 진행): {e}")
    sensor = None

# GPIO 초기화 - 실패해도 계속 진행
try:
    gpio = gpio_control.GPIOControl()
    logger.info("GPIO 초기화 완료")
except Exception as e:
    logger.error(f"GPIO 초기화 중 오류 발생 (계속 진행): {e}")
    gpio = None

auto_record_data         = sql_format.AutoRecdFormat
auto_record_data.farm_id = farm_id

def get_each_sensor_value():
    # readings                    = sensor.get_all_sensor_value()

    # outdoor_sensor = db.get_outdoor_sensor_val()
    # auto_record_data.outdoor_temp_val = round(outdoor_sensor.outdoor_temp_val,1)
    # auto_record_data.outdoor_humi_val = round(outdoor_sensor.outdoor_humi_val,1)
    # if readings:
    #     auto_record_data.humi_val         = round(readings['humidity'], 1)           # 습도 (BME280)
    #     auto_record_data.htemp_val        = round(readings['temperature'], 1)        # 온도 (BME280)
    #     auto_record_data.co2_val          =       readings['co2']                    # CO₂ 농도 (MH-Z19B)
    #     auto_record_data.wtemp_val        = round(readings['water_temperature'], 1)  # 수온 (DS18B20)
    # else:
    #     auto_record_data.humi_val  = 0
    #     auto_record_data.htemp_val = 0
    #     auto_record_data.co2_val   = 0
    #     auto_record_data.wtemp_val = 0

    # auto_record_data.recd_date  = datetime.now()
    # 1) 실내/수온/CO2 읽기 - 널/타입 방어
    if sensor is not None:
        readings = sensor.get_all_sensor_value() or {}
    else:
        logger.debug("센서가 초기화되지 않음 - 기본값 사용")
        readings = {}
    try:
        humi  = readings.get('humidity', 0)
        temp  = readings.get('temperature', 0)
        co2   = readings.get('co2', 0)
        wtemp = readings.get('water_temperature', 0)

        # 숫자화/반올림 방어
        auto_record_data.humi_val   = round(float(humi), 1) if humi is not None else 0
        auto_record_data.htemp_val  = round(float(temp), 1) if temp is not None else 0
        auto_record_data.co2_val    = int(co2) if co2 is not None else 0
        auto_record_data.wtemp_val  = round(float(wtemp), 1) if wtemp is not None else 0
    except Exception as e:
        logger.error(f"[센서값 가공 오류] {e}")
        auto_record_data.humi_val  = 0
        auto_record_data.htemp_val = 0
        auto_record_data.co2_val   = 0
        auto_record_data.wtemp_val = 0

    # 2) 외기 읽기 - None/타입 혼용 방어 (객체/딕셔너리 겸용)
    try:
        outdoor = db.get_outdoor_sensor_val()
        if outdoor is None:
            out_t, out_h = 0, 0
        elif hasattr(outdoor, 'outdoor_temp_val'):
            out_t = outdoor.outdoor_temp_val
            out_h = outdoor.outdoor_humi_val
        elif isinstance(outdoor, dict):
            out_t = outdoor.get('outdoor_temp_val', 0)
            out_h = outdoor.get('outdoor_humi_val', 0)
        else:
            out_t, out_h = 0, 0

        auto_record_data.outdoor_temp_val = round(float(out_t), 1) if out_t is not None else 0
        auto_record_data.outdoor_humi_val = round(float(out_h), 1) if out_h is not None else 0
    except Exception as e:
        logger.error(f"[외기 센서값 가공 오류] {e}")
        auto_record_data.outdoor_temp_val = 0
        auto_record_data.outdoor_humi_val = 0

    auto_record_data.recd_date = datetime.now()    
    logger.info(f" {farm_id} - {house_id} - {auto_record_data.recd_date} 센서상태 -> 내부온도: {auto_record_data.htemp_val} / 내부습도: {auto_record_data.humi_val} / 외부온도:  {auto_record_data.outdoor_temp_val:.1f} / 외부습드:  {auto_record_data.outdoor_humi_val:.1f} / CO2: {auto_record_data.co2_val} / 수온:  {auto_record_data.wtemp_val} / 조도: {0} / 수위: {0}")

def main_loop():
    logger.info("main_loop 함수 진입")

    if db is None:
        logger.error("DB 연결이 None")
        system_restart_for_error()
        return

    try:
        base_available = db.check_base_available()
        if not base_available:
            logger.warning("check_base_available 실패 - 센서 설정 데이터가 없을 수 있습니다 (계속 진행)")
    except Exception as e:
        logger.error(f"check_base_available 오류: {e} (계속 진행)")
    
    #----------------------------------------------
    # 릴레이 테스트 - 1번부터 15번까지 순차적으로 ON/OFF
    #----------------------------------------------
    if gpio is not None:
        logger.info("릴레이 테스트 시작 - 1번부터 15번까지 순차 테스트")

        for i in range(len(gpio_config.RELAY_GPIO)):
            relay_num = i + 1
            gpio_pin = gpio_config.RELAY_GPIO[i]

            try:
                time.sleep(0.3)
                gpio.relay_control(i, True)
                logger.debug(f"릴레이 {relay_num} ON 완료")

                time.sleep(0.3)
                gpio.relay_control(i, False)
                logger.debug(f"릴레이 {relay_num} OFF 완료")
                logger.info(f"릴레이 {relay_num} (GPIO {gpio_pin}) 테스트 완료")
            except Exception as e:
                logger.error(f"릴레이 {relay_num} 테스트 중 오류 발생: {e}")
                try:
                    gpio.relay_control(i, False)
                except:
                    pass
        logger.info("각 GPIO 릴레이 초기화 완료 !!!")

        #----------------------------------------------
        # 기존 릴레이 초기화 코드 복원
        #----------------------------------------------
        for i in range(len(gpio_config.RELAY_GPIO)):
            gpio.relay_control(i, False)
    else:
        logger.warning("GPIO가 초기화되지 않아 릴레이 테스트를 건너뜁니다")    

    sense_get_time = datetime.now()
    db_wirte_time = datetime.now()

    while True:
        try:
            if (datetime.now() - sense_get_time >= timedelta(seconds=db.get_sensor_refresh_interval()) or db.get_refresh_flag()):
                get_each_sensor_value()
                db.set_auto_recd(auto_record_data)

                if gpio is not None:
                    base_relay_st, base_relay_len = db.get_base_relay_st()
                    for i in range(base_relay_len):
                        single_relay_status = getattr(base_relay_st, f'relay_{i+1}_st')
                        gpio.relay_control(i, single_relay_status)

                    db.set_base_relay_st(gpio.relay_st, auto_record_data.recd_date)
                else:
                    logger.debug("GPIO가 초기화되지 않아 릴레이 제어를 건너뜁니다")

                db.set_refresh_flag(False)

                sense_get_time = datetime.now()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error occurred Main: {e}")
            # 트랜잭션 롤백 시도
            try:
                if db and db.connection:
                    db.connection.rollback()
                    logger.info("트랜잭션 롤백 완료")
            except:
                pass
            system_restart_for_error()


if __name__ == "__main__":
    main_loop()
