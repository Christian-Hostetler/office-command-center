#!/bin/bash
# Installs the office brain on this Mac as a background service for this account.
# It starts when this account logs in, restarts if it ever stops, and needs no admin password.
# Run it on the Mac mini from this folder: ./install.sh   (deploy.sh does this for you)
set -euo pipefail

LABEL="com.office-command-center.brain"
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/office-brain.log"
DOMAIN="gui/$(id -u)"

# python-kasa needs Python 3.11 or newer, and the one macOS ships is older. pip also needs Python's
# XML module to load, which fails on a Homebrew Python built for a newer macOS than this one.
usable() { "$1" -c 'import sys, pyexpat; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; }

if ! usable "$DIR/.venv/bin/python" || ! "$DIR/.venv/bin/python" -m pip --version >/dev/null 2>&1; then
  PYTHON=""
  for candidate in /opt/homebrew/bin/python3 /opt/homebrew/opt/python@3.13/bin/python3.13 \
    /opt/homebrew/opt/python@3.12/bin/python3.12 /opt/homebrew/opt/python@3.11/bin/python3.11 \
    /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && usable "$candidate"; then
      PYTHON="$(command -v "$candidate")"
      break
    fi
  done
  if [ -z "$PYTHON" ]; then
    echo "This needs a working Python 3.11 or newer. Install one from python.org, then run this again."
    exit 1
  fi
  echo "Setting up $("$PYTHON" -V) in $DIR/.venv"
  "$PYTHON" -m venv --clear "$DIR/.venv"
fi
"$DIR/.venv/bin/python" -m pip install --quiet --disable-pip-version-check -r "$DIR/requirements.txt"
PORT="$("$DIR/.venv/bin/python" -c 'import json, sys; print(json.load(open(sys.argv[1])).get("listen", {}).get("port", 8787))' "$DIR/config.json")"

# A launchd agent runs inside this account's login session, so the account has to be logged in at the Mac.
if ! launchctl print "$DOMAIN" >/dev/null 2>&1; then
  echo "$(id -un) has to be logged in at the Mac for the brain to run. Log in there, then run this again."
  exit 1
fi

mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DIR/.venv/bin/python</string>
    <string>-m</string>
    <string>office_brain</string>
    <string>serve</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

# Reload it every time, so new code and settings take effect.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
for attempt in $(seq 1 10); do
  launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null && break
  [ "$attempt" = 10 ] && { echo "launchd wouldn't load $PLIST"; exit 1; }
  sleep 0.5
done

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    ADDRESS="http://$( (scutil --get LocalHostName 2>/dev/null || hostname -s) | tr "[:upper:]" "[:lower:]").local"
    [ "$PORT" = 80 ] || ADDRESS="$ADDRESS:$PORT"
    echo "The brain is running and starts by itself from now on."
    echo "On the office Wi-Fi, open $ADDRESS on the phone."
    echo "Log: $LOG"
    exit 0
  fi
  sleep 0.5
done
echo "The brain didn't start. The end of the log:"
tail -20 "$LOG"
exit 1
