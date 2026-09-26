# Contract between the pieces (owned by P02)

This is an outline. **P02 replaces it with the real thing** before any wave-3 phase starts. Waves 3+ build against it and must not
change it silently: a needed change goes in the PR description, and the review session updates this file.

## 1. Workbook file format additions (P01 writes them, P02 defines them, P03/P07 execute them)
- New step columns (after the existing 26): `BLOCK`, `SIDE_EFFECTS` (Y/blank), `BACKUP_LOCATORS` (JSON list), `STEP_NAME_AUTO` (Y = name is generated).
- New keywords: `IF`/`ELSE`/`END_IF` (variables only), `ITERATION_START`/`ITERATION_END` (per data row), `CALL_TEST`, `DISMISS_IF_SHOWN`,
  `ASSERT_PAGE`, `WAIT_UNTIL`, `PICK_DATE`, `CHOOSE_SUGGESTION`, check kinds (`CHECK_REGEX`, `CHECK_COMPARE`, `CHECK_COUNT`, `CHECK_ENABLED`, ...).
- New hidden sheets (names must not collide with user sheets; prefix `_rr_`): `_rr_fingerprints`, `_rr_environments`, `_rr_variables`
  (friendly labels, secret flag, needs/provides), `_rr_scenarios`.
- Secrets: the cell holds `{SECRET:NAME}`; values live in `secrets.env` per environment.

## 2. Builder model (JSON the server sends the Build UI)
`Workbook { name, file, environments[], tests[], variables[], fingerprints[], scenarios[], problems[] }`,
`Test { id, sheet, kind: web|api|xml, blocks[], steps[], needs[], provides[], lastRun }`,
`Step { row, n, method, name, nameAuto, block, page, locator{primary, backups[], plainWords[]}, value, expected, match, saveAs, onFail,
timeout, enabled, sideEffects, context, legacy, lastResult }`. P02 fills in exact field names and types.

## 3. Server endpoints (all under `/api/build/`, same security rules as today)
Workbook: read, edit (batched ops), draft, save to Excel, history, diff, restore, external-change status.
Variables index, environments, fingerprints, templates, problems. Build session (P08/P09): start, record on/off, pick, check, save,
run-to-here, run-step, run-next, close. API send (P10). Scenarios (P12). Batch label and results (P05/P06: `/api/runs`, `/api/batches`).

## 4. Events (new types go through `events.py`, `runstate.js`, `reporting/from_events.py`)
Page gate result, popup dismissed/not shown, side-effect paused/blocked, backup-locator suggestion, scenario sync reached, build-session events.
