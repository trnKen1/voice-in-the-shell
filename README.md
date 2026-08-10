# voice-in-the-shell

A voice-activated UI layer for LLM agents. It sits on top of an existing LLM/agent capability (action execution with permission, checking back with the user, access-level-scoped tools) and adds:

- **Active listening** — filters for the user's voice before anything is transcribed or acted on
- **Voice input bar** — animates with live microphone volume while the user speaks
- **Voice output bar** — animates with the LLM's synthesized voice while it responds, with live subtitles
- **Pluggable model backend** — connects to a subscription API (e.g. Claude) or a local runtime (e.g. Ollama)

Status: early planning. See the project plan in the Obsidian vault (`20 Software/Voice in the Shell/`) for architecture notes and open decisions.

## Stack

Not yet decided — see the plan doc.

## License

MIT
