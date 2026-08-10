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

// No TTS yet (Phase 4) — mock output amplitude + canned subtitles so the
// output bar and subtitle behavior can be built/demoed independently.
const mockLines = [
  "on it — checking your calendar",
  "sending that now",
  "want me to go ahead?",
  "done — anything else?",
];
let speaking = false;
let lineIndex = 0;

function mockOutputTick() {
  setBars(outputBars, speaking ? 0.3 + Math.random() * 0.7 : 0);
  requestAnimationFrame(mockOutputTick);
}

function speakMock() {
  speaking = true;
  subtitleEl.textContent = mockLines[lineIndex % mockLines.length];
  lineIndex++;
  setTimeout(() => {
    speaking = false;
    subtitleEl.textContent = "listening…";
  }, 2200);
}

startMicVisualizer();
mockOutputTick();
setInterval(speakMock, 4000);
