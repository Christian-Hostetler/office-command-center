"""
The office brain. Runs on the Mac mini.

  python -m office_brain                 run the service the phone app talks to
  python -m office_brain discover        find the Key Lights and Kasa plugs on this network
  python -m office_brain check [device]  Level 2 test: switch each device and time it
  python -m office_brain kasa-login      log in to the Kasa plugs once, for firmware that wants it
  python -m office_brain plug-wifi SSID  put a Kasa plug in setup mode on the Wi-Fi, without the Kasa app
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path

import aiohttp
from aiohttp import web
from kasa import Credentials, Discover, KasaException

from .devices import KeyLight, Target, with_saved_login
from .office import KASA_LOGIN_FILE, Office, kasa_credentials, kasa_credentials_hash
from .server import make_app

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.json"
# The phone app as plain files. deploy.sh builds it from web/ and puts it here.
APP_DIR = Path(__file__).resolve().parent.parent / "app"


def load_config(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def serve(config_path: Path, host: str | None, port: int | None) -> None:
    config = load_config(config_path)
    listen = config.get("listen", {})
    host = host or listen.get("host", "127.0.0.1")
    port = port or listen.get("port", 8787)

    async def build() -> web.Application:
        return make_app(Office(config), config, APP_DIR)

    logging.info("Office brain on http://%s:%s with %s", host, port, config_path)
    web.run_app(build(), host=host, port=port, print=None, access_log=None)


def local_subnet() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))  # no packet is sent, this only picks the network interface
        ip = s.getsockname()[0]
    return ip.rsplit(".", 1)[0]


async def discover() -> None:
    subnet = local_subnet()
    print(f"Looking on {subnet}.x for about 5 seconds...\n")

    async def elgato(session: aiohttp.ClientSession, ip: str) -> dict | None:
        try:
            async with session.get(f"http://{ip}:9123/elgato/accessory-info") as resp:
                info = await resp.json(content_type=None)
                return {"ip": ip, **info}
        except Exception:
            return None

    timeout = aiohttp.ClientTimeout(total=2.5)
    # Ask every address at once. aiohttp's default cap of 100 connections queues the rest,
    # and a light past the first 100 addresses times out while it waits its turn.
    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector, version=aiohttp.HttpVersion10) as session:
        lights_task = asyncio.gather(*(elgato(session, f"{subnet}.{n}") for n in range(1, 255)))
        plugs_task = Discover.discover(discovery_timeout=4, credentials=kasa_credentials())
        lights, plugs = await asyncio.gather(lights_task, plugs_task)

    print("Elgato Key Lights")
    found = [light for light in lights if light]
    for light in found:
        name = light.get("displayName") or light.get("productName")
        print(f"  {name:<22} {light['ip']:<16} MAC {light.get('macAddress', '?'):<18} serial {light.get('serialNumber', '?')}")
    if not found:
        print("  none found")

    print("\nKasa plugs")
    for ip, dev in sorted(plugs.items()):
        try:
            dev = await with_saved_login(dev, kasa_credentials_hash())
            print(f"  {dev.alias:<22} {ip:<16} MAC {dev.mac:<18} {dev.model}  {'on' if dev.is_on else 'off'}")
        except Exception as err:
            print(f"  {ip:<16} found, but couldn't read it: {err}")
        finally:
            await dev.disconnect()
    if not plugs:
        print("  none found")

    print('\nPut each IP in brain/config.json as "host", and reserve it in the router using the MAC.')


async def kasa_login(config_path: Path) -> int:
    """Logs in to a Kasa plug once with the TP-Link account and saves only the login hash, never the password."""
    hosts = [d["host"] for d in load_config(config_path)["devices"] if d["kind"] == "plug" and d.get("host")]
    if not hosts:
        print("Put a plug's IP in brain/config.json first. discover finds it.")
        return 1
    if sys.stdin.isatty():
        print("Type the email and password of the TP-Link account you use in the Kasa app.")
        print("The password stays hidden as you type, and it's never saved.\n")
        email = input("TP-Link email: ").strip()
        password = getpass.getpass("TP-Link password (hidden): ")
    else:
        email, password = sys.stdin.readline().strip(), sys.stdin.readline().rstrip("\n")

    dev = None
    try:
        dev = await Discover.discover_single(hosts[0], discovery_timeout=4, credentials=Credentials(email, password))
        if dev is None:
            print(f"No plug answered at {hosts[0]}.")
            return 1
        await dev.update()
        name, credentials_hash = dev.alias, dev.credentials_hash
    except KasaException as err:
        print(f"The plug didn't accept that login ({err.__class__.__name__}). Check the email and password and try again.")
        return 1
    finally:
        if dev is not None:
            await dev.disconnect()
    if not credentials_hash:
        print(f"{name} doesn't need a login, so there's nothing to save.")
        return 0

    KASA_LOGIN_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Create the file readable by this account only, before anything goes in it.
    fd = os.open(KASA_LOGIN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"credentials_hash": credentials_hash}, f)
    os.chmod(KASA_LOGIN_FILE, 0o600)
    print(f"Logged in to {name}. The login is saved in {KASA_LOGIN_FILE}, and the password itself isn't.")
    return 0


# Where a Kasa plug in setup mode sits, on the Wi-Fi it makes itself.
SETUP_IP = "192.168.0.1"


async def plug_wifi(ssid: str | None) -> int:
    """Sends the office Wi-Fi to a Kasa plug in setup mode. Run it while this Mac is on the plug's own Wi-Fi."""
    if not ssid:
        print("Name the Wi-Fi to join, like: python -m office_brain plug-wifi OfficeWiFi")
        return 1
    if sys.stdin.isatty():
        password = getpass.getpass(f"Password for the {ssid} Wi-Fi (hidden): ")
    else:
        password = sys.stdin.readline().rstrip("\n")

    dev = await Discover.discover_single(SETUP_IP, discovery_timeout=5)
    if dev is None:
        print(f"No plug answered at {SETUP_IP}. Is this Mac on the plug's own Wi-Fi?")
        return 1
    try:
        try:
            await dev.update()
        except KasaException as err:
            logging.debug("Read before the scan failed: %r", err)
        # A plug that just woke up sometimes reports no networks at first, so ask a few times.
        networks = []
        for _ in range(5):
            networks = await dev.wifi_scan()
            if networks:
                break
            await asyncio.sleep(2)
        names = sorted({n.ssid for n in networks if n.ssid})
        print(f"The plug sees: {', '.join(names) or 'no networks'}")
        match = next((n for n in networks if n.ssid == ssid), None)
        if match is None:
            print(f"The plug can't see {ssid}. These plugs only use 2.4 GHz Wi-Fi.")
            return 1
        keytype = str(match.key_type) if match.key_type is not None else "3"
        try:
            await asyncio.wait_for(dev.wifi_join(ssid, password, keytype=keytype), timeout=10)
        except (asyncio.TimeoutError, KasaException) as err:
            # The plug drops its own Wi-Fi the moment it starts joining, so often nothing comes back.
            logging.debug("No answer to the join, which is normal: %r", err)
    finally:
        await dev.disconnect()
    print(f"Sent {ssid} to the plug. Its light turns solid once it's on.")
    return 0


async def check(config_path: Path, only: str | None) -> int:
    """Level 2: one device at a time. Reads it, switches it, puts it back, and times each step."""
    office = Office(load_config(config_path))
    failed = False
    try:
        for device in office.devices.values():
            if only and device.id != only:
                continue
            if not device.configured:
                print(f"{device.name}: not set up yet, skipped")
                continue
            print(f"\n{device.name} ({device.host})")

            async def step(label: str, action) -> bool:
                started = time.monotonic()
                try:
                    await asyncio.wait_for(action, timeout=10)
                    print(f"  ok    {label:<28} {(time.monotonic() - started) * 1000:>6.0f} ms")
                    return True
                except Exception as err:
                    print(f"  FAIL  {label:<28} {err!r}")
                    return False

            if not await step("read", device.refresh()):
                failed = True
                continue
            before = device.reading
            print(f"        it's {'on' if before.on else 'off'}"
                  + (f", {before.brightness}%, {before.kelvin}K" if isinstance(device, KeyLight) else ""))
            if isinstance(device, KeyLight):
                steps = [
                    ("on at 50%, 4500K", Target(on=True, brightness=50, kelvin=4500), 0),
                    ("dim to 10%", Target(on=True, brightness=10), 0),
                    ("fade up to 80% over 2 s", Target(on=True, brightness=80), 2000),
                    ("off", Target(on=False), 0),
                ]
            else:
                steps = [("on", Target(on=True), 0), ("off", Target(on=False), 0)]
            for label, target, fade in steps:
                failed |= not await step(label, device.apply(target, fade))
                await asyncio.sleep(1)
            restore = Target(on=bool(before.on), brightness=before.brightness, kelvin=before.kelvin)
            failed |= not await step("put it back how it was", device.apply(restore, 0))
    finally:
        await office.close()
    print("\nAll passed." if not failed else "\nSomething failed. Fix it before moving on.")
    return 1 if failed else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("kasa").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="office_brain", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "discover", "check", "kasa-login", "plug-wifi"])
    parser.add_argument("device", nargs="?", help="for check: just this device id. For plug-wifi: the Wi-Fi name")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()

    if args.command == "discover":
        asyncio.run(discover())
    elif args.command == "check":
        sys.exit(asyncio.run(check(args.config, args.device)))
    elif args.command == "kasa-login":
        sys.exit(asyncio.run(kasa_login(args.config)))
    elif args.command == "plug-wifi":
        sys.exit(asyncio.run(plug_wifi(args.device)))
    else:
        serve(args.config, args.host, args.port)


if __name__ == "__main__":
    main()
