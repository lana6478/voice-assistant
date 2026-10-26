"""Wake word detection and speech-to-text, both running offline."""

import queue
import time
from pathlib import Path

import numpy as np

from .audio import CHUNK, SAMPLE_RATE, Microphone

CHUNK_SECONDS = CHUNK / SAMPLE_RATE
MAX_COMMAND_SECONDS = 12
SPEECH_PROBABILITY = 0.5

# Nudges Whisper towards the words we expect to hear.
WHISPER_PROMPT = (
    "Play, pause, resume, skip, next song, previous song, volume, shuffle. "
    "Add this song to my playlist. Send a message on Snapchat to Sam saying hello."
)


class Listener:
    def __init__(self, config: dict, mic: Microphone):
        self.mic = mic
        self.speech = config["speech"]

        from openwakeword.vad import VAD

        self.vad = VAD()

        self.wake_model = None
        wake = config["wake_word"]
        if wake["enabled"]:
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            model = wake["model"]
            if not Path(model).exists():
                download_models(model_names=[model])
            self.wake_model = Model(wakeword_models=[model], inference_framework="onnx")
            self.wake_threshold = wake["threshold"]
            mic.start()  # the wake word needs the mic on all the time

        from faster_whisper import WhisperModel

        device = self.speech["device"]
        compute_type = "int8" if device == "cpu" else "float16"
        print(f"Loading Whisper model '{self.speech['model']}' on {device}...", flush=True)
        self.whisper = WhisperModel(self.speech["model"], device=device, compute_type=compute_type)

    def wait_for_activation(self, requests: queue.Queue) -> tuple[str, str | None]:
        """Block until the wake word is heard or a request arrives from the socket
        (the keyboard shortcut, or a typed command). Returns (kind, typed text)."""
        if self.wake_model is None:
            return requests.get()
        while True:
            chunk = self.mic.read(timeout=0.2)
            try:
                return requests.get_nowait()
            except queue.Empty:
                pass
            if chunk is None:
                continue
            scores = self.wake_model.predict(chunk)
            if max(scores.values()) >= self.wake_threshold:
                self.wake_model.reset()
                return ("listen", None)

    def record_command(self) -> np.ndarray | None:
        """Record until the user stops talking. Returns None if they never started."""
        self.mic.flush()
        self.vad.reset_states()
        chunks = []
        started = False
        silent_for = 0.0
        waited = 0.0
        while True:
            chunk = self.mic.read()
            chunks.append(chunk)
            speaking = self.vad.predict(chunk, frame_size=640) > SPEECH_PROBABILITY
            if not started:
                waited += CHUNK_SECONDS
                if speaking:
                    started = True
                    chunks = chunks[-4:]  # keep a little audio from just before speech started
                elif waited > self.speech["start_timeout"]:
                    return None
                continue
            silent_for = 0.0 if speaking else silent_for + CHUNK_SECONDS
            if silent_for >= self.speech["end_silence"] or len(chunks) * CHUNK_SECONDS > MAX_COMMAND_SECONDS:
                return np.concatenate(chunks)

    def transcribe(self, audio: np.ndarray) -> str:
        start = time.monotonic()
        samples = audio.astype(np.float32) / 32768.0
        segments, _ = self.whisper.transcribe(
            samples, language="en", beam_size=5, initial_prompt=WHISPER_PROMPT, vad_filter=True
        )
        text = " ".join(s.text for s in segments).strip()
        print(f"you said: {text!r} ({time.monotonic() - start:.1f}s)", flush=True)
        return text

    def listen(self) -> str | None:
        # Without a wake word the mic only needs to be on while we're listening.
        if self.wake_model is None:
            self.mic.start()
            try:
                audio = self.record_command()
            finally:
                self.mic.stop()
        else:
            audio = self.record_command()
        if audio is None:
            return None
        return self.transcribe(audio) or None
