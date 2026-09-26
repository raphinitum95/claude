# P08: Build session I: controlled browser, pick, locators, run up to here

**Model:** Opus · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P08: Build session I: controlled browser, pick, locators, run up to here`

The live headed browser the builder drives, element picking and replays.

## Read first (only these)
- dev/designs/CONTEXT_workbook_builder_design.md Q5, Q10–13, Q49, Q50
- dev/claude/CONTEXT_workbook_builder_engineering.md section 3 "Interactive build mode"
- dev/designs/workbook-builder-canvas/record.py (overlay pill, hover card, which-one)

## You own
- `src/regrunner/build/ (new package): session.py, locators.py, overlay.js`
- `web/build_api.py (session routes)`
- `web/static/js/views/build/ (session parts)`

## Build
- One build session per workbook; decide and document how it coexists with normal runs.
- Headed browser with injected overlay via Playwright (`add_init_script`, `expose_binding`): survives navigation, frames, new windows; does not trigger site listeners.
- Pick → most stable unique locator (id → test id → stable attribute → class+position) + backups + plain-words description; "which one?" for generic actions; clicking a word makes it a variable and re-verifies live.
- Run up to here / this step / next 5 with a persistent session, using the **same** actions as real runs; "earlier steps changed" warning; side-effect pause dialog.

## Done when
- Browser tests on the mock site only. No OS-level input (guard test passes).

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
