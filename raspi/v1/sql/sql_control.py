import psycopg2

from .    import sql_config, sql_format, sql_query
from gpio import gpio_config as gpioCfg

from log_handler import setup_logger
logger = setup_logger("sql_control")

class SQLControl:
    def __init__(self, farm_id: str):
        self.farm_id = farm_id
        self.connection = psycopg2.connect(
            host        = sql_config.HOST,
            port        = sql_config.PORT,
            user        = sql_config.USER,
            password    = sql_config.PASSWORD,
            database    = sql_config.DATABASE
        )
        self.cursor  = self.connection.cursor()

    # 재배동 사용 가능 여부 확인
    def check_base_available(self) -> bool:
        try:
            self.cursor.execute(sql_query.SELECT_BASE_SET_VALUE_SQL, (self.farm_id, 2))
            result = self.cursor.fetchone()
            if result is None:
                logger.warning(f"farm_id={self.farm_id}, hous_id=2에 대한 센서 설정 데이터가 없습니다")
                return False
            return True
        except Exception as e:
            logger.error(f"check_base_available 오류: {e}")
            return False

    # 릴레이 상태 설정
    def set_base_relay_st(self, relay_st: sql_format.BaseRelayFlagFormat, recd_date: str):
        # 15개 릴레이 데이터 수집
        relay_data = [getattr(relay_st, f'relay_{i+1}_st') for i in range(gpioCfg.USING_RELAY_CNT)]
        # relay_16st_flag 추가 (항상 False)
        relay_data.append(False)
        # farm_id, recd_date 추가
        self.cursor.execute(sql_query.INSERT_RELAY_STATUS_SQL, relay_data + [self.farm_id, recd_date])
        self.connection.commit()

    # 센서 및 릴레이 기록 데이터 삽입
    def set_auto_recd(self, data: sql_format.AutoRecdFormat):
        self.cursor.execute(sql_query.INSERT_AUTO_RECD_SQL, (
            data.farm_id, data.recd_date, data.htemp_val, data.humi_val, data.co2_val, data.wtemp_val, data.outdoor_temp_val, data.outdoor_humi_val))
        self.connection.commit()

    # 갱신 플래그 설정
    def set_refresh_flag(self, flag: bool):
        self.cursor.execute(sql_query.UPDATE_REFRESH_FLAG_SQL, (flag, self.farm_id, 2))
        self.connection.commit()

    # 갱신 플래그 확인
    def get_refresh_flag(self) -> bool:
        self.cursor.execute(sql_query.SELECT_REFRESH_FLAG_SQL, (self.farm_id, 2))
        # return self.cursor.fetchone()[0]
        row = self.cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 3    

    # 센서 갱신 주기 가져오기
    def get_sensor_refresh_interval(self) -> int:
        self.cursor.execute(sql_query.SELECT_SENSOR_REFRESH_INTERVAL_SQL, (self.farm_id, 2))
        # return self.cursor.fetchone()[0]
        row = self.cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 2

    # 기준 온도/습도/CO2 설정값 가져오기
    def get_base_setting_val(self) -> sql_format.BaseSetFormat:
        self.cursor.execute(sql_query.SELECT_BASE_SET_VALUE_SQL, (self.farm_id, 2))
        return sql_format.BaseSetFormat(*self.cursor.fetchone())

    # 외부 온도 습도 센서값 가져오기
    def get_outdoor_sensor_val(self) -> sql_format.BaseSetFormat:
        self.cursor.execute(sql_query.SELECT_OUTDOOR_SENSOR)
        return sql_format.OutdoorSensor(*self.cursor.fetchone())

    # 조명 설정 시간대 가져오기
    def get_lght_set(self) -> list:
        self.cursor.execute(sql_query.SELECT_LGHT_SET_VALUE_SQL, (self.farm_id, 'light'))
        return [sql_format.LghtSetFormat(*row) for row in self.cursor.fetchall()]

    # 급수 설정 시간대 가져오기
    def get_watr_set(self) -> list:
        self.cursor.execute(sql_query.SELECT_WATR_SET_VALUE_SQL, (self.farm_id, 'water'))
        return [sql_format.WatrSetFormat(*row) for row in self.cursor.fetchall()]

    # 릴레이 수동 제어 플래그 확인
    def get_base_relay_manual_control_flag(self) -> bool:
        self.cursor.execute(sql_query.SELECT_RELAY_MANUAL_CONTROL_FLAG_SQL, (self.farm_id, 2))
        return self.cursor.fetchone()[0]

    # 릴레이 상태 가져오기
    def get_base_relay_st(self) -> tuple:
        try:
            self.cursor.execute(sql_query.SELECT_RELAY_STATUS_SQL, (self.farm_id, 2))
            data = self.cursor.fetchone()
            
            if data is None:
                logger.warning(f"Farm ID {self.farm_id}의 릴레이 상태 데이터가 없음. 기본값으로 초기화")
                default_relay_st = sql_format.BaseRelayFlagFormat(*([False] * gpioCfg.USING_RELAY_CNT))
                return default_relay_st, gpioCfg.USING_RELAY_CNT
            
            if len(data) != gpioCfg.USING_RELAY_CNT:
                logger.warning(f"릴레이 데이터 길이 불일치: DB={len(data)}, 설정={gpioCfg.USING_RELAY_CNT}")
            
            return sql_format.BaseRelayFlagFormat(*data), len(data)
            
        except Exception as e:
            logger.error(f"릴레이 상태 조회 중 오류: {e}")
            default_relay_st = sql_format.BaseRelayFlagFormat(*([False] * gpioCfg.USING_RELAY_CNT))
            return default_relay_st, gpioCfg.USING_RELAY_CNT

    # 수온 1도 올리기 위해 소요되는 분 계산
    def get_gap_time_water_to_hot_1do(self, relay1st: bool, relay2st: bool) -> int:
        self.cursor.execute(sql_query.SELECT_GAP_WATER_1_UP_WITH_CHILLER, (self.farm_id, relay1st, relay2st))
        return self.cursor.fetchone()[0]