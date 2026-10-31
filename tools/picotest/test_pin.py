"""The board PIN rule: micropython tools/picotest/test_pin.py"""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
from picolab import pin_for

assert pin_for("The Wrigglers", "192.168.4.16") == "924", pin_for("The Wrigglers", "192.168.4.16")   # h=8+1, r=18+6
assert pin_for("Dirt Nerds", "192.168.81.7") == "1611"       # i=9+7, d=4+7 (a one-digit octet: same digit twice)
assert pin_for("Dirt Nerds", "192.168.4.1") == "105"         # the hotspot address
assert pin_for("PicoLab742", "10.0.0.120") == "101"          # digits in the name do not count: i=9+1, a=1+0
assert pin_for("Compost Cowboys", "192.168.81.203") == "1728"  # o=15+2, y=25+3
assert pin_for("A", "192.168.4.1") == "22"                   # one letter: used twice
assert pin_for("Zz", "10.0.0.99") == "3535"                  # the longest a PIN gets
assert pin_for("Bo-Peep 3", "192.168.4.1") == "166"          # o=15+1, e=5+1: punctuation and digits skipped
assert pin_for("", "192.168.4.1") == "22"                    # no letters at all: 'a' twice
print("pin OK")
