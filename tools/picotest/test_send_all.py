"""Short writes: micropython tools/picotest/test_send_all.py"""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import picolab


class ShortSock:
    """Takes at most 1000 bytes per send, like a busy Wi-Fi socket with a big buffer."""
    def __init__(self):
        self.got = b""

    def send(self, b):
        b = bytes(b[:1000])
        self.got += b
        return len(b)


s = ShortSock()
body = bytes(range(256)) * 97          # ~24 KB, a backfill batch
picolab._send_all(s, body)
assert s.got == body, len(s.got)


class Stalled:
    def send(self, b):
        return 0


try:
    picolab._send_all(Stalled(), b"x" * 10)
    raise AssertionError("a stalled socket must raise")
except OSError:
    pass
print("send_all OK")
