const inputBars = document.querySelectorAll("#bars-in .bar");
const outputBars = document.querySelectorAll("#bars-out .bar");
const subtitleEl = document.getElementById("subtitle");

function setBars(bars, level) {
  bars.forEach((bar, i) => {
    const jitter = 0.6 + Math.random() * 0.4;
    const h = Math.max(0.12, Math.min(1, level * jitter * (1 + i * 0.04)));
    bar.style.transform = `scaleY(${h})`;
  });
}

// Real mic input drives the input bar via the Web Audio API.
async function startMicVisualizer() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);

    function tick() {
      analyser.getByteFrequencyData(data);
      const avg = data.reduce((a, b) => a + b, 0) / data.length;
      const level = Math.min(1, avg / 90);
      setBars(inputBars, level);
      requestAnimationFrame(tick);
    }
    tick();
  } catch (err) {
    setBars(inputBars, 0);
    subtitleEl.textContent = "mic access denied — input bar disabled";
  }
}

let speaking = false;

function outputTick() {
  setBars(outputBars, speaking ? 0.3 + Math.random() * 0.7 : 0);
  requestAnimationFrame(outputTick);
}

// Mock output — canned subtitles + fake amplitude. Used until Phase 2's
// backend is reachable (or if it drops), so the output bar/subtitle can
// still be seen working standalone.
const mockLines = [
  "on it — checking your calendar",
  "sending that now",
  "want me to go ahead?",
  "done — anything else?",
];
let lineIndex = 0;
let mockIntervalId = null;

function speakMock() {
  speaking = true;
  subtitleEl.textContent = mockLines[lineIndex % mockLines.length];
  lineIndex++;
  setTimeout(() => {
    speaking = false;
    subtitleEl.textContent = "listening…";
  }, 2200);
}

function startMock() {
  if (mockIntervalId === null) {
    mockIntervalId = setInterval(speakMock, 4000);
  }
}

function stopMock() {
  if (mockIntervalId !== null) {
    clearInterval(mockIntervalId);
    mockIntervalId = null;
  }
}

// Phase 2 backend — persistent Claude Agent SDK session over a local
// WebSocket (see backend/server.py for the wire protocol). Falls back to
// the mock behavior above whenever it isn't reachable.
const BACKEND_URL = "ws://127.0.0.1:8765";
let ws = null;
let pendingPermission = null; // { requestId, tool }

function connectBackend() {
  ws = new WebSocket(BACKEND_URL);

  ws.onopen = () => {
    stopMock();
    subtitleEl.textContent = "listening…";
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    switch (msg.type) {
      case "speaking_start":
        speaking = true;
        break;
      case "assistant_text":
        subtitleEl.textContent = msg.text;
        break;
      case "speaking_end":
        speaking = false;
        break;
      case "turn_done":
        if (!pendingPermission) subtitleEl.textContent = "listening…";
        break;
      case "permission_request":
        pendingPermission = { requestId: msg.request_id, tool: msg.tool };
        document.body.classList.add("confirm-pending");
        subtitleEl.textContent = `confirm: run ${msg.tool}? say "yes"/"no" or press y/n`;
        break;
      case "permission_resolved":
        // Backend resolved it (voice, typed text, or the y/n keys below) —
        // clear local state so this doesn't fight a stale keypress.
        if (pendingPermission && pendingPermission.requestId === msg.request_id) {
          pendingPermission = null;
          document.body.classList.remove("confirm-pending");
          subtitleEl.textContent = "listening…";
        }
        break;
      case "error":
        subtitleEl.textContent = `error: ${msg.message}`;
        break;
    }
  };

  ws.onclose = () => {
    ws = null;
    startMock();
  };

  ws.onerror = () => {
    // onclose fires right after — let that handle the fallback.
  };
}

function respondToPermission(allow) {
  if (!pendingPermission || !ws) return;
  // Don't clear local state here — wait for the backend's
  // permission_resolved reply, so voice/typed/keyboard resolution paths
  // can't race each other into inconsistent UI state.
  ws.send(
    JSON.stringify({
      type: "permission_response",
      request_id: pendingPermission.requestId,
      allow,
    }),
  );
}

// "T" sends a typed test transcript to the backend — handy for testing
// without speaking (kept intentionally, not just a Phase 1 stopgap).
// While a permission is pending, y/n are the fast local path; the backend
// would also accept a spoken/typed "yes"/"no" as an answer either way.
window.addEventListener("keydown", (e) => {
  if (pendingPermission && (e.key === "y" || e.key === "Y")) {
    respondToPermission(true);
  } else if (pendingPermission && (e.key === "n" || e.key === "N")) {
    respondToPermission(false);
  } else if (!pendingPermission && (e.key === "t" || e.key === "T") && ws) {
    const text = window.prompt("Test transcript to send to the backend:");
    if (text) ws.send(JSON.stringify({ type: "transcript", text }));
  }
});

startMicVisualizer();
outputTick();
startMock();
connectBackend();
