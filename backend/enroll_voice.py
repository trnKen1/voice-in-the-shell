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

import numpy as np
import sounddevice as sd
from resemblyzer import VoiceEncoder, preprocess_wav

SAMPLE_RATE = 16000
DURATION_SECONDS = 15
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "voice_profile.npy")


def record(seconds: int, sample_rate: int) -> np.ndarray:
    print(f"Recording {seconds}s — talk naturally, read a sentence or two aloud...")
    audio = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=1, dtype="float32")
    sd.wait()
    print("Done recording.")
    return audio.flatten()


def main() -> None:
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
