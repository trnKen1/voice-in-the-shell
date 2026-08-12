"""One-time voice enrollment for speaker filtering.

Records a short sample of your voice via the default microphone, computes a
Resemblyzer reference embedding, and saves it to voice_profile.npy. The
active-listening pipeline (audio_pipeline.py) compares every detected
utterance against this profile before letting it through to STT.

Run once: python enroll_voice.py
Re-run any time to replace the saved profile.
"""

import os
import sys
import time

import numpy as np
import sounddevice as sd
from resemblyzer import VoiceEncoder, preprocess_wav

SAMPLE_RATE = 16000
DURATION_SECONDS = 15
COUNTDOWN_SECONDS = 3
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "voice_profile.npy")


def record(seconds: int, sample_rate: int) -> np.ndarray:
    # A built-in countdown, not just a "recording now" print, because this
    # script is often launched by something that can't guarantee the person
    # actually sees that print before recording starts (e.g. an agent
    # relaying "starting now" over chat) — the fixed delay makes the timing
    # deterministic instead of depending on message-delivery latency.
    print(f"Get ready — recording starts in {COUNTDOWN_SECONDS}...", flush=True)
    for n in range(COUNTDOWN_SECONDS, 0, -1):
        print(n, flush=True)
        time.sleep(1)
    print(f"Recording NOW — talk for {seconds}s (read a sentence or two aloud)...", flush=True)
    audio = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=1, dtype="float32")
    sd.wait()
    print("Done recording.", flush=True)
    return audio.flatten()


def main() -> None:
    default_input = sd.query_devices(kind="input")
    print(f"Using microphone: {default_input['name']}", flush=True)
    audio = record(DURATION_SECONDS, SAMPLE_RATE)
    wav = preprocess_wav(audio, source_sr=SAMPLE_RATE)
    if wav.size == 0:
        print("No speech detected in the recording — try again, closer to the mic.", file=sys.stderr)
        sys.exit(1)

    encoder = VoiceEncoder()
    embedding = encoder.embed_utterance(wav)
    np.save(PROFILE_PATH, embedding)
    print(f"Saved voice profile to {PROFILE_PATH}")


if __name__ == "__main__":
    main()
