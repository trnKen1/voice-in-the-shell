"""Phase 4 — text-to-speech.

Wraps a local Piper voice (ONNX, CPU by default — Piper is fast enough on
CPU that GPU isn't needed the way it was for faster-whisper in Phase 1) and
synthesizes assistant text into raw 16-bit PCM audio for the shell to play.

If no voice model is present (see download_voice.py), synthesis is a no-op
and callers get None back — the rest of the app (text turns, subtitles,
permission flow) keeps working without spoken audio.
"""

import logging
import os

log = logging.getLogger("voice-in-the-shell-backend.tts")

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
DEFAULT_VOICE = "en_US-lessac-medium"
MODEL_PATH = os.path.join(MODEL_DIR, f"{DEFAULT_VOICE}.onnx")


class SpeechSynthesizer:
    def __init__(self) -> None:
        self._voice = self._load_voice()

    def _load_voice(self):
        if not os.path.exists(MODEL_PATH):
            log.warning(
                "no Piper voice model at %s — TTS disabled, subtitles will "
                "still work but there'll be no spoken audio. Run "
                "download_voice.py to fix this.",
                MODEL_PATH,
            )
            return None
        from piper import PiperVoice  # deferred: only needed if a model is actually present

        try:
            voice = PiperVoice.load(MODEL_PATH, use_cuda=False)
            # Piper's espeak-ng phonemizer bridge (a native .pyd) loads
            # lazily, on first real synthesize() call — not here. Same trap
            # as faster-whisper's CUDA libs in audio_pipeline.py: .load()
            # alone can silently "succeed" even when the voice is actually
            # unusable (e.g. an OS Application Control / Smart App Control
            # policy blocking the unsigned .pyd). Force one real synthesis
            # now so a broken voice fails once, clearly, at startup instead
            # of logging a fresh traceback on every single assistant turn.
            list(voice.synthesize("test"))
            log.info("Piper voice loaded: %s (%dHz)", DEFAULT_VOICE, voice.config.sample_rate)
            return voice
        except Exception:
            log.exception(
                "Piper voice at %s failed to load or synthesize — TTS disabled, "
                "text-only mode. If this is 'DLL load failed ... Application "
                "Control policy has blocked this file', that's Windows Smart App "
                "Control blocking piper's unsigned espeak-ng bridge — a system "
                "security setting, not a code bug (Settings > Privacy & security "
                "> Windows Security > App & browser control).",
                MODEL_PATH,
            )
            return None

    @property
    def available(self) -> bool:
        return self._voice is not None

    @property
    def sample_rate(self) -> int:
        return self._voice.config.sample_rate if self._voice else 22050

    def synthesize_pcm(self, text: str) -> bytes | None:
        """Blocking — synthesizes `text` to raw 16-bit little-endian mono PCM
        (no WAV header). Call via asyncio.to_thread from async code. Returns
        None if TTS is unavailable or there's nothing to say."""
        if not self._voice or not text.strip():
            return None
        try:
            chunks = [c.audio_int16_bytes for c in self._voice.synthesize(text)]
        except Exception:
            log.exception("synthesis failed for %r", text)
            return None
        return b"".join(chunks) if chunks else None
