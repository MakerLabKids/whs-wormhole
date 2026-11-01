"""Where a Bin pushes: micropython tools/picotest/test_edges.py"""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import picolab
c = picolab._edge_candidates("192.168.82.38")
assert c == ["192.168.82.10:8080", "192.168.80.10:8080", "192.168.80.21:8080", "192.168.80.22:8080", "192.168.80.23:8080"], c
c = picolab._edge_candidates("192.168.80.38")                      # on the Portal's own network: burrow0 is the local one
assert c == ["192.168.80.10:8080", "192.168.80.21:8080", "192.168.80.22:8080", "192.168.80.23:8080"], c
assert picolab._edge_candidates("10.0.0.5", ["127.0.0.1:8211"]) == ["127.0.0.1:8211"]
print("edges OK")
