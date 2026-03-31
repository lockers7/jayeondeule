# 데이터베이스 연결 설정
#HOST     = 'ls-7aecc123e3bf8919e49267daf67221af47437c1b.czi2sqs4ipr3.ap-northeast-2.rds.amazonaws.com'
#PORT     = 5432
#DATABASE = 'jayeondeule'
#USER     = 'dbmasteruser'
#PASSWORD = ',9qUjfT~JXoG_DLDSD}*TJ+#nB0EWn3g'

HOST     = 'lockers7.iptime.org'
PORT     = 5432
DATABASE = 'jayeondeule'
USER     = 'postgres'
PASSWORD = 'Wkdusemfdp1@'

# 재시도 설정
RETRY_ATTEMPTS = 5  # DB 연결 재시도 횟수
RETRY_DELAY    = 5  # 각 재시도 사이의 대기 시간(초)
