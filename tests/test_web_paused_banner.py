"""After an HTTP 403 / 429 the runner waits and then starts the test again: the run screen must say so (it used to look hung)."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from regrunner.runmeta import update_meta
from tests.test_web_ui import js_until, open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


def fabricate_paused_run(web, run_id: str, seconds: float) -> None:
    run_dir = web.root / "runs" / run_id
    run_dir.mkdir(parents=True)
    now = datetime.now().astimezone().isoformat(timespec="milliseconds")
    base = {"ts": now, "run_id": run_id}
    events = [
        {**base, "type": "run_started", "workbook": "wb.xlsx", "environment": "UAT", "workers": 1, "headless": True, "warnings": [], "params": {},
         "tests": [{"id": "Qantas#1", "title": "Qantas", "description": "", "scenario": "", "total_steps": 236}]},
        {**base, "type": "test_started", "test": "Qantas#1", "title": "Qantas", "total_steps": 236, "worker": 1, "attempt": 1},
        {**base, "type": "step_failed", "test": "Qantas#1", "step": 1, "total_steps": 236, "row": 3, "name": "Launch Site", "action": "OPEN",
         "status": "FAILED", "duration_ms": 900, "error": "qantas.uat.travelguard.com answered HTTP 403 from CloudFront"},
        {**base, "type": "run_paused", "test": "Qantas#1", "seconds": seconds, "attempt": 1, "of": 1,
         "reason": "qantas.uat.travelguard.com answered HTTP 403 from CloudFront (the CDN / firewall in front of the site)"},
        {**base, "type": "test_started", "test": "Qantas#1", "title": "Qantas", "total_steps": 236, "worker": 1, "attempt": 2},
    ]
    (run_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    update_meta(run_dir, run_id=run_id, status="RUNNING", environment="UAT", started_at=now, workbook="wb.xlsx", tests=1, test_ids=["Qantas#1"])


async def test_a_run_waiting_after_a_block_says_so_and_counts_down(web):
    fabricate_paused_run(web, "20260924-999999-UAT", seconds=90)
    async with open_ui(web, path="/#/run/20260924-999999-UAT") as page:
        await js_until(page, "document.body.innerText.includes('Paused: the site blocked this machine')")
        text = await page.locator("body").inner_text()
        assert "Nothing is stuck" in text and "retry 1 of 1" in text and "CloudFront" in text
        first = await page.evaluate("(document.body.innerText.match(/Waiting (\\d+) s/) || [])[1]")
        assert first and 60 <= int(first) <= 90
        await js_until(page, "(function () { const m = document.body.innerText.match(/Waiting (\\d+) s/); return m && Number(m[1]) < " + first + "; })()")   # it counts down
        assert page.errors == []


async def test_the_banner_is_gone_once_the_wait_is_over(web):
    fabricate_paused_run(web, "20260924-999998-UAT", seconds=1)
    async with open_ui(web, path="/#/run/20260924-999998-UAT") as page:
        await js_until(page, "document.body.innerText.includes('Qantas')")
        await page.wait_for_timeout(2500)
        assert "Paused: the site blocked this machine" not in await page.locator("body").inner_text()
