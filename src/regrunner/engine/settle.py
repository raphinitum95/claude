"""Adaptive replacement for fixed ``Wait`` sleeps.

A tiny script (installed in every frame of every page) tracks in-flight fetch/XHR requests and the
time of the last DOM mutation.  ``settle`` returns as soon as the page has been quiet - no pending
requests and no DOM changes - for ``quiet_ms``, never later than the row's own seconds.  Legacy
sleeps were guesses sized for the slowest case; this returns as soon as the page is actually ready.
"""
from __future__ import annotations

import asyncio
import time

SETTLE_INIT_JS = r"""
(() => {
  if (window.__rr) return;
  const rr = window.__rr = { inflight: 0, mutated: performance.now(), network: performance.now() };
  const bump = () => { rr.mutated = performance.now(); };
  const observe = () => { try { new MutationObserver(bump).observe(document.documentElement,
      { subtree: true, childList: true, attributes: true, characterData: true }); } catch (_) {} };
  if (document.documentElement) observe(); else document.addEventListener('DOMContentLoaded', observe, { once: true });
  const done = () => { rr.inflight = Math.max(0, rr.inflight - 1); rr.network = performance.now(); };
  if (window.fetch) {
    const f = window.fetch;
    window.fetch = function (...a) { rr.inflight++; rr.network = performance.now();
      return f.apply(this, a).then(r => { done(); return r; }, e => { done(); throw e; }); };
  }
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...a) { rr.inflight++; rr.network = performance.now();
    this.addEventListener('loadend', done, { once: true }); return send.apply(this, a); };
  rr.idleFor = () => rr.inflight > 0 ? 0 : performance.now() - Math.max(rr.mutated, rr.network);
})();
"""


async def idle_ms(page) -> float:
    """Smallest idle time over all frames (a frame that cannot answer counts as busy)."""
    async def one(frame) -> float:
        try:
            return float(await frame.evaluate("window.__rr ? window.__rr.idleFor() : 1e9"))
        except Exception:
            return 0.0
    frames = [f for f in page.frames if not f.is_detached()]
    if not frames:
        return 0.0
    return min(await asyncio.gather(*(one(f) for f in frames)))


async def settle(page, max_s: float, quiet_ms: int = 400, min_s: float = 0.0) -> float:
    """Wait until ``page`` is quiet (or ``max_s`` elapses). Returns the seconds actually waited."""
    started = time.monotonic()
    deadline = started + max_s
    floor = started + min(min_s, max_s)
    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        if now >= floor and await idle_ms(page) >= quiet_ms:
            break
        await asyncio.sleep(0.05)
    return time.monotonic() - started
