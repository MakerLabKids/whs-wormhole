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
