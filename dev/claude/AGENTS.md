# AGENTS.md: START HERE (every AI agent, every session)

> Read this file first and only this file. It tells you where things live, what to change and which tests to run.
> Open other files only when the table in section 3 points you to them. Do **not** read `README.md` (56 KB) end to end:
> it is the user manual, organised by the headings listed in section 8, so jump to one heading.
> Keep the repository root for what users need: AI notes, briefs and designs go in `dev/` (section 4), never at the root.
> Keep this file true: if you add a module, a test file, a config section or a rule, update the matching line here (section 10).

---

## 0. How to talk to the user (applies to every reply)

The user has ADHD and a short attention span, so keep replies **short and direct**. Write in conversational prose, the way a person
would talk, and put the most important thing first. Skip filler, preamble, recaps and long explanations; go deeper only when asked.
Use bullets or lists only when the content really is a list (steps, several files, several failures), not as the default format.
Short doesn't mean incomplete: always include failures, risks, required actions (restart the UI, copy files) and which tests ran.

---

## 1. Hard rules (break one and the user has to clean up after you)

1. **Never run a real workbook against a real site** (QA / UAT / PROD hosts). A "connectivity check" once placed a real UAT purchase.
   Verify on the local mock site only (`tests/site/`). Safe without asking: `regrunner plan|list|lint|selectors audit` (no browser).
   Any `regrunner run` of a file in `workbooks/` = a live transaction: ask first, naming the test, environment and side effects.
2. **Never retry, re-type or re-click a step** to make it pass. It hides real site bugs. Waiting longer is allowed; repeating is not.
   (Whole-test re-runs exist only for WAF blocks, captcha replays and infrastructure crashes = the `NOT_RUN` outcome.)
3. **No OS-level keyboard/mouse** anywhere (guarded by `tests/test_keys_events_config.py`). **No captcha/WAF evasion**, no UA/IP rotation.
4. **Never echo secrets** (passwords, TOTP secrets, one-time codes, API keys, bypass tokens) in events, notes, logs, reports or chat.
   Reports are shared with a QA team (`publish.dir`).
5. **Python 3.9 must keep working** (`requires-python >= 3.9`; the work computer uses 3.9). Create `asyncio.Event/Lock/Queue`
   inside coroutines only (guarded by `tests/test_py39_compat.py`). Annotations use `from __future__ import annotations`.
6. **Run only the tests your change touches** (section 5). The full suite is 668 tests / ~40 min: only when the user asks.
   Always tell the user which tests you ran.
7. **Do not edit the user's workbooks** (`workbooks/*.xlsx`). If a cell is wrong, tell the user which cell and why.
8. **Changes to server code** (`src/regrunner/web/app.py` or anything it imports at server start) **need the user to restart the UI**.
   Engine code runs in a fresh subprocess per run; JS/CSS are served fresh (reload the page). Say which applies.
   The user also copies changed files to their work computer: list the files you changed.
9. Match the surrounding style: long descriptive names, docstrings that explain *why*, test names that are full sentences.

---

## 2. The project in 60 seconds

`regrunner` replaces a legacy Windows/Excel Selenium runner with **Python + Playwright**. Test cases live in **Excel workbooks**
(one sheet per flow, one row per step, 26 keyword columns such as `Method`, `FindBy_Value`, `Value`, `Output_Value`, `Exact_Match`).
The runner reads a workbook, evaluates its formulas itself, runs each test in an isolated browser context, several at once
(`runner.workers`), and writes a run folder with evidence. Non-technical QA people drive it from a **web UI** (`regrunner serve`,
FastAPI + vanilla JS, no build step). Behaviour must match the legacy runner (the oracle is `~/Downloads/TG_Testing_Framework_py3_v4.2.zip`;
read its source before assuming a site or workbook bug).

Real runs happen on the user's **Windows work computer** (no 2FA there); run folders are copied into `runs/` here to be analysed.
This Mac cannot log into the real sites (2FA). If evidence is missing, change the engine to record it and ask the user to re-run there.

Run pipeline (one run = one workbook):

```
workbook/*.xlsx ─► workbook/model.py (tests, row loop, formulas via formula.py)
     ─► engine/runner.py  plan_run → open_run → Engine (shared Playwright, pool.py workers, schedule.py + order.py deps, throttle.py per site)
          ─► engine/test_runner.py  (one test: row by row; captcha gate, blank params, stop-after-failures)
               ─► engine/actions.py @action handlers ─► engine/session.py BrowserSession (pages, frames, ready/settle/nav watch)
          ─► engine/api_runner.py  (API sheets instead of UI steps)
     ─► events.py bus ─► runs/<id>/events.jsonl ─► reporting/console.py, web UI (runstate.js reducer), reporting/from_events.py
     ─► reporting/results.py → results.json, html_report.py → report.html(+pdf), publish.py → shared copy
```

---

## 3. Task router: "I need to change X" → files → tests

Test file names are in `tests/`. **fast** = no browser, seconds. **browser** = real Chromium against the mock site.

| Task / symptom | Edit | Run these tests |
|---|---|---|
| New or changed step keyword (`Method` column) | `engine/actions.py` (`@action("NAME", element=True)`) | the test for that behaviour below + `test_keys_events_config.py` |
| Click behaviour (click did not take, covered, aria-disabled, JS_Click visibility, windows) | `engine/actions.py`, `engine/enabled.py`, `engine/session.py` | `test_click_and_load.py`, `test_click_and_window_rules.py`, `test_aria_disabled_click.py` |
| Typing / Set / SendKeys, field wiped, blur checks, server call after input | `engine/actions.py`, `engine/session.py` (`type_into`, `settle_after_input`, `_watch_calls`), `engine/keys.py` | `test_typed_fields.py`, `test_input_settle.py`, `test_keys_events_config.py` |
| Page not ready, navigation after click, waits, timeouts, slow machines | `engine/patience.py` (`Patience`, `WaitNotice`), `engine/session.py` (`ensure_ready`, `activity`, `_watch_activity`, `load`), `engine/settle.py`, `config.py` (`TimeoutCfg`, `WaitCfg`, `PatienceCfg`) | `test_patience.py`, `test_page_ready.py`, `test_click_and_load.py`, `test_input_settle.py`, `test_stop_after_failures.py` |
| Browser crash / OOM / disconnect / driver death = `NOT_RUN` + whole-test re-run | `engine/session.py` (`mark_infra`, `check_infra`), `engine/test_runner.py` (`_not_run_step`), `engine/runner.py` (`run_case`, `restart_driver`) | `test_infra_rerun.py` |
| Output / Output_Property / Exact_Match / Contains / "actual" values | `engine/actions.py`, `engine/test_runner.py` (`_output_of`), `engine/outcome.py` | `test_outcome.py` (fast), `test_output_value_property.py`, `test_output_value_actual.py`, `test_option_text.py` |
| Pass/fail rules (Ignore_not_existing_object etc.) | `engine/outcome.py` (port of legacy `validateresults`) | `test_outcome.py` (fast) |
| Flow keywords (SET_VARIABLE, IF/ELSE/END_IF, ITERATION_START/END, CALL_TEST, JSON_READ), `{NAME}` / `{SECRET:NAME}` in cells, the run's variable pool, `_rr_environments` (required vars refuse the run) | `workbook/variables.py`, `workbook/model.py` (`prepare_row`, `value_of`, `record`, `plan`), `engine/test_runner.py` (`FlowControl`, row loop jumps, `run_called`, masking), `engine/actions.py` (handlers), `engine/order.py` (Needs/Provides), `preflight.py` (`environment_problem`) | `test_flow_variables.py` (fast), `test_flow_keywords.py` (mock site + one web API check) |
| One test's step loop: stop rules, captcha stop, blank params, skipped rows hint | `engine/test_runner.py` | `test_stop_after_failures.py`, `test_skipped_rows_hint.py`, `test_blank_params.py`, `test_captcha.py` |
| Failed-step evidence (detail, diagnosis, full-page screenshot, saved HTML) | `engine/failure_capture.py` | `test_failure_capture.py`, `test_full_page_screenshot.py` |
| Excel formula / function (`VLOOKUP`, `TEXT`, `NUMBERVALUE`...) | `workbook/formula.py` (`@function("NAME")`), `workbook/textfmt.py` | `test_formula.py`, `test_lookup_totp.py` (fast) |
| Workbook reading, token substitution, blnExecute, write-back, Params rows | `workbook/model.py`, `workbook/sheet.py` | `test_model.py` (fast), `test_blank_params.py`, `test_variables_set.py`, `test_real_workbook.py` (fast, skips without the file) |
| Writing workbooks (edit cells/rows/columns, hidden `_rr_*` sheets, save + backup, drafts, lock/external-change checks) | `workbook/writer.py` (`WorkbookEditor`) | `test_workbook_roundtrip.py` (`-k "not real"` = 2 s; the real-workbook cases take ~2.5 min) |
| Workbook Builder model (tests/blocks/steps/variables JSON, ops, undo/draft/save/history/diff), builder problems, `/api/build/*` | `workbook/builder.py`, `lint.py` (`builder_problems`), `web/build_api.py`; the shapes are fixed in `dev/plan/CONTRACT.md` | `test_builder_model.py` (~10 s, real workbooks included), `test_build_api.py` (2 s). **Restart UI** for build_api changes |
| API (web-service) sheets: WEBSERVICE_URL / Environment_Parameter, InputOutput, templates | `workbook/api.py`, `workbook/api_template.py`, `engine/api_runner.py` | `test_api_tests.py`, `test_api_purchase_flavour.py` |
| Test order, dependencies, chains ("waits for") | `engine/order.py`, `engine/schedule.py` | `test_run_order.py`, `test_web_run_order.py` if UI touched |
| Workers, several workbooks at once, joining a run, progress, shutdown/cancel | `engine/runner.py`, `engine/pool.py`, `engine/inbox.py`, `engine/diagnostics.py` | `test_multi_run.py`, `test_progress_and_parked_worker.py`, `test_shutdown.py`, `test_py39_compat.py` |
| WAF 403/429, cool-down, pacing per site | `engine/throttle.py`, `engine/session.py` (`raise_if_blocked`), `engine/runner.py` (`run_case`) | `test_waf.py`, `test_web_paused_banner.py` |
| Captcha detection / solve-by-hand window (out of scope unless asked) | `engine/captcha.py`, `engine/test_runner.py` (`_captcha_gate`) | `test_captcha.py`, `test_web_captcha.py` |
| ASK_USER step, asking a person mid-run | `engine/ask.py`, `cli.py` (`TerminalAsker`), `web/app.py` (answer endpoint) | `test_ask_user.py`, `test_web_ask_user.py` |
| TOTP / GET_GOOGLE_TOKEN / Okta one-time codes (+ code-to-Verify gap, `code_submitted`) | `totp.py`, `engine/actions.py` (`get_google_token`, `code_typed`, `code_submitted`) | `test_totp_reuse.py`, `test_lookup_totp.py` (fast), `test_totp_login.py` (mock Okta, 5 workers) |
| Browser choice (Chrome/Edge/WebKit "Safari"/Chromium), launch, which browser ran | `browsers.py`, `config.py` (`BrowserCfg`), `preflight.py` | `test_browsers.py`, `test_browser_channel.py`, `test_web_browser_choice.py` |
| Selectors: selectors.yaml, XPath→CSS, harvest, audit | `selectors/*.py` | `test_selectors.py`; harvest also `test_e2e.py -k harvest` |
| Config key added/changed | `config.py` (dataclass `*Cfg`) + `config.yaml` (document it inline) + README "Configuration" | `test_keys_events_config.py` + the feature's tests |
| New event type | `events.py`, emitter, `reporting/from_events.py` (replay), `web/static/js/runstate.js` (reducer), `reporting/console.py` | `test_keys_events_config.py`, `test_web_ui.py -k reducer`, feature's web test |
| results.json / HTML / PDF report | `reporting/results.py`, `reporting/html_report.py` | `test_e2e.py -k report`, `test_variables_set.py` |
| Shared copy for the team (`publish:`) | `publish.py` | `test_publish.py` |
| CLI command / flag | `cli.py` (and `web/app.py` `cli_flags()` so the UI shows the same command) | `test_cli.py`, `test_py39_compat.py`, `test_web_ui.py -k every_setting` |
| `lint`, `plan`, `list`, preflight/doctor | `lint.py`, `insight.py`, `preflight.py` | `test_web_api.py -k insight`, `test_cli.py`, feature tests that mention lint |
| Web backend route / run manager | `web/app.py` (routes ~line 695+, `RunManager`) | `test_web_api.py` (+ `-k` the route), `test_web_multi_run.py` for pool/join. **Restart UI.** |
| New run screen (workbooks, tests, settings, order card) | `web/static/js/views/newrun.js`, `wbfilter.js`, `browsers.js` | `test_web_ui.py -k <feature>`, `test_web_multi_ui.py`, `test_web_workbook_search.py`, `test_web_run_order.py` |
| Run-in-progress screen, banners, live state (yellow "waiting on purpose" banner, lane waitline) | `web/static/js/views/live.js`, `runstate.js` | `test_web_waiting_banner.py`, `test_web_paused_banner.py`, `test_web_variables.py`, `test_web_ask_user.py`, `test_web_ui.py -k "run_from_click"` |
| Results screen | `web/static/js/views/results.js` | `test_web_ui.py -k "failed_run or failed_step"` |
| Dialogs (delete workbook, lint/plan/audit, PROD confirm, sign-in) | `web/static/js/views/modals.js`, `actions.js` | `test_web_delete_workbook.py`, `test_web_ui.py -k "prod or lint or signing"` |
| Styles / theme | `web/static/app.css`, `theme.js` | `test_web_ui.py -k theme` |
| Measuring a run: time split per step/test, queue time, resource sampler, third-party hosts, site version | `engine/timing.py`, `engine/resources.py`, `engine/session.py` (`_watch_hosts`, `collect_lag`, spans), `engine/test_runner.py`, `engine/schedule.py` (`queued_s`), `config.py` (`MeasureCfg`) | `test_measure.py`; scaling benchmark (opt-in, slow, never in the default subset): `RR_BENCHMARK=1 .venv/bin/pytest -s tests/test_benchmark_scaling.py` |
| Run history, "what changed" markers, compare, CSV export (`regrunner history`) | `history.py`, `cli.py` (`cmd_history`) | `test_history.py` |
| Launchers, first-run setup, desktop icon, own-window UI, the folder shared with other people | `Start QA Regression.bat/.command`, `cli.py` (`open_in_app_window`, `serve --app --exit-when-closed`), `web/presence.py` + `static/js/presence.js` (hello/goodbye; stop when the last window closes, never mid-run), `dev/make_share_folder.py`, `dev/share/START HERE.txt` | `test_cli.py` (`-k "app_window or serve"`), `test_exit_when_closed.py`; launchers have no automated test: say so |
| Analyse a run folder the user copied in | read `runs/<id>/` (section 7); `regrunner history` for trends across runs; no code change until the cause is proven | none |

Always add to the list: `test_py39_compat.py` if you touched asyncio/runner/CLI; `test_keys_events_config.py` if you touched config, events or input.

---

## 4. Repo map (sizes in lines so you know what is big)

```
dev/                 NOT shared (make_share_folder.py leaves it out): everything for developers and AI agents
  claude/AGENTS.md   this file (.claude/CLAUDE.md imports it)
  claude/CONTEXT_*.md  hand-off briefs for a specific piece of work in progress (read only if your task is that work)
  designs/           design briefs (CONTEXT_workbook_builder_design.md); put new design briefs/exports here, not at the root
  designs/workbook-builder-canvas/  scripts that generate every Workbook Builder design board (markup to copy when building a screen)
  plan/              the Workbook Builder build plan: PLAN.md (rules, order, status), CONTRACT.md, phases/Pxx-*.md, YOUR_GUIDE.md (for the user)
  make_share_folder.py  builds share/QA Regression/ + .zip (git-ignored) for other people: launchers, src/, config, README, workbooks
  share/START HERE.txt  the one-page instructions copied into that folder
README.md            user manual, 56 KB: read one section at a time (section 8)
config.yaml          behaviour settings, every key commented; sections: runner browser timeouts waits output screenshots
                     failure_capture selectors captcha_bypass auth review reports behaviour measure tags patience; publish/api/ask/captcha are
                     commented out (defaults in config.py)
secrets.env          git-ignored secrets (RR_VAR_<COLUMN>, bypass tokens); never print it. secrets.env.example = the template
selectors.yaml       logical selector map (sheet Locator column → this → legacy XPath)
Start QA Regression.command/.bat   double-click launchers: first run creates .venv + installs + desktop icon (Windows .lnk
                     with app.ico; macOS QA Regression.app bundle with app.icns, remade when the folder moves),
                     reinstalls when pyproject.toml changes, then `python -m regrunner serve --app --exit-when-closed` (own Edge/Chrome window;
                     closing it stops the server, then the .command closes its Terminal window via osascript)
workbooks/           the user's real workbooks (DO NOT EDIT, DO NOT RUN live). .trash/ = deleted from UI, .chains/ = saved run orders
runs/<run-id>/       run folders (git-ignored); many are copies from the work computer
.auth/               saved sign-in state + totp_last.json (git-ignored)

src/regrunner/
  cli.py        486   `regrunner run|list|plan|lint|selectors|auth|report|serve|doctor|publish`; split_workbooks; TerminalAsker
  config.py     397   Config + *Cfg dataclasses (defaults live here), load_config, secrets.env loading
  events.py     160   EventBus + event types (JSONL)
  browsers.py   301   browser registry, resolve/probe/pick_default, identity of the browser a run used
  totp.py       162   RFC 6238 codes; reserve_window() so two logins never get the same code
  insight.py    134   read-only workbook questions for UI/CLI (tests, flows, summary)
  lint.py       290   workbook lint + builder_problems (the Build tab's live problems, on the builder model JSON)
  preflight.py  161   doctor + UI readiness checks; environment_problem (required environment variables, runner + server)
  publish.py    243   shared copy (report.html + summary.txt) to publish.dir
  signin.py      87   one-time SSO sign-in → storage state
  runmeta.py     25   run.json;  priority.py 24 (nice)
  history.py    378   `regrunner history`: all run folders as one record, what-changed markers, compare, CSV (never values typed/read)
  capture/review.py 88  console errors / failed requests collected for review
  engine/
    runner.py      823  orchestration: RunOptions, plan_run/open_run/announce_run, Engine (workers, retries, run_case), execute(_many)
    test_runner.py 460  TestRunner: one test row by row; masking; captcha gate; blank params; stop rules
    actions.py    1159  every Method → Playwright (42 @action handlers); JS snippets (VISIBLE_TEXT_JS, CLICKABLE_JS, CURRENT_VALUE_JS...)
    session.py     870  BrowserSession: context, pages, frames, ensure_ready, navigation/call watches, WAF block detection
    patience.py    180  waits that end on evidence, not a clock (Patience) + WaitNotice (worker_waiting / worker_resumed events)
    timing.py      216  where a step's time went (site / wait / runner / computer / other; SiteClock, spans), run summary, site-version fingerprint
    resources.py   402  resources.jsonl sampler (CPU, free memory, swap, browsers' memory, loop lag; stdlib, psutil if present), machine_info, runner_version
    settle.py 61 · enabled.py 97 · keys.py 87 · outcome.py 83 · order.py 243 · schedule.py 72 · pool.py 100
    inbox.py 115 · throttle.py 71 · captcha.py 65 · ask.py 118 · failure_capture.py 449 · api_runner.py 343 · diagnostics.py 17
  workbook/
    model.py 812 (Workbook, TestCase, TestRuntime, prepare_row, value_of, plan) · sheet.py 262 · formula.py 755 · textfmt.py 156
    variables.py 339 (VariablePool, environment table, secret_value, {NAME} substitute, IF conditions, flow_map of IF/loops)
    writer.py 1400 (WorkbookEditor: patches only the XML an edit touches; row insert/delete/move rewrite every reference)
    builder.py 1850 (Workbook Builder model: build_model, apply_ops, BuildDocument undo/draft/save/history/diff, BuildStore; CONTRACT.md)
    api.py 495 · api_template.py 113
  selectors/  spec.py resolve.py xpath2css.py migrate.py harvest.py
  reporting/  results.py (data model) html_report.py console.py from_events.py
  web/
    app.py 1081   FastAPI: create_app, RunManager, cli_flags(), routes under /api/...
    presence.py   UiPresence: which UI windows are open (/api/ui/hello, /api/ui/goodbye) for serve --exit-when-closed
    build_api.py  /api/build/* routes (register_build_routes: one line in create_app); later builder phases add their own modules
    static/index.html, app.css, js/{main,state,api,actions,runstate,morph,util,fmt,icons,theme,browsers,wbfilter,presence}.js
    static/js/views/{shell,newrun,live,results,modals}.js

tests/
  conftest.py          `site` (session mock server URL), `make_cfg(**{"section.key": v})` (fast timeouts), resets totp state
  site/server.py       mock site (AEM-like pages, WAF/FLAKY switches, recaptcha routes, /policy/purchase/v2 API, OKTA once-only code check,
                       /bin/slow?ms= /bin/hang /bin/forever); *.html pages per scenario (slow, cpu, never_load, okta, alert...)
  workbook_factory.py  build_workbook()/build_flow(): synthetic workbooks with the real 26 columns and formula tricks;
                       build_steps_workbook(): flows written by the test (sheet.add rows) with their own Params
  flow_books.py        book(): tiny workbooks as lists of rows (+ Params rows, loop data sheets, `_rr_environments`) for the flow keywords
  web_fixtures.py      `web` fixture: live UI server on a scratch project whose workbooks point only at the mock site
  test_*.py            56 files; see section 5 (test_benchmark_scaling.py is opt-in: RR_BENCHMARK=1)
```

---

## 5. Tests: what to run

Runner: `.venv/bin/pytest` (Python 3.12 venv; editable install; Chromium + WebKit already downloaded on this Mac).
Cloud sessions (claude.ai/code): `.claude/hooks/session-start.sh` builds `.venv` at start and pins Playwright 1.56.0 to the image's Chromium; WebKit is not available there.

| Scope | Command | Size / time |
|---|---|---|
| One file | `.venv/bin/pytest -q tests/test_page_ready.py` | seconds to ~1 min |
| One test | `.venv/bin/pytest -q tests/test_web_ui.py -k theme` | |
| No-browser subset | `.venv/bin/pytest -q -m "not browser"` | 397 tests, ~4 min (2.5 of them: real workbooks in `test_workbook_roundtrip.py`) |
| Full suite (**only if the user asks**) | `.venv/bin/pytest -q` | 668 tests, ~40 min |

- Marker `browser` = needs Playwright (module-level `pytestmark` or per test); `realworkbook` = needs `workbooks/UAT_AEM_Travelex Regression_v9.1.xlsx` (skips otherwise).
- Pure-logic files (all fast): `test_workbook_roundtrip -k "not real"`, `test_formula`, `test_lookup_totp`, `test_model`, `test_outcome`, `test_keys_events_config`, `test_py39_compat`, `test_totp_reuse`, `test_real_workbook`.
- `test_web_*.py`, `test_e2e.py`, `test_multi_run.py` are the slow ones: use `-k` to pick the test for the screen/feature you changed.
- Writing a new test: build a workbook with `tests/workbook_factory.py`, point it at the `site` fixture, add a mock page in `tests/site/`
  (and a route in `server.py` if it needs server behaviour). Name tests as sentences describing the behaviour. Keep them on the mock site.
- UI tests: Playwright `wait_for_function` is blocked by the app's CSP (poll with `page.evaluate`); after a re-render use the `tick()` retry
  helper pattern; `pick_only(page, name)` in `test_web_ui.py` selects exactly one workbook.
- Python 3.9 check (after runner/asyncio/CLI changes, if the user wants it): scratch venv from `/usr/bin/python3` (3.9.6) +
  `eval_type_backport`, project copied to the scratchpad; run the relevant files there.

---

## 6. Workbook semantics you will need (full detail: README "How the workbook is interpreted")

- Sheets: one action sheet per flow; `<Flow>_Params` sheets (one row per test instance: `Purchase#1` = Params row 3, `#2` = row 5...);
  `DataSheets` lists flows in order; `Global` holds `Environment` etc.; API sheets have `BLNEXECUTE` + `WEBSERVICE_URL` or
  `ENVIRONMENT_PARAMETER`, plus an `InputOutput` sheet.
- Row runs when `blnExecute` (col A) is `Y`. An empty blnExecute = skipped on purpose (legacy did the same).
- Tokens in `Value` / `FindBy_Value` / `Expected_Value` that name a Params column are substituted; an empty Params cell is asked for or fails
  (legacy typed the token name).
- `Ignore_not_existing_object=Y` swallows all errors except an Exact_Match mismatch. Exact_Match + Contains both blank = no comparison.
- A step's "actual" starts as its own `Output_Value` cell; an unresolved API `output_json` path stores the text `None`.
- Legacy oracle for disputes: `~/Downloads/TG_Testing_Framework_py3_v4.2.zip` (`TG_GUI/GUI_Test_Main.pyw`, `Web_Objects.py`,
  `GUI_Functions.py`, `TG_WebService/*`). Unzip into the scratchpad, never into the repo.

---

## 7. Analysing a run folder (`runs/<run-id>/`)

`run.json` (status, workbook path, browser), `results.json` (per test/step: status, expected, actual, `detail`, `diagnosis`, notes),
`events.jsonl` (everything, replayable), `runner.log` (task dumps on stalls), `tests/<Test#N>/` (screenshots, `network.jsonl` = first-party
calls, saved HTML, API `request.txt`/`response.json`), `report.html`, `summary.txt`.
Method: find the first failed step, read its `detail` + `diagnosis`, check `network.jsonl` around it (403 = WAF; a click that "passed"
but the page did not react usually means an unanswered/blocked call), compare with the legacy semantics before blaming the site.

---

## 8. README headings (jump straight to one; `grep -n '^##' README.md` for line numbers)

Quick start · Set up · Which browser a run uses · Before the first real run · How the workbook is interpreted (Actions, Captchas) ·
Speed, precision and staying out of the way · Selectors · Web UI (API) · Evidence (API tests, Tests that depend on each other,
Values set by the tests, publish, Event stream) · Configuration · Extending · Known limits · Tests

---

## 9. Current state and known gotchas

**Done 2026-09-26 (uncommitted; check `git status`):** "accurate at any worker count" (brief: `dev/claude/CONTEXT_accurate_at_any_worker_count.md`).
Evidence-based waiting (`engine/patience.py`, `patience:` in config.yaml; `runner.step_hard_cap_s` 7200 / `test_timeout_s` 43200 are backstops only);
`NOT_RUN` outcome + infra re-runs (`runner.infra_retries`, run status `INCOMPLETE`); TOTP margin from the measured code-to-Verify gap
(`totp.safe_margin/record_gap`, gaps in `.auth/totp_last.json`); login codes masked like secrets; auth-domain 4xx bodies in `network.jsonl`;
dialogs answered as they open when the next step is an ALERT step; `worker_waiting`/`worker_resumed` events + yellow banner (`--wait*` CSS tokens).
Unverified on real sites: Okta per-account limits, real polling/third-party traffic vs. patience, real code-to-Verify gaps.

**Workbook Builder (2026-09-26): built in phases** by separate sessions following `dev/plan/PLAN.md` (status table at its end). PRs go into `qa-regression`.
P01 (writer) done: everything that writes a workbook goes through `workbook/writer.py`, never openpyxl `save` (it drops printer settings,
customXml, dynamic-array metadata and cached values). Untested here: opening an edited file in real Excel (no Excel/LibreOffice Calc in the cloud).
P02 (model, contract, problems, `/api/build/*`) done: `dev/plan/CONTRACT.md` is the interface every later phase builds on. The builder reads cells
as written (never evaluates formulas); blocks come from section rows (text in column A, no Method: the real workbooks' page headings) until a
block op writes the `BLOCK` column; a formula in blnExecute makes a step a locked legacy card; new keywords exist in the model only (engine: P03/P07).

P03 (engine I) done: the run-wide variable pool (`RunCtx.pool`; every name a step saves, any test, read as `{NAME}`), Needs/Provides ordering,
SET_VARIABLE / JSON_READ / IF / loops / CALL_TEST (a called test's steps are reported as the caller's steps after the CALL_TEST step, via
`_CallBus`), `_rr_environments` (required vars refuse the run: `EnvironmentMissing` + `env_missing` event, and HTTP 422 `env_missing` from
`/api/runs`), `{SECRET:NAME}` masked in events/results/reports/network.jsonl/review items. `step_skipped` is now emitted (IF sides not taken).

**In progress (2026-09-26): "same speed at 1 or 20 tests"** (brief with the user's decisions: `dev/claude/CONTEXT_efficiency_at_scale.md`).
Done: Phase 0 (measure: `timing` per step/test/run, `queue_s`, `resources.jsonl`, `third_party`, `site_version`, `machine`; opt-in benchmark)
and Phase 1 (`regrunner history`). **Next: the user reviews Phase 0 numbers from a real run on the work computer before Phase 2+ is built.**
Unverified: the Windows paths of `engine/resources.py` (ctypes; no Windows here), numbers from real sites.

Gotchas:
- `data-key` is the DOM patcher's (`morph.js`) identity attribute: never use it for action parameters (use `data-field`).
- In `newrun.js`, `acts` = click handlers, `changes` = change handlers. morph.js never rewrites a focused input's value.
- State-changing API calls need header `X-Requested-With: regrunner` and a local Host/Origin.
- The UI replays the whole event stream after a reload: new events must rebuild correctly in `runstate.js` and `from_events.py`.
- "Safari" = Playwright WebKit, not Safari.app. The work computer cannot download Playwright browsers: it uses installed Chrome/Edge.
- API templates on `L:\...` exist only on the work computer; "template not found" here is expected.
- Writer: rows a move carries keep relative row refs at the same distance (running counts `=COUNTA($B$1:B15)` stay "row above");
  `$` refs follow their cell. New text is written as inline strings; after any change `fullCalcOnLoad` makes Excel recalculate.
- Measure before claiming numbers (sizes, timings) to the user.
- `{NAME}` is replaced on the prepared step only, never written into the sheet state (a loop runs the row again); the Output_Value as written is
  cached per row (`_authored_output`) because `record()` writes the result over it. Planning (`runtime.plan()`) must use a pool of its own.
- While a JS dialog is open the page answers nothing (evaluate/screenshot hang): code that probes the page must check `session.pending_dialog` first.
- Patient waits must stay bounded by *evidence*: only the page's own requests count as "working" (third-party / polling / animation never do).
- Wrap new runner work or deliberate waits in `timing.span("runner"|"wait", kind)` (`timing_of(ctx)` in actions) so the time split stays honest.
  Measuring must never change behaviour or record values (history/CSV hold times, statuses, kinds and versions only).

---

## 10. Keeping this file useful

Update this file in the same change when you: add/rename a module or test file (sections 3-4), add a config section or rule (1, 4),
finish or start a multi-session piece of work (9), or learn a gotcha the next agent would otherwise rediscover (9).
Keep entries one line; details belong in README (users) or code docstrings (developers).
