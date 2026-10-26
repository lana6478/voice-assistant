"""The main loop: wait for the wake word or shortcut, listen, work out what was meant, do it."""

import os
import queue
import socket
import threading
import traceback

from . import intents
from .audio import Feedback, Microphone
from .config import SOCKET_PATH
from .listener import Listener
from .popup import SendPopup
from .snapchat import Snapchat, SnapchatError
from .spotify import Spotify, SpotifyError

class Assistant:
    def __init__(self, config: dict):
        self.config = config
        self.feedback = Feedback(**config["feedback"])
        self.spotify = Spotify(config)
        self.snapchat = Snapchat(config)
        self.requests: queue.Queue = queue.Queue()
        self.mic = Microphone(config["speech"]["microphone"])
        self.listener = Listener(config, self.mic)

    def run(self):
        threading.Thread(target=self._serve_socket, daemon=True).start()
        wake = self.config["wake_word"]
        how = f"say \"{wake['model'].replace('_', ' ')}\" or press your shortcut" if wake["enabled"] else "press your shortcut"
        print(f"Ready - {how}.", flush=True)
        try:
            while True:
                kind, text = self.listener.wait_for_activation(self.requests)
                if kind == "listen":
                    self.feedback.chime()
                    text = self.listener.listen()
                    if not text:
                        print("(heard nothing)", flush=True)
                        continue
                self.handle(text)
                self.mic.flush()
        finally:
            self.snapchat.close()
            self.mic.close()
            SOCKET_PATH.unlink(missing_ok=True)

    def handle(self, text: str):
        intent = intents.parse(text)
        if intent is None:
            self.feedback.error()
            self.feedback.say("Sorry, I don't know that.")
            return
        print(f"intent: {intent.name} {intent.slots}", flush=True)
        try:
            reply = self.dispatch(intent)
        except (SpotifyError, SnapchatError) as e:
            self.feedback.error()
            reply = str(e)
        except Exception as e:
            traceback.print_exc()
            self.feedback.error()
            reply = f"Something went wrong: {e}"
        if reply:
            self.feedback.say(reply)

    def dispatch(self, intent: intents.Intent) -> str | None:
        s = intent.slots
        sp = self.spotify
        match intent.name:
            case "spotify_pause":
                sp.pause()
            case "spotify_resume":
                sp.resume()
            case "spotify_next":
                sp.next()
            case "spotify_previous":
                sp.previous()
            case "spotify_play_track":
                return sp.play_track(s["query"], s.get("artist"))
            case "spotify_play_album":
                return sp.play_album(s["query"])
            case "spotify_play_artist":
                return sp.play_artist(s["query"])
            case "spotify_play_playlist":
                return sp.play_playlist(s["query"])
            case "spotify_add_to_playlist":
                return sp.add_to_playlist(s["playlist"], s.get("song"))
            case "spotify_like":
                return sp.like_current()
            case "spotify_now_playing":
                return sp.now_playing()
            case "spotify_volume_set":
                return sp.set_volume(int(s["level"]))
            case "spotify_volume_up":
                sp.change_volume(+10)
            case "spotify_volume_down":
                sp.change_volume(-10)
            case "spotify_shuffle":
                return sp.shuffle(s["on"])
            case "snapchat_send":
                return self.send_snapchat(s["who"], s["message"])
            case "cancel":
                return "Okay."
        return None

    def send_snapchat(self, who: str, message: str) -> str:
        popup = SendPopup(who, message)
        try:
            # Find the chat first so the confirmation uses their real Snapchat name.
            name = self.snapchat.open_chat(who)
            if self.config["snapchat"]["confirm"]:
                popup.update("Say “yes” to send", "waiting", to=name)
                self.feedback.say(f"Send {message} to {name}?")
                answer = self.listener.listen()
                if not answer or not intents.is_yes(answer):
                    popup.finish("Cancelled", "failed")
                    return "Okay, I won't send it."
            popup.update("Sending…", to=name)
            reply = self.snapchat.send_to_open_chat(message)
        except Exception:
            popup.finish("Couldn't send", "failed", close_after=4)
            raise
        popup.finish("Sent ✓", "done")
        return reply

    def _serve_socket(self):
        """Accepts commands from `voice-assistant trigger` (your keyboard shortcut) and
        `voice-assistant do "..."`."""
        SOCKET_PATH.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o600)
        server.listen()
        while True:
            conn, _ = server.accept()
            with conn:
                message = conn.recv(4096).decode().strip()
                if message == "listen":
                    self.requests.put(("listen", None))
                elif message.startswith("text "):
                    self.requests.put(("text", message[5:]))
                conn.sendall(b"ok")


def send_to_daemon(message: str) -> bool:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(SOCKET_PATH))
    except (FileNotFoundError, ConnectionRefusedError):
        return False
    with client:
        client.sendall(message.encode())
        client.recv(16)
    return True
