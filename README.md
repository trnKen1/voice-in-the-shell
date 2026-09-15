# Duck-e-bugger

A voice-activated UI layer for LLM agents. It sits on top of an existing LLM/agent capability (action execution with permission, checking back with the user, access-level-scoped tools) and adds:

- **Active listening** — filters for the user's voice before anything is transcribed or acted on
- **Voice input bar** — animates with live microphone volume while the user speaks
- **Voice output bar** — animates with the LLM's synthesized voice while it responds, with live subtitles
- **Pluggable model backend** — connects to a subscription API (e.g. Claude) or a local runtime (e.g. Ollama)

> The name nods to [rubber duck debugging](https://en.wikipedia.org/wiki/Rubber_duck_debugging) — talking through your code out loud until the bug shows itself. Unlike the desk toy, this duck talks back: it's a full voice-driven agent that listens, executes permissioned actions, and responds — not just a silent sounding board.

Status: Phases 0-4 done — overlay HUD shell, active listening (VAD + speaker filter + local STT), a Claude Agent SDK backend over WebSocket, voice-driven permission confirmation, and real text-to-speech (local Piper voice) are all working. The output bar is now driven by an `AnalyserNode` on the actual synthesized audio, not mocked amplitude — falls back to text-only (no audio, bar stays a synthetic pulse) if no voice model is installed. See the project plan in the Obsidian vault (`20 Software/Duck-e-bugger/`) for architecture notes, decisions, and current pickup point.

## Stack

- **Shell:** [Tauri](https://tauri.app/) (Rust backend + OS WebView2) — small footprint, native window control (transparent/always-on-top/tray) needed for an overlay HUD
- **Frontend:** vanilla HTML/CSS/JS, Web Audio API for the volume-reactive bars
- **Backend** (`backend/`): local Python service, bridges the shell to a persistent Claude Agent SDK session over WebSocket (`ws://127.0.0.1:8765`). Also hosts the active-listening pipeline (mic → Silero VAD → Resemblyzer speaker match → faster-whisper GPU STT) and text-to-speech (Piper, local, CPU). Tool-permission requests round-trip through the shell UI instead of auto-approving. Ollama/local-model backend is not wired yet — Claude only for now.

## Development

Requires Rust (via [rustup](https://rustup.rs/)) and, on Windows, the MSVC C++ Build Tools.

```bash
npm install
npm run tauri dev
```

The shell alone falls back to mocked output/subtitles. For the real backend (transcription, agent responses, permission flow), see `backend/README.md` — runs on your existing Claude Code/claude.ai subscription login by default (an `ANTHROPIC_API_KEY` is only needed if you want metered billing instead), and for GPU transcription, a CUDA build of `torch`.

## License

MIT
