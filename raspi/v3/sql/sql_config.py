#--------------------------------
# 데이터베이스 접속 정보
#--------------------------------
HOST     = 'lockers7.iptime.org'
PORT     = 5432
DATABASE = 'jayeondeule'
USER     = 'postgres'
PASSWORD = 'Wkdusemfdp1@'

#----------------------------
# 데이터베이스 접속 시도 회수
#----------------------------
RETRY_ATTEMPTS = 5  # DB 연결 재시도 횟수
RETRY_DELAY    = 5  # 각 재시도 사이의 대기 시간(초)

#----------------------------
# 관수밸브, 조명 설정 키
#----------------------------
TYPE_WATER = "water"
TYPE_LIGHT = "light"