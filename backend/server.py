"""voice-in-the-shell backend — Phase 2.

Hosts a persistent Claude Agent SDK session and bridges it to the Tauri
shell over a local WebSocket. The shell sends transcripts (later: real STT
output, currently: whatever the shell forwards); this service streams back
assistant text and routes tool-permission checks through the shell instead
of auto-approving or auto-denying them.

Wire protocol (JSON over WebSocket, one connection per shell instance):

Shell -> backend:
    {"type": "transcript", "text": "..."}
    {"type": "permission_response", "request_id": "...", "allow": bool, "message": "..."}

Backend -> shell:
    {"type": "speaking_start"}
    {"type": "assistant_text", "text": "..."}
    {"type": "speaking_end"}
    {"type": "turn_done"}
    {"type": "permission_request", "request_id": "...", "tool": "...", "input": {...}}
    {"type": "error", "message": "..."}
"""

import asyncio
import json
import logging
import os
import uuid

from dotenv import load_dotenv
import websockets

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("voice-in-the-shell-backend")

HOST = "127.0.0.1"
PORT = 8765

# Conservative default: read-only tools auto-approved. Everything else
# (Write, Edit, Bash, ...) falls through to can_use_tool and gets a
# confirmation round-trip through the shell before it runs.
DEFAULT_ALLOWED_TOOLS = ["Read", "Glob", "Grep"]

PERMISSION_TIMEOUT_SECONDS = 120


async def handle_connection(websocket) -> None:
    log.info("shell connected")
    pending_permissions: dict[str, asyncio.Future] = {}
    transcript_queue: asyncio.Queue[str] = asyncio.Queue()

    async def can_use_tool(tool_name, input_data, context):
        request_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        pending_permissions[request_id] = future
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
            return PermissionResultDeny(message="No response from shell — denied by timeout")
        if allow:
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(message=message or "Denied by user")

    options = ClaudeAgentOptions(
        allowed_tools=DEFAULT_ALLOWED_TOOLS,
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

    async with ClaudeSDKClient(options=options) as client:
        turn_task = asyncio.create_task(run_turns(client))
        try:
            async for raw in websocket:
                msg = json.loads(raw)
                msg_type = msg.get("type")
                if msg_type == "transcript":
                    await transcript_queue.put(msg["text"])
                elif msg_type == "permission_response":
                    future = pending_permissions.pop(msg.get("request_id"), None)
                    if future and not future.done():
                        future.set_result((msg.get("allow", False), msg.get("message")))
                else:
                    log.warning("unknown message type: %s", msg_type)
        finally:
            turn_task.cancel()
            log.info("shell disconnected")


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY is not set — agent turns will fail until it is")
    async with websockets.serve(handle_connection, HOST, PORT):
        log.info("listening on ws://%s:%s", HOST, PORT)
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
