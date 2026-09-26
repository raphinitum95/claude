# Workbook Builder: build plan (the "dev lead" document)

Every build session reads **this file** and **its own phase file** (`dev/plan/phases/Pxx-*.md`), nothing else up front.
The product decisions are in `dev/designs/CONTEXT_workbook_builder_design.md` (Q1–Q53) and
`dev/claude/CONTEXT_workbook_builder_engineering.md`; read only the parts your phase file points to.
Project rules are in `dev/claude/AGENTS.md` and always apply (never run real sites, never retry a step, never echo secrets, Python 3.9...).

## Decisions that are fixed

- **Only the new runner matters.** New columns, keywords and hidden sheets may be added freely; the legacy Windows runner does not need to read them.
  Existing workbooks must still load and run unchanged.
- **`qa-regression` is the main branch.** Every PR goes into `qa-regression`.
- **A batch is a UI label.** Each workbook is still its own run (engineering file, section 5, "batches").
- The interface between pieces is `dev/plan/CONTRACT.md`. Change it only in the phase that owns it, or say so in your PR.

## How every phase session works

1. **Setup is automatic** (`.claude/hooks/session-start.sh` builds `.venv`). Use `.venv/bin/pytest`.
2. Read this file, your phase file, then only the code your phase file lists. Don't explore the rest of the repo.
3. Work on the branch the session gives you. Stay inside the files your phase **owns**; if you must touch another phase's file, keep it to the
   smallest change and name it in the PR.
4. New server routes go in their own module (e.g. `web/build_api.py` with `register_build_routes(app, ...)`), plus **one** line in
   `create_app` in `web/app.py`. That keeps parallel phases from colliding in `app.py`.
5. Test only what you touched (AGENTS.md section 5), on the mock site. Add tests named as sentences.
6. **Checkpoint:** after each finished part, commit and push, and add one line under "Progress" in your phase file
   (what's done, what's next). If the chat stops, the next session resumes from there.
7. When done: update `dev/claude/AGENTS.md` (new modules/tests/rules, section 3-4 and 9), open **one PR into `qa-regression`** titled
   `Pxx: <name>`, with the tests you ran in the body. Then stop. Don't merge it yourself.
8. Keep replies to the user short (AGENTS.md section 0). Ask only when a decision is really theirs.

## Review session (the dev lead's check, run after each phase)

1. Find the open PR for the phase. Read the phase file's "Done when" list and `CONTRACT.md`.
2. Read the **diff only**. Check: it stays in its owned files, matches the contract, follows AGENTS.md hard rules, no secrets echoed,
   Python 3.9-safe, tests named for behaviour.
3. Run the phase's listed tests plus `.venv/bin/pytest -q -m "not browser"`.
4. If `qa-regression` moved, merge it into the PR branch and resolve conflicts (no rebase, no force-push).
5. Small problems: fix them and push. Anything big or a real design question: write it in the PR and tell the user in two lines. Don't merge.
6. All green: **merge the PR into `qa-regression`**, then **delete the PR's branch on GitHub** (`git push origin --delete <branch>`;
   never delete `qa-regression`). Tick the phase in the status table below (on `qa-regression`), and tell the user in two lines what's next.

## Order (waves). Phases in the same wave can run at the same time.

| Wave | Phase | What | Model | Owns (main files) |
|---|---|---|---|---|
| 1 | P01 | Excel writer + round-trip fidelity | Opus | `workbook/writer.py` (new), `workbook/sheet.py` (write side), `tests/test_workbook_roundtrip.py` |
| 2 | P02 | Builder model, contract, problems, build API | Opus | `workbook/builder.py` (new), `lint.py`, `web/build_api.py` (new), `dev/plan/CONTRACT.md` |
| 3 | P03 | Engine I: variables, IF, loops, CALL_TEST, environments, secrets | Opus | `engine/actions.py`, `engine/test_runner.py`, `engine/order.py`, `workbook/model.py`, `config.py` |
| 3 | P04 | Build tab UI: shell tabs, workbook map, variable map, editor, grid, drawer, problems, save/history | Sonnet | `web/static/js/views/build/*` (new), `views/shell.js` (tabs), `app.css` (build section) |
| 3 | P05 | Run tab: one list, one plan, batch label, live batch | Sonnet | `views/newrun.js`, `views/live.js`, `runstate.js`, `runmeta.py`, `web/run_batch.py` (new) |
| 4 | P06 | Results tab: history, batch page, causes, test page, compare | Sonnet | `views/results.js`, `views/results/*` (new), `web/results_api.py` (new), `history.py` (read helpers) |
| 4 | P07 | Engine II: page gates, wait until, popups, side effects, backup locators, checks, widgets | Opus | `engine/actions.py`, `engine/session.py`, `engine/outcome.py`, `selectors/*` |
| 5 | P08 | Build session I: controlled browser, pick, locators, run up to here | Opus | `build/session.py`, `build/locators.py`, `build/overlay.js` (new package `src/regrunner/build/`) |
| 6 | P09 | Build session II: recorder, check/save this, typed → variable, widgets, fingerprints | Opus | `build/recorder.py`, `build/overlay.js`, `views/build/record*.js` |
| 6 | P10 | API/XML building: form, send now, response tree, imports | Opus | `build/api_builder.py`, `views/build/api*.js`, `engine/api_runner.py` (XML) |
| 6 | P11 | Templates, copy/paste, duplicate, find/replace, rename, computed values, file watch | Sonnet | `workbook/templates.py`, `workbook/refactor.py`, `workbook/formula.py`, `views/build/dialogs*.js` |
| 7 | P12 | Concurrency scenarios: sheet, engine barriers, board, live lanes, results | Opus | `engine/scenario.py`, `views/build/scenario.js`, live/results lane parts |
| 8 | P13 | Fix-in-builder loop, last-run overlay, polish, README, full suite | Sonnet | small edits across; `README.md` |

Paths are under `src/regrunner/` unless they start with `dev/` or `tests/`.

## Status (the review session updates this)

| Phase | State | PR | Notes |
|---|---|---|---|
| P01 | not started | | |
| P02 | not started | | |
| P03 | not started | | |
| P04 | not started | | |
| P05 | not started | | |
| P06 | not started | | |
| P07 | not started | | |
| P08 | not started | | |
| P09 | not started | | |
| P10 | not started | | |
| P11 | not started | | |
| P12 | not started | | |
| P13 | not started | | |
