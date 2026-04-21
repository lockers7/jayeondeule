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
        
        # CO2 센서 (UART) — 장치 미연결 시에도 나머지 센서는 살아나게 독립 방어
        try:
            self.co2_sensor = serial.Serial(sensor_config.SERIAL_PORT, sensor_config.BAUD_RATE, timeout=1)
        except Exception as e:
            logger.warning(f"[CO2 센서 초기화 실패] - {e}")
            self.co2_sensor = None

        # 1-Wire 수온 센서 디바이스 파일 경로
        # [2026-04-22 수정] DEVICE_FOLDERS 는 sensor_config import 시점에 한번만 glob 됨.
        # 부팅 직후 서비스가 1-Wire 커널 감지보다 먼저 실행되면 빈 리스트가 캐시되어
        # "연결 안됨" 으로 고정되던 문제 방지 — 매 읽기마다 _rescan_ds18b20 으로 재검색.
        self._rescan_ds18b20()

    def _rescan_ds18b20(self):
        """/sys/bus/w1/devices/ 를 런타임에 재스캔하여 self.device_files 를 갱신."""
        import glob
        folders = glob.glob(sensor_config.BASE_PATH + '28*')
        self.device_files = [folder + '/w1_slave' for folder in folders]

        # I2C 버스 공용 — SHT4x/BME280 둘 다 사용. 버스 자체 초기화 실패해도 계속 진행.
        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)
            time.sleep(0.2)
        except Exception as e:
            logger.warning(f"[I2C 버스 초기화 실패] - {e}")
            self.i2c = None

        # SHT45 — RuntimeError(CRC), OSError 등도 잡아 다른 센서와 독립시킴
        # (ValueError 만 잡던 과거 버그로 SHT45 CRC 실패 시 SENSControl 전체가 죽어
        #  BME280·CO2·수온까지 0.0 으로 표시되는 문제가 있었음)
        if self.i2c is not None:
            try:
                self.sensor = sht4x.SHT4x(self.i2c)
                self.sensor.mode = sht4x.Mode.NOHEAT_HIGHPRECISION
                logger.info(f"SHT4x initialized. Serial: {self.sensor.serial_number}")
            except Exception as e:
                logger.warning(f"[SHT4x 초기화 실패] - {e}")
                self.sensor = None
        else:
            self.sensor = None

        # BME280 — 마찬가지로 독립 방어 (이미 Exception 범위)
        if self.i2c is not None:
            try:
                self.bme280 = Adafruit_BME280_I2C(self.i2c, address=sensor_config.I2C_BME280_ADDRESS)
            except Exception as e:
                logger.warning(f"[BME280 초기화 실패] - {e}")
                self.bme280 = None
        else:
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
        # CO2 센서 미연결 시 안전 반환 (초기화 실패 대응)
        if self.co2_sensor is None:
            return 0
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
        # [2026-04-22] 부팅 직후 1-Wire 지연 감지 대응 — device_files 가 비어있으면 재스캔
        if not self.device_files:
            self._rescan_ds18b20()
        if not self.device_files:
            print("No DS18B20 sensor detected.")
            return 0

        try:
            device_file = self.device_files[0]
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
        
        # [2026-04-22] 부팅 직후 1-Wire 감지 지연에 대비해 상태 판정 시 재스캔
        if not self.device_files:
            self._rescan_ds18b20()
        status["DS18B20 (수온)"] = len(self.device_files) > 0
        
        status["조도 센서"] = None  # GPIO 디지털 — 연결 확인 불가
        status["수위 센서"] = None  # GPIO 디지털 — 연결 확인 불가
        return status
    