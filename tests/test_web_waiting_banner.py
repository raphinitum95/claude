"""Whenever a worker waits on purpose (the next login code, a slow page, a re-run after a browser crash), the run screen shows a yellow warning:
which test / worker, why in plain words, and a countdown when the length is known.  It goes away when the wait ends, and survives a reload."""
from __future__ import annotations

import json
import re
from datetime import datetime

import pytest

from regrunner.runmeta import update_meta
from tests.test_web_ui import js_until, open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser

LOGIN = "Waiting 25 s for the next login code: another test has just used this account's current code, and the site accepts each code once."
SLOW = "Waiting for the element: the site has not answered yet (GET /bin/quote, 42 s so far). The step waits for it instead of failing."


def fabricate(web, run_id: str, *, seconds: float = 25) -> tuple:
    run_dir = web.root / "runs" / run_id
    run_dir.mkdir(parents=True)
    now = datetime.now().astimezone().isoformat(timespec="milliseconds")
    base = {"ts": now, "run_id": run_id}
    tests = [{"id": "Purchase#1", "title": "Purchase", "description": "", "scenario": "", "total_steps": 40},
             {"id": "Purchase#2", "title": "Purchase", "description": "", "scenario": "", "total_steps": 40}]
    events = [
        {**base, "type": "run_started", "workbook": "wb.xlsx", "environment": "UAT", "workers": 2, "headless": True, "warnings": [], "params": {}, "tests": tests},
        {**base, "type": "test_started", "test": "Purchase#1", "title": "Purchase", "total_steps": 40, "worker": 1, "attempt": 1},
        {**base, "type": "test_started", "test": "Purchase#2", "title": "Purchase", "total_steps": 40, "worker": 2, "attempt": 1},
        {**base, "type": "worker_waiting", "test": "Purchase#2", "worker": 2, "step": 9, "wait": "w1", "code": "login_code", "message": LOGIN, "seconds": seconds},
        {**base, "type": "worker_waiting", "test": "Purchase#1", "worker": 1, "step": 14, "wait": "w2", "code": "slow_page", "message": SLOW},
    ]
    path = run_dir / "events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    update_meta(run_dir, run_id=run_id, status="RUNNING", environment="UAT", started_at=now, workbook="wb.xlsx", tests=2, test_ids=["Purchase#1", "Purchase#2"])
    return path, base


def append(path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({**event, "ts": datetime.now().astimezone().isoformat(timespec="milliseconds")}) + "\n")


def rgb(text: str) -> tuple:
    return tuple(int(float(x)) for x in re.findall(r"[\d.]+", text)[:3])


async def test_waiting_workers_are_listed_in_yellow_with_the_reason_and_a_countdown(web):
    path, base = fabricate(web, "20260926-999990-UAT")
    async with open_ui(web, path="/#/run/20260926-999990-UAT") as page:
        await js_until(page, "document.body.innerText.includes('2 workers are waiting on purpose')")
        text = await page.locator("body").inner_text()
        assert "W2 · Purchase#2" in text and "another test has just used this account's current code" in text
        assert "W1 · Purchase#1" in text and "the site has not answered yet" in text and "Nothing is stuck" in text
        assert "Workers now:" in text and "1 waiting for a login code" in text and "1 waiting for a slow page" in text      # the run level, in one line
        first = await page.evaluate("(document.querySelector('#waits').innerText.match(/(\\d+) s left/) || [])[1]")
        assert first and 15 <= int(first) <= 25
        await js_until(page, "(function () { const m = document.querySelector('#waits').innerText.match(/(\\d+) s left/); return m && Number(m[1]) < " + first + "; })()")
        lanes = await page.locator("article.card .waitline").count()
        assert lanes == 2                                                    # each worker's own card says it too

        await page.reload()                                                  # a reload mid-wait rebuilds it from the event stream
        await js_until(page, "document.body.innerText.includes('2 workers are waiting on purpose')")

        append(path, {**base, "type": "worker_resumed", "test": "Purchase#2", "worker": 2, "step": 9, "wait": "w1", "code": "login_code", "waited_s": 25})
        await js_until(page, "document.body.innerText.includes('A worker is waiting on purpose')")
        assert "another test has just used" not in await page.locator("#waits").inner_text()
        append(path, {**base, "type": "worker_resumed", "test": "Purchase#1", "worker": 1, "step": 14, "wait": "w2", "code": "slow_page", "waited_s": 50})
        await js_until(page, "!document.querySelector('#waits')")
        assert page.errors == []


@pytest.mark.parametrize("theme", ["light", "dark"])
async def test_the_waiting_banner_reads_yellow_and_legible_in_both_themes(web, theme):
    fabricate(web, f"20260926-99998{0 if theme == 'light' else 1}-UAT")
    async with open_ui(web, path=f"/#/run/20260926-99998{0 if theme == 'light' else 1}-UAT") as page:
        await page.evaluate(f"document.documentElement.dataset.theme = '{theme}'; document.querySelectorAll('[data-theme]').forEach((e) => e.dataset.theme = '{theme}')")
        await js_until(page, "!!document.querySelector('.bn-wait')")
        colours = await page.evaluate("""(() => {
          const b = document.querySelector('.bn-wait');
          const paint = (el) => { for (let n = el; n; n = n.parentElement) { const c = getComputedStyle(n).backgroundColor; if (!/rgba\\(0, 0, 0, 0\\)|transparent/.test(c)) return c; } return 'rgb(255,255,255)'; };
          return {bg: getComputedStyle(b).backgroundColor, under: paint(b.parentElement), text: getComputedStyle(b).color, border: getComputedStyle(b).borderTopColor};
        })()""")
        bg = rgb(colours["bg"])
        alpha = float(re.findall(r"[\d.]+", colours["bg"])[3]) if colours["bg"].startswith("rgba") else 1.0
        under = rgb(colours["under"])
        shown = tuple(round(alpha * c + (1 - alpha) * u) for c, u in zip(bg, under))       # what the eye sees: the banner over the page
        r, g, b = shown
        border = rgb(colours["border"])
        assert border[0] > border[2] + 60 and border[1] > border[2] + 20, colours          # the edge is amber / yellow
        if theme == "light":
            assert r > 240 and g > 220 and b < 205, (shown, colours)                          # a clearly yellow fill
        else:
            assert r > g > b and r - b > 12, (shown, colours)                                  # a warm amber tint on the dark page

        def lum(c):
            def ch(v):
                v /= 255
                return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
            return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])
        text = rgb(colours["text"])
        hi, lo = max(lum(text), lum(shown)), min(lum(text), lum(shown))
        assert (hi + 0.05) / (lo + 0.05) >= 7, (colours, shown)                               # AAA contrast for the words
