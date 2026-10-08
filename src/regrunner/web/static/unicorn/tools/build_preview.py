#!/usr/bin/env python3
"""Regenerate ``unicorn/preview.html`` from ``svg/unicorn-front-sitting.svg``.

Why a generated page: the rig's states are ``data-*`` attributes on ``#unicorn``, and JavaScript can only flip them when the SVG is inline
(an ``<object>`` is blocked on ``file://``). The SVG stays the single source of truth; this page only inlines it next to some buttons.
The MOODS table below is the same one documented in ``docs/rig-spec.md``: keep them in step.

Run:  python3 src/regrunner/web/static/unicorn/tools/build_preview.py      (Python 3.9 compatible, standard library only)
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SVG = HERE / "svg" / "unicorn-front-sitting.svg"
OUT = HERE / "preview.html"

MOODS = {
    "neutral": {"eyes": "open", "brows": "neutral", "mouth": "neutral", "ears": "neutral", "fx": "none"},
    "happy": {"eyes": "open", "brows": "up", "mouth": "smile", "ears": "neutral", "fx": "none"},
    "excited": {"eyes": "wide", "brows": "up", "mouth": "open", "ears": "perk", "fx": "sparkle"},
    "joyful": {"eyes": "closed", "brows": "up", "mouth": "open", "ears": "perk", "fx": "sparkle"},
    "sad": {"eyes": "sad", "brows": "sad", "mouth": "frown", "ears": "droop", "fx": "none"},
    "scared": {"eyes": "scared", "brows": "scared", "mouth": "open", "ears": "flat", "fx": "sweat"},
    "angry": {"eyes": "angry", "brows": "angry", "mouth": "frown", "ears": "back", "fx": "steam"},
}

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
  <div class="bar" id="moods" role="group" aria-label="Mood"></div>
  <div class="bar">
    <label><input type="checkbox" id="idle-toggle" checked> idle animation</label>
    <button id="blink" type="button">Blink now</button>
    <button id="settle" type="button">Rest</button>
    <label>strength <input type="range" id="intensity" min="0" max="1.5" step="0.1" value="1"></label>
    <label><input type="checkbox" id="pivots-toggle"> show pivots</label>
  </div>
  <div class="bar">
    <span>state: <code id="state"></code></span>
    <span>idle: <code id="idle-stats"></code></span>
  </div>
</main>
<script src="js/idle.js"></script>
<script>
const MOODS = __MOODS__;
const root = document.getElementById("unicorn");
const bar = document.getElementById("moods");
function setMood(name) {
  const m = MOODS[name];
  for (const k of Object.keys(m)) root.setAttribute("data-" + k, m[k]);
  for (const b of bar.children) b.setAttribute("aria-pressed", String(b.dataset.mood === name));
  document.getElementById("state").textContent = JSON.stringify(m);
}
for (const name of Object.keys(MOODS)) {
  const b = document.createElement("button");
  b.type = "button"; b.textContent = name; b.dataset.mood = name;
  b.addEventListener("click", () => setMood(name));
  bar.appendChild(b);
}
document.getElementById("pivots-toggle").addEventListener("change", e => root.classList.toggle("show-pivots", e.target.checked));
// Idle animation (js/idle.js): one 30 fps loop, paused when the tab is hidden, off under prefers-reduced-motion.
const idle = UnicornIdle.attach(document.querySelector("#stage svg"));
const idleToggle = document.getElementById("idle-toggle");
idleToggle.addEventListener("change", () => (idleToggle.checked ? idle.start() : idle.stop()));
document.getElementById("blink").addEventListener("click", () => idle.blinkNow());
document.getElementById("settle").addEventListener("click", () => { idle.settle(); idleToggle.checked = false; });
document.getElementById("intensity").addEventListener("input", e => idle.setIntensity(parseFloat(e.target.value)));
let lastFrames = 0;
setInterval(() => {
  const s = idle.stats();
  document.getElementById("idle-stats").textContent = (s.running ? ((s.frames - lastFrames) * 2) + " fps, " : "stopped, ") + s.writes + " style writes";
  lastFrames = s.frames;
}, 500);
setMood("neutral");
</script>
</body>
</html>
"""


def main() -> None:
    svg = SVG.read_text(encoding="utf-8")
    if svg.startswith("<?xml"):
        svg = svg.split("?>", 1)[1].lstrip()
    html = PAGE.replace("__SVG__", svg).replace("__MOODS__", json.dumps(MOODS))
    OUT.write_text(html, encoding="utf-8")
    print("wrote", OUT, len(html), "bytes")


if __name__ == "__main__":
    main()
