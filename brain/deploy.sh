#!/bin/bash
# Copies the brain to the Mac mini and restarts it there. Run it from your laptop with your own login
# on the mini and its name on the Wi-Fi: MINI=you@your-mac-mini.local brain/deploy.sh
# Both Macs have to be on the same network.
set -euo pipefail

MINI="${MINI:?Set MINI to your login on the Mac mini, like MINI=you@your-mac-mini.local brain/deploy.sh}"
KEY="${KEY:-$HOME/.ssh/id_ed25519}"
DIR="$(cd "$(dirname "$0")" && pwd)"
SSH="ssh -i $KEY -o IdentitiesOnly=yes"

# The phone app, built as plain files the brain serves on the office Wi-Fi.
(cd "$DIR/../web" && rm -rf out && OFFICE_LOCAL=1 npx --no-install next build >/dev/null)
rm -rf "$DIR/app" && cp -R "$DIR/../web/out" "$DIR/app"

$SSH -n "$MINI" 'mkdir -p ~/office-command-center/brain'
rsync -az --delete --exclude .venv --exclude __pycache__ --exclude .env -e "$SSH" \
  "$DIR/" "$MINI:office-command-center/brain/"
# The Kasa login from `python -m office_brain kasa-login`, if there is one. It's a hash, not the password.
LOGIN="$HOME/.config/office-command-center/kasa.json"
if [ -f "$LOGIN" ]; then
  $SSH "$MINI" 'umask 077 && mkdir -p ~/.config/office-command-center && cat > ~/.config/office-command-center/kasa.json' <"$LOGIN"
fi
$SSH -n "$MINI" 'cd ~/office-command-center/brain && ./install.sh'
