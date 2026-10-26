import os
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "voice-assistant"
SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "voice-assistant.sock"

DEFAULTS = {
    "wake_word": {"enabled": True, "model": "hey_jarvis", "threshold": 0.5},
    "speech": {
        "model": "small.en",
        "device": "cpu",
        "microphone": "",
        "start_timeout": 5.0,
        "end_silence": 0.9,
    },
    "feedback": {"speak": True, "chime": True},
    "spotify": {
        "client_id": "",
        "client_secret": "",
        "redirect_uri": "http://127.0.0.1:8888/callback",
    },
    "snapchat": {"confirm": True, "headless": False, "browser_channel": "chrome", "contacts": {}},
}


def load_config() -> dict:
    user = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            user = tomllib.load(f)
    config = {}
    for section, defaults in DEFAULTS.items():
        config[section] = {**defaults, **user.get(section, {})}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config
