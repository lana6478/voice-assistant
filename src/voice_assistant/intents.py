"""Turns a sentence like "add this song to my gym playlist" into an Intent."""

import re
from dataclasses import dataclass, field


@dataclass
class Intent:
    name: str
    slots: dict = field(default_factory=dict)


FILLER = re.compile(
    r"^(?:(?:hey )?jarvis|alexa|hey mycroft|okay|ok|um|uh|so|and|please|"
    r"can you|could you|would you|will you|i want to|i'd like to|i want you to)\b\s*"
)

CURRENT_SONG = re.compile(
    r"^(?:this|that|it|this one|that one|the current|the current song|this song|that song|"
    r"this track|that track|the song|the track|what's playing|what is playing|the song that's playing)$"
)

LIKED_SONGS = re.compile(r"^(?:my )?(?:liked|like|loved|favou?rite)(?: songs?| tracks?| music)?$")

# (intent name, pattern). The first match wins, so more specific patterns come first.
PATTERNS = [
    # --- Snapchat ---
    ("snapchat_send", r"^(?:send|text) (?:a )?(?:snapchat |snap )?(?:message |snap |chat |text )?(?:on snapchat )?"
                      r"to (?P<who>.+?)(?: on snapchat)? (?:saying|that says|says|that) (?P<message>.+)$"),
    ("snapchat_send", r"^(?:send|text) (?P<who>.+?) (?:a )?(?:snapchat |snap )?(?:message|snap|chat|text)"
                      r"(?: on snapchat)? (?:saying|that says|says|that) (?P<message>.+)$"),
    ("snapchat_send", r"^(?:message|snapchat|snap|text) (?P<who>.+?)(?: on snapchat)? (?:saying|that says|that) (?P<message>.+)$"),
    ("snapchat_send", r"^tell (?P<who>(?:my )?\S+)(?: on snapchat)? (?:that )?(?P<message>.+)$"),
    # --- Spotify: library ---
    ("spotify_like", r"^(?:like|heart|save|favou?rite) (?:this|that|it|the current)(?: song| track| one)?$"),
    ("spotify_add_to_playlist", r"^(?:add|put|save) (?P<song>.+?) (?:to|in|into|on) (?:my |the )?(?P<playlist>.+?)(?: playlist)?$"),
    # --- Spotify: playback ---
    ("spotify_play_playlist", r"^(?:play|put on|start) (?:the )?playlist (?:called )?(?P<query>.+)$"),
    ("spotify_play_playlist", r"^(?:play|put on|start) (?:my |the )?(?P<query>.+?) playlist$"),
    ("spotify_play_album", r"^(?:play|put on) (?:the )?album (?:called )?(?P<query>.+)$"),
    ("spotify_play_artist", r"^(?:play|put on) (?:some )?(?:music |songs )?(?:by|from) (?P<query>.+)$"),
    ("spotify_play_artist", r"^(?:play|put on) (?:the )?artist (?P<query>.+)$"),
    ("spotify_pause", r"^(?:pause|stop|hold)(?: the)?(?: music| song| spotify| it| playback)?$"),
    ("spotify_resume", r"^(?:play|resume|continue|unpause|start)(?: the)?(?: music| song| spotify| it| playback| playing)?$"),
    ("spotify_next", r"^(?:next|skip)(?: this)?(?: song| track| one)?$|^(?:play the )?next (?:song|track)$"),
    ("spotify_previous", r"^(?:previous|last|go back|back)(?: to the)?(?: song| track| one)?$|^play the (?:previous|last) (?:song|track)$"),
    ("spotify_volume_set", r"^(?:set |turn )?(?:the )?volume (?:to |at )?(?P<level>\d{1,3})(?: percent)?$"),
    ("spotify_volume_up", r"^(?:volume up|turn (?:it|the volume|the music) up|turn up the (?:volume|music)|louder)$"),
    ("spotify_volume_down", r"^(?:volume down|turn (?:it|the volume|the music) down|turn down the (?:volume|music)|quieter)$"),
    ("spotify_shuffle", r"^(?:turn )?shuffle (?P<state>on|off)$|^(?:turn )?(?P<state2>on|off) shuffle$"),
    ("spotify_shuffle", r"^shuffle(?: (?:it|my music|the music|this))?$"),
    ("spotify_now_playing", r"^(?:what's|what is) (?:this song|this|playing|the song|the current song)(?: called)?$|^what (?:song|track) is (?:this|playing)$"),
    ("spotify_play_track", r"^(?:play|put on) (?:the song )?(?P<query>.+?)(?: by (?P<artist>.+?))?(?: on spotify)?$"),
    # --- General ---
    ("cancel", r"^(?:cancel|never ?mind|nothing|stop listening|forget it)$"),
]
PATTERNS = [(name, re.compile(pattern)) for name, pattern in PATTERNS]


def clean(text: str) -> str:
    text = text.lower().replace("%", " percent").replace("’", "'")
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    text = clean(text)
    previous = None
    while previous != text:
        previous = text
        text = FILLER.sub("", text).strip()
    return text


def _original_ending(original: str, normalized_part: str) -> str:
    """The last words of `original` matching `normalized_part`, keeping capitals and punctuation."""
    words = original.split()[-len(normalized_part.split()):]
    return " ".join(words).rstrip(".") or normalized_part


def parse(original: str) -> Intent | None:
    text = normalize(original)
    for name, pattern in PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        slots = {k: v for k, v in match.groupdict().items() if v}
        if name == "snapchat_send":
            slots["message"] = _original_ending(original, slots["message"])
        if name == "spotify_shuffle":
            state = slots.pop("state", None) or slots.pop("state2", None) or "on"
            slots = {"on": state == "on"}
        if name == "spotify_add_to_playlist":
            song = slots.pop("song")
            if LIKED_SONGS.match(slots["playlist"]) and CURRENT_SONG.match(song):
                return Intent("spotify_like")
            slots["song"] = None if CURRENT_SONG.match(song) else song
        return Intent(name, slots)
    return None


def is_yes(text: str) -> bool:
    return bool(re.match(r"^(?:yes|yeah|yep|yup|sure|send it|send|do it|go ahead|correct|ok|okay)\b", clean(text)))
