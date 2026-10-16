"""Burrow: the Wormhole classroom edge service (Raspberry Pi 5).

Ingests worm-bin telemetry from Pico "Bins", keeps it safe on a microSD
as immutable 15-minute castings, mirrors castings with the other Burrows,
uploads to the Surface (Cloudflare) when there is any internet, and serves
the local dashboards. Standard library only.
"""
VERSION = "0.1.0"
