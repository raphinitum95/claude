# P12: Concurrency scenarios

**Model:** Opus · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P12: Concurrency scenarios`

Run several tests (or one test twice with different rows) as one unit with sync points.

## Read first (only these)
- dev/designs/CONTEXT_workbook_builder_design.md Q35, Q36
- dev/designs/workbook-builder-canvas/api.py (scenario board), run.py (live scenario)
- engine/runner.py, pool.py, totp.py

## You own
- `src/regrunner/engine/scenario.py (new)`
- `web/static/js/views/build/scenario.js`
- `scenario parts of live.js / results views`

## Build
- `_rr_scenarios` sheet; barriers ("all wait here") and order markers ("A before B"); report per lane; a failed lane still releases the others.
- Two lanes logging in as the same user get separate TOTP windows (`totp.reserve_window`).
- Scenario board in Build; live lanes; per-lane results.

## Done when
- `test_totp_reuse.py`, `test_multi_run.py` + new scenario tests pass.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
