import argparse
import subprocess
import sys

from .config import CONFIG_PATH, load_config


def main():
    parser = argparse.ArgumentParser(prog="voice-assistant", description="Voice assistant for Spotify and Snapchat.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="start the assistant (listens for the wake word and shortcut)")
    commands.add_parser("trigger", help="make the running assistant start listening (bind this to a shortcut)")
    do = commands.add_parser("do", help='run a typed command, e.g. voice-assistant do "pause"')
    do.add_argument("text", nargs="+")
    commands.add_parser("parse", help="show how a sentence would be understood, without doing it").add_argument("text", nargs="+")
    commands.add_parser("spotify-login", help="log in to Spotify (one time)")
    commands.add_parser("snapchat-login", help="log in to Snapchat Web (one time)")
    commands.add_parser("test-mic", help="record one command and print what Whisper heard")
    args = parser.parse_args()

    if args.command in ("trigger", "do"):
        from .assistant import send_to_daemon

        message = "listen" if args.command == "trigger" else "text " + " ".join(args.text)
        if not send_to_daemon(message):
            _notify("Voice assistant isn't running", "Start it with: voice-assistant run")
            sys.exit("The assistant isn't running. Start it with: voice-assistant run")
        return

    if args.command == "parse":
        from .intents import parse

        print(parse(" ".join(args.text)))
        return

    if not CONFIG_PATH.exists():
        print(f"Note: no {CONFIG_PATH.name} found, using defaults. Copy config.example.toml to get started.")
    config = load_config()

    if args.command == "spotify-login":
        from .spotify import Spotify

        Spotify(config).login()
    elif args.command == "snapchat-login":
        from .snapchat import Snapchat

        Snapchat(config).login()
    elif args.command == "test-mic":
        from .audio import Microphone
        from .listener import Listener

        config["wake_word"]["enabled"] = False
        mic = Microphone(config["speech"]["microphone"])
        listener = Listener(config, mic)
        print("Say something...")
        print(listener.listen() or "(heard nothing)")
        mic.close()
    elif args.command == "run":
        from .assistant import Assistant

        try:
            Assistant(config).run()
        except KeyboardInterrupt:
            pass


def _notify(title: str, body: str):
    subprocess.run(["notify-send", title, body], check=False)
