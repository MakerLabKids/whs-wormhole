# a controllable clock: ticks advance only when we say so (or on sleep)
_now = [1000]
def ticks_ms(): return _now[0]
def ticks_us(): return _now[0] * 1000
def ticks_diff(a, b): return a - b
def ticks_add(a, b): return a + b
def sleep(s): _now[0] += int(s * 1000)
def sleep_ms(ms): _now[0] += ms
def sleep_us(us): _now[0] += us // 1000
def time(): return 1700000000 + _now[0] // 1000
def advance(s): _now[0] += int(s * 1000)
def localtime(*a): return (2026, 10, 16, 0, 0, 0, 0, 0)
