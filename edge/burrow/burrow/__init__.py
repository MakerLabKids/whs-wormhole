"""Burrow: the Wormhole classroom edge service (Raspberry Pi 5).

Ingests worm-bin telemetry from Pico "Bins", keeps it safe on a microSD
as immutable 15-minute castings, mirrors castings with the other Burrows,
uploads to the Surface (Cloudflare) when there is any internet, and serves
the local dashboards. Standard library only.
"""
VERSION = "0.1.0"


def build():
    """The commit this install came from ("4df0cf4 2026-10-31T22:10Z"), from
    the BUILD file the deploy tools write next to the package; "" if none."""
    import os
    for p in (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BUILD"), "/opt/burrow/BUILD"):
        try:
            with open(p) as f:
                return f.read().strip()
        except OSError:
            pass
    return ""


BUILD = build()
