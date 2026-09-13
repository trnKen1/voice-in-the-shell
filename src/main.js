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

// Phase 4 — real synthesized audio drives the output bar via the Web Audio
// API, same AnalyserNode approach as the input bar. Falls back to the
// synthetic pulse below whenever no audio is actually flowing (e.g. no
// Piper voice model is installed on the backend, so it only ever sends
// text) — see handleAudioStart/handleAudioEnd.
let outputCtx = null;
let outputAnalyser = null;
let outputAnalyserData = null;
let nextPlaybackTime = 0;
let audioSourcesPlaying = 0;
let pendingAudioMeta = null; // { sampleRate, channels } while between audio_start/audio_end
let pendingAudioChunks = [];

function ensureOutputAudio() {
  if (outputCtx) return;
  outputCtx = new AudioContext();
  outputAnalyser = outputCtx.createAnalyser();
  outputAnalyser.fftSize = 256;
  outputAnalyser.connect(outputCtx.destination);
  outputAnalyserData = new Uint8Array(outputAnalyser.frequencyBinCount);
  nextPlaybackTime = outputCtx.currentTime;
}

function handleAudioStart(msg) {
  ensureOutputAudio();
  pendingAudioMeta = { sampleRate: msg.sample_rate, channels: msg.channels || 1 };
  pendingAudioChunks = [];
}

function handleAudioChunk(buffer) {
  if (!pendingAudioMeta) return; // stray binary frame outside an audio_start/audio_end pair
  pendingAudioChunks.push(buffer);
}

// Decodes the accumulated 16-bit PCM chunks for one assistant_text block
// into an AudioBuffer and schedules it right after whatever's already
// queued, so back-to-back blocks play in order with no gap or overlap.
function handleAudioEnd() {
  const meta = pendingAudioMeta;
  const chunks = pendingAudioChunks;
  pendingAudioMeta = null;
  pendingAudioChunks = [];
  if (!meta || chunks.length === 0) return;

  const totalBytes = chunks.reduce((n, b) => n + b.byteLength, 0);
  const merged = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(new Uint8Array(chunk), offset);
    offset += chunk.byteLength;
  }
  const pcm16 = new Int16Array(merged.buffer);
  const frameCount = Math.floor(pcm16.length / meta.channels);
  if (frameCount === 0) return;

  const audioBuffer = outputCtx.createBuffer(meta.channels, frameCount, meta.sampleRate);
  for (let ch = 0; ch < meta.channels; ch++) {
    const channelData = audioBuffer.getChannelData(ch);
    for (let i = 0; i < frameCount; i++) {
      channelData[i] = pcm16[i * meta.channels + ch] / 32768;
    }
  }

  const source = outputCtx.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(outputAnalyser);
  const startAt = Math.max(outputCtx.currentTime, nextPlaybackTime);
  source.start(startAt);
  nextPlaybackTime = startAt + audioBuffer.duration;
  audioSourcesPlaying++;
  cancelIdleSubtitle();
  source.onended = () => {
    audioSourcesPlaying = Math.max(0, audioSourcesPlaying - 1);
    if (audioSourcesPlaying === 0 && turnFinished) scheduleIdleSubtitle(800);
  };
}

// The backend sends turn_done right after the text, but TTS audio arrives
// (and plays) afterward — so the subtitle is held until playback ends, or
// for a reading-time delay when no audio comes (text-only mode).
let idleSubtitleTimer = null;
let turnFinished = true;

function cancelIdleSubtitle() {
  if (idleSubtitleTimer !== null) {
    clearTimeout(idleSubtitleTimer);
    idleSubtitleTimer = null;
  }
}

function scheduleIdleSubtitle(delayMs) {
  cancelIdleSubtitle();
  idleSubtitleTimer = setTimeout(() => {
    idleSubtitleTimer = null;
    if (!pendingPermission && audioSourcesPlaying === 0) subtitleEl.textContent = "listening…";
  }, delayMs);
}

function outputTick() {
  if (audioSourcesPlaying > 0) {
    outputAnalyser.getByteFrequencyData(outputAnalyserData);
    const avg = outputAnalyserData.reduce((a, b) => a + b, 0) / outputAnalyserData.length;
    setBars(outputBars, Math.min(1, avg / 90));
  } else {
    setBars(outputBars, speaking ? 0.3 + Math.random() * 0.7 : 0);
  }
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
const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 5000;
let ws = null;
let pendingPermission = null; // { requestId, tool }
let reconnectDelayMs = RECONNECT_MIN_MS;

// The backend takes ~20s to load its models, so the HUD usually starts
// first — keep retrying instead of staying in mock mode forever.
function connectBackend() {
  const socket = new WebSocket(BACKEND_URL);
  ws = socket;
  socket.binaryType = "arraybuffer"; // raw PCM audio chunks, not Blobs — see handleAudioChunk

  socket.onopen = () => {
    reconnectDelayMs = RECONNECT_MIN_MS;
    stopMock();
    subtitleEl.textContent = "listening…";
  };

  socket.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      handleAudioChunk(event.data);
      return;
    }
    const msg = JSON.parse(event.data);
    switch (msg.type) {
      case "speaking_start":
        speaking = true;
        turnFinished = false;
        cancelIdleSubtitle();
        break;
      case "assistant_text":
        cancelIdleSubtitle();
        subtitleEl.textContent = msg.text;
        break;
      case "audio_start":
        handleAudioStart(msg);
        break;
      case "audio_end":
        handleAudioEnd();
        break;
      case "speaking_end":
        speaking = false;
        break;
      case "turn_done":
        turnFinished = true;
        if (audioSourcesPlaying === 0) {
          scheduleIdleSubtitle(Math.max(3000, subtitleEl.textContent.length * 60));
        }
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

  socket.onclose = () => {
    if (ws === socket) ws = null;
    startMock();
    setTimeout(connectBackend, reconnectDelayMs);
    reconnectDelayMs = Math.min(RECONNECT_MAX_MS, reconnectDelayMs * 2);
  };

  socket.onerror = () => {
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
