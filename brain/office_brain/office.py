"""The office: every device, the mode recipes, and what's true right now."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from kasa import Credentials

from .devices import BaseDevice, Http, Target, build_device
from .schedule import parse_schedule, run_schedule

log = logging.getLogger("office")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Where `python -m office_brain kasa-login` saves the TP-Link login. It holds a hash, never the password.
KASA_LOGIN_FILE = Path.home() / ".config" / "office-command-center" / "kasa.json"


def kasa_credentials() -> Credentials | None:
    """Only needed if a plug turns out to use TP-Link's newer, logged-in protocol."""
    user, password = os.environ.get("KASA_USERNAME"), os.environ.get("KASA_PASSWORD")
    return Credentials(user, password) if user and password else None


def kasa_credentials_hash() -> str | None:
    try:
        return json.loads(KASA_LOGIN_FILE.read_text()).get("credentials_hash") or None
    except (OSError, ValueError):
        return None


class Office:
    def __init__(self, config: dict):
        self.name: str = config.get("name", "Office")
        self.fade_ms = int(config.get("fade_ms", 2000))
        self.poll_s = float(config.get("poll_s", 3))
        self.http = Http()
        credentials, credentials_hash = kasa_credentials(), kasa_credentials_hash()
        self.devices: dict[str, BaseDevice] = {}
        for spec in config["devices"]:
            device = build_device(spec, self.http, credentials, credentials_hash)
            self.devices[device.id] = device
        self.modes: list[dict] = config["modes"]
        self.modes_by_id = {m["id"]: m for m in self.modes}
        for mode in self.modes:
            for device_id in mode["set"]:
                if device_id not in self.devices:
                    raise ValueError(f"Mode {mode['id']!r} uses {device_id!r}, which isn't in devices")
        self.schedule = parse_schedule(config.get("schedule", []), self.modes_by_id)
        self.mode_lock = asyncio.Lock()
        self.running: str | None = None
        self.last_mode: str | None = None
        self.last_run: dict | None = None
        self._pollers: list[asyncio.Task] = []

    # Reading state

    async def refresh(self, device: BaseDevice) -> None:
        if not device.configured:
            return
        try:
            await asyncio.wait_for(device.refresh(), timeout=6)
            device.mark_ok()
        except Exception as err:  # a device that doesn't answer shouldn't stop the others
            device.mark_failed(err)

    async def refresh_all(self) -> None:
        await asyncio.gather(*(self.refresh(d) for d in self.devices.values()))

    async def _poll(self, device: BaseDevice) -> None:
        while True:
            if not device.lock.locked():
                async with device.lock:
                    await self.refresh(device)
            await asyncio.sleep(self.poll_s)

    def start_polling(self) -> None:
        # One loop per device, so a light that's offline never slows down the rest.
        self._pollers = [asyncio.create_task(self._poll(d)) for d in self.devices.values() if d.configured]

    def start_schedule(self) -> None:
        if self.schedule:
            self._pollers.append(asyncio.create_task(run_schedule(self)))

    async def close(self) -> None:
        for task in self._pollers:
            task.cancel()
        await asyncio.gather(*self._pollers, return_exceptions=True)
        for device in self.devices.values():
            await device.close()
        await self.http.close()

    # Modes

    def matches(self, mode: dict) -> bool:
        """True when every device we can see is already where this mode puts it."""
        checked = False
        for device_id, spec in mode["set"].items():
            device = self.devices[device_id]
            if not device.configured or not device.online:
                continue
            target, reading = Target.parse(spec), device.reading
            if reading.on is None or reading.on != target.on:
                return False
            if target.on and device.kind == "keylight":
                if target.brightness is not None and abs((reading.brightness or 0) - target.brightness) > 1:
                    return False
                if target.kelvin is not None and abs((reading.kelvin or 0) - target.kelvin) > 120:
                    return False
            checked = True
        return checked

    def active_mode(self) -> str | None:
        matching = [m["id"] for m in self.modes if self.matches(m)]
        if self.last_mode in matching:
            return self.last_mode
        return matching[0] if matching else None

    async def _apply(self, device: BaseDevice, target: Target, fade_ms: int) -> dict:
        result = {"device": device.id, "name": device.name}
        if not device.configured:
            return {**result, "status": "skipped", "message": "isn't set up yet"}
        if not target.on and device.off_delay_s and device.reading.on:
            # The camera gets a few seconds before its power is cut, so it can finish writing.
            await asyncio.sleep(device.off_delay_s)
        started = time.monotonic()
        async with device.lock:
            try:
                await asyncio.wait_for(device.apply(target, fade_ms), timeout=fade_ms / 1000 + 10)
                device.mark_ok()
                status = {"status": "ok"}
            except Exception as err:
                device.mark_failed(err, at_once=True)
                log.warning("%s: %r", device.name, err)
                status = {"status": "failed", "message": device.error}
        return {**result, **status, "ms": round((time.monotonic() - started) * 1000)}

    async def run_mode(self, mode_id: str) -> dict:
        mode = self.modes_by_id[mode_id]
        async with self.mode_lock:
            self.running = mode_id
            started = time.monotonic()
            try:
                results = await asyncio.gather(
                    *(
                        self._apply(self.devices[device_id], Target.parse(spec), self.fade_ms)
                        for device_id, spec in mode["set"].items()
                    )
                )
            finally:
                self.running = None
            self.last_mode = mode_id
            self.last_run = {
                "mode": mode_id,
                "ok": all(r["status"] != "failed" for r in results),
                "at": now_iso(),
                "ms": round((time.monotonic() - started) * 1000),
                "results": results,
            }
            log.info("Mode %s: %s", mode["name"], self.last_run)
            return self.last_run

    async def set_device(self, device_id: str, change: dict) -> dict:
        """One device by hand from the app. No fade, so a slider feels instant."""
        device = self.devices[device_id]
        if "on" not in change and device.kind == "plug":
            raise ValueError("A plug needs on: true or false")
        on = bool(change.get("on", True))
        target = Target(on=on, brightness=change.get("brightness"), kelvin=change.get("kelvin"))
        return await self._apply(device, target, fade_ms=int(change.get("fade_ms", 0)))

    def state(self) -> dict:
        return {
            "name": self.name,
            "time": now_iso(),
            "devices": [d.snapshot() for d in self.devices.values()],
            "modes": [{"id": m["id"], "name": m["name"], "note": m.get("note", "")} for m in self.modes],
            "activeMode": self.active_mode(),
            "lastMode": self.last_mode,
            "running": self.running,
            "lastRun": self.last_run,
            "schedule": self.schedule,
        }
