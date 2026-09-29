"""Results tab (dev/plan/phases/P06-results-tab.md): batch page (causes, trend, what changed, re-run), test page
(block map from the workbook + backup locators + this test's history), compare.  The heavy lifting in
``web/results_api.py`` takes plain paths and data, so most of this is exercised directly, without a server or a
browser; ``test_re_running_a_batchs_failures_starts_a_new_labelled_batch`` is the one real (browser) run."""
from __future__ import annotations

import json

import pytest

from regrunner.runmeta import read_meta, update_meta
from regrunner.web.results_api import (ResultsApiError, batch_metas, block_status, build_compare, build_test_page,
                                       cause_message, cause_of, grouped_by_batch, rerun_plan)
from tests.test_web_batches import fake_run
from tests.test_web_ui import open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)
from tests.workbook_factory import build_workbook


def _results_json(run_dir, tests):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(json.dumps({"environment": "UAT", "tests": tests}), encoding="utf-8")


def _step(row, status, **extra):
    return {"row": row, "seq": row, "status": status, **extra}


# -- cause classification (pure) ---------------------------------------------------------------------------------
def test_cause_of_recognises_a_page_gate_and_an_unset_variable_before_falling_back_to_history_kinds():
    gate = {"status": "FAILED", "steps": [_step(1, "PASSED"), _step(2, "FAILED", action="ASSERT_PAGE", error="URL was wrong")]}
    dependency = {"status": "FAILED", "steps": [_step(1, "FAILED", action="SET", error="variable POLICY_NO has no value")]}
    missing = {"status": "FAILED", "steps": [_step(1, "FAILED", action="CLICK", error="Element not found after 30 s")]}
    not_run = {"status": "NOT_RUN", "infra": "browser crashed", "steps": []}
    assert cause_of(gate) == "gate" and cause_of(dependency) == "unmet_dependency"
    assert cause_of(missing) == "element_missing" and cause_of(not_run) == "infra"
    assert "Step 2" in cause_message(gate, "gate") and "URL was wrong" in cause_message(gate, "gate")
    assert cause_message(not_run, "infra") == "browser crashed"


# -- block map coloring (pure) -----------------------------------------------------------------------------------
def test_block_status_is_fail_if_any_of_its_rows_failed_else_pass_pend_or_warn():
    block = {"firstRow": 5, "lastRow": 9}
    assert block_status(block, {5: "PASSED", 6: "FAILED"}, last_row=20) == "fail"
    assert block_status(block, {5: "PASSED", 6: "PASSED"}, last_row=20) == "pass"
    assert block_status(block, {}, last_row=2) == "pend"                 # never reached: entirely after the last executed row
    assert block_status(block, {}, last_row=20) == "warn"                # inside the run, but this test never touched these rows


def test_batch_metas_sorts_by_start_time_and_404s_an_unknown_batch():
    metas = [{"run_id": "b", "batch_id": "x", "started_at": "2026-01-01T00:00:05"}, {"run_id": "a", "batch_id": "x", "started_at": "2026-01-01T00:00:00"},
             {"run_id": "solo", "started_at": "2026-01-01T00:00:10"}]
    assert [m["run_id"] for m in batch_metas(metas, "x")] == ["a", "b"]
    assert list(grouped_by_batch(metas)) == ["x"]                        # a run with no batch_id is not grouped
    with pytest.raises(ResultsApiError) as exc:
        batch_metas(metas, "no-such-batch")
    assert exc.value.kind == "not_found"


# -- the block map, read fresh from the workbook (pure: no server, no browser) -------------------------------------
def test_build_test_page_colors_the_real_blocks_from_the_workbook_by_the_runs_own_step_rows(tmp_path):
    wb_dir = tmp_path / "workbooks"
    wb_dir.mkdir()
    rows = build_workbook(wb_dir / "mock.xlsx", flows=["FlowA"], enabled=["FlowA"])["FlowA"]   # real "Open" / "Quote" / "Result" blocks
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "r1"
    update_meta(run_dir, run_id="r1", workbook=str(wb_dir / "mock.xlsx"), environment="UAT", status="FAILED")
    steps = [_step(rows["open"], "PASSED"), _step(rows["bypass"], "PASSED"), _step(rows["exist"], "PASSED"),
             _step(rows["banner_out"], "FAILED", error="Comparison Failed: expected X")]
    _results_json(run_dir, [{"id": "FlowA", "sheet": "FlowA", "status": "FAILED", "steps": steps}])

    page = build_test_page(run_dir, wb_dir, runs_dir, "FlowA")
    by_title = {b["title"]: b["status"] for b in page["blocks"]}
    assert by_title["Open"] == "pass" and by_title["Quote"] == "fail" and by_title["Result"] == "pend"
    assert page["verdict"] in ("new", "no_history")                # only one run so far
    assert page["history"] and page["history"][-1]["status"] == "FAILED"


def test_build_test_page_degrades_gracefully_when_the_workbook_is_gone(tmp_path):
    run_dir = tmp_path / "runs" / "r1"
    update_meta(run_dir, run_id="r1", workbook="deleted.xlsx", environment="UAT", status="PASSED")
    _results_json(run_dir, [{"id": "FlowA", "sheet": "FlowA", "steps": [_step(2, "PASSED")]}])
    page = build_test_page(run_dir, tmp_path / "workbooks", tmp_path / "runs", "FlowA")
    assert page["blocks"] == [] and page["backups"] == {}


def test_build_test_page_404s_a_run_or_test_that_does_not_exist(tmp_path):
    with pytest.raises(ResultsApiError) as missing_run:
        build_test_page(tmp_path / "runs" / "nope", tmp_path / "workbooks", tmp_path / "runs", "FlowA")
    assert missing_run.value.kind == "not_found"
    run_dir = tmp_path / "runs" / "r1"
    _results_json(run_dir, [{"id": "FlowA", "sheet": "FlowA", "steps": []}])
    update_meta(run_dir, run_id="r1", workbook="mock.xlsx", environment="UAT", status="PASSED")
    with pytest.raises(ResultsApiError) as missing_test:
        build_test_page(run_dir, tmp_path / "workbooks", tmp_path / "runs", "NoSuchTest")
    assert missing_test.value.kind == "not_found"


# -- re-run planning (pure) ------------------------------------------------------------------------------------
def test_rerun_plan_picks_only_workbooks_with_a_failure_and_carries_over_the_original_settings(tmp_path):
    runs_dir = tmp_path / "runs"
    (runs_dir / "b-mock").mkdir(parents=True)
    (runs_dir / "b-mock" / "results.json").write_text(json.dumps({"environment": "UAT", "workers": 4,
        "config": {"screenshots": {"mode": "on_failure"}, "behaviour": {"retries": 1}}, "browser": {"id": "chromium", "headless": True},
        "tests": [{"id": "FlowA", "status": "PASSED"}, {"id": "FlowB", "status": "FAILED"}]}), encoding="utf-8")
    _results_json(runs_dir / "b-bad", [{"id": "FlowX", "status": "PASSED"}])
    metas = [{"run_id": "b-mock", "workbook": "mock.xlsx"}, {"run_id": "b-bad", "workbook": "bad.xlsx"}]
    plan = rerun_plan(metas, runs_dir)
    assert plan["picks"] == [{"workbook": "mock.xlsx", "tests": ["FlowB"]}] and plan["skipped"] == ["bad.xlsx"]
    assert plan["environment"] == "UAT" and plan["workers"] == 4 and plan["screenshots"] == "on_failure" and plan["retries"] == 1
    assert plan["browser"] == "chromium" and plan["headed"] is False


def test_rerun_plan_refuses_a_running_batch_prod_or_nothing_failed(tmp_path):
    runs_dir = tmp_path / "runs"
    with pytest.raises(ResultsApiError) as busy:
        rerun_plan([{"run_id": "r", "workbook": "mock.xlsx", "active": True}], runs_dir)
    assert busy.value.kind == "busy"
    with pytest.raises(ResultsApiError) as nothing:
        rerun_plan([{"run_id": "r", "workbook": "mock.xlsx"}], runs_dir)                # no results.json at all: nothing to re-run
    assert nothing.value.kind == "nothing_failed"
    _results_json(runs_dir / "p", [{"id": "FlowA", "status": "FAILED"}])
    (runs_dir / "p" / "results.json").write_text(json.dumps({"environment": "PROD", "tests": [{"id": "FlowA", "status": "FAILED"}]}), encoding="utf-8")
    with pytest.raises(ResultsApiError) as prod:
        rerun_plan([{"run_id": "p", "workbook": "mock.xlsx"}], runs_dir)
    assert prod.value.kind == "prod_confirm"


# -- compare (pure) ---------------------------------------------------------------------------------------------
def test_build_compare_makes_a_tests_by_runs_grid_with_a_verdict_per_row(tmp_path):
    runs_dir = tmp_path / "runs"
    (runs_dir / "r1").mkdir(parents=True)
    (runs_dir / "r1" / "results.json").write_text(json.dumps({"run_id": "r1", "started_at": "2026-01-01T00:00:00", "workbook": "mock.xlsx",
        "environment": "UAT", "tests": [{"id": "FlowA", "status": "PASSED"}]}), encoding="utf-8")
    (runs_dir / "r2").mkdir()
    (runs_dir / "r2" / "results.json").write_text(json.dumps({"run_id": "r2", "started_at": "2026-01-02T00:00:00", "workbook": "mock.xlsx",
        "environment": "UAT", "tests": [{"id": "FlowA", "status": "FAILED"}]}), encoding="utf-8")
    grid = build_compare(runs_dir, ["mock.xlsx"], 8)
    row = next(r for r in grid["rows"] if r["test"] == "FlowA")
    assert row["cells"] == ["PASSED", "FAILED"] and row["verdict"] == "new"
    assert len(grid["columns"]["mock.xlsx"]) == 2


# -- through the real HTTP API (fast: fabricated finished runs, no browser) -----------------------------------------
def test_the_batch_page_groups_failures_by_cause_and_lists_every_test_with_a_verdict(web):
    fake_run(web, "g1-mock", workbook="mock.xlsx", status="PASSED", started_at="2026-02-01T00:00:00", batch_id="g1")
    fake_run(web, "g1-bad", workbook="bad.xlsx", status="FAILED", started_at="2026-02-01T00:00:05", batch_id="g1")
    (web.run_dir("g1-mock") / "results.json").write_text(json.dumps({"environment": "UAT",
        "tests": [{"id": "FlowA", "status": "PASSED", "steps": []}]}), encoding="utf-8")
    (web.run_dir("g1-bad") / "results.json").write_text(json.dumps({"environment": "UAT",
        "tests": [{"id": "FlowX", "status": "FAILED", "steps": [_step(2, "FAILED", action="CLICK", error="Element not found")]}]}), encoding="utf-8")
    with web.client() as c:
        page = c.get("/api/results/batches/g1").json()
    assert page["batch"]["id"] == "g1" and {t["id"] for t in page["tests"]} == {"FlowA", "FlowX"}
    (group,) = page["groups"]
    assert group["kind"] == "element_missing" and group["items"][0]["test"] == "FlowX"
    with web.client() as c:
        assert c.get("/api/results/batches/no-such-batch").status_code == 404


def test_compare_endpoint_defaults_to_every_workbook_that_has_run(web):
    fake_run(web, "cmp1", workbook="mock.xlsx", status="PASSED", started_at="2026-02-02T00:00:00")
    (web.run_dir("cmp1") / "results.json").write_text(json.dumps({"environment": "UAT", "tests": [{"id": "FlowA", "status": "PASSED"}]}), encoding="utf-8")
    with web.client() as c:
        grid = c.get("/api/results/compare").json()
    assert "mock.xlsx" in grid["columns"]


@pytest.mark.browser
def test_re_running_a_batchs_failures_starts_a_new_labelled_batch(web):
    """``bad.xlsx``'s extra step (``failing_step``, web_fixtures.py) fails both its flows deterministically, so a
    re-run's own failures can themselves be re-run; ``mock.xlsx``'s flows pass, so it is skipped both times."""
    with web.client() as c:
        started = c.post("/api/runs", json={"workbooks": [{"workbook": "mock.xlsx", "tests": ["FlowA"]},
                                                          {"workbook": "bad.xlsx", "tests": ["FlowX", "FlowY"]}]})
        assert started.status_code == 200, started.text
        batch_id = started.json()["batch_id"]
        for run_id in started.json()["run_ids"]:
            web.wait_finished(run_id, 240)

        rerun = c.post(f"/api/results/batches/{batch_id}/rerun-failed")
        assert rerun.status_code == 200, rerun.text
        body = rerun.json()
        assert body["skipped_no_failures"] == ["mock.xlsx"]                        # FlowA passed: nothing of its to re-run
        new_batch = body["batch_id"]
        assert new_batch and new_batch != batch_id
        for run_id in body["run_ids"]:
            web.wait_finished(run_id, 240)
            meta = read_meta(web.run_dir(run_id))
            assert meta["test_ids"] == ["FlowX", "FlowY"] and meta["rerun_of"] == batch_id
            assert meta["batch_label"] == f"re-run of batch {batch_id}"

        solo = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowA"], "batch_id": "solo-pass"})
        assert solo.status_code == 200, solo.text
        web.wait_finished(solo.json()["run_id"], 240)
        nothing_left = c.post("/api/results/batches/solo-pass/rerun-failed")
        assert nothing_left.status_code == 409 and nothing_left.json()["kind"] == "nothing_failed"


@pytest.mark.browser
async def test_the_results_tab_can_be_browsed_from_history_to_batch_to_test_to_compare(web):
    """A fabricated finished batch (no real run needed): the Results tab still has to read it, show its causes,
    open one test's real block map, and reach Compare - the whole click path, in a real browser."""
    fake_run(web, "ui1-mock", workbook="mock.xlsx", status="FAILED", started_at="2026-03-01T00:00:00", batch_id="ui1", batch_label="UI batch")
    (web.run_dir("ui1-mock") / "results.json").write_text(json.dumps({"environment": "UAT", "workbook": "mock.xlsx",
        "tests": [{"id": "FlowA", "sheet": "FlowA", "status": "FAILED", "duration_s": 1.2,
                  "steps": [{"row": 3, "seq": 1, "status": "PASSED", "name": "Open Browser", "action": "OPEN"},
                            {"row": 4, "seq": 2, "status": "FAILED", "name": "Bypass cookie", "action": "OUTPUT",
                             "error": "Comparison Failed: expected bypass:TEST-UAT-TOKEN"}]}]}), encoding="utf-8")
    async with open_ui(web, path="/#/results") as page:
        await page.wait_for_selector("text=Pick a batch or run")
        # Other tests sharing this module-scoped ``web`` fixture may have made more recent batches/runs, so the
        # landing page's "most recent" shortcut is not reliable here: find this batch by its own link instead.
        await page.locator('a[href="#/results/batch/ui1"]').first.click()
        await page.wait_for_selector("text=Failures, grouped by cause")
        await page.get_by_role("link", name="Open").first.click()
        await page.wait_for_selector("text=Where it stopped")
        assert await page.locator("text=Bypass cookie").count() >= 1               # the failed step's evidence card rendered
        await page.get_by_role("link", name="Compare runs", exact=False).first.click()
        await page.wait_for_selector("text=Last 8 runs")
        assert not page.errors, page.errors


@pytest.mark.browser
async def test_fix_in_builder_opens_the_build_tab_on_the_failed_step_with_its_last_run_evidence(web):
    """``bad.xlsx``'s FlowX fails deterministically on its extra ``failing_step`` (web_fixtures.py): "Fix in builder"
    on the Results test page should land the Build tab on exactly that step, with the last run's error, screenshot
    and a passive badge on the step's card - not just the test."""
    with web.client() as c:
        started = c.post("/api/runs", json={"workbook": "bad.xlsx", "tests": ["FlowX"]})
        assert started.status_code == 200, started.text
        run_id = started.json()["run_id"]
    detail = web.wait_finished(run_id, 240)
    assert detail["meta"]["status"] == "FAILED"

    async with open_ui(web, path=f"/#/results/test/{run_id}/FlowX") as page:
        await page.wait_for_selector("text=Where it stopped")
        await page.get_by_role("button", name="Fix in builder", exact=True).click()
        await page.wait_for_function("location.hash.startsWith('#/build/bad.xlsx/test/FlowX')")
        await page.wait_for_selector("img[alt='Screenshot from the failed run']")           # the inspector's evidence card
        assert await page.locator("text=failed last run").count() >= 1                      # the passive badge on the step's card
        assert not page.errors, page.errors


@pytest.mark.browser
async def test_a_run_opened_from_the_results_history_stays_in_the_results_tab(web):
    fake_run(web, "solo-ui-mock", workbook="mock.xlsx", status="FAILED", started_at="2026-03-02T00:00:00")
    (web.run_dir("solo-ui-mock") / "results.json").write_text(json.dumps({"environment": "UAT", "workbook": "mock.xlsx",
        "tests": [{"id": "FlowA", "sheet": "FlowA", "status": "FAILED", "duration_s": 1.0,
                  "steps": [{"row": 4, "seq": 1, "status": "FAILED", "name": "Bypass cookie", "action": "OUTPUT", "error": "Comparison Failed"}]}]}),
        encoding="utf-8")
    async with open_ui(web, path="/#/results") as page:
        await page.wait_for_selector("text=Pick a batch or run")
        await page.locator('a[href="#/results/run/solo-ui-mock"]').first.click()
        await page.wait_for_function("location.hash === '#/results/run/solo-ui-mock'")
        await page.wait_for_selector("text=Bypass cookie")                                         # the run's own page...
        assert await page.locator(".tab-btn.on").inner_text() == "Results"                          # ...inside the Results tab
        assert not page.errors, page.errors


@pytest.mark.browser
async def test_the_batch_and_test_pages_open_each_runs_full_results_and_its_html_report(web):
    """Everything the Run tab's run page offers is reachable from the Results tab: each run of a batch links to its full results page and
    its HTML report (only when the report exists), and a test page links to the report at that test."""
    for run_id, wb, when in (("rp1-mock", "mock.xlsx", "2026-05-01T00:00:00"), ("rp1-bad", "bad.xlsx", "2026-05-01T00:00:01")):
        fake_run(web, run_id, workbook=wb, status="PASSED", started_at=when, batch_id="rp1")
        (web.run_dir(run_id) / "results.json").write_text(json.dumps({"environment": "UAT", "workbook": wb, "status": "PASSED", "tests": [
            {"id": "FlowA", "sheet": "FlowA", "status": "PASSED", "duration_s": 1.0, "steps": [{"row": 3, "seq": 1, "status": "PASSED", "name": "Open", "action": "OPEN"}]}]}),
            encoding="utf-8")
    (web.run_dir("rp1-mock") / "report.html").write_text("<html><body>the report</body></html>", encoding="utf-8")     # only this run has a report
    async with open_ui(web, path="/#/results/batch/rp1") as page:
        await page.wait_for_selector("text=Runs in this batch")
        row_mock, row_bad = page.locator('[data-key="run-rp1-mock"]'), page.locator('[data-key="run-rp1-bad"]')
        assert await row_mock.get_by_role("link", name="HTML report").get_attribute("href") == "/runs/rp1-mock/files/report.html"
        assert await row_bad.get_by_role("link", name="HTML report").count() == 0                                        # no report file, no dead link
        assert await row_mock.get_by_role("link", name="Results").get_attribute("href") == "#/results/run/rp1-mock"
        async with page.context.expect_page() as popup:
            await row_mock.get_by_role("link", name="HTML report").click()
        assert "the report" in await (await popup.value).inner_text("body")
        await row_mock.get_by_role("link", name="Results").click()
        await page.wait_for_selector("text=Open HTML report")                                                             # the same run page the Run tab shows
        assert await page.locator(".tab-btn.on").inner_text() == "Results"

        await page.goto(web.base + "/#/results/test/rp1-mock/FlowA")
        link = page.get_by_role("link", name="HTML report")
        await link.wait_for()
        assert (await link.get_attribute("href")).endswith("/runs/rp1-mock/files/report.html#t-FlowA")
        assert not page.errors, page.errors


@pytest.mark.browser
async def test_every_status_badge_fits_inside_its_own_box_in_the_batch_tests_table(web):
    """The badge sat in a fixed-width grid column, so a long label (CANCELLED, INTERRUPTED) spilled out of its pill."""
    statuses = ("CANCELLED", "INTERRUPTED", "INCOMPLETE", "NOT_RUN", "PASSED", "FAILED")
    fake_run(web, "pill-run", workbook="mock.xlsx", status="FAILED", started_at="2026-05-02T00:00:00", batch_id="pill1")
    (web.run_dir("pill-run") / "results.json").write_text(json.dumps({"environment": "UAT", "workbook": "mock.xlsx", "tests": [
        {"id": f"T{i}", "sheet": f"T{i}", "status": s, "duration_s": 1.0, "steps": []} for i, s in enumerate(statuses)]}), encoding="utf-8")
    async with open_ui(web, path="/#/results/batch/pill1") as page:
        await page.wait_for_selector("text=All tests")
        spilled = await page.evaluate("Array.from(document.querySelectorAll('.pill')).filter(p => p.scrollWidth > p.clientWidth + 1).map(p => p.textContent)")
        assert spilled == [] and await page.locator(".pill", has_text="Cancelled").count() >= 1
