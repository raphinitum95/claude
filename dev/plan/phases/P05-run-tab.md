# P05: Run tab: one list, one plan, batch label, live batch

**Model:** Sonnet · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P05: Run tab: one list, one plan, batch label, live batch`

Replace the per-workbook Tests + Run order cards with one grouped list and one plan; show batches as one live view.

## Read first (only these)
- dev/designs/workbook-builder-canvas/run2.py (RunSetup, RunLiveBatch markup and the plan/timeline logic)
- engineering file section 5 "Run and Results tabs, and batches"
- web/static/js/views/newrun.js, live.js, runstate.js; runmeta.py

## You own
- `web/static/js/views/newrun.js`
- `web/static/js/views/live.js`
- `web/static/js/runstate.js`
- `src/regrunner/runmeta.py`
- `src/regrunner/web/run_batch.py (new) + one line in web/app.py`

## Build
- "What to run": tests grouped by workbook (fold/unfold, tri-state select, tag filter across workbooks), "after X" chip on dependent tests.
- One Run plan: Order view (chains, drag to reorder/chain; reuses `order.py` chains) and Timeline view (chains on workers, estimated from last-run durations).
- Batch id + label written to each run's `run.json`; runs stay individual. A run started while a batch runs is separate; "Add tests to this batch" creates new runs with the same batch id.
- Live batch view: per-workbook progress rows (filter), worker cards coloured by workbook, "Failed so far".

## Done when
- `test_web_ui.py`, `test_web_multi_ui.py`, `test_web_run_order.py`, `test_web_multi_run.py` pass (update them where the layout changed on purpose).
- **Restart UI** noted.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
