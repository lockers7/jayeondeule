import time
import lgpio 
from .    import gpio_config as cfg
from sql  import sql_format  as sqlFmt
from log_handler import setup_logger

logger = setup_logger("gpio_control")

class GPIOControl:
    def __init__(self):
        self.relay_gpio = cfg.RELAY_GPIO
        self.relay_st   = sqlFmt.BaseRelayFlagFormat()

        try:
            self.h = lgpio.gpiochip_open(0) 
        except lgpio.error as e:
            logger.warning(f"GPIO 핀이 이미 사용 중입니다. 강제 해제 후 다시 시도합니다.{e}")
            self.cleanup()
            time.sleep(1)
            self.h = lgpio.gpiochip_open(0)

        for i, pin in enumerate(self.relay_gpio):
            try:
                lgpio.gpio_claim_output(self.h, pin)
                lgpio.gpio_write(self.h, pin, 0) 
                
                setattr(self.relay_st, f'relay_{i+1}_st', False)
            except lgpio.error as e:
                logger.error(f"GPIO {pin} 설정 중 오류 발생: {e}")

        logger.info("GPIO 클래스 초기화 완료")

    def __del__(self):
        self.cleanup()

    def cleanup(self):
        try:
            if hasattr(self, 'h') and self.h is not None:
                lgpio.gpiochip_close(self.h)
                self.h = None
        except Exception as e:
            logger.error(f"GPIO 핸들 닫기 중 오류 발생: {e}")

    def __output_control(self, pin, status: bool):
        lgpio.gpio_write(self.h, pin, 1 if status else 0)

    def relay_control(self, pin_no: int, status: bool):
        if pin_no < 0 or pin_no >= len(self.relay_gpio):
            logger.error(f"잘못된 릴레이 번호: {pin_no} (범위: 0-{len(self.relay_gpio)-1})")
            return

        try:
            self.__output_control(self.relay_gpio[pin_no], status)
            setattr(self.relay_st, f'relay_{pin_no+1}_st', status)
        except Exception as e:
            logger.error(f"릴레이 제어 중 오류 발생 (pin_no: {pin_no}, status: {status}): {e}")
