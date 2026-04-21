import os
import serial
import busio
import board
import time
import adafruit_sht4x  as sht4x
# BME280 / BMP280 라이브러리 — 둘 중 하나만 있어도 동작하도록 try import
try:
    from adafruit_bme280.advanced import Adafruit_BME280_I2C
except Exception:
    Adafruit_BME280_I2C = None
try:
    import adafruit_bmp280 as _bmp280_mod
except Exception:
    _bmp280_mod = None

from sensor import sensor_config
from gpio   import gpio_control as gpioCtl

from log_handler import setup_logger
logger = setup_logger("sensor_conftrol")

# 외부 온습도 센서 chip ID 식별 — Bosch 센서별 고유값 (레지스터 0xD0)
_BME280_CHIP_ID = 0x60   # 온도+습도+기압
_BMP280_CHIP_ID = 0x58   # 온도+기압 (습도 없음)
#==============================================================================================================
# 센서 값을 읽는 클래스
#==============================================================================================================
class SENSControl:
    def __init__(self, farm_id: str, house_id: str, gpio: gpioCtl.GPIOControl):
        self.farm_id      = farm_id
        self.house_id     = house_id
        self.gpio         = gpio
        
        # CO2 센서 (UART, MH-Z19B)
        # [2026-04-27] 라즈베리파이 재부팅 직후 /dev/ttyAMA0 노출 지연 또는 센서
        # 워밍업 미완료로 인해 단 1회 시도에서 실패하면 self.co2_sensor=None 으로
        # 굳어 수동 재기동 전엔 회복 불가하던 문제를 보완. 초기화 N회 재시도 +
        # get_co2_now_val 런타임 자동 재초기화로 무인 자가복구.
        self.co2_sensor = None
        self._init_co2_sensor()

        # 1-Wire 수온 센서 디바이스 파일 경로
        # [2026-04-22] DEVICE_FOLDERS 는 import 시점에 한번만 glob 되어 부팅 직후
        # 서비스가 1-Wire 커널 감지보다 빨리 실행되면 빈 리스트로 굳던 문제 방지.
        # [2026-04-27] init 단계에서 짧은 polling 으로 28-* 노출 대기 → 시작 시
        # 'DS18B20 연결 안됨' 으로 잘못 로깅되는 race 제거. 끝까지 미감지면 매
        # 읽기마다 _rescan_ds18b20 (get_water_temp_now_val) 으로 향후 회복.
        self._init_ds18b20_with_wait()
        # I2C 라인 센서(SHT4x / BME280 / BMP280)는 1회 초기화. 1-Wire 와 무관하므로
        # _rescan_ds18b20 와 분리해 미감지 시 매 read 마다 init 로그가 폭주하지 않도록.
        # [2026-04-27] _rescan_ds18b20 책임분리.
        self._init_i2c_sensors()

    def _init_co2_sensor(self, max_attempts: int = 8, delay: float = 2.0):
        """MH-Z19B (UART) 초기화 — 부팅 직후 /dev/ttyAMA0 미노출 / 센서 워밍업
        지연을 흡수하기 위해 짧은 간격으로 재시도. max_attempts=1, delay=0 으로
        호출하면 런타임 즉시 재시도 모드(non-blocking)로 동작."""
        port = sensor_config.SERIAL_PORT
        for attempt in range(1, max_attempts + 1):
            if not os.path.exists(port):
                if max_attempts > 1:
                    logger.info(f"[CO2] {port} 미노출 — 대기 ({attempt}/{max_attempts})")
                time.sleep(delay)
                continue
            try:
                ser = serial.Serial(port, sensor_config.BAUD_RATE, timeout=1)
                ser.reset_input_buffer()
                # 통신 1회 검증 — 워밍업 중에도 9바이트 응답은 즉시 옴
                ser.write(b'\xFF\x01\x86\x00\x00\x00\x00\x00\x79')
                resp = ser.read(9)
                if len(resp) == 9 and resp[0] == 0xFF and resp[1] == 0x86:
                    self.co2_sensor = ser
                    logger.info(f"[CO2] MH-Z19B 초기화 성공 ({attempt}/{max_attempts})")
                    return True
                ser.close()
                if max_attempts > 1:
                    logger.info(f"[CO2] 응답 불완전 — 워밍업 대기 ({attempt}/{max_attempts})")
            except Exception as e:
                if max_attempts > 1:
                    logger.warning(f"[CO2] 초기화 실패 ({attempt}/{max_attempts}): {e}")
            time.sleep(delay)
        if max_attempts > 1:
            logger.warning(f"[CO2] {max_attempts}회 시도 실패 — 런타임 자동 재시도 대기")
        self.co2_sensor = None
        return False

    def _rescan_ds18b20(self):
        """/sys/bus/w1/devices/ 를 런타임에 재스캔하여 self.device_files 를 갱신.
        [2026-04-27] 단일책임 — 이 함수는 1-Wire 디바이스 파일 갱신만 수행.
        I2C 라인 센서 초기화는 _init_i2c_sensors() 로 분리되어 __init__ 에서 1회만 호출.
        [2026-04-27 추가] 연결 상태 전이(연결됨↔연결 안됨) 시 logger.info 로 한 번씩
        기록 → 운영 중 간헐적 단선/복구를 journalctl 에서 시각으로 추적 가능."""
        import glob
        folders = glob.glob(sensor_config.BASE_PATH + '28*')
        new_files = [folder + '/w1_slave' for folder in folders]
        prev_connected = bool(getattr(self, 'device_files', []))
        new_connected = bool(new_files)
        self.device_files = new_files
        if prev_connected != new_connected:
            state = '연결됨' if new_connected else '연결 안됨'
            logger.info(f"[DS18B20] 연결 상태 변경: {state}")

    def _init_ds18b20_with_wait(self, max_attempts: int = 10, delay: float = 2.0):
        """부팅 직후 1-Wire 커널 스캔 미완료 race 대응 — 28-* 디바이스 노출까지
        N회 polling. (CO2 의 /dev/ttyAMA0 노출 대기와 동일 패턴.)
        [2026-04-27] 시작 시점에 device_files 가 비어있어 'DS18B20 연결 안됨'
        으로 잘못 로깅되던 문제 보완. 노출되면 즉시 return, 끝까지 미노출이면
        device_files 빈 채로 종료(런타임 _rescan 이 향후 회복 시도)."""
        for attempt in range(1, max_attempts + 1):
            self._rescan_ds18b20()
            if self.device_files:
                if attempt > 1:
                    logger.info(f"[DS18B20] 1-Wire 노출 대기 후 감지 ({attempt}/{max_attempts})")
                return True
            time.sleep(delay)
        logger.warning(f"[DS18B20] {max_attempts}회 polling 후에도 미노출 — 런타임 자동 재시도")
        return False

    def _init_i2c_sensors(self):
        """I2C 버스 + SHT4x + BME280/BMP280 초기화 — __init__ 에서 1회 호출.
        실패한 센서는 None 으로 두고 한 번만 경고 로그. 런타임 재초기화 없음
        (CO2 와 달리 I2C 라인 센서는 부팅 직후 즉시 응답하며, 재시도 폴링이
        오히려 로그 스팸을 일으키므로 단발성으로 처리)."""
        # I2C 버스 공용 — SHT4x/BME280 둘 다 사용
        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)
            time.sleep(0.2)
        except Exception as e:
            logger.warning(f"[I2C 버스 초기화 실패] - {e}")
            self.i2c = None

        # SHT45 — RuntimeError(CRC), OSError 등도 잡아 다른 센서와 독립시킴
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

        # 외부 온습도 — BME280(습도 O) 또는 BMP280(습도 X) 자동 분기
        self.bme280 = None
        self.bmp280 = None
        if self.i2c is not None:
            self._init_bme_or_bmp280(sensor_config.I2C_BME280_ADDRESS)

    def _init_bme_or_bmp280(self, addr):
        """0x76(또는 0x77) 에 응답하는 외부 온습도 센서를 chip ID 로 식별해
        BME280 또는 BMP280 으로 초기화. 라이브러리 미설치·통신 실패는
        조용히 흡수하고 self.bme280/self.bmp280 은 None 으로 남긴다."""
        chip_id = self._read_chip_id(addr)
        if chip_id is None:
            logger.warning(f"[외부 온습도] 0x{addr:02X} 응답 없음 — BME280/BMP280 모두 미연결")
            return
        if chip_id == _BME280_CHIP_ID:
            if Adafruit_BME280_I2C is None:
                logger.warning("[BME280 감지] adafruit_bme280 미설치")
                return
            try:
                self.bme280 = Adafruit_BME280_I2C(self.i2c, address=addr)
                logger.info(f"[BME280] 초기화 성공 (chip 0x{chip_id:02X}, addr 0x{addr:02X})")
            except Exception as e:
                logger.warning(f"[BME280 초기화 실패] - {e}")
                self.bme280 = None
        elif chip_id == _BMP280_CHIP_ID:
            if _bmp280_mod is None:
                logger.warning("[BMP280 감지] adafruit_bmp280 미설치 — pip install adafruit-circuitpython-bmp280")
                return
            try:
                self.bmp280 = _bmp280_mod.Adafruit_BMP280_I2C(self.i2c, address=addr)
                logger.info(f"[BMP280] 초기화 성공 (chip 0x{chip_id:02X}, addr 0x{addr:02X}) — 습도는 0 으로 처리")
            except Exception as e:
                logger.warning(f"[BMP280 초기화 실패] - {e}")
                self.bmp280 = None
        else:
            logger.warning(f"[외부 온습도] 알 수 없는 chip ID 0x{chip_id:02X} (BME280=0x60 / BMP280=0x58)")

    def _read_chip_id(self, addr):
        """레지스터 0xD0 에서 1바이트 chip ID 읽기. 통신 실패 시 None."""
        try:
            while not self.i2c.try_lock():
                pass
            try:
                buf = bytearray(1)
                self.i2c.writeto_then_readfrom(addr, bytes([0xD0]), buf)
                return buf[0]
            finally:
                self.i2c.unlock()
        except Exception:
            return None

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

        # 실외 온습도 — BME280 우선, 없으면 BMP280(습도 0), 둘 다 없으면 0
        if self.bme280:
            outdoor_tprt = self.bme280.temperature - 1.5
            outdoor_hmdt = self.bme280.relative_humidity
        elif self.bmp280:
            outdoor_tprt = self.bmp280.temperature - 1.5
            outdoor_hmdt = 0.0   # BMP280 은 습도 센서 없음
        else:
            outdoor_tprt = 0.0
            outdoor_hmdt = 0.0

        return indoor_tprt, indoor_hmdt, outdoor_tprt, outdoor_hmdt

    #-----------------------------------------------------------------------------
    # CO2 농도 측정
    #-----------------------------------------------------------------------------
    def get_co2_now_val(self):
        # 미연결 상태면 런타임 재초기화(non-blocking) 시도 — 부팅 직후 init 이
        # 실패해도 다음 사이클부터 자동 회복.
        if self.co2_sensor is None:
            self._init_co2_sensor(max_attempts=1, delay=0)
            if self.co2_sensor is None:
                return 0
        try:
            self.co2_sensor.reset_input_buffer()
            self.co2_sensor.write(b'\xFF\x01\x86\x00\x00\x00\x00\x00\x79')
            response = self.co2_sensor.read(9)
            if len(response) == 9 and response[0] == 0xFF and response[1] == 0x86:
                return response[2] * 256 + response[3]
            logger.warning("[CO2] 응답 형식 불일치 — 다음 사이클 재초기화")
        except Exception as e:
            logger.warning(f"[CO2] 읽기 오류 — 다음 사이클 재초기화: {e}")
        try:
            self.co2_sensor.close()
        except Exception:
            pass
        self.co2_sensor = None
        return 0

    #-----------------------------------------------------------------------------
    # DS18B20 수온 센서 온도 측정
    # [2026-04-27] 1-Wire 버스 노이즈로 인한 간헐적 CRC 실패 대응 — 최대 3회
    # 재시도. 기존 단일 read 흐름은 _read_water_temp_once 로 그대로 보존하면서
    # fall-through 경로(CRC=NO, lines[1] 누락, 응답 형식 불일치 등)의 암시적
    # None 반환을 명시 0 반환으로 보완 (상위 round() TypeError 차단).
    #-----------------------------------------------------------------------------
    def get_water_temp_now_val(self):
        for _ in range(3):
            v = self._read_water_temp_once()
            if v is not None:
                return v
            time.sleep(0.05)
        return 0

    def _read_water_temp_once(self):
        """DS18B20 수온 1회 read. 성공 시 float, 실패 시 None (재시도 신호).
        [2026-04-27] 매 read 마다 무조건 재 glob — 커널이 응답 실패한 sensor 의
        28-* 디렉토리를 자동 제거하므로 cached path 가 즉시 stale 됨. 매번 glob
        해 stale 캐시 stat 호출(File ENOENT) 을 회피하고 _rescan_ds18b20 의 상태
        전이 로깅이 정확한 시점에 발화하도록."""
        self._rescan_ds18b20()
        if not self.device_files:
            return None   # 미감지 — 호출자가 0 으로 변환

        try:
            device_file = self.device_files[0]
            with open(device_file, 'r') as f:
                lines = f.readlines()
            if len(lines) >= 2 and lines[0].strip()[-3:] == 'YES':
                equals_pos = lines[1].find('t=')
                if equals_pos != -1:
                    temp_string = lines[1][equals_pos + 2:]
                    return float(temp_string) / 1000.0
        except Exception as e:
            logger.warning(f"[DS18B20] 수온 read 예외 (재시도): {e}")
        return None   # CRC=NO / 응답 형식 불일치

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
            
        # 외부 온습도 — BME280(습도 O) 또는 BMP280(습도 X) 자동 분기
        try:
            if self.bme280 is not None:
                self.bme280.temperature
                status["BME280 (실외 온습도)"] = True
            elif self.bmp280 is not None:
                self.bmp280.temperature
                status["BMP280 (실외 온도·기압)"] = True   # 습도 없음 명시
            else:
                status["BME280/BMP280 (실외 온습도)"] = False
        except Exception:
            status["BME280/BMP280 (실외 온습도)"] = False
        
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
    