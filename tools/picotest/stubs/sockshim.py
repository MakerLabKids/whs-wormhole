# The unix port's socket lacks sendall (the rp2 port has it). Wrap it.
import sys
import socket as _real

class _Sock:
    def __init__(self, *a, **k):
        self._s = k.pop("_wrap", None) or _real.socket(*a, **k)
    def __getattr__(self, n):
        return getattr(self._s, n)
    def sendall(self, b):
        mv = memoryview(b)
        while len(mv):
            n = self._s.send(mv)
            mv = mv[n:]
    def accept(self):
        c, a = self._s.accept()
        return _Sock(_wrap=c), a

class SockMod:
    socket = _Sock
    getaddrinfo = _real.getaddrinfo
    SOL_SOCKET = _real.SOL_SOCKET
    SO_REUSEADDR = _real.SO_REUSEADDR
    AF_INET = _real.AF_INET
    SOCK_STREAM = _real.SOCK_STREAM

sys.modules["socket"] = SockMod
