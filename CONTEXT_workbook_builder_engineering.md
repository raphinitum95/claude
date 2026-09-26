# Context: make the Workbook Builder actually work (engine, file format, API), plus the Run-section changes it needs

You are picking up an **engineering task** on `regrunner`, a Python + Playwright regression runner. The UI for the new **Build** tab is designed separately (`CONTEXT_workbook_builder_design.md`, which lists every product decision as Q1–Q53). **Read that file first.** This file covers what has to exist behind the design and what is missing today.

## The project in one paragraph

`/Users/raphaeldelossantos/Documents/qa-regression` replaces a legacy Windows/Excel Selenium runner. Test cases live in Excel workbooks (`workbooks/*.xlsx`): one sheet per test (one row per step, keyword columns), plus `Params_N` data sheets, `DataSheets` (which tests run) and `Global`. The runner (`src/regrunner/`, installed editable in `.venv`) reads a workbook, runs each test in its own Playwright browser context (several at once), and writes a run folder (`runs/<id>/`: `results.json`, `events.jsonl`, `runner.log`, screenshots, `network.jsonl`, `report.html`). The web UI is `regrunner serve` (FastAPI in `web/app.py`, vanilla ES modules in `web/static/js/views/{newrun,live,results,modals,shell}.js`, DOM patcher `morph.js`, event reducer `runstate.js`, tokens in `app.css`). `README.md` documents the behaviour. Config: `config.yaml`, secrets: `secrets.env`.

## Code to read before changing anything

| Area | Files |
|---|---|
| Workbook model | `workbook/model.py` (columns: `UI_COLUMNS`, `RESULT_COLUMNS`, `DATA_COLUMNS`, token substitution, blnExecute), `workbook/sheet.py` (**openpyxl, read-only today**: loads with and without cached values), `workbook/formula.py` (own Excel formula evaluator, verified against ~3,180 cached values) |
| API tests | `workbook/api.py` (`WEBSERVICE_URL`/`WEBSERVICE_METHOD`/`JSON_FORMAT`/`DT_*`), `workbook/api_template.py` (Replace/Output templates, `api.templates_dir` / `RR_API_TEMPLATES_DIR`), `engine/api_runner.py` |
| Actions | `engine/actions.py`: about 55 method names mapped to Playwright. **`UNSUPPORTED` includes `SET_VARIABLE`, `JSON_READ`, `GO_TO_ROW`, `ITERATION_START`, `ITERATION_END`, `DRAGANDDROP`, `DB_*`, `SEND_EMAIL`, `FILE_COMPARE`, `RUN_SCRIPT`.** |
| Running | `engine/runner.py` (workers, retries, run loop), `engine/test_runner.py` (step loop), `engine/session.py` (page-ready gates, navigation watch, `click_and_verify`, typed-field checks), `engine/settle.py`, `engine/patience.py` (new, uncommitted), `engine/order.py` (test chains, `save_chains` is the **only** code that writes to a workbook today), `engine/outcome.py`, `engine/ask.py`, `engine/inbox.py` |
| Locators | `selectors/` (`resolve.py`: chain sheet `Locator` column → `selectors.yaml` → legacy XPath; `harvest.py`, `migrate.py`, `xpath2css.py`), `capture/review.py` |
| Sign-in and secrets | `signin.py`, `totp.py`, `config.py`, `secrets.env` |
| Checks | `lint.py`, `preflight.py` |
| Web | `web/app.py`: existing endpoints `/api/workbooks`, `/tests`, `/order`, `/lint`, `/plan`, `/audit`, `/api/runs*`, `/api/auth/*`, `/selectors/apply` |

Also read `CONTEXT_accurate_at_any_worker_count.md`, a parallel workstream on patience and worker-count independence. `engine/patience.py`, `engine/settle.py` and `config.py` are uncommitted work from it; don't clobber them.

## Rules the user has set (keep them)

- **Never run anything against the real sites (QA/UAT/PROD) without asking first.** A "connectivity check" once completed a real UAT purchase. Use the mock site (`tests/site`) and synthetic workbooks (`tests/web_fixtures.py`).
- **Run only the tests your change touches.** The full suite is about 500 browser tests (~40 min).
- **Never retry, re-type or re-click to make a step pass**, and **never heal silently**. That would hide real site bugs (false passes).
- No OS-level keyboard or mouse input (a test guards this). No captcha or WAF evasion; captcha and WAF are treated as solved.
- Must work on **Python 3.9** (work Mac), and on Windows and macOS. Chromium downloads are blocked on the work laptop (`browser.channel: chrome`/`msedge`).
- Web gotchas:
  - `data-key` is the DOM patcher's identity attribute; use `data-field` for action parameters.
  - The strict CSP blocks `wait_for_function`; poll with `page.evaluate`.
  - State-changing API calls need the header `X-Requested-With: regrunner` plus a local Host/Origin.
  - `morph.js` never rewrites a focused input's value.
- The legacy runner zip (`~/Downloads/TG_Testing_Framework_py3_v4.2.zip`) is the reference for existing keyword semantics (e.g. `Ignore_not_existing_object=Y` swallows all errors; Set clears, Write/Type append; an unresolved `Output_Value` path is the text "None").

## Work needed, by area

### 1. Workbook writing (the foundation; nothing writes sheets today)
- **Round-trip editing** of test sheets, `Params_N`, `DataSheets` and `Global`, plus new sheets and new workbooks in `workbooks/`.
- openpyxl drops cached formula values, some data validation, images, charts and comments, and may disturb styles. Decide and test what must survive.
  - Formulas like `=S49` and `=IF($D$13="PASSED",…)` are used in the workbooks.
  - The runner evaluates formulas itself, so missing cached values may be fine for the runner, but Excel users must see correct values when they open the file.
  - Build a round-trip test: load → save → diff every cell, formula and style against the original, using the real workbooks read-only as fixtures.
- **Legacy rows** (GO_TO_ROW, formula-driven blnExecute, etc.) must be preserved byte-for-byte (Q28).
- **Autosave draft** beside the workbook, **"Save to Excel"** with a timestamped backup, and a History list with restore and a per-step diff (Q30).
- **Detect external changes** (mtime or hash) and Excel's lock file (`~$name.xlsx`). Offer reload or merge; when locked, wait and say "close it in Excel" (Q29).
- **New columns and keywords** (Q3). Old readers must ignore them; the legacy runner compatibility question is open, so ask the user.
  - Columns: `BLOCK` (Q14), side-effect flag (Q13), backup locators (Q49), page-gate/fingerprint reference (Q53), friendly label for variables (Q37: header comment or a hidden sheet).
  - Keywords: `IF`/`ELSE`/`END_IF` on variables only, `ITERATION_START/END` per data row, `CALL_TEST`, `DISMISS_IF_SHOWN`, `ASSERT_PAGE`, `WAIT_UNTIL`, smart widget steps (`PICK_DATE`, `CHOOSE_SUGGESTION`), and the extra check kinds (regex, compare, count, enabled…).
- Workbook-level stores:
  - the page-fingerprint table (Q53);
  - the environment-variables table (Q43/44);
  - Needs/Provides per test (Q21), or derive them;
  - scenario sheets (Q36).
  - Choose sheet names that won't collide with existing ones.
- **Template library**: one shared file next to the workbooks (Q17), insert = copy, with variable mapping (Q16).
- Copy/paste and duplicate at step, block, test and workbook level, plus workbook-wide find-and-replace (Q26).
- Rename a variable everywhere it's used, including formulas that reference it (Q37).
- Computed values write **real Excel formulas** that `formula.py` must be able to evaluate (Q23). Add any functions it lacks, e.g. `TODAY`, `NOW`, `TEXT`, `RANDBETWEEN`.

### 2. Engine support for the new keywords and behaviour
- **Implement what is `UNSUPPORTED` today** where the design needs it: `SET_VARIABLE`, `JSON_READ` (response checks), loops, `CALL_TEST`, IF on variables.
- **Workbook-wide shared variable pool** across tests in a run, with ordering by Needs/Provides (Q21). Today each test runs in its own isolated context, several at once; `engine/order.py` already has chains. A test that calls another mid-way must run that test to completion (in its own browser context or none for API) and then resume.
- **Page-arrival gate** (`ASSERT_PAGE` / fingerprint: URL part AND landmark). This is **always a hard stop** on failure, regardless of `Ignore_not_existing_object`. Integrate it with `session.watch_for_navigation` / `ensure_ready`. The recorder proposes a fingerprint when a click changes the URL.
- **Environment variables**:
  - per-workbook table, filled from the run's chosen environment;
  - required ones (DOMAIN at least) **block the run with an error** if missing (preflight plus server-side);
  - editable environment list (Q44);
  - anything marked production keeps the typed PROD confirmation and blocks side-effect steps.
- **Secret variables** `{SECRET:NAME}`: values in `secrets.env` per environment, never in the workbook, the logs, `events.jsonl` or reports (Q42). Audit every place a step value is echoed.
- **Side-effect steps** (Q13): in build-mode replays, pause before the step and ask (reuse the `engine/ask.py` event pattern). PROD always blocks them. Full runs are unchanged.
- **Backup locators** (Q49): on a primary miss, still FAIL, but probe the backups and put "backup found N matches + screenshot + proposed locator" into the step's `detail`/`diagnosis`. "Accept new locator" writes it back (see `selectors/apply`).
- **"Dismiss if shown"** is always logged as "appeared / did not" (Q25).
- **Concurrency scenarios** (Q35/36): run several tests, or one test twice with different data rows, as one unit with **sync barriers** ("all lanes wait here") and ordering ("A before B"). Report per lane. This interacts with the worker pool and with the `totp.py` one-code-per-window rule; two lanes that log in with the same user need distinct TOTP windows.

### 3. Interactive build mode (new; biggest piece)
- **A controlled headed browser window** launched by the server (Q5), with an **injected overlay** (Q50) that is a floating pill and hover card.
  - It must survive navigations (`add_init_script`), iframes and new windows, and it must not trigger the site's own listeners.
  - It talks back to the builder over a binding (`expose_binding`) or the websocket.
  - Watch the site's CSP; inject via Playwright, not a `<script src>`.
- **Recorder** (Q6): record-toggle events → steps at the builder's cursor.
  - Typed text becomes a variable suggestion (Q7).
  - Switch window/frame/back steps are added automatically (Q34).
  - Widget patterns collapse (date picker, autocomplete) (Q51).
  - No fixed waits are recorded (Q41).
  - Replay must use the same actions as real runs (`engine/actions.py`, `session.py` gates), not a separate code path, or build-mode results won't match real runs.
- **Locator generation** (Q10/Q11):
  - from a direct pick, the most stable unique locator (id → test id → stable attribute → class+position), plus backups;
  - for a generic action, highlight every match, ask which one, then build a direct locator;
  - a plain-words description of the element ("button 'Choose' inside card 'Max'") where any part can become a variable, then the locator is rebuilt and re-verified live.
  - Reuse `selectors/` (resolve/harvest/xpath2css).
- **"Check this" / "Save this"** from the live element (Q8): read the current text, value, state and count to prefill the check.
- **Run up to here / run this step / run next N** with a **persistent session** (Q12), plus the "earlier steps changed, replay from the start" warning. Uses the "Building with: row N" data row (Q24).
- **API/XML building** (Q18/Q19):
  - "Send now" with the environment's values;
  - response as a tree; clicking a value produces a JSON path or XPath, with array handling ("item where plan = {PLAN}");
  - cURL paste and Postman collection import;
  - fill from existing API template files.
  - XML/XPath evaluation is new (lxml is fine if it installs on the locked-down Mac; check).
- **Problems engine** (Q31): extend `lint.py` to run live on the builder's in-memory model. It covers unset variables, missing expected values, last-run locator misses, unmapped template variables, danger steps on PROD, and missing environment values. It never blocks saving.
- **Last-run overlay** (Q32/33): map each step to its last results (`runs/*/results.json`, by workbook + sheet + row). Show pass/fail dots and a passive "failed on last run" badge until a later run passes that step.

### 4. Server API (FastAPI, `web/app.py`)
Endpoints are needed for:
- the workbook model (read/edit/save/draft/history/diff);
- templates;
- variables (the set-by / used-by index for the variable map, Q22);
- environments;
- fingerprints;
- the build session (launch browser, record on/off, pick/check/save, run-to-here, run-step, close);
- API send;
- scenarios.

Also:
- Keep the existing security pattern (`X-Requested-With`, local Host/Origin).
- **One build session per workbook at a time**, and decide how it coexists with a normal run (there is "one active run" today).

### 5. Run section (Run / Results screens): the enhancements the builder needs
- **Environment selector drives the environment-variables table.** Missing required values show a blocking error on New run, naming the variable and the environment, with a link to Build → settings. Enforce it server-side too.
- **Scenario runs**: choose a scenario like a test. The live view shows lanes side by side with the sync points reached; results are per lane.
- **Results: "Fix in builder"** on every failed step. It deep-links to Build at workbook/test/step with the run id, so the builder shows the screenshot and error.
- **Page-gate failures** are shown distinctly ("Never reached Payment page: URL was …, landmark missing") as a hard stop, not as a "not found" cascade.
- **Backup-locator suggestion card** on failures, with "Accept new locator" (extends the existing selectors-apply flow).
- **Side-effect steps**: shown with their flag in the plan and live view. On PROD, the run plan shows them as blocked.
- **"Dismiss if shown" outcomes** appear in results.
- **Secrets are never shown** in live logs, results or reports.
- The user said "slight enhancements to the run section" and may have more in mind: **ask them for their list** before starting this part.

## Suggested order
1. Excel round-trip writer plus the round-trip fidelity test on copies of the real workbooks. Everything depends on it.
2. The in-memory builder model + server API + problems engine (no browser yet).
3. New keywords in the engine (variables pool, SET_VARIABLE, IF/loops, CALL_TEST, ASSERT_PAGE, environment variables, secrets), each with mock-site tests.
4. Interactive build session (browser, overlay, recorder, locator generation, run-to-here).
5. API/XML building, templates, scenarios.
6. Run-section changes.

Stop and ask the user before any step that touches a real site, and before changing the sheet format in a way the legacy runner or existing workbooks could trip over.
