# Router tools — GL.iNet 4.x (GL-SFT1200 "Opal")

`glinet.py` talks to the stock admin API at `http://<router>/rpc`. No SSH, no LuCI.

    GLINET_PASSWORD='...' tools/routers/glinet.py status
    GLINET_PASSWORD='...' tools/routers/glinet.py call wifi get_config
    GLINET_PASSWORD='...' tools/routers/glinet.py call clients get_list

Password comes from `GLINET_PASSWORD` or a `.env` key (`router_admin` by default);
it is never put in a URL. See the login algorithm in `glinet.py` (proven against a
captured 4.8.3 handshake in `test_glinet.py`).

## Facts discovered against a real GL-SFT1200 on firmware 4.8.3

Login handshake (`alg` 5, `hash-method` sha256):

    cipher = crypt(password, "$<alg>$<salt>$")           # $5$ = sha256-crypt
    hash   = sha256("root:" + cipher + ":" + nonce)

JSON-RPC errors come back either as a JSON `error` object (HTTP 200) **or** as a
bare nginx **HTTP 500** page when the ubus call rejects the params — the client
parses both. "Method not found" is code -32601.

Useful read methods (object, method):

    system get_info        system get_status      wifi get_config
    wifi get_status        clients get_list        repeater get_config / get_status

### Setting the 2.4 GHz SSID (the classroom "WormHole")

`wifi set_config` wants this exact shape (captured from the panel). The gotcha is
`iface_name` (not `name`) plus `device`/`hwmode`/`htmode`; a wrong key is an HTTP 500.

    call wifi set_config {
      "iface_name": "default_radio0",   # 2.4 GHz main radio (radio0)
      "device":     "radio0",
      "ssid":       "WormHole",
      "key":        "supersecret",
      "encryption": "psk2",             # WPA2-PSK, what the Pico W wants
      "hidden":     false,
      "hwmode":     "11g/n",
      "htmode":     "HT20",             # 20 MHz; "auto" lets the router choose
      "channel":    1,                  # 0 = auto; room 1/2/3 => ch 1/6/11
      "txpower":    "Max",
      "random_bssid": false
    }

Result `[]` means success. The 5 GHz main radio is `default_radio1` / `radio1`; its
`hwmode` is `11a/n/ac`, `htmode` is `80` (80 MHz), channel 36 or 149 (fixed, non-DFS —
the Opal does not hold DFS "auto"). Example, the hub's backhaul:

    call wifi set_config {
      "iface_name":"default_radio1","device":"radio1",
      "ssid":"WormHole-Core","key":"<backhaul>","encryption":"psk2","hidden":false,
      "hwmode":"11a/n/ac","htmode":"80","channel":36,"txpower":"Max","random_bssid":false
    }

Still to capture (schemas not yet reverse-engineered): LAN IP + DHCP, the repeater
join (5 GHz backhaul), and port forwarding. Changing the LAN IP drops the path to
the box, so do it last / on-site. See `docs/design/routers.html` for the per-role plan.

## First-run init and the repeater backhaul (classroom routers joining the hub)

A factory router is uninitialised; set its admin password first (unauth `ui init`):

    GLINET_PASSWORD='...' tools/routers/glinet.py init     # no-op if already initialised

Join the hub's 5 GHz WormHole-Core (make a classroom router a repeater of the hub):

    call repeater scan                 # returns res[] of {ssid, band, bssid, signal, encryption.uci, ...}
    call repeater connect {"ssid":"WormHole-Core","key":"<backhaul>","bssid":"<from scan>",
                           "device":"radio1","band":"5g","encryption":"psk2"}
    call repeater get_status           # state_name "connected", ipv4.ip = lease from the hub

Order for a classroom router (Tunnel N): set 2.4 GHz WormHole, then LAN to 192.168.8N.1
(so its LAN does not overlap the hub's 192.168.8.0/24 WAN it joins), then the repeater
connect, then the Burrow port-forward. Change the LAN last — it drops the path to the box.

### Firmware note
Boxes ship on mixed firmware (seen: 4.3.28 and 4.8.3). The login handshake, `wifi set_config`,
`ui init` and `repeater scan/connect` are the same across both. The admin-panel RPC method names
for LAN/DHCP/port-forward differ between versions, so upgrade a router to the fleet's target
(4.8.3) before scripting those. `repeater scan`/`connect` need a longer RPC timeout (~35 s).

## Firmware upgrade (local file, no internet needed) — captured from the 4.3.28 panel

Files: https://dl.gl-inet.com/router/sft1200 → "DOWNLOAD FOR COMMON UPGRADE" (the `.tar`), e.g.
`https://fw.gl-inet.com/firmware/sft1200/release4/sft1200-4.8.3_release4-1006-0609-1780999327.tar`
(sha256 f84630b6…ff5e1f). Keep a copy in `firmware/routers/` (gitignored).

    1. POST http://<router>/upload      multipart/form-data (the panel's uploader; carries the sid)
    2. call upgrade check_firmware_local {}      -> {"version":"4.8.3", "release_note":..., verification}
    3. call upgrade upgrade_local {"keep_config":true,"keep_package":true}   -> []  then ~4 min reboot

keep_config keeps admin password, Wi-Fi, repeater and LAN. Panel view names on 4.x (hash routes
`#/<view>`): upgrade, lanip, wireless, internet, firewallview, clients, adminpw, timezone, reset …
(from `call ui get_menu_list`).
