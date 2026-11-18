"""Runs the real drivers against fake devices.  python -m unittest discover -s tests -t ."""

from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from office_brain import schedule
from office_brain.office import Office
from office_brain.schedule import due, parse_schedule
from office_brain.server import host_ok, make_app
from tests.fakes import start_fake_office

BASE = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text())
ORIGIN = "http://localhost:3000"


class OfficeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        base = copy.deepcopy(BASE)
        base["fade_ms"] = 0
        self.fakes, self.config = await start_fake_office(base)
        for device in self.config["devices"]:
            if device["id"] == "camera":
                device["off_delay_s"] = 0.3
        self.office = Office(self.config)
        await self.office.refresh_all()

    async def asyncTearDown(self) -> None:
        await self.office.close()
        for fake in self.fakes.values():
            await fake.stop()

    async def test_reads_every_device(self):
        state = self.office.state()
        self.assertTrue(all(d["online"] for d in state["devices"]), state["devices"])
        main = next(d for d in state["devices"] if d["id"] == "main")
        self.assertEqual((main["on"], main["brightness"], main["kelvin"]), (False, 20, 4000))

    async def test_meetings_sets_every_device(self):
        run = await self.office.run_mode("meetings")
        self.assertTrue(run["ok"], run)
        self.assertEqual(self.fakes["main"].light, {"on": 1, "brightness": 60, "temperature": 250})
        self.assertEqual(self.fakes["fill"].light, {"on": 1, "brightness": 30, "temperature": 250})
        self.assertEqual([self.fakes[p].relay for p in ("bookshelf", "camera")], [1, 0])
        self.assertEqual(self.office.active_mode(), "meetings")

    async def test_shutdown_waits_before_cutting_the_camera(self):
        await self.office.run_mode("filming")
        self.assertEqual(self.office.active_mode(), "filming")
        run = await self.office.run_mode("shutdown")
        self.assertTrue(run["ok"], run)
        camera = next(r for r in run["results"] if r["device"] == "camera")
        lamps = next(r for r in run["results"] if r["device"] == "bookshelf")
        self.assertGreaterEqual(run["ms"], 300)
        self.assertLess(lamps["ms"], 300)
        self.assertEqual(camera["status"], "ok")
        self.assertEqual(self.fakes["camera"].relay, 0)
        self.assertEqual(self.fakes["main"].light["on"], 0)
        self.assertEqual(self.office.active_mode(), "shutdown")

    async def test_fade_steps_the_light_up(self):
        self.office.fade_ms = 600
        run = await self.office.run_mode("filming")
        self.assertTrue(run["ok"], run)
        levels = [p["brightness"] for p in self.fakes["main"].puts if "brightness" in p]
        self.assertGreaterEqual(len(levels), 3)
        self.assertEqual(levels, sorted(levels))
        self.assertEqual(levels[-1], 45)
        self.office.fade_ms = 400
        await self.office.run_mode("shutdown")
        # Off after a fade puts the old level back, so the light remembers 45%, not 3%.
        self.assertEqual(self.fakes["main"].light, {"on": 0, "brightness": 45, "temperature": 192})

    async def test_an_offline_light_is_reported_and_the_rest_still_run(self):
        await self.fakes["fill"].stop()
        run = await self.office.run_mode("meetings")
        self.assertFalse(run["ok"])
        fill = next(r for r in run["results"] if r["device"] == "fill")
        self.assertEqual((fill["status"], fill["message"]), ("failed", "didn't answer"))
        self.assertEqual(self.fakes["main"].light["brightness"], 60)
        self.assertFalse(next(d for d in self.office.state()["devices"] if d["id"] == "fill")["online"])

    async def test_a_lamp_changed_by_hand_shows_up(self):
        await self.office.run_mode("meetings")
        self.fakes["bookshelf"].relay = 0  # someone flips the lamps off at the plug
        await self.office.refresh_all()
        lamps = next(d for d in self.office.state()["devices"] if d["id"] == "bookshelf")
        self.assertFalse(lamps["on"])
        self.assertIsNone(self.office.active_mode())

    async def test_devices_not_set_up_are_skipped(self):
        config = copy.deepcopy(self.config)
        next(d for d in config["devices"] if d["id"] == "camera")["host"] = None
        office = Office(config)
        await office.refresh_all()
        run = await office.run_mode("meetings")
        await office.close()
        camera = next(r for r in run["results"] if r["device"] == "camera")
        self.assertTrue(run["ok"])
        self.assertEqual(camera["status"], "skipped")


class ApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        base = copy.deepcopy(BASE)
        base["fade_ms"] = 0
        self.fakes, config = await start_fake_office(base)
        self.app_dir = tempfile.TemporaryDirectory()
        app_dir = Path(self.app_dir.name)
        (app_dir / "index.html").write_text("<title>Office app</title>")
        (app_dir / "_next" / "static").mkdir(parents=True)
        (app_dir / "_next" / "static" / "app.js").write_text("// app")
        self.client = TestClient(TestServer(make_app(Office(config), config, app_dir)))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.app_dir.cleanup()
        for fake in self.fakes.values():
            await fake.stop()

    async def test_state_and_mode(self):
        resp = await self.client.get("/api/state", headers={"Origin": ORIGIN})
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers["Access-Control-Allow-Origin"], ORIGIN)
        state = await resp.json()
        self.assertEqual([m["id"] for m in state["modes"]], ["deep-work", "meetings", "filming", "shutdown"])
        self.assertEqual([(e["at"], e["name"]) for e in state["schedule"]], [("08:00", "Deep Work"), ("17:00", "Shutdown")])
        resp = await self.client.post("/api/modes/meetings", json={}, headers={"Origin": ORIGIN})
        body = await resp.json()
        self.assertTrue(body["run"]["ok"], body)
        self.assertEqual(body["state"]["activeMode"], "meetings")

    async def test_one_device_by_hand(self):
        resp = await self.client.post("/api/devices/main", json={"brightness": 42, "kelvin": 5600})
        body = await resp.json()
        self.assertEqual(body["result"]["status"], "ok", body)
        self.assertEqual(self.fakes["main"].light, {"on": 1, "brightness": 42, "temperature": 179})
        resp = await self.client.post("/api/devices/bookshelf", json={"on": True})
        self.assertEqual(self.fakes["bookshelf"].relay, 1)

    async def test_preflight_from_the_app(self):
        resp = await self.client.options("/api/modes/meetings", headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true",
        })
        self.assertEqual(resp.status, 204)
        self.assertEqual(resp.headers["Access-Control-Allow-Private-Network"], "true")

    async def test_other_websites_cant_press_modes(self):
        resp = await self.client.post("/api/modes/shutdown", json={}, headers={"Origin": "https://evil.example"})
        self.assertEqual(resp.status, 403)
        resp = await self.client.post("/api/modes/shutdown", data="{}", headers={"Content-Type": "text/plain"})
        self.assertEqual(resp.status, 415)
        self.assertEqual(self.fakes["bookshelf"].relay, 0)

    async def test_unknown_mode(self):
        resp = await self.client.post("/api/modes/nope", json={})
        self.assertEqual(resp.status, 404)

    async def test_serves_the_app_on_the_wifi(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        self.assertIn("Office app", await resp.text())
        self.assertEqual(resp.headers["Cache-Control"], "no-store")
        resp = await self.client.get("/_next/static/app.js")
        self.assertIn("immutable", resp.headers["Cache-Control"])
        # The app the mini serves presses modes from the mini's own address.
        own = f"http://{self.client.host}:{self.client.port}"
        resp = await self.client.post("/api/modes/deep-work", json={}, headers={"Origin": own})
        self.assertEqual(resp.status, 200, await resp.text())
        self.assertEqual(self.fakes["bookshelf"].relay, 1)

    async def test_other_names_for_this_mac_are_refused(self):
        evil = {"Host": "evil.example", "Origin": "http://evil.example"}
        resp = await self.client.post("/api/modes/shutdown", json={}, headers=evil)
        self.assertEqual(resp.status, 403)
        resp = await self.client.get("/api/state", headers={"Host": "evil.example"})
        self.assertEqual(resp.status, 403)

    def test_host_names(self):
        for host in ["office-mini.local", "Office-Mini.local:80", "192.168.1.20", "192.168.1.20:80",
                     "localhost:8787", "[::1]:80", "office-mini.your-tailnet.ts.net"]:
            self.assertTrue(host_ok(host), host)
        for host in ["evil.example", "evil.example:80", "local", "mini.local.evil.example"]:
            self.assertFalse(host_ok(host), host)


class ScheduleTest(unittest.IsolatedAsyncioTestCase):
    MODES = {"deep-work": {"name": "Deep Work"}, "shutdown": {"name": "Shutdown"}}

    def test_runs_once_a_day_at_its_time(self):
        entries = parse_schedule([{"at": "18:00", "mode": "shutdown"}, {"at": "6:30", "mode": "deep-work"}], self.MODES)
        self.assertEqual([e["at"] for e in entries], ["06:30", "18:00"])
        fired: dict = {}
        self.assertEqual(due(entries, datetime(2026, 11, 18, 6, 29, 59), fired), [])
        self.assertEqual([e["mode"] for e in due(entries, datetime(2026, 11, 18, 6, 30, 5), fired)], ["deep-work"])
        fired["06:30"] = date(2026, 11, 18)
        self.assertEqual(due(entries, datetime(2026, 11, 18, 6, 31), fired), [])
        # A brain that was off at 6:30 doesn't turn the lights on at noon.
        self.assertEqual(due(entries, datetime(2026, 11, 18, 12, 0), {}), [])
        self.assertEqual([e["mode"] for e in due(entries, datetime(2026, 11, 18, 18, 2), fired)], ["shutdown"])
        self.assertEqual([e["mode"] for e in due(entries, datetime(2026, 11, 19, 6, 30), fired)], ["deep-work"])

    def test_a_typo_stops_the_brain_from_starting(self):
        with self.assertRaises(ValueError):
            parse_schedule([{"at": "06:30", "mode": "deep-wrok"}], self.MODES)
        with self.assertRaises(ValueError):
            parse_schedule([{"at": "25:00", "mode": "shutdown"}], self.MODES)

    async def test_a_failed_run_tries_once_more(self):
        calls = []

        class Stub:
            async def run_mode(self, mode):
                calls.append(mode)
                return {"ok": False}

        with mock.patch.object(schedule, "RETRY_S", 0):
            await schedule.run_entry(Stub(), {"at": "18:00", "mode": "shutdown", "name": "Shutdown"})
        self.assertEqual(calls, ["shutdown", "shutdown"])


if __name__ == "__main__":
    unittest.main()
