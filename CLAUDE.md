# Office Command Center

A phone remote for an office. One tap runs a mode that sets every Key Light, lamp and camera plug at once. Read this whole file before changing anything. The README is the setup guide.

## How it fits together

- **brain/** is a Python service (aiohttp plus python-kasa 0.12) that runs on a Mac that stays on. It talks to each device directly over the office Wi-Fi, serves the phone app, and runs the daily schedule. There's no cloud and no VPN.
- **web/** is the phone app (Next.js 16). `brain/deploy.sh` builds it as plain files with `OFFICE_LOCAL=1`, and the brain serves them from `brain/app/`. The phone opens the Mac's `.local` name on the Wi-Fi.
- Built without `OFFICE_LOCAL`, the same app is a demo with pretend devices, or it reaches a brain at an address saved in its Settings.

## Devices, modes and the schedule

All of it lives in `brain/config.json`.

- **devices**: `keylight` is an Elgato Key Light, through its local HTTP API on port 9123 with no login. `plug` is a TP-Link Kasa plug through python-kasa, local only. A device with no `host` is skipped. `off_delay_s` makes the brain wait before it cuts a plug's power.
- **modes**: each one sets every device to `"on"`, `"off"`, or `{ "brightness": 45, "kelvin": 5200 }`. Key Lights take color as mireds (1,000,000 / kelvin, from 143 to 344), and the brain converts. A mode fades the lights over `fade_ms`.
- **schedule**: entries like `{ "at": "08:00", "mode": "deep-work" }`, by the Mac's clock. An entry can run up to 5 minutes late after a restart, never later, and it retries once a minute later if a device didn't answer. A typo stops the brain from starting, so it's caught at deploy instead of on a morning.
- If a mode's light values change, update the demo in `web/lib/brain.ts` to match, and the fade test in `brain/tests/test_office.py`, which checks Filming's main light.

## Rules that never bend

- **The Key Lights stay powered all the time on a normal outlet. Never put them on a smart plug.**
- **The camera plug never cuts power while the camera is recording.** The camera device has `off_delay_s: 5`, so the brain waits before turning it off. Keep that delay.
- **Never expose the brain to the open internet.** It only answers to a .local name, an IP address, localhost or a Tailscale .ts.net name. Any other Host header gets a 403, which blocks DNS rebinding. A POST from another website is refused unless its origin is in `allowed_origins`, and a POST has to be JSON, which forces a browser preflight.
- **Passwords are only typed by the person, at a hidden prompt.** Never ask for one in chat, and never put one in a file, a command line argument or a log. `plug-wifi` and `kasa-login` read them from a hidden prompt or a pipe, and `kasa-login` saves only the login hash.

## Changing things

- **A mode, the schedule or a device**: edit `brain/config.json`, then run `MINI=you@your-mac-mini.local brain/deploy.sh` from the laptop. It builds the app, copies everything to the Mac over SSH, and restarts the brain.
- **Tests**: `cd brain && ../.venv/bin/python -m unittest discover -s tests -t .`. Run them before every deploy.
- **One device at a time**: `cd brain && ../.venv/bin/python -m office_brain check [id]` switches each one and times it.
- **Find devices**: `../.venv/bin/python -m office_brain discover`.
- **By hand**: POST JSON like `{"on":true,"brightness":45,"kelvin":5200}` to `/api/devices/<id>`, or `{}` to `/api/modes/<id>`, with `Content-Type: application/json`. `GET /api/state` shows everything.
- **A pretend office to work against**: `cd brain && ../.venv/bin/python -m tests.fakes`, then `cd web && npm run dev`, and in Settings use `http://127.0.0.1:8787`.
- **A plug the Kasa app won't set up**: hold the plug's button until it blinks amber and green, put the laptop on the plug's own Wi-Fi, and run `../.venv/bin/python -m office_brain plug-wifi <Wi-Fi name>`. The person types the Wi-Fi password at the hidden prompt. Holding the button that way also clears the plug's TP-Link account binding but keeps its name.

## The Mac that runs the brain

- `install.sh` runs it as a LaunchAgent, `com.office-command-center.brain`, in the logged-in user's session with KeepAlive, so it restarts itself if it crashes. That user has to stay logged in at the Mac.
- It listens on 0.0.0.0:80. macOS lets a normal user use port 80.
- The log is at `~/Library/Logs/office-brain.log`. It records every POST and every refusal, so look there first when the phone can't connect.
- macOS Local Network privacy blocks Python from reaching the devices until Python is turned on in System Settings, Privacy & Security, Local Network. A Python upgrade can turn that switch back off. The router always answers, so test against a light, not the router.
- `install.sh` needs a Python 3.11 or newer whose XML module loads, because pip needs it. A Homebrew Python built for a newer macOS than the one installed can fail that, so it tries the other installs in turn.

## Next.js gotchas

- `next.config.ts` turns on `output: "export"` only when `OFFICE_LOCAL=1`. Static export can't use cacheComponents or partialPrefetching, so those stay on for the hosted demo only.
- The web manifest is a plain file in `web/public/manifest.webmanifest`. A `manifest.ts` route breaks the export.
- `LOCAL` in `web/lib/brain.ts` makes the app use its own address as the brain and hides the address field in Settings.
