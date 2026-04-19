import smbus2 as smbus
import glob

# BME280 온도/습도/기압 센서 I2C 설정
I2C_ADDRESS        = 0x76
I2C_BME280_ADDRESS = I2C_ADDRESS  # sensor_control.py 참조 호환 (#01 동일 네이밍)
I2C_BUS            = smbus.SMBus(1)

# MH-Z19B CO2 센서 설정
# Raspberry Pi에서 사용 가능한 시리얼 포트 목록 (우선순위 순서)
SERIAL_PORT_CANDIDATES = ["/dev/ttyAMA0", "/dev/serial0", "/dev/ttyS0", "/dev/ttyUSB0"]
SERIAL_PORT = "/dev/ttyAMA0"  # raspi_02 실제 포트 (/dev/ttyS0은 부재)
BAUD_RATE = 9600

# DS18B20 수온 센서 1-Wire 설정
BASE_PATH = '/sys/bus/w1/devices/'
DEVICE_FOLDERS = glob.glob(BASE_PATH + '28*')  # 연결된 모든 DS18B20 센서 가져오기
DEVICE_FILES = [device_folder + '/w1_slave' for device_folder in DEVICE_FOLDERS]
