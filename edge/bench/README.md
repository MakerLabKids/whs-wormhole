# The bench: a Pi 5 at home that is always on

Not a Burrow. It sits on the home router (Ethernet, DHCP reservation, `bench.local`) and does
three things the laptop cannot do well:

1. **A fixed iperf3 server** (port 5201). Every Burrow's throughput run can aim at it from
   school (add `"bench": "<its public route>"` to `net.targets` once a route exists), and at
   home it is the yardstick for every other box: `iperf3 -c bench.local`.
2. **A USB lab.** Picos, ESPs and Arduinos plug into the bench, not the laptop. Over ssh the
   AI (or you) can flash and talk to them: `picotool info -a`, `mpremote connect /dev/ttyACM0`,
   `esptool.py`, `arduino-cli`, `picocom -b 115200 /dev/ttyACM0`. udev rules make every board
   usable without root; `/dev/pico0`.. are symlinks to Pico serial ports. The repo is cloned
   to `~/wormhole`, so `tools/fleet/flash.py` (the desk loop) runs on the bench itself.
3. **Always reachable.** On the LAN: `ssh worm@bench.local`. From anywhere: a Cloudflare
   tunnel named `bench` with an ssh (and optional http) hostname, installed with
   `edge/burrow/install-cloudflared.sh <token>`; the AI then needs the Access service token
   (see the Zero Trust notes) to open ssh through it.

## Setup

1. Prepare a card with `edge/burrow/prep-card.sh` (user `worm`, ssh on), boot the Pi on the
   home router, wait for ssh.
2. `scp -r edge/bench worm@<ip>:` (or clone the repo) and run `sudo ./setup-bench.sh`.
   Idempotent; ~10 min the first time (picotool is built from source).
3. Reserve its address on the router; create the `bench` tunnel and run the cloudflared
   installer if you want it from outside the house.

## Why not a Burrow

A Burrow is a classroom appliance: read-only root, a room number, a Tunnel Opal to mind.
The bench is a workshop computer: writable, tools installed, boards hanging off it. Keeping
them different keeps the classroom image small and the bench free to change.
