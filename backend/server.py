"""voice-in-the-shell backend — Phase 2.

Hosts a persistent Claude Agent SDK session and bridges it to the Tauri
shell over a local WebSocket. The shell sends transcripts (later: real STT
output, currently: whatever the shell forwards); this service streams back
assistant text and routes tool-permission checks through the shell instead
of auto-approving or auto-denying them.

Wire protocol (JSON over WebSocket, one connection per shell instance):

Shell -> backend:
    {"type": "transcript", "text": "..."}  # manual test path (no STT yet in the shell)
    {"type": "permission_response", "request_id": "...", "allow": bool, "message": "..."}

Backend -> shell:
    {"type": "speaking_start"}
    {"type": "assistant_text", "text": "..."}
    {"type": "speaking_end"}
    {"type": "turn_done"}
    {"type": "permission_request", "request_id": "...", "tool": "...", "input": {...}}
    {"type": "permission_resolved", "request_id": "..."}
    {"type": "error", "message": "..."}

Phase 1: transcripts also arrive from the local active-listening pipeline
(mic -> VAD -> speaker filter -> STT, see audio_pipeline.py).

Phase 3: incoming text (from either source) is routed through
resolve_or_queue() — if a permission confirmation is pending, it's checked
for a yes/no answer (voice_commands.interpret_yes_no) and consumed as the
answer instead of becoming a new agent turn. Access-level scoping (which
tools are auto-approved) is loaded from access_config.json, not hardcoded,
so it can be edited without touching code.
"""

import asyncio
import json
import logging
import os
import uuid

from dotenv import load_dotenv
import websockets

from audio_pipeline import ActiveListeningPipeline
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
)
from voice_commands import interpret_yes_no

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("voice-in-the-shell-backend")

HOST = "127.0.0.1"
PORT = 8765

# Conservative default: read-only tools auto-approved. Everything else
# (Write, Edit, Bash, ...) falls through to can_use_tool and gets a
# confirmation round-trip through the shell before it runs. Overridden by
# access_config.json when present — see load_allowed_tools().
DEFAULT_ALLOWED_TOOLS = ["Read", "Glob", "Grep"]
ACCESS_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "access_config.json")

PERMISSION_TIMEOUT_SECONDS = 120


def load_allowed_tools() -> list[str]:
    if os.path.exists(ACCESS_CONFIG_PATH):
        try:
            with open(ACCESS_CONFIG_PATH, encoding="utf-8") as f:
                config = json.load(f)
            tools = config.get("allowed_tools")
            if isinstance(tools, list):
                return tools
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("failed to read %s (%s), using defaults", ACCESS_CONFIG_PATH, exc)
    return DEFAULT_ALLOWED_TOOLS


async def handle_connection(websocket, pipeline: ActiveListeningPipeline) -> None:
    log.info("shell connected")
    pending_permissions: dict[str, asyncio.Future] = {}
    pending_confirmation_request_id: str | None = None
    transcript_queue: asyncio.Queue[str] = asyncio.Queue()

    async def resolve_permission(request_id: str, allow: bool, message: str | None = None) -> bool:
        """Resolves a pending can_use_tool future and notifies the shell.
        Returns False if there was nothing pending under that id."""
        nonlocal pending_confirmation_request_id
        future = pending_permissions.pop(request_id, None)
        if not future or future.done():
            return False
        future.set_result((allow, message))
        if pending_confirmation_request_id == request_id:
            pending_confirmation_request_id = None
        await websocket.send(json.dumps({"type": "permission_resolved", "request_id": request_id}))
        return True

    async def resolve_or_queue(text: str) -> None:
        """Incoming text (voice or typed) either answers a pending
        confirmation or becomes a new agent turn — never both."""
        if pending_confirmation_request_id is not None:
            decision = interpret_yes_no(text)
            if decision is not None:
                await resolve_permission(pending_confirmation_request_id, decision)
            else:
                log.info("heard %r while awaiting confirmation — no clear yes/no, ignoring", text)
            return
        await transcript_queue.put(text)

    async def run_active_listening() -> None:
        async for text in pipeline.listen():
            log.info("active listening transcript: %s", text)
            await resolve_or_queue(text)

    async def can_use_tool(tool_name, input_data, context):
        nonlocal pending_confirmation_request_id
        request_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        pending_permissions[request_id] = future
        pending_confirmation_request_id = request_id
        await websocket.send(json.dumps({
            "type": "permission_request",
            "request_id": request_id,
            "tool": tool_name,
            "input": input_data,
        }))
        try:
            allow, message = await asyncio.wait_for(future, timeout=PERMISSION_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            pending_permissions.pop(request_id, None)
            if pending_confirmation_request_id == request_id:
                pending_confirmation_request_id = None
            await websocket.send(json.dumps({"type": "permission_resolved", "request_id": request_id}))
            return PermissionResultDeny(message="No response from shell — denied by timeout")
        if allow:
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(message=message or "Denied by user")

    options = ClaudeAgentOptions(
        allowed_tools=load_allowed_tools(),
        permission_mode="default",
        can_use_tool=can_use_tool,
    )

    async def run_turns(client: ClaudeSDKClient) -> None:
        while True:
            text = await transcript_queue.get()
            await websocket.send(json.dumps({"type": "speaking_start"}))
            try:
                await client.query(text)
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if hasattr(block, "text"):
                                await websocket.send(json.dumps({
                                    "type": "assistant_text",
                                    "text": block.text,
                                }))
                    elif isinstance(message, ResultMessage) and message.subtype != "success":
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": f"agent turn ended with an error: {message.subtype}",
                        }))
            except Exception as exc:  # noqa: BLE001 — surface any turn failure to the shell
                log.exception("turn failed")
                await websocket.send(json.dumps({"type": "error", "message": str(exc)}))
            finally:
                await websocket.send(json.dumps({"type": "speaking_end"}))
                await websocket.send(json.dumps({"type": "turn_done"}))

    pipeline.start()
    async with ClaudeSDKClient(options=options) as client:
        turn_task = asyncio.create_task(run_turns(client))
        listening_task = asyncio.create_task(run_active_listening())
        try:
            async for raw in websocket:
                msg = json.loads(raw)
                msg_type = msg.get("type")
                if msg_type == "transcript":
                    await resolve_or_queue(msg["text"])
                elif msg_type == "permission_response":
                    await resolve_permission(
                        msg.get("request_id"), msg.get("allow", False), msg.get("message")
                    )
                else:
                    log.warning("unknown message type: %s", msg_type)
        finally:
            turn_task.cancel()
            listening_task.cancel()
            pipeline.stop()
            log.info("shell disconnected")


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY is not set — agent turns will fail until it is")

    log.info("loading active-listening pipeline (VAD + speaker filter + STT)...")
    pipeline = ActiveListeningPipeline()
    log.info("active-listening pipeline ready")

    async def handler(websocket):
        await handle_connection(websocket, pipeline)

    async with websockets.serve(handler, HOST, PORT):
        log.info("listening on ws://%s:%s", HOST, PORT)
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
