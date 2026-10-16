# picotest: run the Pico firmware on your laptop

`lib/picolab.py` carries the fleet behaviour (Wi-Fi ladder state machine, push
loop, RAM history ring). This harness runs it under the MicroPython **unix
port** with stub `machine`/`network` modules and a fake clock, talking to a real
Burrow on 127.0.0.1:8211, and walks the whole story: boot + join, first push,
`/data` and `/history`, network loss, hotspot after 60 s, rescan, rejoin,
hotspot close after 10 stable minutes, and the `wormmaster` rescue ladder.

```
sudo apt-get install micropython        # the unix port, any recent version
tools/picotest/run.sh
```

Expected: 17 PASS lines and `17 checks, 0 failed`. The stubs are tiny on
purpose; they model exactly what the firmware touches (scan, connect,
isconnected, ifconfig, status('rssi'), AP config). Real radios are, of
course, the real test; this catches logic errors before you walk to a bin.
