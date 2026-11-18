"""The brain's small web API, and the phone app itself, served on the office Wi-Fi."""

from __future__ import annotations

import fnmatch
import ipaddress
import json
import logging
from pathlib import Path

from aiohttp import web

from .office import Office

log = logging.getLogger("office.server")

OFFICE = web.AppKey("office", Office)


def host_ok(host: str) -> bool:
    """The names the app is opened at: the mini's own .local name, an IP address, or localhost.

    Any other name means a website pointed its own domain at this Wi-Fi to sneak past the browser's
    origin rules (DNS rebinding), so those requests are refused.
    """
    name = host.split("]")[0].lstrip("[") if host.startswith("[") else host.rsplit(":", 1)[0]
    name = name.lower().rstrip(".")
    if name == "localhost" or name.endswith(".local") or name.endswith(".ts.net"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def make_app(office: Office, config: dict, app_dir: Path | None = None) -> web.Application:
    allowed_origins: list[str] = config.get("allowed_origins", [])
    allowed_logins: list[str] = config.get("allowed_logins", [])

    def origin_ok(origin: str | None) -> bool:
        return bool(origin) and any(fnmatch.fnmatchcase(origin, pattern) for pattern in allowed_origins)

    @web.middleware
    async def guard(request: web.Request, handler):
        origin = request.headers.get("Origin")
        # The app the mini serves itself sends its own address as the origin.
        same_origin = origin == f"{request.scheme}://{request.host}"
        if not host_ok(request.host):
            response: web.StreamResponse = web.json_response({"error": f"{request.host} isn't this Mac"}, status=403)
        elif request.method == "OPTIONS":
            response = web.Response(status=204)
        elif allowed_logins and request.headers.get("Tailscale-User-Login") not in allowed_logins:
            response = web.json_response({"error": "This Tailscale account isn't allowed"}, status=403)
        elif request.method == "POST" and origin and not (same_origin or origin_ok(origin)):
            response = web.json_response({"error": f"{origin} isn't allowed"}, status=403)
        elif request.method == "POST" and request.content_type != "application/json":
            # Requiring JSON forces a browser preflight, so no other website can press a mode.
            response = web.json_response({"error": "Send JSON"}, status=415)
        else:
            try:
                response = await handler(request)
            except web.HTTPException as err:
                response = web.json_response({"error": err.reason}, status=err.status)
        if origin_ok(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Max-Age"] = "600"
            if request.headers.get("Access-Control-Request-Private-Network") == "true":
                response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Vary"] = "Origin"
        # The app's script files have their contents in their names, so they never change.
        immutable = request.path.startswith("/_next/static/") and response.status == 200
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-store"
        # Presses and refusals only. The app reads the state every few seconds, and those would bury the rest.
        if request.method == "POST" or response.status >= 400:
            log.info("%s %s from %s at %s -> %s", request.method, request.path, origin or "no origin",
                     request.host, response.status)
        return response

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "name": request.app[OFFICE].name})

    async def state(request: web.Request) -> web.Response:
        return web.json_response(request.app[OFFICE].state())

    async def run_mode(request: web.Request) -> web.Response:
        office = request.app[OFFICE]
        mode_id = request.match_info["mode"]
        if mode_id not in office.modes_by_id:
            raise web.HTTPNotFound(reason=f"No mode called {mode_id}")
        run = await office.run_mode(mode_id)
        return web.json_response({"run": run, "state": office.state()})

    async def set_device(request: web.Request) -> web.Response:
        office = request.app[OFFICE]
        device_id = request.match_info["device"]
        if device_id not in office.devices:
            raise web.HTTPNotFound(reason=f"No device called {device_id}")
        try:
            change = await request.json()
            result = await office.set_device(device_id, change)
        except (json.JSONDecodeError, ValueError, TypeError) as err:
            raise web.HTTPBadRequest(reason=str(err))
        return web.json_response({"result": result, "state": office.state()})

    async def on_startup(app: web.Application) -> None:
        await app[OFFICE].refresh_all()
        app[OFFICE].start_polling()
        app[OFFICE].start_schedule()

    async def on_cleanup(app: web.Application) -> None:
        await app[OFFICE].close()

    app = web.Application(middlewares=[guard])
    app[OFFICE] = office
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/modes/{mode}", run_mode)
    app.router.add_post("/api/devices/{device}", set_device)
    if app_dir and (app_dir / "index.html").is_file():
        # The phone app, built by deploy.sh. Open the mini's address in Safari and this is what loads.
        async def index(request: web.Request) -> web.FileResponse:
            return web.FileResponse(app_dir / "index.html")

        app.router.add_get("/", index)
        app.router.add_static("/", app_dir)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app
