# ═══════════════════════════════════════════════════════════════════════
# I2C LCD (PCF8574 백팩 + HD44780 호환) 제어 모듈.
# 매 sensor read 사이클마다 jayeondeule.py 가 update() 호출 → LCD 갱신.
# 하드웨어가 없거나 init 실패하면 self.lcd=None 으로 두고 update 는 no-op 처리해
# 다른 호스트(LCD 미장착)에 동일 코드 배포되어도 영향 없음.
# --->
# LCDControl: 초기화 + sensor readings → 4줄(또는 2줄) 포맷 + I2C 쓰기
# update: 매 read 사이클 호출 — auto_record_data 의 시멘틱 필드 6종 표시
# close: GPIO/I2C cleanup (서비스 종료 시)
# ═══════════════════════════════════════════════════════════════════════
import os
import threading
import time
from datetime import datetime

try:
    from RPLCD.i2c import CharLCD
except Exception:
    CharLCD = None

from log_handler import setup_logger
logger = setup_logger("lcd_control")


# ══════════════════
# 환경설정 (env 로 override 가능)
# ══════════════════
LCD_I2C_ADDR = int(os.environ.get("LCD_I2C_ADDR", "0x27"), 0)
LCD_I2C_PORT = int(os.environ.get("LCD_I2C_PORT", "1"))
LCD_COLS     = int(os.environ.get("LCD_COLS", "20"))
LCD_ROWS     = int(os.environ.get("LCD_ROWS", "4"))

# 인사말 marquee — 환경변수로 override 가능. HD44780 기본 CGROM 은 ASCII+
# 한자/카타카나(A02 ROM) 만 지원해 한글이 깨질 수 있음 → 깨지면 로마자/영문으로 변경.
LCD_GREETING       = os.environ.get("LCD_GREETING", "안녕하세요.")
LCD_MARQUEE_DELAY  = float(os.environ.get("LCD_MARQUEE_DELAY", "0.3"))   # 초/문자


class LCDControl:
    def __init__(self, addr=LCD_I2C_ADDR, port=LCD_I2C_PORT,
                 cols=LCD_COLS, rows=LCD_ROWS, greeting=LCD_GREETING):
        self.cols = cols
        self.rows = rows
        self._lock = threading.Lock()
        self._update_failed_logged = False
        self.lcd = None

        # marquee — row 0 에 인사말을 좌→우로 흐르게 표시. 시각 갭(2칸)을 두어
        # 텍스트가 한 화면을 다 지나가면 다시 등장하는 회전 버퍼 형태.
        self._greeting = greeting + "  "
        self._marquee_idx = 0
        self._marquee_thread = None
        self._marquee_stop = threading.Event()

        if CharLCD is None:
            logger.warning("[LCD] RPLCD 미설치 — 표시 비활성")
            return
        try:
            self.lcd = CharLCD(
                i2c_expander='PCF8574',
                address=addr,
                port=port,
                cols=cols,
                rows=rows,
                auto_linebreaks=False,
            )
            self.lcd.clear()
            self.lcd.write_string("Jayeondeule")
            self.lcd.crlf()
            self.lcd.write_string("Starting...")
            logger.info(f"[LCD] 초기화 성공 ({cols}x{rows} @ 0x{addr:02X})")
            # marquee 백그라운드 스레드 시작 — daemon 으로 메인 종료 시 자동 정리
            self._marquee_thread = threading.Thread(target=self._marquee_loop,
                                                     daemon=True)
            self._marquee_thread.start()
        except Exception as e:
            logger.warning(f"[LCD] 초기화 실패 (LCD 표시 비활성): {e}")
            self.lcd = None

    # ─────────────────────────────────────────────────────────────────
    # marquee 루프 — row 0 에 LCD_MARQUEE_DELAY 간격으로 한 칸씩 좌측 스크롤.
    # update() 의 sensor 행 갱신과는 row 가 달라 충돌 없으나 동일 LCD 객체를
    # 공유하므로 self._lock 으로 직렬화. RPLCD 의 write_string 는 입력 문자열을
    # 내부 charmap 에 따라 1바이트씩 보내므로 한글/UTF-8 은 깨질 수 있음 — 이 경우
    # LCD_GREETING 환경변수로 ASCII 텍스트 지정 권장.
    # ─────────────────────────────────────────────────────────────────
    def _marquee_loop(self):
        # 회전 버퍼 — 길이 = greeting + cols 만큼 padding (스무스 진입/퇴출)
        text = self._greeting + (' ' * self.cols)
        n = len(text)
        while not self._marquee_stop.is_set():
            try:
                # cols 길이 윈도우 — 인덱스가 끝을 넘으면 모듈러로 회전
                window = ''
                for j in range(self.cols):
                    window += text[(self._marquee_idx + j) % n]
                with self._lock:
                    if self.lcd is None:
                        return
                    self.lcd.cursor_pos = (0, 0)
                    self.lcd.write_string(window)
                self._marquee_idx = (self._marquee_idx + 1) % n
            except Exception:
                pass
            self._marquee_stop.wait(LCD_MARQUEE_DELAY)

    # ─────────────────────────────────────────────────────────────────
    # auto_record_data → sensor 행 포맷. row 0 은 marquee 가 점유하므로
    # 이 함수는 row 1 부터 채울 텍스트만 반환 (rows-1 줄). 16x2 환경에서는
    # row 1 한 줄만 가시.
    # ─────────────────────────────────────────────────────────────────
    def _format_sensor_lines(self, rec):
        if rec is None:
            return ["No sensor data".ljust(self.cols)[:self.cols]]
        farm = getattr(rec, 'farm_id', '') or '-'
        house = getattr(rec, 'hous_id', '') or '-'
        now = datetime.now().strftime("%H:%M:%S")
        in_t  = self._fmt_num(getattr(rec, 'indr_tprt_valu', None))
        in_h  = self._fmt_int(getattr(rec, 'indr_hmdt_valu', None))
        out_t = self._fmt_num(getattr(rec, 'oudr_tprt_valu', None))
        out_h = self._fmt_int(getattr(rec, 'oudr_hmdt_valu', None))
        co2   = self._fmt_int(getattr(rec, 'co2_valu', None))
        wt    = self._fmt_num(getattr(rec, 'watr_tprt_valu', None))

        if self.rows >= 4 and self.cols >= 20:
            # row 1: farm/house + 시각, row 2: 실내, row 3: 실외+수온/CO2
            return [
                f"{farm}-{house:<3} {now}".ljust(self.cols)[:self.cols],
                f"In  T{in_t}C H{in_h}%".ljust(self.cols)[:self.cols],
                f"WT{wt}C CO2{co2} O{out_t}".ljust(self.cols)[:self.cols],
            ]
        # 16x2 (또는 그 외) — row 1 한 줄에 압축
        return [
            f"T{in_t}H{in_h} W{wt} {co2}".ljust(self.cols)[:self.cols],
        ]

    @staticmethod
    def _fmt_num(v, default='-'):
        try:
            return f"{float(v):4.1f}"
        except Exception:
            return default

    @staticmethod
    def _fmt_int(v, default='-'):
        try:
            return f"{int(float(v)):>3d}"
        except Exception:
            return default

    # ─────────────────────────────────────────────────────────────────
    # 매 sensor 사이클 호출. row 0 은 marquee 가 점유하므로 row 1 부터 갱신.
    # 실패 시 1회만 경고 로깅 → 스팸 방지.
    # ─────────────────────────────────────────────────────────────────
    def update(self, auto_record_data):
        if self.lcd is None:
            return
        lines = self._format_sensor_lines(auto_record_data)
        with self._lock:
            try:
                for i, text in enumerate(lines):
                    row = i + 1   # row 0 은 marquee 전용
                    if row >= self.rows:
                        break
                    self.lcd.cursor_pos = (row, 0)
                    self.lcd.write_string(text)
                self._update_failed_logged = False
            except Exception as e:
                if not self._update_failed_logged:
                    logger.warning(f"[LCD] 갱신 실패 (이후 반복 경고 억제): {e}")
                    self._update_failed_logged = True

    def close(self):
        # marquee 스레드 종료 신호
        self._marquee_stop.set()
        if self._marquee_thread is not None:
            try:
                self._marquee_thread.join(timeout=1.0)
            except Exception:
                pass
        if self.lcd:
            try:
                self.lcd.close(clear=True)
            except Exception:
                pass
            self.lcd = None
