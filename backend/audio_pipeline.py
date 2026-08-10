"""Phase 1 — active listening pipeline.

Continuously captures the microphone, uses Silero VAD to segment speech from
silence/noise, gates each segment against the enrolled voice profile
(Resemblyzer cosine similarity) so only the user's own speech proceeds, then
transcribes accepted segments with faster-whisper (GPU).

If no voice_profile.npy exists yet (see enroll_voice.py), speaker filtering
is skipped and every detected utterance is transcribed — useful for testing
the VAD/STT stages before enrolling, but not the intended steady state.
"""

import asyncio
import logging
import os
import queue
import sys
import sysconfig

import numpy as np
import sounddevice as sd

log = logging.getLogger("voice-in-the-shell-backend.audio")


def _register_nvidia_dll_dirs() -> None:
    """faster-whisper's ctranslate2 backend loads cuBLAS/cuDNN at inference
    time. The pip packages nvidia-cublas-cu12 / nvidia-cudnn-cu12 install
    those DLLs into site-packages but don't add them to PATH, so ctranslate2
    can't find them unless we register the directories first — must happen
    before `faster_whisper` (and therefore ctranslate2) is imported.

    `os.add_dll_directory` alone isn't enough here: it only affects
    LoadLibraryEx calls made with the extended search flags, and
    ctranslate2's loader doesn't use them. Prepending to PATH also covers
    the classic DLL search order, which is what actually works."""
    if sys.platform != "win32":
        return
    site_packages = sysconfig.get_path("purelib")
    for pkg in ("cublas", "cudnn"):
        dll_dir = os.path.join(site_packages, "nvidia", pkg, "bin")
        if os.path.isdir(dll_dir):
            os.add_dll_directory(dll_dir)
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")


_register_nvidia_dll_dirs()

from faster_whisper import WhisperModel  # noqa: E402 — must follow DLL registration
from resemblyzer import VoiceEncoder, preprocess_wav  # noqa: E402
from silero_vad import VADIterator, load_silero_vad  # noqa: E402

SAMPLE_RATE = 16000
VAD_CHUNK_SAMPLES = 512  # Silero VAD's required frame size at 16kHz
MIN_UTTERANCE_SECONDS = 0.3  # discard shorter blips (coughs, clicks)
SPEAKER_MATCH_THRESHOLD = 0.75
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "voice_profile.npy")
WHISPER_MODEL_SIZE = "small"


class ActiveListeningPipeline:
    def __init__(self) -> None:
        self._vad_model = load_silero_vad()
        self._vad_iterator = VADIterator(self._vad_model, sampling_rate=SAMPLE_RATE)
        self._encoder = VoiceEncoder()  # auto-selects CUDA if available, else CPU
        self._profile = self._load_profile()
        self._whisper = self._load_whisper()

    def _load_whisper(self) -> WhisperModel:
        try:
            model = WhisperModel(WHISPER_MODEL_SIZE, device="cuda", compute_type="float16")
            # ctranslate2 loads its CUDA libs lazily — construction can
            # succeed even when cuBLAS/cuDNN aren't actually loadable. Force
            # one real inference here so a missing DLL fails at startup
            # instead of on the user's first spoken query.
            list(model.transcribe(np.zeros(SAMPLE_RATE, dtype="float32"), language="en")[0])
            log.info("faster-whisper running on GPU (%s)", WHISPER_MODEL_SIZE)
            return model
        except Exception as exc:  # noqa: BLE001 — no usable CUDA runtime for ctranslate2
            log.warning(
                "GPU unavailable for faster-whisper (%s), falling back to CPU (slower): %s",
                WHISPER_MODEL_SIZE,
                exc,
            )
            return WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        self._audio_queue: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream: sd.InputStream | None = None

    def _load_profile(self) -> np.ndarray | None:
        if os.path.exists(PROFILE_PATH):
            log.info("loaded voice profile from %s", PROFILE_PATH)
            return np.load(PROFILE_PATH)
        log.warning(
            "no voice_profile.npy found — speaker filtering disabled, every "
            "detected utterance will be transcribed. Run enroll_voice.py to fix this."
        )
        return None

    def start(self) -> None:
        def callback(indata, frames, time_info, status):
            if status:
                log.warning("sounddevice status: %s", status)
            self._audio_queue.put(indata[:, 0].copy())

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=VAD_CHUNK_SAMPLES,
            callback=callback,
        )
        self._stream.start()
        log.info("mic stream started")

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        log.info("mic stream stopped")

    def _speaker_matches(self, segment: np.ndarray) -> bool:
        if self._profile is None:
            return True
        wav = preprocess_wav(segment, source_sr=SAMPLE_RATE)
        if wav.size == 0:
            return False
        embedding = self._encoder.embed_utterance(wav)
        similarity = float(
            np.dot(embedding, self._profile)
            / (np.linalg.norm(embedding) * np.linalg.norm(self._profile))
        )
        log.debug("speaker similarity: %.3f", similarity)
        return similarity >= SPEAKER_MATCH_THRESHOLD

    def _transcribe(self, segment: np.ndarray) -> str:
        segments, _info = self._whisper.transcribe(segment, language="en")
        return " ".join(s.text.strip() for s in segments).strip()

    async def listen(self):
        """Async generator yielding transcribed text for accepted utterances."""
        loop = asyncio.get_event_loop()
        buffer: list[np.ndarray] = []
        in_speech = False

        while True:
            chunk = await loop.run_in_executor(None, self._audio_queue.get)
            event = self._vad_iterator(chunk, return_seconds=True)

            if in_speech:
                buffer.append(chunk)

            if event and "start" in event:
                in_speech = True
                buffer = [chunk]
            elif event and "end" in event and in_speech:
                in_speech = False
                segment = np.concatenate(buffer) if buffer else np.array([], dtype="float32")
                buffer = []
                if segment.size < SAMPLE_RATE * MIN_UTTERANCE_SECONDS:
                    continue

                matched = await loop.run_in_executor(None, self._speaker_matches, segment)
                if not matched:
                    log.debug("utterance discarded — speaker mismatch")
                    continue

                text = await loop.run_in_executor(None, self._transcribe, segment)
                if text:
                    yield text
