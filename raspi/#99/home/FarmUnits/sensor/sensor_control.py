import glob
import serial
import busio
import board
import time
import adafruit_sht4x  as sht4x
from adafruit_bme280.advanced import Adafruit_BME280_I2C

from sensor import sensor_config
from gpio   import gpio_control as gpioCtl

from log_handler import setup_logger
logger = setup_logger("sensor_conftrol")
#==============================================================================================================
# 센서 값을 읽는 클래스
#==============================================================================================================
class SENSControl:
    def __init__(self, farm_id: str, house_id: str, gpio: gpioCtl.GPIOControl):
        self.farm_id      = farm_id
        self.house_id     = house_id
        self.gpio         = gpio
        
        self.co2_sensor   = serial.Serial(sensor_config.SERIAL_PORT, sensor_config.BAUD_RATE, timeout=1)

        try:
            self.i2c    = busio.I2C(board.SCL, board.SDA)
            time.sleep(0.2)
            self.sensor = sht4x.SHT4x(self.i2c)
            self.sensor.mode = sht4x.Mode.NOHEAT_HIGHPRECISION
            print(f"SHT4x initialized. Serial: {self.sensor.serial_number}")
        except ValueError as e:
            print(f"[SHT4x 초기화 실패] - {e}")
            self.sensor = None 
                   
        try:
            self.bme280 = Adafruit_BME280_I2C(self.i2c, address=sensor_config.I2C_BME280_ADDRESS)
        except Exception as e:
            print(f"[BME280 초기화 실패] - {e}")
            self.bme280 = None

    #------------------------------------------------------------
    # 센서 값 읽기 공통 모듈
    #------------------------------------------------------------
    def safe_read(default=0.0):
        def decorator(fn):
            def wrapper(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    print(f"[센서 예외] {fn.__name__}: {e}")
                    return default
            return wrapper
        return decorator

    #------------------------------------------------------------
    # 현재 온도, 습도, 기압 값 읽기
    #------------------------------------------------------------
    @safe_read((0.0, 0.0, 0.0, 0.0))
    def get_tprt_hmdt_now_val(self):
        # 실내: SHT4x 부재 시 0
        if self.sensor:
            indoor_tprt, indoor_hmdt = self.sensor.measurements
        else:
            indoor_tprt, indoor_hmdt = 0.0, 0.0

        # 실외: BME280 부재 시 0
        if self.bme280:
            outdoor_tprt = self.bme280.temperature - 1.5
            outdoor_hmdt = self.bme280.relative_humidity
        else:
            outdoor_tprt = 0.0
            outdoor_hmdt = 0.0

        return indoor_tprt, indoor_hmdt, outdoor_tprt, outdoor_hmdt

    #-----------------------------------------------------------------------------
    # CO2 농도 측정
    #-----------------------------------------------------------------------------
    def get_co2_now_val(self):
        try:
            self.co2_sensor.write(b'\xFF\x01\x86\x00\x00\x00\x00\x00\x79')
            response = self.co2_sensor.read(9)

            co2_value = -1
            if len(response) == 9 and response[0] == 0xFF and response[1] == 0x86:
                co2_value = response[2] * 256 + response[3]
                return co2_value
            else:
                print("Invalid response from CO2 sensor.")
                return 0

        except Exception as e:
            print("Error reading CO2:", e)
            return 0

    #-----------------------------------------------------------------------------
    # DS18B20 수온 센서 온도 측정
    #-----------------------------------------------------------------------------
    def get_water_temp_now_val(self):
        device_folders = glob.glob(sensor_config.BASE_PATH + '28*')
        if not device_folders:
            print("No DS18B20 sensor detected.")
            return 0

        try:
            device_file = device_folders[0] + '/w1_slave'
            with open(device_file, 'r') as f:
                lines = f.readlines()
                if lines[0].strip()[-3:] == 'YES':
                    equals_pos = lines[1].find('t=')
                    if equals_pos != -1:
                        temp_string = lines[1][equals_pos + 2:]
                        temperature = float(temp_string) / 1000.0
                        return temperature
        except Exception as e:
            print("Error reading water temperature:", e)
            return 0

    #-----------------------------------------------------------------------------
    # 모든 센서의 값을 한 번에 읽기
    #-----------------------------------------------------------------------------
    def get_all_sensor_value(self):
        results = {}
        indoor_tprt, indoor_hmdt, outdoor_tprt, outdoor_hmdt = self.get_tprt_hmdt_now_val()
        results = {
            'indr_tprt_valu': indoor_tprt,
            'indr_hmdt_valu': indoor_hmdt,
            'oudr_tprt_valu': outdoor_tprt,
            'oudr_hmdt_valu': outdoor_hmdt,
        } 
        co2               = self.get_co2_now_val()
        water_temperature = self.get_water_temp_now_val()
        light_water_level = self.gpio.get_light_water_level_sensor_value()
        if isinstance(light_water_level, (list, tuple)) and len(light_water_level) == 2:
            light_level = light_water_level[0]
            water_level = light_water_level[1]
        else:
            logger.error("조도/수위 센서 값이 비정상 반환됨. 기본값 0 적용")
            light_level = 0
            water_level = 0
        results.update({
            'co2_valu'       : co2,
            'watr_tprt_valu' : water_temperature,
            'ligt_level_valu': light_level,
            'watr_level_valu': water_level,
        })
        return results

    #-----------------------------------------------------------------------------
    # 모든 센서의 연결 상태 확인
    #-----------------------------------------------------------------------------
    def check_sensor_connections(self):
        status = {}
        
        # try:
        #     self.sht30.temperature
        #     status["SHT30 (실내 온습도)"] = True
        # except Exception:
        #     status["SHT30 (실내 온습도)"] = False
        
        try:
            self.sensor.measurements  # SHT4x 확인용
            status["SHT45 (실내 온습도)"] = True
        except Exception:
            status["SHT45 (실내 온습도)"] = False
            
        try:
            self.bme280.temperature
            status["BME280 (실외 온습도)"] = True
        except Exception:
            status["BME280 (실외 온습도)"] = False
        
        try:
            self.co2_sensor.write(b'\xFF\x01\x86\x00\x00\x00\x00\x00\x79')
            response = self.co2_sensor.read(9)
            status["MH-Z19B (CO2)"] = len(response) == 9 and response[0] == 0xFF and response[1] == 0x86
        except Exception:
            status["MH-Z19B (CO2)"] = False
        
        status["DS18B20 (수온)"] = len(glob.glob(sensor_config.BASE_PATH + '28*')) > 0
        
        status["조도 센서"] = None  # GPIO 디지털 — 연결 확인 불가
        status["수위 센서"] = None  # GPIO 디지털 — 연결 확인 불가
        return status
    