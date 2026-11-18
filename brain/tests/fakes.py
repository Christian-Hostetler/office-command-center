"""
Pretend devices that speak the same protocols as the real ones, so the brain can be tested
before the hardware arrives.

  python -m tests.fakes    runs a fake office and the brain against it on http://127.0.0.1:8787
"""

from __future__ import annotations

import asyncio
import json
import struct

from aiohttp import web


class FakeKeyLight:
    """Elgato's HTTP API on port 9123: GET and PUT /elgato/lights."""

    def __init__(self, name: str, port: int = 0):
        self.name = name
        self.port = port
        self.light = {"on": 0, "brightness": 20, "temperature": 250}
        self.puts: list[dict] = []
        self._runner: web.AppRunner | None = None

    async def _lights(self, request: web.Request) -> web.Response:
        if request.method == "PUT":
            body = await request.json()
            change = body["lights"][0]
            self.puts.append(change)
            self.light.update({k: int(v) for k, v in change.items() if k in self.light})
        return web.json_response({"numberOfLights": 1, "lights": [self.light]})

    async def _info(self, request: web.Request) -> web.Response:
        return web.json_response({
            "productName": "Elgato Key Light", "displayName": self.name,
            "serialNumber": "FAKE0001", "firmwareVersion": "1.0.3", "macAddress": "3C:6A:9D:00:00:01",
        })

    async def start(self) -> "FakeKeyLight":
        app = web.Application()
        app.router.add_route("*", "/elgato/lights", self._lights)
        app.router.add_get("/elgato/accessory-info", self._info)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self.port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None


def xor_encrypt(data: bytes) -> bytes:
    key, out = 171, bytearray()
    for byte in data:
        key ^= byte
        out.append(key)
    return bytes(out)


def xor_decrypt(data: bytes) -> bytes:
    key, out = 171, bytearray()
    for byte in data:
        out.append(key ^ byte)
        key = byte
    return bytes(out)


class FakeKasaPlug:
    """TP-Link's classic local protocol: TCP, a 4 byte length, then XOR-scrambled JSON."""

    def __init__(self, alias: str, port: int = 0):
        self.alias = alias
        self.port = port
        self.relay = 0
        self.commands: list[str] = []
        self._server: asyncio.base_events.Server | None = None

    def sysinfo(self) -> dict:
        return {
            "sw_ver": "1.0.2 Build 200915 Rel.085940", "hw_ver": "1.0", "model": "EP10(US)",
            "deviceId": "8006FAKE" + self.alias.encode().hex()[:32].upper(), "oemId": "FAKEOEM",
            "hwId": "FAKEHW", "rssi": -48, "latitude_i": 0, "longitude_i": 0, "alias": self.alias,
            "status": "new", "obd_src": "tplink", "mic_type": "IOT.SMARTPLUGSWITCH", "feature": "TIM",
            "mac": "B0:A7:B9:00:00:01", "updating": 0, "led_off": 0, "relay_state": self.relay,
            "on_time": 0, "icon_hash": "", "dev_name": "Smart Wi-Fi Plug Mini", "active_mode": "none",
            "next_action": {"type": -1}, "err_code": 0,
        }

    def respond(self, request: dict) -> dict:
        response: dict = {}
        for module, methods in request.items():
            if module != "system":
                response[module] = {"err_code": -1, "err_msg": "module not support"}
                continue
            response[module] = {}
            for method, params in methods.items():
                self.commands.append(method)
                if method == "get_sysinfo":
                    response[module][method] = self.sysinfo()
                elif method == "set_relay_state":
                    self.relay = int(params["state"])
                    response[module][method] = {"err_code": 0}
                else:
                    response[module][method] = {"err_code": -2, "err_msg": "member not support"}
        return response

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                (size,) = struct.unpack(">I", await reader.readexactly(4))
                request = json.loads(xor_decrypt(await reader.readexactly(size)))
                payload = xor_encrypt(json.dumps(self.respond(request)).encode())
                writer.write(struct.pack(">I", len(payload)) + payload)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def start(self) -> "FakeKasaPlug":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            self._server = None


async def start_fake_office(base_config: dict, ports: dict[str, int] | None = None):
    """Start one fake per device and return (fakes by id, a config pointed at them)."""
    ports = ports or {}
    fakes: dict = {}
    devices = []
    for spec in base_config["devices"]:
        port = ports.get(spec["id"], 0)
        fake = FakeKeyLight(spec["name"], port) if spec["kind"] == "keylight" else FakeKasaPlug(spec["name"], port)
        fakes[spec["id"]] = await fake.start()
        devices.append({**spec, "host": "127.0.0.1", "port": fake.port})
    return fakes, {**base_config, "devices": devices}


async def _run_fake_office() -> None:
    from pathlib import Path

    from office_brain.office import Office
    from office_brain.server import make_app

    base = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text())
    ports = {"main": 19123, "fill": 19124, "bookshelf": 19991, "camera": 19993}
    _, config = await start_fake_office(base, ports)
    config["fade_ms"] = 600
    config["devices"] = [{**d, "off_delay_s": min(d.get("off_delay_s", 0), 1)} for d in config["devices"]]
    runner = web.AppRunner(make_app(Office(config), config), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 8787).start()
    print("Fake office running. Brain on http://127.0.0.1:8787  (Ctrl+C to stop)")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(_run_fake_office())
    except KeyboardInterrupt:
        pass
