"""A fake `bluetooth` module for the unix port: enough of the BLE class
for lib/blelink.py (register services, advertise, writes from a fake
central, notifies collected). `ble.central_writes(handle, data)` plays a
phone writing; `ble.notified` is what it would have received."""
FLAG_READ = 0x0002
FLAG_WRITE_NO_RESPONSE = 0x0004
FLAG_WRITE = 0x0008
FLAG_NOTIFY = 0x0010


class UUID:
  def __init__(self, v):
    self.v = v
  def __bytes__(self):
    if isinstance(self.v, int):
      return bytes((self.v & 0xff, self.v >> 8))
    h = self.v.replace("-", "")
    return bytes(int(h[i:i + 2], 16) for i in range(0, 32, 2))[::-1]
  def __repr__(self):
    return "UUID(%r)" % self.v


class BLE:
  _last = None

  def __init__(self):
    BLE._last = self
    self._active = False
    self._irq = None
    self._bufs = {}
    self._append = {}
    self.adv = None
    self.notified = []
    self.notify_fail = 0            # OSError the next n notifies (a full queue)

  def active(self, on=None):
    if on is not None:
      self._active = bool(on)
    return self._active

  def irq(self, fn):
    self._irq = fn

  def config(self, *a, **kw):
    return (0, b"\x00" * 6)

  def gatts_register_services(self, services):
    out, h = [], 16
    for _, chars in services:
      hs = []
      for _ in chars:
        self._bufs[h] = b""
        hs.append(h)
        h += 2
      out.append(tuple(hs))
    return tuple(out)

  def gatts_set_buffer(self, handle, size, append=False):
    self._append[handle] = append

  def gatts_read(self, handle):
    v = self._bufs.get(handle, b"")
    if self._append.get(handle):
      self._bufs[handle] = b""
    return v

  def gatts_write(self, handle, data):
    self._bufs[handle] = bytes(data)

  def gatts_notify(self, conn, handle, data=None):
    if self.notify_fail:
      self.notify_fail -= 1
      raise OSError(12)
    self.notified.append(bytes(data))

  def gap_advertise(self, interval_us, adv_data=None, resp_data=None, connectable=True):
    self.adv = (interval_us, bytes(adv_data) if adv_data else None, bytes(resp_data) if resp_data else None)

  # ---- the fake phone -------------------------------------------------
  def connect(self, conn=1):
    self._irq(1, (conn, 0, b""))

  def disconnect(self, conn=1):
    self._irq(2, (conn, 0, b""))

  def central_writes(self, handle, data, conn=1):
    if self._append.get(handle):
      self._bufs[handle] = self._bufs.get(handle, b"") + bytes(data)
    else:
      self._bufs[handle] = bytes(data)
    self._irq(3, (conn, handle))

  def received(self):
    """Everything notified so far, joined."""
    return b"".join(self.notified)
