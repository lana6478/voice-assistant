"""Spotify control.

Basic controls (play/pause/next/previous/play a specific song) go through MPRIS, the
Linux D-Bus media interface the Spotify desktop app exposes, so they work on free
accounts and are instant. Search, playlists, likes, volume and shuffle use the
Spotify Web API (spotipy).
"""

import difflib
import shutil
import socket
import subprocess
import time

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

from .config import DATA_DIR

SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-library-modify",
])

MPRIS_NAME = "org.mpris.MediaPlayer2.spotify"
MPRIS_PATH = "/org/mpris/MediaPlayer2"


class SpotifyError(Exception):
    """An error with a message that's fine to read out to the user."""


class Spotify:
    def __init__(self, config: dict):
        self.config = config["spotify"]
        self._api = None

    # ---------- setup ----------

    def auth_manager(self, open_browser: bool = True) -> SpotifyOAuth:
        if not self.config["client_id"] or not self.config["client_secret"]:
            raise SpotifyError("Spotify isn't set up yet. Add your client ID and secret to config dot toml.")
        return SpotifyOAuth(
            client_id=self.config["client_id"],
            client_secret=self.config["client_secret"],
            redirect_uri=self.config["redirect_uri"],
            scope=SCOPES,
            cache_handler=CacheFileHandler(cache_path=str(DATA_DIR / "spotify-token.json")),
            open_browser=open_browser,
        )

    def login(self):
        """Interactive one-time login; saves a token the daemon reuses."""
        api = spotipy.Spotify(auth_manager=self.auth_manager())
        print(f"Logged in to Spotify as {api.me()['display_name']}.")

    @property
    def api(self) -> spotipy.Spotify:
        if self._api is None:
            manager = self.auth_manager(open_browser=False)
            if manager.get_cached_token() is None:
                raise SpotifyError("You need to log in to Spotify first. Run voice assistant spotify login.")
            self._api = spotipy.Spotify(auth_manager=manager, retries=0)
        return self._api

    # ---------- MPRIS (desktop app) ----------

    def _mpris(self, method: str, *args: str) -> bool:
        cmd = ["dbus-send", "--print-reply", f"--dest={MPRIS_NAME}", MPRIS_PATH,
               f"org.mpris.MediaPlayer2.Player.{method}", *args]
        return subprocess.run(cmd, capture_output=True).returncode == 0

    def _app_running(self) -> bool:
        cmd = ["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.DBus",
               "/org/freedesktop/DBus", "org.freedesktop.DBus.NameHasOwner", f"string:{MPRIS_NAME}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return "boolean true" in result.stdout

    def ensure_app_running(self):
        if self._app_running():
            return
        if not shutil.which("spotify"):
            raise SpotifyError("I can't find the Spotify app.")
        subprocess.Popen(["spotify"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(40):
            time.sleep(0.5)
            if self._app_running():
                time.sleep(2)  # give it a moment to connect before we send commands
                return
        raise SpotifyError("Spotify didn't start in time.")

    def pause(self):
        self.ensure_app_running()
        self._mpris("Pause")

    def resume(self):
        self.ensure_app_running()
        self._mpris("Play")

    def next(self):
        self.ensure_app_running()
        self._mpris("Next")

    def previous(self):
        self.ensure_app_running()
        self._mpris("Previous")

    # ---------- playing things ----------

    def _play(self, uri: str):
        """Play a track/album/playlist/artist URI. Uses the Web API (Premium) if it can,
        otherwise asks the desktop app to open it directly."""
        self.ensure_app_running()
        try:
            device = self._local_device()
            if uri.startswith("spotify:track:"):
                self.api.start_playback(device_id=device, uris=[uri])
            else:
                self.api.start_playback(device_id=device, context_uri=uri)
            return
        except spotipy.SpotifyException as e:
            if e.http_status not in (403, 404):
                raise
        except SpotifyError:
            pass
        self._mpris("OpenUri", f"string:{uri}")

    def _local_device(self) -> str | None:
        devices = self.api.devices()["devices"]
        if not devices:
            return None
        hostname = socket.gethostname().lower()
        for device in devices:
            if device["name"].lower() == hostname:
                return device["id"]
        for device in devices:
            if device["is_active"]:
                return device["id"]
        return devices[0]["id"]

    def play_track(self, query: str, artist: str | None = None) -> str:
        search = f"track:{query} artist:{artist}" if artist else query
        items = self.api.search(q=search, type="track", limit=1)["tracks"]["items"]
        if not items and artist:
            items = self.api.search(q=f"{query} {artist}", type="track", limit=1)["tracks"]["items"]
        if not items:
            raise SpotifyError(f"I couldn't find {query}.")
        track = items[0]
        self._play(track["uri"])
        return f"Playing {track['name']} by {track['artists'][0]['name']}."

    def play_album(self, query: str) -> str:
        items = self.api.search(q=query, type="album", limit=1)["albums"]["items"]
        if not items:
            raise SpotifyError(f"I couldn't find the album {query}.")
        self._play(items[0]["uri"])
        return f"Playing {items[0]['name']} by {items[0]['artists'][0]['name']}."

    def play_artist(self, query: str) -> str:
        items = self.api.search(q=query, type="artist", limit=1)["artists"]["items"]
        if not items:
            raise SpotifyError(f"I couldn't find {query}.")
        self._play(items[0]["uri"])
        return f"Playing {items[0]['name']}."

    def play_playlist(self, query: str) -> str:
        playlist = self._find_my_playlist(query, editable_only=False)
        if playlist is None:
            items = [p for p in self.api.search(q=query, type="playlist", limit=5)["playlists"]["items"] if p]
            if not items:
                raise SpotifyError(f"I couldn't find a playlist called {query}.")
            playlist = items[0]
        self._play(playlist["uri"])
        return f"Playing {playlist['name']}."

    # ---------- library ----------

    def _my_playlists(self) -> list[dict]:
        playlists = []
        page = self.api.current_user_playlists(limit=50)
        while page:
            playlists += [p for p in page["items"] if p]
            page = self.api.next(page) if page["next"] else None
        return playlists

    def _find_my_playlist(self, name: str, editable_only: bool) -> dict | None:
        playlists = self._my_playlists()
        if editable_only:
            me = self.api.me()["id"]
            playlists = [p for p in playlists if p["owner"]["id"] == me or p.get("collaborative")]
        by_name = {p["name"].lower(): p for p in playlists}
        name = name.lower().strip()
        if name in by_name:
            return by_name[name]
        for playlist_name, playlist in by_name.items():
            if name in playlist_name or playlist_name in name:
                return playlist
        close = difflib.get_close_matches(name, by_name.keys(), n=1, cutoff=0.6)
        return by_name[close[0]] if close else None

    def _current_track(self) -> dict:
        playing = self.api.current_user_playing_track()
        if not playing or not playing.get("item") or playing["item"].get("type") != "track":
            raise SpotifyError("Nothing is playing right now.")
        return playing["item"]

    def add_to_playlist(self, playlist_name: str, song: str | None = None) -> str:
        playlist = self._find_my_playlist(playlist_name, editable_only=True)
        if playlist is None:
            raise SpotifyError(f"I couldn't find a playlist of yours called {playlist_name}.")
        if song:
            items = self.api.search(q=song, type="track", limit=1)["tracks"]["items"]
            if not items:
                raise SpotifyError(f"I couldn't find {song}.")
            track = items[0]
        else:
            track = self._current_track()
        self.api.playlist_add_items(playlist["id"], [track["uri"]])
        return f"Added {track['name']} to {playlist['name']}."

    def like_current(self) -> str:
        track = self._current_track()
        self.api.current_user_saved_tracks_add([track["id"]])
        return f"Added {track['name']} to your liked songs."

    def now_playing(self) -> str:
        track = self._current_track()
        return f"This is {track['name']} by {', '.join(a['name'] for a in track['artists'])}."

    # ---------- volume / shuffle (Web API needs Premium) ----------

    def set_volume(self, level: int) -> str:
        level = max(0, min(100, level))
        try:
            self.api.volume(level)
        except spotipy.SpotifyException:
            _system_volume(f"{level}%")
        return f"Volume {level} percent."

    def change_volume(self, step: int):
        try:
            playback = self.api.current_playback()
            current = playback["device"]["volume_percent"] if playback else None
            if current is None:
                raise SpotifyError("no device")
            self.api.volume(max(0, min(100, current + step)))
        except (spotipy.SpotifyException, SpotifyError):
            _system_volume(f"{abs(step)}%{'+' if step > 0 else '-'}")

    def shuffle(self, on: bool) -> str:
        try:
            self.api.shuffle(on)
        except spotipy.SpotifyException as e:
            if e.http_status == 403:
                raise SpotifyError("Changing shuffle needs Spotify Premium.")
            raise
        return f"Shuffle {'on' if on else 'off'}."


def _system_volume(change: str):
    """Fallback when the Web API can't change Spotify's volume: change the system volume."""
    subprocess.run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", change], check=False)
