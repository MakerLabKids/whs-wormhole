"""The Bluetooth door: the same requests as the board's web page, one
line each, over the Nordic UART service (the one every BLE terminal app
and the Surface's Bluetooth page speak).

    ble = blelink.BleLink(app, data_fn)     # after picolab.WebApp()
    ...
    ble.poll()                              # every loop pass

Send "/data" and the readings come back as one JSON line. Send
"/msg?slot=1&title=Hi&l1=there&pin=1612" and the message is set exactly
as the page would set it: the line goes through WebApp.dispatch(), so the
PIN, its lockout and every route (/msg, /name, /set, /cal) are the same.
Text is URL-encoded (%20 for a space, + works too). Replies end in "\\n"
and come in notification-sized pieces; read until the newline.

The board advertises the UART service UUID and its name, so a phone can
find it with no Wi-Fi change at all. Bluetooth and Wi-Fi share the Pico
W's radio and run together.
"""
import json
import bluetooth
from micropython import const
import picolab

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_MTU_EXCHANGED = const(21)

UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_LE = bytes(reversed(bytes.fromhex("6E400001B5A3F393E0A9E50E24DCCA9E")))   # the same, little-endian, for the advert
_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY)
_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE)
LINE_MAX = 1500          # a /msg line with five full lines url-encoded is ~500 bytes
CHUNKS_PER_POLL = 6      # reply pieces sent per loop pass (the stack queues a few)


class BleLink:
  def __init__(self, app, data_fn=None, name=None):
    self.app = app
    self.data_fn = data_fn
    self.name = (name or app.name)[:26]
    self.ble = bluetooth.BLE()
    self.ble.active(True)
    try:
      self.ble.config(gap_name=self.name)      # the device name a laptop reads once connected (else "MPY BTSTACK")
    except Exception:
      pass
    self.ble.irq(self._irq)
    ((self._tx, self._rx),) = self.ble.gatts_register_services(((UART_UUID, (_TX, _RX)),))
    self.ble.gatts_set_buffer(self._rx, LINE_MAX, True)   # append mode: writes pile up until read
    self._conn = None
    self._in = bytearray()
    self._out = []
    self._mtu = 23
    self.served = 0
    self._event = None                          # "connected"/"dropped", logged from poll() (not the IRQ)
    self._advertise()
    picolab.log("Bluetooth: '%s' (the web page's requests, one line each)" % self.name)

  @property
  def connected(self):
    return self._conn is not None

  def _advertise(self):
    # advertisement: flags + the 128-bit service UUID (so a page can filter
    # on it); the name goes in the scan response, where there is room
    adv = bytes((2, 0x01, 0x06)) + bytes((17, 0x07)) + _UART_LE
    name = self.name.encode()
    resp = bytes((len(name) + 1, 0x09)) + name
    self.ble.gap_advertise(250000, adv_data=adv, resp_data=resp, connectable=True)

  def _irq(self, event, data):
    if event == _IRQ_CENTRAL_CONNECT:
      self._conn = data[0]
      self._in = bytearray()
      self._out = []
      self._event = "connected"
    elif event == _IRQ_CENTRAL_DISCONNECT:
      self._conn = None
      self._out = []
      self._event = "dropped, advertising again"
      self._advertise()
    elif event == _IRQ_GATTS_WRITE:
      if data[1] == self._rx:
        self._in += self.ble.gatts_read(self._rx)
        if len(self._in) > LINE_MAX:
          self._in = bytearray()
    elif event == _IRQ_MTU_EXCHANGED:
      self._mtu = data[1]

  def poll(self):
    """Every loop pass: answer one complete line, send a few reply pieces."""
    if self._event:
      picolab.log("Bluetooth:", self._event)
      self._event = None
    if b"\n" in self._in:
      line, _, rest = bytes(self._in).partition(b"\n")
      self._in = bytearray(rest)
      line = line.strip()
      if line:
        self._answer(line)
    self._send_some()

  def _answer(self, line):
    self.served += 1
    path = line.split(b"?", 1)[0]
    if path == b"/data":
      try:
        d = self.data_fn() if self.data_fn else {}
        ident = self.app.identity()
        for k in ident:
          if k not in d:
            d[k] = ident[k]
      except Exception as e:
        d = {"error": str(e)}
      obj = d
    else:
      status, obj = self.app.dispatch(b"GET " + line + b" HTTP/1.0\r\nX-Via: ble\r\n")
      if status is None:
        obj = {"error": "unknown request", "try": ["/data", "/msg", "/name"] + [p for p, _ in (self.app.routes or [])]}
    self._queue(json.dumps(obj) + "\n")

  def _queue(self, text):
    data = text.encode("utf-8")
    n = max(20, self._mtu - 3)
    for i in range(0, len(data), n):
      self._out.append(data[i:i + n])

  def _send_some(self):
    sent = 0
    while self._out and self._conn is not None and sent < CHUNKS_PER_POLL:
      try:
        self.ble.gatts_notify(self._conn, self._tx, self._out[0])
      except OSError:
        return                                  # the stack's queue is full: next pass
      self._out.pop(0)
      sent += 1

  def close(self):
    try:
      self.ble.active(False)
    except Exception:
      pass
