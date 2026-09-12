"""One-time setup: downloads the default Piper TTS voice model.

Piper voices are two files (a ~60MB ONNX model + a small JSON config)
hosted on Hugging Face. This fetches the default voice (en_US-lessac-medium
— a neutral American English voice, medium quality/speed tradeoff) into
backend/models/. Re-run to re-download if the files are missing or corrupt.

To use a different voice instead, browse https://rhasspy.github.io/piper-samples/
for options, then set VOICE below to match (e.g. "en_US-amy-medium") and
adjust the language path in _VOICE_URL if it changes (e.g. "en/en_US/amy/medium").
"""

import os
import sys
import urllib.request

VOICE = "en_US-lessac-medium"
LANG_PATH = "en/en_US/lessac/medium"  # <lang>/<locale>/<speaker>/<quality>
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")

_BASE_URL = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{LANG_PATH}"


def _download(filename: str) -> None:
    dest = os.path.join(MODEL_DIR, filename)
    if os.path.exists(dest):
        print(f"already have {filename}, skipping")
        return
    url = f"{_BASE_URL}/{filename}"
    print(f"downloading {url} -> {dest}", flush=True)

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        done = min(block_num * block_size, total_size)
        pct = done * 100 // total_size
        print(f"\r  {pct:3d}% ({done // 1_000_000}MB / {total_size // 1_000_000}MB)", end="", flush=True)

    tmp = dest + ".part"
    try:
        urllib.request.urlretrieve(url, tmp, reporthook=_progress)
        print()
        os.replace(tmp, dest)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def main() -> None:
    os.makedirs(MODEL_DIR, exist_ok=True)
    try:
        _download(f"{VOICE}.onnx")
        _download(f"{VOICE}.onnx.json")
    except Exception as exc:  # noqa: BLE001 — report and exit non-zero, no partial state left behind
        print(f"download failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"done — {VOICE} ready in {MODEL_DIR}")


if __name__ == "__main__":
    main()
