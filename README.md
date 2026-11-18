# Office Command Center

One tap on your phone sets up your whole office: the Key Lights, the lamps and the camera. I built it with Claude Code for my own office, and you can set it up for yours.

Want to see it first? The demo at https://office-command.vercel.app runs pretend devices right in your browser.

## How it works

- **brain/** is a small Python service that runs on a Mac that stays on, like a Mac mini. It talks to each light and plug straight over your Wi-Fi, serves the phone app, and runs your daily schedule. Nothing goes through the cloud.
- **web/** is the phone app. The brain serves it on your Wi-Fi, so you open your Mac's name in Safari, add it to your Home Screen, and it opens like any other app.

## What you need

- A Mac that stays on and stays on your office Wi-Fi, with Python 3.11 or newer. Mine is a Mac mini.
- A laptop with Python 3.11 or newer and Node.js 20 or newer, to set everything up.
- Elgato Key Lights. The brain controls them over your Wi-Fi with no login.
- Kasa smart plugs for anything that just turns on and off, like lamps or a camera. I use the EP10, which only joins 2.4 GHz Wi-Fi.

## Set it up

1. On your laptop, from this folder, install what it needs with `python3 -m venv .venv && .venv/bin/pip install -r brain/requirements.txt`, then `cd web && npm install`.
2. Set up each Key Light in Elgato Control Center and each Kasa plug in the Kasa app, on the same Wi-Fi as your Mac. Never put a Key Light on a smart plug.
3. Every command from here runs in the brain folder, so `cd brain` first. If the Kasa app says it can't find any networks, you can skip it: hold the plug's button until it blinks amber and green, put your laptop on the plug's own Wi-Fi (its name starts with TP-Link_Smart Plug), and run `../.venv/bin/python -m office_brain plug-wifi YourWiFiName`. Then type your Wi-Fi password at the hidden prompt.
4. Find your devices with `../.venv/bin/python -m office_brain discover`. Put each IP address in `config.json` as that device's `"host"`, and reserve each one in your router so it never changes.
5. If discover says a plug "did not match our challenge", its firmware wants your TP-Link login. Run `../.venv/bin/python -m office_brain kasa-login` once and type it at the hidden prompt. Only a hash of the login is saved, never the password, and deploy copies it to the Mac.
6. Test each device one at a time with `../.venv/bin/python -m office_brain check`.
7. On the Mac that runs the brain, turn on Remote Login in System Settings, General, Sharing. Then let your laptop's SSH key log in to it with `ssh-copy-id -i ~/.ssh/id_ed25519 you@your-mac-mini.local`.
8. Send the brain over with `MINI=you@your-mac-mini.local ./deploy.sh`, using your user name on that Mac and its name on the Wi-Fi. It builds the phone app, copies everything over, and starts the brain as a background service that restarts itself if it ever stops. It logs in with `~/.ssh/id_ed25519` unless you set `KEY` to another key, and that user has to stay logged in on the Mac.
9. On that Mac, signed in as that user, open System Settings, then Privacy & Security, then Local Network, and turn on Python. macOS keeps the brain off your network until you do. A Python update can turn it back off, so if every device ever shows offline at once, check this first.
10. On your phone, on the office Wi-Fi, open the address deploy printed at the end, like `http://your-mac-mini.local`, in Safari. Tap Share, then Add to Home Screen.

## Make it yours

Everything about your office lives in `brain/config.json`.

- **devices** are your lights and plugs. A device with no `host` is skipped until you add one, and `off_delay_s` makes the brain wait that many seconds before it cuts a plug's power.
- **modes** are the buttons on your phone. Each one sets every device to `"on"`, `"off"`, or a Key Light's brightness and color, like `{ "brightness": 45, "kelvin": 5200 }`. Key Lights go from 2900K, the warmest, up to 7000K.
- **schedule** runs a mode at the same time every day, by the Mac's clock. If the brain restarts right then, an entry can still run up to 5 minutes late, never later, and it tries once more a minute later if a device didn't answer.

After any change, run the same deploy command again.

## Rules it keeps

- **Key Lights stay on a normal outlet with the power always on.** They need power to stay on your Wi-Fi, and that's how the brain reaches them.
- **A camera plug waits before it cuts the power.** The camera in the config waits 5 seconds, so a camera that's recording has time to finish writing first.
- **The brain never faces the internet.** It only answers to your Mac's .local name, an IP address or localhost, and it turns away presses that come from other websites, so a web page can't flip your lights. Keep it on your own Wi-Fi.
- **A password only goes in at a hidden prompt.** Nothing here saves a password, puts one in a file or writes one to a log.

## Try it with no gear

From this folder, run a pretend office with `cd brain && ../.venv/bin/python -m tests.fakes`. In another window, start the app with `cd web && npm run dev`, open http://localhost:3000, and in Settings use `http://127.0.0.1:8787`.

The brain's tests run against the same pretend devices: `cd brain && ../.venv/bin/python -m unittest discover -s tests -t .`

## Change it with Claude Code

`CLAUDE.md` explains the whole project to Claude Code, so you can open this folder in it and ask for new modes, new devices or a new schedule in plain words.

👉 Want my team to build you something? https://loadbearinghq.com/build

It's MIT licensed, so you're free to use it and change it. See [LICENSE](LICENSE).
