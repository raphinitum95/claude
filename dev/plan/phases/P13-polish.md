# P13: Fix-in-builder loop, last-run overlay, docs, full suite

**Model:** Sonnet · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P13: Fix-in-builder loop, last-run overlay, docs, full suite`

Close the loop and finish.

## Read first (only these)
- dev/plan/PLAN.md status notes (open items left by earlier phases)
- README.md headings (AGENTS.md section 8)

## You own
- small edits across the Build/Results views
- `README.md`
- `dev/claude/AGENTS.md`

## Build
- Results "Fix in builder" opens the step with screenshot, error, replay and re-pick; cards show last-run dots and a passive "failed on last run" badge.
- README sections for Build, Run and Results; AGENTS.md current state.
- Run the **full** suite once (the user agreed to this phase doing it).

## Done when
- Full suite green, or every failure listed in the PR with the reason.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
- 2026-09-28 · Fix-in-builder now jumps to the exact failed step (`jumpToStep`, plus an `openBuild` fix so a staged
  `pendingSel` survives a cross-workbook navigation); step cards show a passive "failed last run" badge; the inspector
  shows a "failed on the last run" card with error, screenshot (new `lastResult.screenshot`/`screenshotFull` from
  `builder._last_results`) and a link to the full Results test page. Tests: `test_builder_model.py` (extended),
  `test_web_results.py` (new browser test `test_fix_in_builder_opens_the_build_tab_on_the_failed_step_with_its_last_run_evidence`).
  Next: README Build/Run/Results sections, AGENTS.md, then the full suite.
- 2026-09-28 · README: added `### Run tab` / `### Build tab` / `### Results tab` under `## Web UI` (the Workbook
  Builder's UI had never been documented there, only in `dev/plan/`), extended the `/api/build/*` and `/api/results/*`
  endpoint list, updated AGENTS.md section 8's heading summary. AGENTS.md section 9 got a P13 paragraph. Next: full suite.
- 2026-09-28 · Full suite: `.venv/bin/pytest -q` → 983 passed, 1 failed, 5 skipped (2899.88s). The one failure
  (`test_web_multi_run.py::test_a_new_run_joins_the_workers_that_are_going_and_the_same_workbook_cannot_run_twice`, a
  missed `pool_changed` event under load) is unrelated to anything this phase touched and passed alone on a solo
  re-run - a timing flake, documented in AGENTS.md section 9's gotchas alongside the other known ones. Phase done.
