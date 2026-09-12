# backend

Three things live here:

- **Phase 2 — model backend adapter.** Hosts a persistent Claude Agent SDK session and bridges it to the Tauri shell over a local WebSocket (`ws://127.0.0.1:8765`). See `server.py` for the wire protocol.
- **Phase 1 — active listening.** `audio_pipeline.py`: mic → Silero VAD (speech/silence) → Resemblyzer speaker match (is this *you*?) → faster-whisper (GPU) transcription. Runs inside `server.py`'s connection lifecycle and feeds recognized transcripts into the same queue the shell's manual test messages use.
- **Phase 4 — text-to-speech.** `tts.py`: wraps a local Piper voice model and synthesizes each assistant response to speech, streamed to the shell as raw PCM over the same WebSocket (binary frames, bracketed by `audio_start`/`audio_end`). Requires a downloaded voice model — see below. If none is present, the backend runs text-only (subtitles work, no spoken audio) instead of failing.

## Auth

`ClaudeSDKClient` shells out to a bundled Claude Code CLI (`claude-agent-sdk` ships its own `claude.exe`/`claude` binary), which resolves credentials the same way the CLI itself does:

- If `ANTHROPIC_API_KEY` is set (in `.env` or the environment), it's used — **metered billing**, takes precedence over everything else.
- Otherwise, it falls back to this machine's existing **Claude Code / claude.ai subscription login** (`~/.claude/.credentials.json`) — no separate install, no code change, just don't set the key. Run `claude` once (any install — the bundled CLI, `npm install -g @anthropic-ai/claude-code`, or the desktop app) to log in if this machine hasn't already.

`server.py` logs which one is active on startup (`describe_auth()`). Earlier docs here claimed the Agent SDK "can't use subscription auth" — that was wrong; verified live 2026-09-12 (see the Obsidian notes doc for the test).

**If you want the subscription path and `.env` already has a real key in it, the key wins** — clear `ANTHROPIC_API_KEY` in `.env` to fall through to the subscription login.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env   # optional — only fill in ANTHROPIC_API_KEY if you want metered billing instead of your Claude subscription
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

## Voice output setup (one-time, before Phase 4 produces spoken audio)

```bash
python download_voice.py
```

Downloads the default Piper voice (`en_US-lessac-medium`, ~63MB) into `backend/models/` (gitignored — same reasoning as `voice_profile.npy`, it's a large binary asset, not source). Without it, `server.py` still runs and responds with text/subtitles — `tts.py` just reports `available=False` and no audio is ever sent. To use a different voice, browse [rhasspy.github.io/piper-samples](https://rhasspy.github.io/piper-samples/) and edit `VOICE`/`LANG_PATH` at the top of `download_voice.py` and `DEFAULT_VOICE` in `tts.py` to match.

**Known issue: Windows Smart App Control can block Piper outright.** Piper's espeak-ng phonemizer bridge (`piper/espeakbridge.pyd`) is an unsigned native DLL. If Smart App Control is in enforcement mode, loading it fails with `DLL load failed ... Application Control policy has blocked this file` — `tts.py` catches this at startup (forces one real synthesis before reporting `available=True`, same defensive pattern as the faster-whisper GPU check below) and degrades to text-only instead of crashing, logging a clear one-time warning explaining the cause. There's no per-file exception mechanism for Smart App Control (unlike Defender exclusions) — the only real fix is turning it off entirely (Settings → Privacy & security → Windows Security → App & browser control → Smart App Control), which Microsoft describes as effectively one-way (only reversible by reinstalling Windows). Check `Get-MpPreference` / the registry key `HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy` (`VerifiedAndReputablePolicyState`) to see if it's enforced on your machine before assuming this is a code bug.

## Run

```bash
python server.py
```

## Access levels

`DEFAULT_ALLOWED_TOOLS` in `server.py` is the read-only starter set (`Read`, `Glob`, `Grep`) — auto-approved without asking. Anything else (`Write`, `Edit`, `Bash`, ...) falls through to the `can_use_tool` callback, which round-trips a confirmation through the shell before the tool runs. Widen or narrow the allowed set there as trust in the flow grows.

## Tuning the speaker-match threshold

`SPEAKER_MATCH_THRESHOLD` in `audio_pipeline.py` (default `0.75`) is a cosine-similarity cutoff — lower it if your own voice is getting rejected too often, raise it if other voices are getting through. No principled default; tune against your own mic/room.
