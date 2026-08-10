# backend

Phase 2 — the model backend adapter. Hosts a persistent Claude Agent SDK session and bridges it to the Tauri shell over a local WebSocket (`ws://127.0.0.1:8765`). See `server.py` for the wire protocol.

Requires an `ANTHROPIC_API_KEY` (metered API key — **not** a claude.ai/Claude Code subscription login; third-party apps built on the Agent SDK can't use subscription auth).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env   # then fill in ANTHROPIC_API_KEY
```

## Run

```bash
python server.py
```

## Access levels

`DEFAULT_ALLOWED_TOOLS` in `server.py` is the read-only starter set (`Read`, `Glob`, `Grep`) — auto-approved without asking. Anything else (`Write`, `Edit`, `Bash`, ...) falls through to the `can_use_tool` callback, which round-trips a confirmation through the shell before the tool runs. Widen or narrow the allowed set there as trust in the flow grows.
