#
# Project page (docs, wiring, install link): https://github.com/MakerLabKids/wormhole/tree/main/projects/distance-station
import gc
import json
import random
import socket
import time
from machine import I2C, Pin
import network

# ---------------------------------------------------------------------
# 1. Hardware Setup (400kHz Fast-Mode I2C)
# ---------------------------------------------------------------------
i2c = I2C(0, sda=Pin(0), scl=Pin(1), freq=400000)

oled = None
tof = None

try:
  import ssd1306

  oled = ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3C)

  # Clear display RAM snow and wake charge pump
  oled.poweroff()
  time.sleep_ms(50)
  oled.poweron()
  time.sleep_ms(50)

  oled.fill(0)
  oled.text("Pico 2 W Init", 0, 0)
  oled.show()
  print("OLED initialized successfully.")
except Exception as e:
  print("OLED init error:", e)

try:
  from vl53l0x import VL53L0X

  tof = VL53L0X(i2c, address=0x29)
  print("ToF initialized successfully.")
except Exception as e:
  print("ToF init error:", e)

CALIBRATION_MAP = [
    (0.0, 0.0),
    (132.9, 50.0),
    (180.3, 100.0),
    (287.3, 200.0),
    (378.3, 280.0),
    (398.9, 300.0),
    (426.4, 330.0),
    (451.4, 350.0),
    (488.2, 400.0),
    (551.2, 450.0),
    (600.9, 500.0),
    (655.6, 550.0),
    (702.8, 600.0),
    (756.9, 650.0),
    (808.0, 700.0),
    (864.1, 750.0),
    (920.3, 800.0),
    (971.5, 850.0),
    (1019.1, 900.0),
    (1092.4, 1000.0),
    (2000.0, 2000.0),
]


def calibrate_distance(raw):
  if raw <= CALIBRATION_MAP[0][0]:
    return CALIBRATION_MAP[0][1]
  if raw >= CALIBRATION_MAP[-1][0]:
    return CALIBRATION_MAP[-1][1]
  for i in range(len(CALIBRATION_MAP) - 1):
    x0, y0 = CALIBRATION_MAP[i]
    x1, y1 = CALIBRATION_MAP[i + 1]
    if x0 <= raw <= x1:
      return y0 + ((y1 - y0) / (x1 - x0)) * (raw - x0)
  return raw


def get_reading():
  if not tof:
    return -1
  try:
    v = tof.ping()
    if 35 < v < 2000:
      return int(calibrate_distance(v))
  except Exception:
    pass
  return 0


# ---------------------------------------------------------------------
# 2. Station Identification (Banning 1-9, 67, 158)
# ---------------------------------------------------------------------
NODE_ID_FILE = "node_id.txt"
BANNED_IDS = set(range(1, 10)).union({67, 158})


def load_node_id():
  try:
    with open(NODE_ID_FILE, "r") as f:
      val = int(f.read().strip())
      return val if val not in BANNED_IDS else None
  except Exception:
    return None


def save_node_id(node_id):
  try:
    with open(NODE_ID_FILE, "w") as f:
      f.write(str(node_id))
  except Exception:
    pass


saved_id = load_node_id()
if saved_id:
  node_id = saved_id
else:
  node_id = random.choice(list(set(range(10, 254)) - BANNED_IDS))
  save_node_id(node_id)

ssid_name = "PicoLab" + str(node_id)

# ---------------------------------------------------------------------
# 3. Access Point Setup
# ---------------------------------------------------------------------
ap = network.WLAN(network.AP_IF)
ap.active(True)
ap.ifconfig(("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1"))
ap.config(essid=ssid_name, security=0)

while not ap.active():
  time.sleep(0.1)

if oled:
  try:
    oled.fill(0)
    oled.text("SSID: " + ssid_name, 0, 0)
    oled.text("IP: 192.168.4.1", 0, 12)
    oled.hline(0, 24, 128, 1)
    oled.show()
  except Exception as e:
    print("Initial OLED frame error:", e)

# ---------------------------------------------------------------------
# 4. Socket Listener & Main Loop
# ---------------------------------------------------------------------
HEADER_HTML = b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n"
HEADER_JSON = b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n"

server = None


def init_server():
  # Re-running the program can leave the OLD web socket holding port 80
  # (a soft reset does not free network sockets). Retry with a growing
  # wait, and if it truly will not bind, DO NOT crash: keep running with
  # the screen and the distance sensor. A dead screen is never worth an
  # unbindable port. (This is the bug that took a class's displays down.)
  global server
  addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
  for attempt in range(6):
    try:
      server = socket.socket()
      server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      server.bind(addr)
      server.listen(2)
      server.settimeout(0.05)
      return
    except OSError as e:
      try:
        server.close()
      except Exception:
        pass
      server = None
      if e.errno != 98:
        print("Web server error:", e, "- running without the web page.")
        return
      gc.collect()
      print("Port 80 busy, recycling Wi-Fi (try %d)..." % (attempt + 1))
      try:
        ap.active(False)
        time.sleep(0.5)
        ap.active(True)
        ap.ifconfig(("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1"))
        ap.config(essid=ssid_name, security=0)
      except Exception:
        pass
      time.sleep(1 + attempt)
  print("Port 80 stayed busy - running WITHOUT the web page (screen + sensor still work).")
  server = None


init_server()

print("\n" + "=" * 40)
print("Pico 2 W Active!")
print("SSID:       " + ssid_name)
print("Dashboard:  http://192.168.4.1")
print("=" * 40)

cached_dist = 0

try:
  while True:
    # 1. Read Distance
    cached_dist = get_reading()

    # 2. Update Display
    if oled:
      try:
        oled.fill_rect(0, 28, 128, 36, 0)
        oled.text("Distance:", 0, 30)
        oled.text(
            "ERR" if cached_dist == -1 else str(cached_dist) + " mm", 20, 44
        )
        bar_w = (
            0
            if cached_dist == -1
            else min(128, max(0, int((cached_dist / 1000.0) * 128)))
        )
        oled.fill_rect(0, 58, bar_w, 4, 1)
        oled.show()
      except Exception:
        pass

    # 3. Handle Network Traffic (skip if the web page never opened)
    if not server:
      gc.collect()
      continue
    try:
      cl, client_addr = server.accept()
      cl.settimeout(0.5)

      req = b""
      try:
        req = cl.recv(512)
      except Exception:
        pass

      # Route: /data endpoint
      if b"/data" in req:
        payload = json.dumps({"dist": cached_dist}).encode("utf-8")
        cl.sendall(HEADER_JSON + payload)

      # Route: / dashboard
      else:
        cl.sendall(HEADER_HTML)
        try:
          with open("index.html", "rb") as f:
            while True:
              chunk = f.read(512)
              if not chunk:
                break
              cl.sendall(chunk)
        except Exception:
          cl.sendall(b"<h1>404: File Not Found</h1>")

      cl.close()

    except OSError:
      pass

    gc.collect()

finally:
  if server:
    server.close()
    print("Socket cleanly closed.")
