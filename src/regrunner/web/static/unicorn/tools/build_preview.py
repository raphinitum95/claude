#!/usr/bin/env python3
"""Regenerate ``unicorn/preview.html`` from ``svg/unicorn-front-sitting.svg``.

Why a generated page: the rig's states are ``data-*`` attributes on ``#unicorn``, and JavaScript can only flip them when the SVG is inline
(an ``<object>`` is blocked on ``file://``). The SVG stays the single source of truth; this page only inlines it next to some buttons.
The moods come from ``js/mood.js`` (``UnicornMood.POSES``, the single source of truth, checked against ``docs/rig-spec.md`` by a test).

Run:  python3 src/regrunner/web/static/unicorn/tools/build_preview.py      (Python 3.9 compatible, standard library only)
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SVG = HERE / "svg" / "unicorn-front-sitting.svg"
OUT = HERE / "preview.html"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unicorn rig preview</title>
<style>
  body { margin: 0; font: 15px/1.4 system-ui, sans-serif; background: #CDCDCD; color: #2a2133; }
  main { max-width: 760px; margin: 0 auto; padding: 16px; }
  h1 { font-size: 18px; margin: 4px 0 12px; }
  .stage { background: #CDCDCD; border-radius: 16px; }
  .stage svg { display: block; width: 100%; height: auto; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; align-items: center; }
  button { font: inherit; padding: 8px 14px; border: 0; border-radius: 999px; background: #fff; color: #2a2133; cursor: pointer; }
  button[aria-pressed="true"] { background: #7a4fa3; color: #fff; }
  label { display: inline-flex; gap: 6px; align-items: center; }
  code { background: #fff8; padding: 2px 6px; border-radius: 6px; }
</style>
</head>
<body>
<main>
  <h1>Unicorn rig preview <small>(generated: edit svg/unicorn-front-sitting.svg, then run tools/build_preview.py)</small></h1>
  <div class="stage" id="stage">__SVG__</div>
  <div class="bar" id="moods" role="group" aria-label="Mood (manual override)"></div>
  <div class="bar" role="group" aria-label="Run simulator">
    <button id="run-start" type="button">Start run</button>
    <button id="run-pass" type="button">Pass</button>
    <button id="run-fail" type="button">Fail</button>
    <button id="run-finish" type="button">Finish run</button>
    <label>auto-run pass rate <input type="range" id="auto-rate" min="0" max="100" step="5" value="85"> <output id="auto-rate-out">85%</output></label>
    <button id="run-auto" type="button">Auto-run 30 tests</button>
  </div>
  <div class="bar">
    <label><input type="checkbox" id="idle-toggle" checked> idle animation</label>
    <button id="blink" type="button">Blink now</button>
    <button id="settle" type="button">Rest</button>
    <label>strength <input type="range" id="intensity" min="0" max="1.5" step="0.1" value="1"></label>
    <button id="fx-burst" type="button">Glitter burst</button>
    <button id="fx-rain-toggle" type="button">Rain on / off</button>
    <label><input type="checkbox" id="pivots-toggle"> show pivots</label>
  </div>
  <div class="bar">
    <span>mood: <code id="mood-now"></code></span>
    <span>totals: <code id="totals-now"></code></span>
    <span>idle: <code id="idle-stats"></code></span>
  </div>
</main>
<script src="js/idle.js"></script>
<script src="js/fx.js"></script>
<script src="js/mood.js"></script>
<script>
const svg = document.querySelector("#stage svg");
const root = document.getElementById("unicorn");
const idle = UnicornIdle.attach(svg);
function show(mood, totals) {
  document.getElementById("mood-now").textContent = mood + (manual ? " (manual)" : "");
  const n = totals.passed + totals.failed;
  document.getElementById("totals-now").textContent = totals.passed + " pass / " + totals.failed + " fail" + (n ? " (" + Math.round(100 * totals.passed / n) + "%)" : "") + (totals.done ? " - finished" : totals.running ? " - running" : "");
}
let manual = false;
const fx = UnicornFx.attach(document.getElementById("stage"), { svg: svg });
const unicorn = UnicornMood.create(svg, { idle: idle, fx: fx, onChange: show });
window.unicorn = unicorn;                       // the interface from the brief: unicorn.onRunStart / onTestResult / onRunComplete / setMood
const bar = document.getElementById("moods");
function setManual(name) { manual = !!name; unicorn.setMood(name); for (const b of bar.children) b.setAttribute("aria-pressed", String(b.dataset.mood === (name || "auto"))); }
for (const name of ["auto"].concat(Object.keys(UnicornMood.POSES))) {
  const b = document.createElement("button");
  b.type = "button"; b.textContent = name; b.dataset.mood = name;
  b.addEventListener("click", () => setManual(name === "auto" ? null : name));
  bar.appendChild(b);
}
setManual(null);
const clickTo = (id, fn) => document.getElementById(id).addEventListener("click", fn);
clickTo("run-start", () => { setManual(null); unicorn.onRunStart({}); });
clickTo("run-pass", () => unicorn.onTestResult({ status: "pass" }));
clickTo("run-fail", () => unicorn.onTestResult({ status: "fail" }));
clickTo("run-finish", () => { const t = unicorn.getTotals(); unicorn.onRunComplete({ passed: t.passed, failed: t.failed, total: t.passed + t.failed }); });
document.getElementById("auto-rate").addEventListener("input", e => { document.getElementById("auto-rate-out").textContent = e.target.value + "%"; });
let autoTimer = null;
clickTo("run-auto", () => {
  clearInterval(autoTimer); setManual(null);
  unicorn.onRunStart({ totalTests: 30 });
  let done = 0;
  autoTimer = setInterval(() => {
    const pass = Math.random() * 100 < parseInt(document.getElementById("auto-rate").value, 10);
    unicorn.onTestResult({ status: pass ? "pass" : "fail" });
    done += 1;
    if (done === 30) { clearInterval(autoTimer); const t = unicorn.getTotals(); setTimeout(() => unicorn.onRunComplete({ passed: t.passed, failed: t.failed, total: 30 }), 600); }
  }, 450);
});
clickTo("fx-burst", () => fx.celebrate());
clickTo("fx-rain-toggle", () => fx.rain(!fx.isRaining()));
document.getElementById("pivots-toggle").addEventListener("change", e => root.classList.toggle("show-pivots", e.target.checked));
// Idle animation (js/idle.js): one 30 fps loop, paused when the tab is hidden, off under prefers-reduced-motion.
const idleToggle = document.getElementById("idle-toggle");
idleToggle.addEventListener("change", () => (idleToggle.checked ? idle.start() : idle.stop()));
clickTo("blink", () => idle.blinkNow());
clickTo("settle", () => { idle.settle(); idleToggle.checked = false; });
document.getElementById("intensity").addEventListener("input", e => idle.setIntensity(parseFloat(e.target.value)));
let lastFrames = 0;
setInterval(() => {
  const st = idle.stats();
  idleToggle.checked = st.running || idleToggle.checked && !idle.settled();
  const fs = fx.stats();
  document.getElementById("idle-stats").textContent = (st.running ? ((st.frames - lastFrames) * 2) + " fps, " : "stopped, ") + st.writes + " style writes; fx: " + (fs.running ? fs.live + " particles" : "off");
  lastFrames = st.frames;
}, 500);
unicorn.setMood(null);
</script>
</body>
</html>
"""


def main() -> None:
    svg = SVG.read_text(encoding="utf-8")
    if svg.startswith("<?xml"):
        svg = svg.split("?>", 1)[1].lstrip()
    html = PAGE.replace("__SVG__", svg)
    OUT.write_text(html, encoding="utf-8")
    print("wrote", OUT, len(html), "bytes")


if __name__ == "__main__":
    main()
