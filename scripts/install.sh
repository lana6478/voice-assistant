#!/usr/bin/env bash
# Sets up the GNOME keyboard shortcut and starts the assistant automatically when you log in.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$PROJECT_DIR/.venv/bin/voice-assistant"
SHORTCUT="${1:-<Super><Alt>v}"

cd "$PROJECT_DIR"
uv sync

# --- Keyboard shortcut (GNOME custom shortcut that runs `voice-assistant trigger`) ---
KEY_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/voice-assistant/"
SCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$KEY_PATH"
EXISTING="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)"
if [[ "$EXISTING" != *"$KEY_PATH"* ]]; then
    if [[ "$EXISTING" == "@as []" || "$EXISTING" == "[]" ]]; then
        NEW="['$KEY_PATH']"
    else
        NEW="${EXISTING%]}, '$KEY_PATH']"
    fi
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$NEW"
fi
gsettings set "$SCHEMA" name "'Voice assistant'"
gsettings set "$SCHEMA" command "\"'$BIN' trigger\""
gsettings set "$SCHEMA" binding "'$SHORTCUT'"
echo "Shortcut $SHORTCUT -> voice-assistant trigger"

# --- Start on login (systemd user service) ---
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/voice-assistant.service <<SERVICE
[Unit]
Description=Voice assistant (Spotify + Snapchat)
PartOf=graphical-session.target
After=graphical-session.target pipewire.service

[Service]
ExecStart="$BIN" run
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
SERVICE
systemctl --user daemon-reload
systemctl --user enable --now voice-assistant.service
echo "Assistant service started. Logs: journalctl --user -u voice-assistant -f"
