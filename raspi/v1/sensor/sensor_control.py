import serial
import time
import busio
import board

from . import sensor_config
import adafruit_sht4x  as sht4x
from log_handler import setup_logger

logger = setup_logger("sensor_control")

class SENSControl:
    def __init__(self, farm_id: str):
        self.farm_id = farm_id
        self.co2_sensor = None
        self.sensor = None
        self.device_files = []

        # CO2 센서 설정 - 여러 시리얼 포트를 시도
        self.co2_sensor = None
        if hasattr(sensor_config, 'SERIAL_PORT_CANDIDATES'):
            ports_to_try = sensor_config.SERIAL_PORT_CANDIDATES
        else:
            ports_to_try = [sensor_config.SERIAL_PORT]

        for port in ports_to_try:
            try:
                self.co2_sensor = serial.Serial(port, sensor_config.BAUD_RATE, timeout=1)
                logger.info(f"CO2 센서 초기화 성공: {port}")
                break
            except Exception as e:
                logger.debug(f"CO2 센서 포트 {port} 시도 실패: {e}")
                continue

        if self.co2_sensor is None:
            logger.warning(f"CO2 센서 초기화 실패 - 모든 포트 시도 완료 (계속 진행)")

        # DS18B20 수온 센서 파일 설정
        try:
            self.device_files = [device_folder + '/w1_slave' for device_folder in sensor_config.DEVICE_FOLDERS]
            if self.device_files:
                logger.info(f"DS18B20 수온 센서 {len(self.device_files)}개 감지")
            else:
                logger.warning("DS18B20 수온 센서를 찾을 수 없음 (계속 진행)")
        except Exception as e:
            logger.warning(f"DS18B20 수온 센서 초기화 실패 (계속 진행): {e}")
            self.device_files = []

        # SHT4x 온습도 센서 설정
        try:
            self.i2c    = busio.I2C(board.SCL, board.SDA)
            time.sleep(0.2)
            self.sensor = sht4x.SHT4x(self.i2c)
            self.sensor.mode = sht4x.Mode.NOHEAT_HIGHPRECISION
            time.sleep(0.5)
            logger.info(f"SHT4x initialized. Serial: {self.sensor.serial_number}")
        except Exception as e:
            logger.warning(f"SHT4x 초기화 실패 (계속 진행): {e}")
            self.sensor = None

        # 센서 연결 상태 확인
        try:
            sensor_status = self.check_sensor_connections()
            for device, status in sensor_status.items():
                logger.info(f"센서 연결 상태: {device} - {'연결됨' if status else '연결 안됨'}")
        except Exception as e:
            logger.error(f"센서 연결 상태 확인 중 오류 발생: {str(e)}")

    #------------------------------------------------------------
    # 센서 값 읽기 공통 모듈
    #------------------------------------------------------------
    def safe_read(default=0.0):
        def decorator(fn):
            def wrapper(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    logger.error(f"[센서 예외] {fn.__name__}: {e}")
                    return default
            return wrapper
        return decorator

    # 온도, 기압, 습도 측정
    @safe_read((0.0, 0.0))
    def get_temp_humi_now_val(self):
        try:
            if self.sensor:
                temperature, humidity = self.sensor.measurements
            else:
                temperature, humidity = 0.0, 0.0
            
            return temperature, humidity
        except Exception as e:
            logger.error(f"온습도 센서 읽기 오류: {e}")
            return 0.0, 0.0

    # CO2 농도 측정
    def get_co2_now_val(self):
        if self.co2_sensor is None:
            logger.debug("CO2 센서가 연결되지 않음 - 기본값 0 반환")
            return 0

        try:
            self.co2_sensor.write(b'\xFF\x01\x86\x00\x00\x00\x00\x00\x79')
            response = self.co2_sensor.read(9)

            co2_value = -1
            if len(response) == 9 and response[0] == 0xFF and response[1] == 0x86:
                co2_value = response[2] * 256 + response[3]
                return co2_value
            else:
                logger.warning("Invalid response from CO2 sensor.")
                return 0

        except Exception as e:
            logger.error(f"Error reading CO2: {e}")
            return 0

    # DS18B20 수온 센서 온도 측정
    def get_water_temp_now_val(self):
        if not self.device_files:
            logger.warning("No DS18B20 sensor detected.")
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
            logger.error(f"Error reading water temperature: {e}")
            return 0

    # 모든 센서의 값을 한 번에 읽기
    def get_all_sensor_value(self):
        try:
            temperature, humidity = self.get_temp_humi_now_val()
            co2 = self.get_co2_now_val()
            water_temperature = self.get_water_temp_now_val()
            
            # 각 값이 None인 경우 기본값 설정
            return {
                'temperature': temperature - 1 if temperature is not None else 0,
                'humidity': humidity - 10 if humidity is not None else 0,
                'co2': co2 if co2 is not None else 0,
                'water_temperature': water_temperature if water_temperature is not None else 0
            }
        except Exception as e:
            logger.error(f"센서 값 읽기 오류: {e}")
            # None 대신 기본값 사전 반환
            return {
                'temperature': 0,
                'humidity': 0,
                'co2': 0,
                'water_temperature': 0
            }

    #-----------------------------------------------------------------------------
    # 모든 센서의 연결 상태 확인 (이전 코드에서 추가)
    #-----------------------------------------------------------------------------
    def check_sensor_connections(self):
        status = {}

        try:
            if self.sensor is not None:
                self.sensor.measurements  # SHT4x 확인용
                status["SHT4x (실내 온습도)"] = True
            else:
                status["SHT4x (실내 온습도)"] = False
        except Exception:
            status["SHT4x (실내 온습도)"] = False

        try:
            if self.co2_sensor is not None:
                self.co2_sensor.write(b'\xFF\x01\x86\x00\x00\x00\x00\x00\x79')
                response = self.co2_sensor.read(9)
                status["MH-Z19B (CO2)"] = len(response) == 9 and response[0] == 0xFF and response[1] == 0x86
            else:
                status["MH-Z19B (CO2)"] = False
        except Exception:
            status["MH-Z19B (CO2)"] = False

        status["DS18B20 (수온)"] = len(self.device_files) > 0

        return status
    