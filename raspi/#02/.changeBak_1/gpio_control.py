import lgpio
import time

from gpio import gpio_config as cfg
from sql  import sql_format as sqlFmt

from log_handler import setup_logger
logger = setup_logger("sensor_conftrol")
#==================================================================================================
# GPIO 릴레이 값 처리
#==================================================================================================
class GPIOControl:
    def __init__(self):
        self.relay_gpio   = cfg.RELAY_GPIO
        self.relay_status = sqlFmt.BaseRelayFlagFormat()

        # 기존 GPIO 핸들 해제 후 다시 열기
        try:
            self.h = lgpio.gpiochip_open(0)
        except lgpio.error as e:
            print("GPIO 핀이 이미 사용 중입니다. 강제 해제 후 다시 시도합니다.")
            self.cleanup_gpio()
            time.sleep(1)
            self.h = lgpio.gpiochip_open(0)

        #------------------------------------------
        # 조도, 수위 센서 Read 모드 셋팅 (None = 센서 미장착 → 스킵)
        #------------------------------------------
        if cfg.LIGHT_LEVEL_SENSOR_GPIO is not None:
            lgpio.gpio_claim_input(self.h, cfg.LIGHT_LEVEL_SENSOR_GPIO)
        if cfg.WATER_LEVEL_SENSOR_GPIO is not None:
            lgpio.gpio_claim_input(self.h, cfg.WATER_LEVEL_SENSOR_GPIO)

        #------------------------------
        # 릴레이 초기값을 초기화 — 2호는 active-high 릴레이 모듈:
        # 초기화 시 LOW(0) 써서 모든 릴레이 OFF 보장
        #------------------------------
        for pin in self.relay_gpio:
            try:
                lgpio.gpio_claim_output(self.h, pin)
                lgpio.gpio_write(self.h, pin, 0)
            except lgpio.error as e:
                print(f"GPIO {pin} 설정 중 오류 발생: {e}")

    def __del__(self):
        self.cleanup_gpio()
        
    #-------------------------------
    # GPIO 핸들러 닫기기
    #-------------------------------
    def cleanup_gpio(self):
        try:
            if self.h is not None:
                lgpio.gpiochip_close(self.h)
                self.h = None
        except Exception as e:
            print(f"GPIO 핸들 닫기 중 오류 발생: {e}")

    #----------------------------------------------------------------------------
    # 조도 센서값, 수위센서값 읽음
    #----------------------------------------------------------------------------
    def get_light_water_level_sensor_value(self):
        # 센서 미장착(None)이면 즉시 [0, 0] 반환
        if cfg.LIGHT_LEVEL_SENSOR_GPIO is None and cfg.WATER_LEVEL_SENSOR_GPIO is None:
            return [0, 0]

        light_level, water_level = 0, 0
        try:
            if cfg.LIGHT_LEVEL_SENSOR_GPIO is not None:
                light_level = lgpio.gpio_read(self.h, cfg.LIGHT_LEVEL_SENSOR_GPIO)
            if cfg.WATER_LEVEL_SENSOR_GPIO is not None:
                water_level = lgpio.gpio_read(self.h, cfg.WATER_LEVEL_SENSOR_GPIO)
        except Exception as e:
            print(f"Error reading light, water Level sensor value Err: {str(e)}")
            return [0, 0]

        return [light_level, water_level]

    #----------------------------------------------------------------------------
    # 릴레이 값에 따라 동작 실행
    # 2호는 active-high 릴레이 모듈 → status=True일 때 HIGH(1) 출력
    # (raspi_01/03은 active-low → 0 if status else 1)
    #----------------------------------------------------------------------------
    def __output_control(self, pin, status: bool):
        lgpio.gpio_write(self.h, pin, 1 if status else 0)

    #--------------------------------------------------------------------------------
    # 릴레이 ON/OFF
    #--------------------------------------------------------------------------------
    def relay_control(self, pin_no: int, status: bool):
        self.__output_control(self.relay_gpio[pin_no], status)
        setattr(self.relay_status, f'relay_{pin_no+1}st_flag', status)
