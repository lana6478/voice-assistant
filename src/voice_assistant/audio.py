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
        self.cmd = ["arecord", "-q", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw"]
        if device:
            self.cmd += ["-D", device]
        self.proc = None
        self.chunks: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=200)

    def start(self):
        if self.proc is not None:
            return
        self.chunks = queue.Queue(maxsize=200)
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE)
        threading.Thread(target=self._reader, args=(self.proc, self.chunks), daemon=True).start()

    def stop(self):
        if self.proc is not None:
            self.proc.terminate()
            self.proc.wait()
            self.proc = None

    def _reader(self, proc: subprocess.Popen, chunks: queue.Queue):
        while True:
            data = proc.stdout.read(CHUNK * 2)
            if len(data) < CHUNK * 2:
                if self.proc is proc:  # ended without us stopping it
                    chunks.put(None)
                return
            if chunks.full():
                chunks.get_nowait()
            chunks.put(np.frombuffer(data, dtype=np.int16))

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
        self.stop()


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
