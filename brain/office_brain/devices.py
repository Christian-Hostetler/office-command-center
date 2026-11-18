"""Drivers for each kind of device. Every command goes straight to the device over the home network."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import aiohttp
from kasa import Credentials, Device, DeviceConfig, Discover, KasaException
from kasa.deviceconfig import DeviceConnectionParameters, DeviceEncryptionType, DeviceFamily

# Elgato Key Lights take color temperature in mireds. 143 is 7000K and 344 is 2900K.
MIN_MIRED, MAX_MIRED = 143, 344
MIN_BRIGHTNESS = 3  # the lowest level a Key Light accepts

# EP10 plugs use TP-Link's classic local protocol on port 9999, which needs no login.
CLASSIC_PLUG = DeviceConnectionParameters(DeviceFamily.IotSmartPlugSwitch, DeviceEncryptionType.Xor)

# A poll has to fail this many times in a row before a device shows as offline.
OFFLINE_AFTER = 2


def kelvin_to_mired(kelvin: int) -> int:
    return max(MIN_MIRED, min(MAX_MIRED, round(1_000_000 / kelvin)))


def mired_to_kelvin(mired: int) -> int:
    return round(1_000_000 / mired / 50) * 50


class DeviceError(Exception):
    """A device answered, but not the way we asked."""


@dataclass
class Target:
    on: bool
    brightness: int | None = None
    kelvin: int | None = None

    @classmethod
    def parse(cls, spec: str | dict) -> "Target":
        """A recipe entry is "on", "off", or {"brightness": 60, "kelvin": 4000}."""
        if isinstance(spec, str):
            return cls(on=spec == "on")
        return cls(
            on=spec.get("on", True),
            brightness=spec.get("brightness"),
            kelvin=spec.get("kelvin"),
        )


@dataclass
class Reading:
    on: bool | None = None
    brightness: int | None = None
    kelvin: int | None = None


class BaseDevice:
    kind = "device"

    def __init__(self, spec: dict):
        self.id: str = spec["id"]
        self.name: str = spec["name"]
        self.host: str | None = spec.get("host") or None
        self.port: int | None = spec.get("port")
        self.off_delay_s = float(spec.get("off_delay_s", 0))
        self.reading = Reading()
        self.online = False
        self.error: str | None = None
        self.failures = 0
        self.last_seen: float | None = None
        self.lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return self.host is not None

    def mark_ok(self) -> None:
        self.online = True
        self.failures = 0
        self.error = None
        self.last_seen = time.time()

    def mark_failed(self, err: Exception, *, at_once: bool = False) -> None:
        self.failures += 1
        self.error = friendly_error(err)
        if at_once or self.failures >= OFFLINE_AFTER:
            self.online = False

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "configured": self.configured,
            "online": self.online,
            "on": self.reading.on,
            "brightness": self.reading.brightness,
            "kelvin": self.reading.kelvin,
            "error": self.error,
            "lastSeen": self.last_seen,
        }

    async def refresh(self) -> None:
        raise NotImplementedError

    async def apply(self, target: Target, fade_ms: int) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class KeyLight(BaseDevice):
    """Elgato Key Light. Local HTTP API on port 9123, no login."""

    kind = "keylight"

    def __init__(self, spec: dict, http: "Http"):
        super().__init__(spec)
        self.http = http
        self.url = f"http://{self.host}:{self.port or 9123}/elgato/lights"

    async def _request(self, method: str, body: dict | None = None) -> dict:
        # Some Key Light firmware resets kept-alive connections. Reads go out as HTTP/1.0 and
        # writes close the connection, and each one gets a single retry if the light drops it.
        for attempt in (1, 2):
            try:
                if method == "GET":
                    ctx = self.http.reads.get(self.url)
                else:
                    ctx = self.http.writes.put(self.url, json=body, headers={"Connection": "close"})
                async with ctx as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                    return data["lights"][0]
            except (aiohttp.ClientOSError, aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.15)
        raise AssertionError("unreachable")

    def _remember(self, light: dict) -> None:
        self.reading = Reading(
            on=bool(light["on"]),
            brightness=int(light["brightness"]),
            kelvin=mired_to_kelvin(int(light["temperature"])),
        )

    async def refresh(self) -> None:
        self._remember(await self._request("GET"))

    async def _put(self, **fields: int) -> dict:
        return await self._request("PUT", {"numberOfLights": 1, "lights": [fields]})

    async def _ramp(self, b0: int, b1: int, m0: int, m1: int, fade_ms: int) -> None:
        steps = max(2, fade_ms // 200)
        start = time.monotonic()
        for i in range(1, steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)  # smoothstep, so the fade starts and ends gently
            await self._put(
                on=1,
                brightness=round(b0 + (b1 - b0) * eased),
                temperature=round(m0 + (m1 - m0) * eased),
            )
            wait = start + fade_ms / 1000 * t - time.monotonic()
            if wait > 0 and i < steps:
                await asyncio.sleep(wait)

    async def apply(self, target: Target, fade_ms: int) -> None:
        now = await self._request("GET")
        was_on, b0, m0 = bool(now["on"]), int(now["brightness"]), int(now["temperature"])

        if not target.on:
            if was_on and fade_ms > 0:
                await self._ramp(b0, MIN_BRIGHTNESS, m0, m0, fade_ms)
                await self._put(on=0)
                # Put the old level back while it's off, so the Elgato app or a button press
                # brings it back where it was instead of at 3%.
                await self._put(on=0, brightness=b0)
            elif was_on:
                await self._put(on=0)
        else:
            b1 = max(MIN_BRIGHTNESS, min(100, target.brightness)) if target.brightness else b0
            m1 = kelvin_to_mired(target.kelvin) if target.kelvin else m0
            if fade_ms <= 0:
                await self._put(on=1, brightness=b1, temperature=m1)
            elif not was_on:
                await self._put(on=1, brightness=MIN_BRIGHTNESS, temperature=m1)
                await self._ramp(MIN_BRIGHTNESS, b1, m1, m1, fade_ms)
            elif (b0, m0) != (b1, m1):
                await self._ramp(b0, b1, m0, m1, fade_ms)

        light = await self._request("GET")
        self._remember(light)
        if bool(light["on"]) != target.on:
            raise DeviceError("didn't take the change")
        if target.on and target.brightness and abs(int(light["brightness"]) - b1) > 1:
            raise DeviceError("didn't take the change")


class KasaPlug(BaseDevice):
    """TP-Link Kasa smart plug, through python-kasa. Local only, no cloud."""

    kind = "plug"

    def __init__(self, spec: dict, credentials: Credentials | None, credentials_hash: str | None = None):
        super().__init__(spec)
        self.credentials = credentials
        self.credentials_hash = credentials_hash
        self._dev: Device | None = None

    async def _device(self) -> Device:
        if self._dev is not None:
            return self._dev
        config = DeviceConfig(
            host=self.host,
            port_override=self.port,
            timeout=3,
            connection_type=CLASSIC_PLUG,
            credentials=self.credentials,
        )
        try:
            self._dev = await Device.connect(config=config)
        except KasaException:
            if self.port:
                raise  # a fixed port is a test plug, so there's nothing to discover
            # Newer Kasa firmware switched protocols. Discovery works out which one it speaks.
            dev = await Discover.discover_single(self.host, discovery_timeout=3, credentials=self.credentials)
            if dev is None:
                raise
            self._dev = await with_saved_login(dev, self.credentials_hash)
        return self._dev

    async def refresh(self) -> None:
        dev = await self._device()
        await dev.update()
        self.reading = Reading(on=dev.is_on)

    async def apply(self, target: Target, fade_ms: int) -> None:
        dev = await self._device()
        if target.on:
            await dev.turn_on()
        else:
            await dev.turn_off()
        await dev.update()
        self.reading = Reading(on=dev.is_on)
        if dev.is_on != target.on:
            raise DeviceError("didn't switch")

    async def close(self) -> None:
        if self._dev is not None:
            await self._dev.disconnect()
            self._dev = None


async def with_saved_login(dev: Device, credentials_hash: str | None) -> Device:
    """Reads a plug found by discovery, reconnecting it with the saved TP-Link login when there is one."""
    if not credentials_hash or dev.config.credentials:
        await dev.update()
        return dev
    config = dev.config
    await dev.disconnect()
    config.credentials_hash = credentials_hash
    dev = await Device.connect(config=config)
    await dev.update()
    return dev


def friendly_error(err: Exception) -> str:
    if isinstance(err, DeviceError):
        return str(err)
    if isinstance(err, (asyncio.TimeoutError, TimeoutError, aiohttp.ClientConnectionError, OSError, KasaException)):
        return "didn't answer"
    if isinstance(err, aiohttp.ClientResponseError):
        return f"answered with an error ({err.status})"
    return str(err)[:120] or err.__class__.__name__


class Http:
    """Two HTTP clients for the Key Lights: HTTP/1.0 for reads, and writes that never reuse a connection."""

    def __init__(self, timeout_s: float = 3):
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        self.reads = aiohttp.ClientSession(
            version=aiohttp.HttpVersion10,
            connector=aiohttp.TCPConnector(force_close=True, limit=0),
            timeout=timeout,
        )
        self.writes = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(force_close=True, limit=0),
            timeout=timeout,
        )

    async def close(self) -> None:
        await self.reads.close()
        await self.writes.close()


def build_device(spec: dict, http: Http, credentials: Credentials | None,
                 credentials_hash: str | None = None) -> BaseDevice:
    kind = spec["kind"]
    if kind == "keylight":
        return KeyLight(spec, http)
    if kind == "plug":
        return KasaPlug(spec, credentials, credentials_hash)
    raise ValueError(f"Unknown device kind {kind!r} for {spec['id']}")
