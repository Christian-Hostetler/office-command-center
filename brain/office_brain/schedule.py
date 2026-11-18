"""Runs modes at set times of day, by the Mac mini's own clock. Lives inside the brain, so nothing else has to run."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .office import Office

log = logging.getLogger("office.schedule")

# How long after its time an entry can still start. It covers a brain restart or a busy minute,
# and a mode is safe to run twice, so a restart inside the window costs nothing.
LATE_OK_MIN = 5
CHECK_S = 15
RETRY_S = 60


def parse_schedule(entries: list[dict], modes_by_id: dict[str, dict]) -> list[dict]:
    """Checks the schedule in config.json when the brain starts, so a typo stops the deploy instead of a morning."""
    parsed = []
    for entry in entries:
        hour, minute = (int(part) for part in str(entry["at"]).split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError(f"The schedule time {entry['at']!r} isn't a time of day")
        if entry["mode"] not in modes_by_id:
            raise ValueError(f"The schedule at {entry['at']} names {entry['mode']!r}, which isn't a mode")
        parsed.append({"at": f"{hour:02d}:{minute:02d}", "mode": entry["mode"], "name": modes_by_id[entry["mode"]]["name"]})
    return sorted(parsed, key=lambda e: e["at"])


def due(entries: list[dict], now: datetime, fired: dict[str, date]) -> list[dict]:
    """The entries whose time came in the last few minutes and that haven't run yet today."""
    minutes_now = now.hour * 60 + now.minute
    ready = []
    for entry in entries:
        hour, minute = (int(part) for part in entry["at"].split(":"))
        late = minutes_now - (hour * 60 + minute)
        if 0 <= late < LATE_OK_MIN and fired.get(entry["at"]) != now.date():
            ready.append(entry)
    return ready


async def run_schedule(office: Office) -> None:
    fired: dict[str, date] = {}
    while True:
        now = datetime.now()
        for entry in due(office.schedule, now, fired):
            fired[entry["at"]] = now.date()
            await run_entry(office, entry)
        await asyncio.sleep(CHECK_S)


async def run_entry(office: Office, entry: dict) -> None:
    log.info("Schedule: %s at %s", entry["name"], entry["at"])
    try:
        run = await office.run_mode(entry["mode"])
        if not run["ok"]:
            # One more try a minute later, for a light that was slow to answer the first time.
            await asyncio.sleep(RETRY_S)
            await office.run_mode(entry["mode"])
    except Exception:
        log.exception("Schedule: %s at %s failed", entry["name"], entry["at"])
