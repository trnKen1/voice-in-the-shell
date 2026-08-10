# backend

Two things live here:

- **Phase 2 — model backend adapter.** Hosts a persistent Claude Agent SDK session and bridges it to the Tauri shell over a local WebSocket (`ws://127.0.0.1:8765`). See `server.py` for the wire protocol.
- **Phase 1 — active listening.** `audio_pipeline.py`: mic → Silero VAD (speech/silence) → Resemblyzer speaker match (is this *you*?) → faster-whisper (GPU) transcription. Runs inside `server.py`'s connection lifecycle and feeds recognized transcripts into the same queue the shell's manual test messages use.

Requires an `ANTHROPIC_API_KEY` (metered API key — **not** a claude.ai/Claude Code subscription login; third-party apps built on the Agent SDK can't use subscription auth).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env   # then fill in ANTHROPIC_API_KEY
```

`torch` needs a CUDA build to use the GPU — plain `pip install torch` from PyPI defaults to a CPU-only wheel even with an NVIDIA GPU present. If `torch.cuda.is_available()` comes back `False` after the install above, reinstall explicitly:

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130 --force-reinstall
```

(`cu130` matches an RTX 50-series/Blackwell GPU on a recent driver — check `nvidia-smi`'s reported CUDA version and adjust the tag if you're on different hardware.)

## Voice enrollment (one-time, before Phase 1 works as intended)

```bash
python enroll_voice.py
```

Records ~15 seconds of your voice, saves a Resemblyzer reference embedding to `voice_profile.npy` (gitignored — it's personal). Without this file, `audio_pipeline.py` still runs VAD + STT but **skips speaker filtering** — every detected utterance gets transcribed, not just yours. Re-run any time to replace the profile.

## Run

```bash
python server.py
```

## Access levels

`DEFAULT_ALLOWED_TOOLS` in `server.py` is the read-only starter set (`Read`, `Glob`, `Grep`) — auto-approved without asking. Anything else (`Write`, `Edit`, `Bash`, ...) falls through to the `can_use_tool` callback, which round-trips a confirmation through the shell before the tool runs. Widen or narrow the allowed set there as trust in the flow grows.

## Tuning the speaker-match threshold

`SPEAKER_MATCH_THRESHOLD` in `audio_pipeline.py` (default `0.75`) is a cosine-similarity cutoff — lower it if your own voice is getting rejected too often, raise it if other voices are getting through. No principled default; tune against your own mic/room.
