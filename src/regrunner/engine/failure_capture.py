"""What was wrong with the page when a step failed.

"Timeout 30000ms exceeded" (a click) or "Object was not found" says nothing about *why*: whether something covers the link, the link is
in another frame, the frame was still loading, or the page keeps moving it.  When a step fails this reads the page - it never clicks,
types or scrolls anything - and keeps the answers next to the step (``diagnosis`` in ``results.json`` / the report):

* what the element is and whether a person could use it (visible, enabled, in view, standing still),
* what is on top of it at the point a click lands - in its own frame, and on the page that holds the frame,
* how many elements the step's locator matches in every frame (an element in a frame the step did not switch to),
* the frames of the page and the state of the one the step searched,
* the page's and the frame's HTML (scripts removed) in ``tests/<test>/dom/``.

Gathering is bounded (``failure_capture.budget_s``) and never raises: a step that already failed must not fail differently because its
evidence could not be collected.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable

from ..selectors.resolve import build_chain
from .enabled import DISABLED_BY_JS, SHORT_JS

# Runs in the document that holds the element (``root`` = the element) or, with ``arg.point``, in a document at that point (``root`` = <html>).
# Read-only.  It waits 150 ms between two measurements of the element to see whether it stands still (Playwright's "element is not stable").
_PROBE_JS = r"""async (root, arg) => {
  const doc = root.ownerDocument, win = doc.defaultView;
  const cut = (s, n) => { s = String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n) + '…' : s; };
  /*SHORT*/
  const rect = (r) => ({x: Math.round(r.left * 10) / 10, y: Math.round(r.top * 10) / 10, w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10});
  /*DISABLED_BY*/
  const target = arg.point ? null : root;
  const out = {url: cut(win.location.href, 300), ready: doc.readyState, viewport: [win.innerWidth, win.innerHeight],
               scroll: [Math.round(win.scrollX), Math.round(win.scrollY)], name: win.name || ''};
  let point = arg.point || null;
  if (target) {
    const r1 = target.getBoundingClientRect();
    await new Promise((done) => setTimeout(done, 150));
    const r2 = target.getBoundingClientRect();
    const cs = win.getComputedStyle(target);
    const off = disabledBy(target);
    const shown = typeof target.checkVisibility === 'function' ? target.checkVisibility({checkVisibilityCSS: true}) : (cs.display !== 'none' && cs.visibility !== 'hidden');
    out.element = {
      desc: short(target), html: cut(target.outerHTML, 300), rect: rect(r2), text: cut(target.innerText || target.textContent, 80),
      value: typeof target.value === 'string' ? cut(target.value, 60) : '',

      visible: shown && r2.width > 0 && r2.height > 0, display: cs.display, visibility: cs.visibility, opacity: cs.opacity, pointerEvents: cs.pointerEvents,
      disabled: !!off, disabledBy: off ? {desc: short(off.node), kind: off.kind, self: off.node === target, html: cut(off.node.outerHTML, 240)} : null,
      inert: !!target.closest('[inert]'),
      moving: Math.abs(r1.left - r2.left) > 0.5 || Math.abs(r1.top - r2.top) > 0.5 || Math.abs(r1.width - r2.width) > 0.5 || Math.abs(r1.height - r2.height) > 0.5,
      inViewport: r2.left >= 0 && r2.top >= 0 && r2.right <= win.innerWidth && r2.bottom <= win.innerHeight,
    };
    point = [r2.left + r2.width / 2, r2.top + r2.height / 2];
  }
  if (!point) return out;
  const [x, y] = point;
  let top = (x >= 0 && y >= 0 && x <= win.innerWidth && y <= win.innerHeight) ? doc.elementFromPoint(x, y) : null;
  while (top && top.shadowRoot) {
    const inner = top.shadowRoot.elementFromPoint(x, y);
    if (!inner || inner === top) break;
    top = inner;
  }
  let relation = 'none';
  if (top) {
    if (target) relation = top === target ? 'itself' : target.contains(top) ? 'inside' : top.contains(target) ? 'ancestor' : 'other';
    else relation = (top.tagName === 'IFRAME' || top.tagName === 'FRAME') ? 'frame' : 'other';
  }
  const chain = [];
  for (let n = top, i = 0; n && i < 6; n = n.parentElement, i++) chain.push(short(n));
  out.point = [Math.round(x), Math.round(y)];
  out.top = top ? {desc: short(top), relation, html: cut(top.outerHTML, 300), text: cut(top.innerText || top.textContent, 80), chain,
                   pointerEvents: win.getComputedStyle(top).pointerEvents} : {relation};
  const overlays = [];
  for (const n of doc.querySelectorAll('body *')) {
    if (target && (n === target || n.contains(target) || target.contains(n))) continue;
    const r = n.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || x < r.left || x > r.right || y < r.top || y > r.bottom) continue;
    const cs = win.getComputedStyle(n);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.pointerEvents === 'none') continue;
    if (!(cs.position === 'fixed' || ((cs.position === 'absolute' || cs.position === 'sticky') && cs.zIndex !== 'auto'))) continue;
    overlays.push({desc: short(n), z: cs.zIndex, position: cs.position, opacity: cs.opacity, rect: rect(r), text: cut(n.innerText, 60)});
  }
  overlays.sort((a, b) => (parseInt(b.z, 10) || 0) - (parseInt(a.z, 10) || 0));
  out.overlays = overlays.slice(0, 6);
  return out;
}"""

PROBE_JS = _PROBE_JS.replace("/*SHORT*/", SHORT_JS).replace("/*DISABLED_BY*/", DISABLED_BY_JS)     # what "not enabled" means is defined once, in enabled.py

_SHOWN_JS = "e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (typeof e.checkVisibility !== 'function' || e.checkVisibility({checkVisibilityCSS: true})); }"
_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.I | re.S)
_LOG_LINE = re.compile(r"^\s*-\s+(.*\S)\s*$")
_REASON = re.compile(r"intercepts pointer events|not enabled|not visible|not stable|outside of the viewport|scheduled navigations|not attached|strict mode violation|is disabled", re.I)


def _url_of(url: str) -> str:
    """A URL without its query and fragment (they can carry tokens) and short enough to read."""
    url = (url or "").split("#", 1)[0].split("?", 1)[0]
    return url if len(url) <= 200 else url[:200] + "…"


def _label(frame, main, position: int) -> str:
    if frame == main:
        return "main page"
    if frame.name:
        return f"frame '{frame.name}'"
    return f"frame #{position} ({_url_of(frame.url) or 'no address'})"


def last_log_lines(detail: str, count: int = 3) -> list[str]:
    """What Playwright's call log says it was stuck on: the last distinct *reason* lines ("<div> intercepts pointer events", "element is not enabled"),
    or - when it gave no reason - its last lines.  (A retry loop ends with "waiting for element to be visible, enabled and stable", which says nothing.)"""
    lines: list[str] = []
    for raw in (detail or "").splitlines():
        m = _LOG_LINE.match(raw)
        if m and m.group(1) not in lines[-1:]:
            lines.append(m.group(1))
    tail: list[str] = []
    for line in reversed([l for l in lines if _REASON.search(l)] or lines):
        if line not in tail:
            tail.append(line)
        if len(tail) == count:
            break
    return list(reversed(tail))


def _quote(text: str | None) -> str:
    return f" (“{text}”)" if text else ""


def _mask_all(obj: Any, mask: Callable[[str], str]) -> Any:
    """``mask`` applied to every string in the evidence (what a person typed in as a secret must not end up in a run folder)."""
    if isinstance(obj, str):
        return mask(obj)
    if isinstance(obj, dict):
        return {k: _mask_all(v, mask) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_all(v, mask) for v in obj]
    return obj


async def _bounded(coro, seconds: float) -> Any:
    try:
        return await asyncio.wait_for(coro, seconds)
    except Exception:
        return None


def xpath_prefixes(expr: str, limit: int = 8) -> list[str]:
    """An XPath cut at its location steps, each with everything before it (``//div[@id="a"]//span[contains(.,'x/y')]/b`` -> the div, div//span, div//span/b): what
    it takes to see which step of a locator stops matching.  Slashes inside ``[...]``, ``(...)`` or quotes are not step boundaries.  ``[]`` when it is one step."""
    starts, depth, quote = [], 0, ""
    for i, ch in enumerate(expr):
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch in "[(":
            depth += 1
        elif ch in "])":
            depth = max(0, depth - 1)
        elif ch == "/" and depth == 0 and (i == 0 or expr[i - 1] != "/"):
            starts.append(i)
    if len(starts) < 2 or starts[0] != 0:
        return []
    cuts = starts[1:] + [len(expr)]
    return [expr[:end] for end in cuts][:limit]


def _shorten(text: str, n: int = 110) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


async def _parts(scope, selector: str) -> list[dict[str, Any]]:
    """For an XPath that matches nothing: how many elements each growing prefix of it matches in ``scope`` - up to the step that leaves none."""
    if not selector.startswith("xpath="):
        return []
    out: list[dict[str, Any]] = []
    previous = ""
    for prefix in xpath_prefixes(selector[len("xpath="):]):
        count = await _bounded(scope.locator("xpath=" + prefix).count(), 1.5)
        out.append({"part": prefix[len(previous):], "count": count})
        previous = prefix
        if not count:
            break
    return out if len(out) > 1 or (out and not out[0]["count"]) else []


async def _matches(ctx, page, frames: list, main, scope) -> list[dict[str, Any]]:
    step, cfg = ctx.step, ctx.cfg
    try:
        chain = build_chain(step.findby, step.findby_value, step.locator_column, ctx.selector_map, legacy_fallback=cfg.selectors.legacy_fallback)[:3]
    except Exception:
        return []
    labels = [_label(f, main, i) for i, f in enumerate(frames)]
    rows = []
    for strategy in chain:
        counts = await asyncio.gather(*(_bounded(f.locator(strategy.selector).count(), 1.5) for f in frames))
        row = {"locator": strategy.describe(), "index": strategy.index if strategy.index is not None else step.index,
               "where": {label: count for label, count in zip(labels, counts) if count is not None},
               "searched": next((labels[i] for i, f in enumerate(frames) if f == scope), "main page")}
        here = row["where"].get(row["searched"]) or 0
        if not here:
            parts = await _parts(scope, strategy.selector)
            if parts:
                row["parts"] = parts                        # which step of the locator leaves nothing
        elif 1 < here <= 12:
            shown = await asyncio.gather(*(_bounded(scope.locator(strategy.selector).nth(i).evaluate(_SHOWN_JS), 1.5) for i in range(here)))
            row["visible"] = [bool(v) if v is not None else None for v in shown]      # which of the several matches a person could see
        rows.append(row)
    return rows


def _layer_line(lead: str, probe: dict[str, Any], top: dict[str, Any]) -> list[str]:
    """The positioned layer over the click point, unless it is the very element already named as being on top."""
    layers = [o for o in probe.get("overlays") or [] if o["desc"] != top.get("desc")]
    if not layers:
        return []
    o = layers[0]
    return [f"{lead}: <{o['desc']}> (z-index {o['z']}, {o['position']}, opacity {o['opacity']}{_quote(o.get('text'))})."]


def summarize(diag: dict[str, Any], error: str = "", log: list[str] | None = None) -> list[str]:
    """The findings in plain words, most telling first (what the report shows above the raw evidence).  ``log``: the last lines of the browser's call log."""
    out: list[str] = []
    for m in diag.get("matches", [])[:1]:
        where, searched = m["where"], m["searched"]
        here = where.get(searched)
        elsewhere = {k: v for k, v in where.items() if k != searched and v}
        if not here and elsewhere:
            out.append(f"{m['locator']} matches nothing in the {searched} the step searched, but does match in "
                       + ", ".join(f"{k} (x{v})" for k, v in elsewhere.items())
                       + ": the step is in the wrong frame (a Switch to Frame row is missing, extra or came too early).")
        elif here and here > 1:
            shown = m.get("visible")
            if shown and any(v for v in shown if v is not None) and not shown[m["index"] if m["index"] < len(shown) else -1]:
                seen = [str(i) for i, v in enumerate(shown) if v]
                out.append(f"{m['locator']} matches {here} elements in the {searched} and Index {m['index']} picked one that is hidden; the visible one{'s' if len(seen) > 1 else ''} "
                           f"{'are' if len(seen) > 1 else 'is'} Index {' / '.join(seen)}.")
            else:
                out.append(f"{m['locator']} matches {here} elements in the {searched}; Index {m['index']} picked one of them (a hidden earlier match would explain a click that never works).")
        elif not here and not elsewhere and where:
            out.append(f"{m['locator']} matches nothing in any frame: the element is not on the page (yet, or any more).")
        parts = m.get("parts") or []
        if parts and not here:
            stop = next((i for i, p in enumerate(parts) if not p["count"]), None)
            if stop == 0:
                out.append(f"Not even the first part of the locator, {_shorten(parts[0]['part'])}, matches anything in the {searched}.")
            elif stop is not None:
                so_far = "".join(p["part"] for p in parts[:stop])
                out.append(f"The locator matches up to {_shorten(so_far)} ({parts[stop - 1]['count']} element{'s' if parts[stop - 1]['count'] != 1 else ''}), "
                           f"but nothing once {_shorten(parts[stop]['part'])} is added: that part does not match what the page has (check its text and attributes against the page).")
    el, hit, top_page = diag.get("element"), diag.get("hit"), diag.get("hit_page")
    frame = diag.get("frame") or {}
    inside = "Inside its frame" if frame.get("path") else "On the page"
    comparison = error == "Comparison Failed"            # the element was found and read, and gave nothing: what a click needs is beside the point
    if comparison:
        el = hit = top_page = None
    if top_page:                                          # the page around the frame goes first: it takes the click before the frame ever sees it
        relation, top = (top_page.get("top") or {}).get("relation"), top_page.get("top") or {}
        if relation == "other":
            out.append(f"On the main page, above the frame at that point, is <{top.get('desc')}>{_quote(top.get('text'))}: it takes the click before the frame does"
                       " - this is what makes Playwright report 'intercepts pointer events' and keep retrying.")
        elif relation == "frame":
            out.append("On the main page nothing covers the frame at that point.")
        elif relation == "none":
            out.append("The point is outside the main page's viewport.")
        out.extend(_layer_line("Positioned layer on the main page over that point", top_page, top))
    if el:
        if not el.get("visible"):
            out.append(f"The element is not visible (display: {el.get('display')}, visibility: {el.get('visibility')}, size {el['rect']['w']}x{el['rect']['h']}).")
        if el.get("disabledBy"):
            off = el["disabledBy"]
            where = "it" if off.get("self") else f"<{off['desc']}>, which contains it,"
            out.append(f"The element counts as disabled: {where} has {off['kind']}. Playwright waits for a disabled element to become enabled and does not click it meanwhile"
                       + ("; Selenium (the legacy runner) never looked at aria-disabled, which is why the same click used to work." if "aria" in off["kind"] else "."))
        elif any("not enabled" in line.lower() for line in log or []):
            out.append("Playwright kept reporting the element as not enabled, but no disabled state was found on it or around it when the page was examined "
                       "(it may have been set only for a while, or sits in a shadow DOM that cannot be read).")
        if el.get("inert"):
            out.append("The element is inside an inert (non-interactive) region.")
        if el.get("pointerEvents") == "none":
            out.append("The element has pointer-events: none, so a click cannot reach it.")
        if el.get("moving"):
            out.append("The element kept moving or changing size while it was measured (an animation or a layout that does not settle): Playwright waits for it to stand still.")
        if el.get("visible") and not el.get("inViewport"):
            out.append("The element is partly or wholly outside the viewport.")
    if hit and not (el and not el.get("visible")):         # an element with no size has no point a click could land on
        top = hit.get("top") or {}
        relation = top.get("relation")
        if relation in ("itself", "inside"):
            out.append(f"{inside} nothing covers the element: at the point a click lands, the element itself is on top.")
        elif relation in ("other", "ancestor"):
            kind = "an element around it" if relation == "ancestor" else "another element"
            out.append(f"{inside}, at the point a click lands, {kind} is on top of the element: <{top.get('desc')}>{_quote(top.get('text'))}"
                       " - this is what makes Playwright report 'intercepts pointer events' and keep retrying.")
        elif relation == "none":
            out.append("The point a click lands on is outside the viewport, so nothing could be clicked there.")
        out.extend(_layer_line(f"{inside} a positioned layer is over that point", hit, top))
    read = diag.get("element") if comparison else None
    if read:                                              # the step read nothing although the element was found
        hidden = read.get("display") == "none" or read.get("visibility") == "hidden"
        if hidden:
            out.append("The step read an empty text because the element is hidden (display: none / visibility: hidden): a hidden element's text counts as empty "
                       "(the legacy runner did the same). The locator probably points at a copy of the text that stays hidden while another copy is shown.")
        elif read.get("value") and not read.get("text"):
            out.append(f"The element has no text, but its value is “{read['value']}”: read it with Output_Property = value.")
        elif not read.get("text"):
            out.append("The element contains no text" + (" and takes no room on the page" if not read.get("visible") else "") + ": the text is probably in another element.")
        elif not read.get("visible"):
            out.append("The element has text but is not visible (no size or out of sight), so it reads as empty (the legacy runner did the same).")
    if frame.get("ready") not in (None, "complete"):
        what = f"The frame the step searched ({frame.get('name') or 'unnamed'})" if frame.get("path") else "The page"
        out.append(f"{what} was still loading (readyState: {frame['ready']}).")
    if diag.get("frame_missing"):
        out.append(f"The frame the step had switched to ({diag['frame_missing']}) is no longer on the page.")
    told = " ".join(log or []).lower()
    clear = bool(el and el.get("visible") and not el.get("disabled") and not el.get("inert") and "not enabled" not in told and el.get("pointerEvents") != "none" and not el.get("moving")
                 and ((hit or {}).get("top") or {}).get("relation") in ("itself", "inside")
                 and (not top_page or (top_page.get("top") or {}).get("relation") == "frame"))
    if clear and "Timeout" in error:                      # everything a click needs is fine now: what was it waiting for?
        if any("navigation" in line.lower() for line in log or []):
            out.append("Nothing was in the way: the click was made, and the browser then waited for the navigation it started, which did not finish in time "
                       "(the page it goes to loaded slowly, hung, or was blocked).")
        else:
            out.append("Nothing is in the way now (visible, enabled, standing still, not covered), so whatever stopped the click was there only while it was being "
                       "tried - the browser's log lines above say what it was stuck on.")
    if not out and error:
        out.append("The page shows nothing obviously wrong at this moment; see the browser's own error and the saved HTML.")
    return out


def _snapshot(html: str, why: str, url: str, limit_kb: int, mask: Callable[[str], str]) -> str:
    html = _SCRIPT.sub("<script></script>", html)
    html = mask(html)
    limit = limit_kb * 1024
    cut = ""
    if len(html) > limit:
        html, cut = html[:limit], f"\n<!-- cut here: the page is bigger than {limit_kb} KB (failure_capture.dom_max_kb) -->"
    header = (f"<!-- regrunner failure snapshot: {why}. Taken from {_url_of(url) or 'the page'} right after the step failed; "
              "scripts removed, so it is a still picture of the DOM, not a working page. -->\n")
    return header + html + cut


async def capture_failure(ctx, *, error: str, detail: str, run_dir: Path, dom_dir: Path | None, stem: str,
                          mask: Callable[[str], str] = lambda s: s) -> dict[str, Any] | None:
    """Evidence for one failed step (see the module docstring).  ``None`` when there is no browser page to look at."""
    session, cfg = ctx.session, ctx.cfg.failure_capture
    if not cfg.enabled or session is None or not session.is_open:
        return None
    diag: dict[str, Any] = {}
    try:
        await asyncio.wait_for(_gather(ctx, diag, run_dir, dom_dir, stem, mask), cfg.budget_s)
    except asyncio.TimeoutError:
        diag["incomplete"] = f"gathering was stopped after {cfg.budget_s:g} s"
    except Exception as err:
        diag["incomplete"] = f"could not be gathered: {type(err).__name__}"
    last = last_log_lines(detail)
    diag["summary"] = summarize(diag, error, last)
    if last:
        diag["playwright_last"] = last
    return _mask_all(diag, mask) or None


async def _gather(ctx, diag: dict[str, Any], run_dir: Path, dom_dir: Path | None, stem: str, mask: Callable[[str], str]) -> None:
    session, cfg = ctx.session, ctx.cfg.failure_capture
    page = session.page
    main = page.main_frame
    frames = list(page.frames)[:12]
    diag["page"] = {"url": _url_of(page.url), "windows": len([p for p in session.pages if not p.is_closed()])}
    diag["frames"] = [{"label": _label(f, main, i), "url": _url_of(f.url), "detached": f.is_detached()} for i, f in enumerate(frames)]
    path = [f"{s.by}:{s.value}" if s.by != "name" else str(s.value) for s in session.frame_path]
    scope = page
    try:
        scope = await session.scope()
    except Exception:
        if session.frame_path:
            diag["frame_missing"] = " > ".join(path)
    in_frame = scope is not page and scope != main
    scope_frame = scope if in_frame else main
    diag["frame"] = {"path": path, "name": getattr(scope_frame, "name", "") or ""}
    target = ctx.out.target

    async def probe_element():
        if target is None:
            return
        try:
            info = await target.evaluate(PROBE_JS, {"point": None}, timeout=3000)
        except Exception:
            diag["element_gone"] = "the element was no longer on the page when the failure was examined"
            return
        diag["element"] = info.pop("element", None)
        diag["hit"] = info
        diag["frame"].update(url=info.get("url", ""), ready=info.get("ready"))

    async def probe_page():
        if target is None or not in_frame:
            return
        try:
            box = await target.bounding_box(timeout=1500)
            if not box:
                return
            point = [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2]
            diag["hit_page"] = await main.locator("html").evaluate(PROBE_JS, {"point": point}, timeout=3000)
        except Exception:
            return

    async def scope_state():
        if target is None:
            try:
                diag["frame"]["ready"] = await asyncio.wait_for(scope_frame.evaluate("document.readyState"), 1.5)
                diag["frame"]["url"] = _url_of(scope_frame.url)
            except Exception:
                pass

    async def title():
        try:
            diag["page"]["title"] = (await asyncio.wait_for(page.title(), 1.5))[:200]
        except Exception:
            pass

    async def matches():
        rows = await _matches(ctx, page, frames, main, scope_frame)
        if rows:
            diag["matches"] = rows

    await asyncio.gather(probe_element(), probe_page(), scope_state(), title(), matches(), return_exceptions=True)
    if cfg.dom_snapshot and dom_dir is not None:
        diag["dom"] = await _save_dom(main, scope_frame, run_dir, dom_dir, stem, cfg.dom_max_kb, mask)


async def _save_dom(main, scope_frame, run_dir: Path, dom_dir: Path, stem: str, limit_kb: int, mask: Callable[[str], str]) -> dict[str, str]:
    saved: dict[str, str] = {}
    targets = [("page", main)] + ([("frame", scope_frame)] if scope_frame != main else [])
    for kind, frame in targets:
        html = await _bounded(frame.content(), 4.0)
        if not html:
            continue
        why = f"the {'frame the step searched' if kind == 'frame' else 'page'}"
        try:
            dom_dir.mkdir(parents=True, exist_ok=True)
            path = dom_dir / f"{stem}.{kind}.html"
            path.write_text(_snapshot(html, why, frame.url, limit_kb, mask), encoding="utf-8")
        except OSError:
            continue
        saved[kind] = path.relative_to(run_dir).as_posix()
    return saved
