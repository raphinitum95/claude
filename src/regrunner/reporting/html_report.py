"""Self-contained HTML report (screenshots embedded, timestamps stamped) with optional PDF export.

The HTML has no external dependencies, so it can be emailed, archived or opened offline as the
proof of testing.  The PDF is produced by printing the very same HTML with Playwright.
"""
from __future__ import annotations

import asyncio
import base64
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import browsers
from .results import variables_of

_CSS = """
:root{--bg:#fff;--fg:#1b1f24;--muted:#5b6673;--line:#dfe3e8;--card:#f6f8fa;--pass:#1a7f37;--pass-bg:#dafbe1;
--fail:#cf222e;--fail-bg:#ffebe9;--warn:#9a6700;--warn-bg:#fff8c5;--info:#0969da;--info-bg:#ddf4ff;--code:#eef1f4}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--line:#30363d;--card:#161b22;
--pass:#3fb950;--pass-bg:#12261a;--fail:#f85149;--fail-bg:#2d1518;--warn:#d29922;--warn-bg:#2b230d;--info:#58a6ff;
--info-bg:#0c2238;--code:#1c2128}}
*{box-sizing:border-box}a{color:var(--info)}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1400px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px}
.muted{color:var(--muted)}.pill{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid transparent}
.PASSED{color:var(--pass);background:var(--pass-bg)}.FAILED,.ERROR{color:var(--fail);background:var(--fail-bg)}
.CANCELLED,.RUNNING,.QUEUED,.INTERRUPTED{color:var(--warn);background:var(--warn-bg)}.warning{color:var(--warn);background:var(--warn-bg)}
.info{color:var(--info);background:var(--info-bg)}.error{color:var(--fail);background:var(--fail-bg)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px}.tile b{display:block;font-size:22px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em;position:sticky;top:0;background:var(--bg)}
details.test{border:1px solid var(--line);border-radius:8px;margin:10px 0;background:var(--bg)}
details.test>summary{cursor:pointer;padding:10px 14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;background:var(--card);border-radius:8px}
details.test[open]>summary{border-bottom:1px solid var(--line);border-radius:8px 8px 0 0}
code,.mono{font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}code{background:var(--code);padding:1px 5px;border-radius:4px;word-break:break-all}
tr.failed td{background:var(--fail-bg)}tr.ignored td:first-child{box-shadow:inset 3px 0 var(--warn)}
.thumb{height:64px;border:1px solid var(--line);border-radius:4px;cursor:zoom-in;display:block}
.thumb.full{margin-top:4px;width:64px;object-fit:cover;object-position:top;border-style:dashed}
#lb.tall{align-items:flex-start;overflow:auto}#lb.tall img{max-width:min(96vw,1200px);max-height:none;margin:0 auto}
.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;font-size:12px}.kv span:nth-child(odd){color:var(--muted)}
.note{font-size:12px;color:var(--muted)}.scroll{overflow:auto;max-height:70vh}
.why{margin-top:6px;font-size:12px}.why-line{margin:2px 0}.why details{margin-top:4px}.why summary{cursor:pointer;color:var(--muted)}
.why pre{white-space:pre-wrap;word-break:break-word;background:var(--code);padding:6px 8px;border-radius:4px;max-height:260px;overflow:auto;margin:4px 0}
.browser{margin:6px 0 2px}.browser .pill{font-size:13px}
#lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:9;align-items:center;justify-content:center;cursor:zoom-out}
#lb img{max-width:96vw;max-height:96vh;border-radius:6px}
.banner{background:var(--info-bg);color:var(--info);border-radius:8px;padding:8px 12px;margin:10px 0;font-size:13px}
@media print{.thumb{height:70px}details.test{break-inside:auto}tr{break-inside:avoid}th{position:static}.scroll{max-height:none;overflow:visible}
#lb{display:none!important}body{font-size:11px}}
"""

_JS = """
function lb(img){const l=document.getElementById('lb');l.querySelector('img').src=img.src;l.classList.toggle('tall',img.dataset.full==='1');l.style.display='flex'}
document.getElementById('lb').addEventListener('click',e=>{e.currentTarget.style.display='none'});
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('lb').style.display='none'});
function expandAll(open){document.querySelectorAll('details.test').forEach(d=>d.open=open)}
"""


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def visible_ws(text: str) -> str:
    """Make invisible characters visible - the usual cause of an Exact_Match mismatch."""
    return (text.replace(" ", "⍽").replace("\t", "→").replace("\r", "").replace("\n", "↵\n")
            .replace("​", "‹zwsp›"))


def _time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M:%S.%f")[:-3]
    except (TypeError, ValueError):
        return ""


def _dur(ms: int) -> str:
    return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def _embed(run_dir: Path, rel: str | None, mode: str, failed: bool, full: bool = False) -> str:
    if not rel or mode == "none" or (mode == "failures" and not failed):
        return ""
    path = run_dir / rel
    if not path.is_file():
        return ""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    cls, alt = ("thumb full", "whole page (scroll)") if full else ("thumb", "step screenshot")
    return f'<img class="{cls}" data-full="{1 if full else 0}" loading="lazy" alt="{alt}" title="{alt}" onclick="lb(this)" src="data:{mime};base64,{b64}">'


def _where(counts: dict[str, Any]) -> str:
    return ", ".join(f"{esc(label)} ×{count}" for label, count in counts.items()) or "-"


def _why(step: dict[str, Any]) -> str:
    """A failed step's findings (plain words) with the evidence behind them folded away: the browser's own error, where the locator matches, the frames, the saved HTML."""
    diag, detail = step.get("diagnosis") or {}, step.get("detail") or ""
    if not diag and not detail:
        return ""
    lines = "".join(f'<div class="why-line">{esc(line)}</div>' for line in diag.get("summary", []))
    raw = []
    if diag.get("playwright_last"):
        raw.append('<div class="note">the browser was stuck on: ' + " · ".join(f"<code>{esc(x)}</code>" for x in diag["playwright_last"]) + "</div>")
    if detail:
        raw.append(f'<div class="note">the browser\'s whole error</div><pre class="mono">{esc(detail)}</pre>')
    for m in diag.get("matches", []):
        raw.append(f'<div class="kv"><span>matches</span><span><code>{esc(m["locator"])}</code> {_where(m["where"])} <span class="muted">(searched: {esc(m["searched"])}; Index {esc(m["index"])})</span></span></div>')
    page = diag.get("page") or {}
    if page:
        raw.append(f'<div class="kv"><span>page</span><span>{esc(page.get("title", ""))} <span class="muted">{esc(page.get("url", ""))}</span></span></div>')
    frame = diag.get("frame") or {}
    if frame:
        raw.append(f'<div class="kv"><span>frame searched</span><span>{esc(" > ".join(frame.get("path") or []) or "main page")}'
                   f' <span class="muted">{esc(frame.get("url", ""))} {esc(frame.get("ready", ""))}</span></span></div>')
    if diag.get("frames"):
        raw.append('<div class="kv"><span>frames</span><span>' + "<br>".join(f'{esc(f["label"])} <span class="muted">{esc(f["url"])}</span>' for f in diag["frames"]) + "</span></div>")
    for key, title in (("element", "element"),):
        el = diag.get(key)
        if el:
            raw.append(f'<div class="kv"><span>{title}</span><span><code>{esc(el.get("html", ""))}</code></span></div>')
    top = (diag.get("hit") or {}).get("top") or {}
    if top.get("html"):
        raw.append(f'<div class="kv"><span>on top of it</span><span><code>{esc(top["html"])}</code></span></div>')
    top = (diag.get("hit_page") or {}).get("top") or {}
    if top.get("html"):
        raw.append(f'<div class="kv"><span>on top, main page</span><span><code>{esc(top["html"])}</code></span></div>')
    for kind, rel in (diag.get("dom") or {}).items():
        raw.append(f'<div class="kv"><span>saved HTML ({esc(kind)})</span><span><code>{esc(rel)}</code></span></div>')
    if diag.get("incomplete"):
        raw.append(f'<div class="note">{esc(diag["incomplete"])}</div>')
    folded = f"<details><summary>evidence</summary>{''.join(raw)}</details>" if raw else ""
    return f'<div class="why"><span class="pill info">why</span>{lines}{folded}</div>'


def _step_row(step: dict[str, Any], run_dir: Path, mode: str) -> str:
    failed = step["status"] == "FAILED"
    cls = "failed" if failed else ("ignored" if step.get("ignored_error") else "")
    detail = []
    if step.get("locator"):
        detail.append(f'<div class="kv"><span>locator</span><code>{esc(step["locator"])}</code></div>')
    if step.get("value"):
        detail.append(f'<div class="kv"><span>value</span><code>{esc(step["value"])}</code></div>')
    for var in step.get("sets", []):
        detail.append(f'<div class="kv"><span class="pill info">sets {esc(var.get("name"))}</span><code>{esc(var.get("stored", var.get("value", "")))}</code></div>')
    if step.get("expected") or failed and step.get("comparison"):
        mode_label = {"exact": "exact match", "contains": "contains", "": "not compared"}[step.get("comparison") or ""]
        detail.append(f'<div class="kv"><span>expected ({mode_label})</span><code>{esc(visible_ws(step.get("expected", "")))}</code></div>')
    if step.get("actual") != "" or failed:
        detail.append(f'<div class="kv"><span>actual</span><code>{esc(visible_ws(step.get("actual", "")))}</code></div>')
    if step.get("error"):
        detail.append(f'<div><span class="pill FAILED">{esc(step["error"])}</span></div>')
    if failed:
        detail.append(_why(step))
    if step.get("ignored_error"):
        detail.append(f'<div class="note">ignored (Ignore_not_existing_object=Y): {esc(step["ignored_error"])}</div>')
    for note in step.get("notes", []):
        detail.append(f'<div class="note">{esc(note)}</div>')
    return (
        f'<tr class="{cls}"><td>{step["seq"]}</td><td class="muted">{step["row"]}</td>'
        f'<td>{esc(step["name"] or "")}</td><td><code>{esc(step["action"])}</code></td>'
        f'<td><span class="pill {esc(step["status"])}">{esc(step["status"])}</span></td>'
        f'<td>{"".join(detail)}</td><td class="muted" title="{esc(step.get("started_at"))}">'
        f'{_time(step.get("started_at", ""))}<br>{_dur(step.get("duration_ms", 0))}</td>'
        f'<td>{_embed(run_dir, step.get("screenshot"), mode, failed)}{_embed(run_dir, step.get("screenshot_full"), mode, failed, full=True)}</td></tr>')


def _review_rows(test: dict[str, Any]) -> str:
    rows = []
    for item in test.get("review", []):
        kind = item.get("type")
        if kind == "console_error":
            what = f'<span class="pill error">{esc(item.get("kind", "console"))}</span>'
            body = esc(item.get("message", "")) + (f' <span class="muted">({esc(item.get("url"))})</span>' if item.get("url") else "")
        elif kind == "network_error":
            status = item.get("status")
            what = f'<span class="pill error">{esc(status) if status else esc(item.get("kind"))}</span>'
            body = f'<code>{esc(item.get("method", ""))}</code> {esc(item.get("url", ""))} <span class="muted">{esc(item.get("message", ""))}</span>'
        else:
            what = f'<span class="pill {esc(item.get("severity", "info"))}">{esc(item.get("category", "review"))}</span>'
            body = esc(item.get("message", ""))
        count = f' <span class="muted">×{item["count"]}</span>' if item.get("count", 1) > 1 else ""
        rows.append(f'<tr><td>{esc(test["id"])}</td><td>{item.get("step", "")} <span class="muted">{esc(item.get("step_name", ""))}</span></td>'
                    f'<td>{what}</td><td>{body}{count}</td></tr>')
    return "".join(rows)


def _browser_line(browser: dict[str, Any]) -> str:
    """The browser every test of the run used, right under the title: it is part of what the report proves."""
    if browser.get("id") in ("none", "unknown"):
        return f'<div class="browser"><b>Browser</b> {esc(browser.get("text"))}' + (
            ' <span class="muted">This run did not record which browser it used.</span>' if browser.get("id") == "unknown" else "") + "</div>"
    mode = "headless" if browser.get("headless", True) else "headed (windows were shown)"
    note = ""
    if browser.get("approximate"):
        note = (f' <span class="muted">{esc(browser.get("what"))}</span>')
    elif not browser.get("recorded", True):
        note = ' <span class="muted">This run did not record its browser; this is what its saved settings select. The exact version is unknown.</span>'
    return f'<div class="browser"><b>Browser</b> <span class="pill info">{esc(browser.get("text"))}</span> <span class="muted">{esc(mode)}</span>{note}</div>'


def _browser_details(browser: dict[str, Any]) -> str:
    if browser.get("id") in ("none", "unknown"):
        return f'<div class="kv"><span>Browser</span><span>{esc(browser.get("text"))}</span></div>'
    rows = [("Browser", browser.get("text", "")), ("Engine", " ".join(x for x in (browser.get("engine_label", ""), browser.get("version", "")) if x)),
            ("Mode", "headless" if browser.get("headless", True) else "headed"), ("User agent", browser.get("user_agent", "") or "not recorded"),
            ("What ran", browser.get("what", ""))]
    return '<div class="kv">' + "".join(f"<span>{esc(k)}</span><span>{esc(v)}</span>" for k, v in rows) + "</div>"


def render_html(data: dict[str, Any], run_dir: Path, screenshots: str = "all") -> str:
    summary = data.get("summary", {})
    tests = data.get("tests", [])
    status = data.get("status", "")
    browser = browsers.identity_of(data)
    tiles = [("Tests", summary.get("tests", 0)), ("Passed", summary.get("passed", 0)),
             ("Failed", summary.get("failed", 0) + summary.get("errored", 0)), ("Steps", summary.get("steps", 0)),
             ("Failed steps", summary.get("steps_failed", 0)), ("To review", summary.get("review_items", 0)),
             ("Duration", f'{data.get("duration_s", 0):.0f} s'), ("Workers", data.get("workers", 1))]
    out = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>Regression report {esc(data.get("run_id"))}</title><style>{_CSS}</style></head><body><main>',
           f'<h1>Regression report <span class="pill {esc(status)}">{esc(status)}</span></h1>',
           f'<div class="muted">{esc(Path(data.get("workbook", "")).name)} · environment <b>{esc(data.get("environment"))}</b> · '
           f'run <code>{esc(data.get("run_id"))}</code> · started {esc(data.get("started_at"))} · finished {esc(data.get("ended_at"))}</div>',
           _browser_line(browser)]
    if data.get("partial"):
        out.append('<div class="banner">This run stopped before it finished. The report was rebuilt from the event log: '
                   'tests that were mid-flight are marked INTERRUPTED, and repeat counts of review items restart at 1.</div>')
    for w in data.get("warnings", []):
        out.append(f'<div class="banner">{esc(w)}</div>')
    out.append('<div class="tiles">' + "".join(f'<div class="tile"><span class="muted">{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in tiles) + "</div>")
    out.append("<h2>Tests</h2><table><tr><th>Test</th><th>Result</th><th>Steps</th><th>Failed</th><th>Review</th><th>Started</th><th>Duration</th></tr>")
    for t in tests:
        out.append(f'<tr><td><a href="#t-{esc(t["id"])}">{esc(t["title"])}</a> <span class="muted">{esc(t.get("description", ""))}</span></td>'
                   f'<td><span class="pill {esc(t["status"])}">{esc(t["status"])}</span></td><td>{len(t.get("steps", []))}/{t.get("total_steps", 0)}</td>'
                   f'<td>{t.get("failed", 0)}</td><td>{len(t.get("review", []))}</td><td class="muted">{_time(t.get("started_at", ""))}</td>'
                   f'<td>{t.get("duration_s", 0):.1f} s</td></tr>')
    out.append('</table>')
    rows = [(t, v) for t in tests for v in variables_of(t)]
    if rows:                                                       # what the tests produced: a quote number, a policy number...
        out.append('<h2>Values set by the tests</h2><p class="muted">Parameters a step filled in (its Output_Value names a Params column). '
                   'They are what later tests of the run, and the API tests, read.</p>'
                   '<table><tr><th>Test</th><th>Variable</th><th>Value</th><th>Set by</th><th>Stored in</th></tr>')
        for t, v in rows:
            by = "entered by hand" if v.get("by_hand") else f'step {esc(v.get("seq"))} · row {esc(v.get("row"))} <span class="muted">{esc(v.get("step", ""))}</span>'
            out.append(f'<tr><td><a href="#t-{esc(t["id"])}">{esc(t["id"])}</a></td><td><code>{esc(v.get("name"))}</code></td>'
                       f'<td><code>{esc(v.get("stored", v.get("value", "")))}</code></td><td>{by}</td><td class="muted">{esc(v.get("cell", ""))}</td></tr>')
        out.append('</table>')
    out.append('<p><a href="javascript:expandAll(true)">Expand all</a> · <a href="javascript:expandAll(false)">Collapse all</a></p>')

    out.append("<h2>Step-by-step evidence</h2>")
    for t in tests:
        open_attr = " open" if t["status"] != "PASSED" else ""
        out.append(f'<details class="test" id="t-{esc(t["id"])}"{open_attr}><summary><b>{esc(t["title"])}</b>'
                   f'<span class="pill {esc(t["status"])}">{esc(t["status"])}</span>'
                   f'<span class="muted">{esc(t.get("scenario", ""))} · {len(t.get("steps", []))} steps · {t.get("passed", 0)} passed · {t.get("failed", 0)} failed'
                   f' · {t.get("duration_s", 0):.1f} s · attempt {t.get("attempt", 1)}</span></summary>')
        if t.get("error"):
            out.append(f'<div class="banner">{esc(t["error"])}</div>')
        out.append('<div class="scroll"><table><tr><th>#</th><th>Row</th><th>Step</th><th>Action</th><th>Result</th><th>Detail</th><th>Time</th><th>Screenshot</th></tr>')
        out.extend(_step_row(s, run_dir, screenshots) for s in t.get("steps", []))
        out.append("</table></div></details>")

    review_rows = "".join(_review_rows(t) for t in tests)
    out.append('<h2>Things to review</h2><p class="muted">Console errors, uncaught page exceptions, failed requests and HTTP 4xx/5xx '
               'responses seen while the tests ran. This section is informational: it never changes a pass/fail result.</p>')
    if review_rows:
        out.append('<div class="scroll"><table><tr><th>Test</th><th>Step</th><th>Type</th><th>Detail</th></tr>' + review_rows + "</table></div>")
    else:
        out.append('<p class="muted">Nothing to review.</p>')
    out.append('<h2>Run settings</h2>' + _browser_details(browser)
               + f'<pre class="mono">{esc(json.dumps(data.get("config", {}), indent=2))}</pre>')
    out.append('</main><div id="lb"><img alt=""></div><script>' + _JS + "</script></body></html>")
    return "".join(out)


async def build_report(run_dir: Path, pdf: bool = False, screenshots: str | None = None,
                       from_events: bool = False) -> dict[str, str]:
    if from_events:
        from .from_events import results_from_events
        rebuilt = results_from_events(run_dir)
        rebuilt.save(run_dir / "results.json")
    data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    mode = screenshots or data.get("config", {}).get("reports", {}).get("screenshots", "all") or "all"
    def write_html() -> None:
        (run_dir / "report.html").write_text(render_html(data, run_dir, mode), encoding="utf-8")
    await asyncio.to_thread(write_html)                                    # (embedding the screenshots takes a moment: other runs in the process keep going meanwhile)
    artifacts = {"report_html": "report.html"}
    if pdf:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            wanted = browsers.BY_ID.get(browsers.identity_of(data)["id"])     # printing to PDF only works in a Chromium-based browser (WebKit cannot), whichever one the run used
            candidates = [wanted] if wanted is not None and wanted.engine == "chromium" else []
            candidates += [b for b in (browsers.CHROME, browsers.EDGE, browsers.CHROMIUM) if b not in candidates]
            browser, error = None, None
            for kind in candidates:
                try:
                    browser = await pw.chromium.launch(headless=True, **({"channel": kind.channel} if kind.channel else {}))
                    break
                except Exception as err:
                    error = error or err
            if browser is None:
                raise error or RuntimeError("no Chromium-based browser to print the PDF with")
            try:
                page = await browser.new_page()
                await page.goto((run_dir / "report.html").resolve().as_uri(), wait_until="load")
                await page.evaluate("expandAll(true)")
                await page.emulate_media(media="print")
                await page.pdf(path=str(run_dir / "report.pdf"), format="A4", landscape=True, print_background=True,
                               margin={"top": "12mm", "bottom": "12mm", "left": "8mm", "right": "8mm"})
            finally:
                await browser.close()
        artifacts["report_pdf"] = "report.pdf"
    return artifacts
