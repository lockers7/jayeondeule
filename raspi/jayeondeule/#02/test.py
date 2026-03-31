import adafruit_sht4x
import board
import busio

i2c = busio.I2C(board.SCL, board.SDA)  # GPIO3 (SDA), GPIO5 (SCL)
sensor = adafruit_sht4x.SHT4x(i2c)
print("Serial number:", sensor.serial_number)