"""Microphone input (via arecord, so no PortAudio needed) and audio/spoken feedback."""

import queue
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
CHUNK = 1280  # 80 ms, the frame size openWakeWord expects

CHIME = Path("/usr/share/sounds/freedesktop/stereo/message.oga")
ERROR_SOUND = Path("/usr/share/sounds/freedesktop/stereo/dialog-warning.oga")


class Microphone:
    """Reads the mic on a background thread so audio never piles up while we're busy."""

    def __init__(self, device: str = ""):
        cmd = ["arecord", "-q", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw"]
        if device:
            cmd += ["-D", device]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        self.chunks: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=200)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while True:
            data = self.proc.stdout.read(CHUNK * 2)
            if len(data) < CHUNK * 2:
                self.chunks.put(None)
                return
            if self.chunks.full():
                self.chunks.get_nowait()
            self.chunks.put(np.frombuffer(data, dtype=np.int16))

    def read(self, timeout: float | None = None) -> np.ndarray | None:
        """Next 80 ms chunk, or None if `timeout` passes first."""
        try:
            chunk = self.chunks.get(timeout=timeout)
        except queue.Empty:
            return None
        if chunk is None:
            raise RuntimeError("Microphone stopped sending audio (is arecord working?)")
        return chunk

    def flush(self):
        """Throw away buffered audio, e.g. the assistant's own voice."""
        while not self.chunks.empty():
            self.chunks.get_nowait()

    def close(self):
        self.proc.terminate()


def rms(chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))


class Feedback:
    def __init__(self, speak: bool = True, chime: bool = True):
        self.speak_enabled = speak and shutil.which("spd-say") is not None
        self.chime_enabled = chime

    def say(self, text: str):
        print(f"assistant: {text}", flush=True)
        if self.speak_enabled:
            subprocess.run(["spd-say", "-w", text], check=False)

    def chime(self):
        self._play(CHIME)

    def error(self):
        self._play(ERROR_SOUND)

    def _play(self, sound: Path):
        if self.chime_enabled and sound.exists():
            subprocess.run(["pw-play", str(sound)], check=False, stderr=subprocess.DEVNULL)
