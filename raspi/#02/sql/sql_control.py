import os
import psycopg2

from sql  import sql_config, sql_format, sql_query
from gpio import gpio_config

from log_handler import setup_logger
logger = setup_logger("sql_conftrol")
#===========================================================================================================
# 데이터베이스 데이터 관리 클래스
#===========================================================================================================
class SQLControl:
    def __init__(self, farm_id: str, house_id: str):
        self.farm_id  = farm_id
        self.house_id = house_id

        self.connection = psycopg2.connect(
            host        = sql_config.HOST,
            port        = sql_config.PORT,
            database    = sql_config.DATABASE,
            user        = sql_config.USER,
            password    = sql_config.PASSWORD
        )
        self.cursor  = self.connection.cursor()

    #---------------------------------------
    # 재배사 기초 정보 유무 확인
    #---------------------------------------
    def check_base_available(self) -> bool:
        try:
            self.cursor.execute(sql_query.SELECT_BASE_SET_VALUE_SQL, (self.farm_id, self.house_id))
            return True
        except Exception:
            return False
        
    #----------------------------
    # 릴레이 상태값 설정
    # DB 스키마는 16개 relay_*_flag 컬럼 고정. USING_RELAY_CNT(15)로 하면
    # 컬럼 1개 부족으로 IndexError. range(16) + default False로 안전 처리.
    #----------------------------
    def set_base_relay_status(self, relay_status: sql_format.BaseRelayFlagFormat, recd_date: str):
        relay_data = [getattr(relay_status, f'relay_{i+1}st_flag', False) for i in range(16)]
        self.cursor.execute(sql_query.INSERT_RELAY_STATUS_SQL, [self.farm_id, self.house_id, recd_date] + relay_data )
        self.connection.commit()

    #---------------------------------------
    # 실시간 센서 값 저장
    #---------------------------------------
    def set_auto_recd(self, data: sql_format.AutoRecdFormat):
        self.cursor.execute(sql_query.INSERT_AUTO_RECD_SQL, (
            data.farm_id, data.hous_id, data.recd_dttm, data.indr_tprt_valu, data.indr_hmdt_valu, data.oudr_tprt_valu, data.oudr_hmdt_valu, data.co2_valu, data.watr_tprt_valu, data.ligt_level_valu, data.watr_level_valu))
        self.connection.commit()

    #---------------------------------------
    # 갱신 플래그 설정
    #---------------------------------------
    def set_refresh_flag(self, flag: bool):
        self.cursor.execute(sql_query.UPDATE_REFRESH_FLAG_SQL, (flag, self.farm_id, self.house_id))
        self.connection.commit()


    #---------------------------------------
    # 갱신 플래그 확인
    #---------------------------------------
    def get_refresh_flag(self) -> bool:
        self.cursor.execute(sql_query.SELECT_REFRESH_FLAG_SQL, (self.farm_id, self.house_id))
        return self.cursor.fetchone()[0]

    #---------------------------------------
    # 센서 갱신 주기 확인
    #---------------------------------------
    def get_sensor_refresh_interval(self) -> float:
        self.cursor.execute(sql_query.SELECT_SENSOR_REFRESH_INTERVAL_SQL, (self.farm_id, self.house_id))
        return self.cursor.fetchone()[0]

    #---------------------------------------
    # 현재 릴레이 설정 값 확인
    # DB 컬럼 수(16) ≥ 실제 RELAY_GPIO 배열 크기(USING_RELAY_CNT)
    # gpio.relay_control 에서 배열 index 초과 방지를 위해 USING_RELAY_CNT 반환.
    #---------------------------------------
    def get_base_relay_status(self) -> tuple:
        self.cursor.execute(sql_query.SELECT_RELAY_STATUS_SQL, (self.farm_id, self.house_id))
        data = self.cursor.fetchone()
        if data is None:
            return sql_format.BaseRelayFlagFormat(False, False, False, False, True, True, False, False, False, False, False, False, False, False, False, False), gpio_config.USING_RELAY_CNT
        return sql_format.BaseRelayFlagFormat(*data), gpio_config.USING_RELAY_CNT

    #---------------------------------------
    # [2026-04-27] 다른 재배사의 최근 외부 온습도 평균
    # 2호 재배사는 외부 센서 부재 — 1·3호의 가장 최근 기록 평균을 차용해 저장.
    # 5분 이내 유효 데이터(oudr_tprt_valu != 0)만 평균. 데이터 없으면 (0.0, 0.0).
    #---------------------------------------
    def get_peer_outdoor_avg(self, peer_house_ids: tuple) -> tuple:
        try:
            self.cursor.execute(sql_query.SELECT_PEER_OUTDOOR_AVG_SQL,
                                (self.farm_id, list(peer_house_ids)))
            row = self.cursor.fetchone()
            self.connection.commit()
            if row and row[0] is not None and row[1] is not None:
                return float(row[0]), float(row[1])
        except Exception as e:
            try:
                self.connection.rollback()
            except Exception:
                pass
            logger.warning(f"[peer_outdoor_avg] 조회 실패: {e}")
        return 0.0, 0.0
