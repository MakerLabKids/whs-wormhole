# Install day (first school deployment)

What to carry: the Portal + burrow0, three Tunnels + burrow1-3 (each Pi on its own-numbered
Opal: 431 = Tunnel 1, 33a1 = Tunnel 2, f35 = Tunnel 3), one 27 W supply per Pi, the laptop
with one Ethernet cable, a phone logged in to whs.makerlabkids.com, the ntfy app subscribed
to the alert topic.

## 1. Before leaving home (5 min)

    tools/fleet/site_check.py --site home        # everything green at home first

## 2. Portal + burrow0 in the worm room (10 min)

Power the Portal and burrow0 (cabled to the Portal). The Portal must join BYLD: burrow0's
watchdog does this on its own within 2 min (it dials the list: Q-tastic, BYLD, Loki, Guess).
On the phone: whs.makerlabkids.com/signal/0 shows the Portal's BYLD signal twice a second.
Walk the Portal around: the number you want is -65 dBm or better; red (-72) means move it.
Then whs.makerlabkids.com/admin (Devices): burrow0 must say cloud ok, clock ntp, Opal ok via
BYLD. If cloud stays down: the school is blocking something; `site_check.py` names what
(captive portal, TLS, NTP: see "what could go wrong" below).

## 3. Each Tunnel + its Pi (5 min each)

Power the Tunnel and its Pi in the classroom. The Tunnel joins WormHole-Core on its own
(the backhaul); whs.makerlabkids.com/signal/N shows that hop's signal while you carry it.
Green or yellow = fine. If it stays red or it falls back to BYLD (Devices page says
"via BYLD"), the hop does not reach: move the Tunnel or the Portal, or accept the fallback.
Devices page: the Tunnel's card goes green and, 15 min later, shows measured throughput.

## 4. The all-up test (2 min, laptop cabled to any Opal)

    tools/fleet/site_check.py --site school --lan --measure

Every row PASS. WARN rows are judgement calls (signal, a slow link); FAIL rows are work.

## 5. Bins

Flash/power the Picos; the wall at whs.makerlabkids.com groups them by period. A bin that
joins the wrong room's Tunnel still shows under its period, with the Burrow it came
through in small print. Pull a bin's lid: the live 1/s view on its page shows the surface
distance change within a second.

## What could go wrong, in the order it is likely

- School Wi-Fi has client isolation: fine for us (only the Portal is a client of it).
- The school blocks UDP 443 (QUIC): cloudflared is pinned to HTTP/2, no effect.
- NTP blocked: clocks step from the cloud; `clock free` on the Devices page for a few minutes
  after boot is normal, hours is not.
- A content filter intercepting TLS: cloud uploads fail with a certificate error; the Burrow
  flags `captive`. Nothing to do but ask IT for an exception for whs.makerlabkids.com.
- Rogue-AP containment: Picos drop off every few minutes with no pattern. Tell IT the four
  boxes are yours before they find them.
- A Pi that reboots on its own: power. Every Pi on its own 27 W supply, nothing else on it.
- No alerts arriving: `npx wrangler secret put ALERT_URL` was never run, or the phone is not
  subscribed to that topic. The Devices page says "notifier configured" when it is.

## If a Burrow goes silent

Within 3 minutes the phone gets "burrowN silent" and the Devices page shows the open alert.
Its last events (quiet bins, Opal joins, reboots) are on the same page, pushed the moment they
happened, so the story of what went wrong is already in the cloud when you look.
