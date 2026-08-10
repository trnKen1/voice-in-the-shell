# voice-in-the-shell

A voice-activated UI layer for LLM agents. It sits on top of an existing LLM/agent capability (action execution with permission, checking back with the user, access-level-scoped tools) and adds:

- **Active listening** — filters for the user's voice before anything is transcribed or acted on
- **Voice input bar** — animates with live microphone volume while the user speaks
- **Voice output bar** — animates with the LLM's synthesized voice while it responds, with live subtitles
- **Pluggable model backend** — connects to a subscription API (e.g. Claude) or a local runtime (e.g. Ollama)

Status: early development — shell prototype (overlay HUD, mic-reactive bars, mock subtitles) in progress. See the project plan in the Obsidian vault (`20 Software/Voice in the Shell/`) for architecture notes, decisions, and current pickup point.

## Stack

- **Shell:** [Tauri](https://tauri.app/) (Rust backend + OS WebView2) — small footprint, native window control (transparent/always-on-top/tray) needed for an overlay HUD
- **Frontend:** vanilla HTML/CSS/JS, Web Audio API for the volume-reactive bars
- **Everything downstream of the shell** (voice filtering, STT, TTS, agent/model calls): a local Python service, not yet built — see the plan doc

## Development

Requires Rust (via [rustup](https://rustup.rs/)) and, on Windows, the MSVC C++ Build Tools.

```bash
npm install
npm run tauri dev
```

## License

MIT
