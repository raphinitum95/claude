# P06: Results tab

**Model:** Sonnet · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P06: Results tab`

Results as its own tab, built around what to fix first.

## Read first (only these)
- dev/designs/workbook-builder-canvas/run2.py (ResultsHome, ResultsTest, ResultsCompare) and run.py (failure detail cards)
- web/static/js/views/results.js; history.py
- engineering file section 5

## You own
- `web/static/js/views/results.js`
- `web/static/js/views/results/*.js (new)`
- `src/regrunner/web/results_api.py (new) + one line in web/app.py`
- `src/regrunner/history.py (read helpers only)`

## Build
- History list (batches and single runs; filters workbook, environment, status).
- Batch page: verdict, what changed since last time, failures grouped by cause (gate hard stop, not found, wrong value, skipped because a dependency failed, NOT_RUN), all tests with a last-10 trend strip and new/flaky/fixed tags, links to each underlying run. Re-run failed = new batch labelled "re-run of …".
- Test page: where it stopped on the block map, evidence, backup-locator card, this test's history. Compare: tests × last N runs grid with markers. "Fix in builder" links (deep link format from CONTRACT).

## Done when
- `test_web_ui.py -k "failed_run or failed_step"`, `test_history.py` and new results tests pass.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
2026-09-27 · Done: `web/results_api.py` (batch page with causes/trend/what-changed/re-run-failed, test page with a block map read fresh from
the workbook + backups + history, compare), `history.py` (`last_n_statuses`, `trend_verdict`), the Results tab UI (`views/results/*.js`:
history rail, batch, test, compare, wired into `main.js`'s `#/results...` routes and the header's "Results" tab), `test_web_results.py`
(13 tests, mostly no-browser). AGENTS.md updated. Ran `test_web_ui.py -k "failed_run or failed_step"`, `test_history.py`,
`test_web_results.py`, `test_web_build.py`, and the full `-m "not browser"` subset (477 passed) - all green. Next: nothing planned; open
questions for the reviewer are in the PR description (CSV export, real backup-locator probing needs P07, the "unmet dependency" vs.
"skipped because a dependency failed" cause distinction).
