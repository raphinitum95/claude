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
6. **Run only the tests your change touches** (section 5). The full suite is 988 tests / 40+ min: only when the user asks.
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
| P07 keywords: ASSERT_PAGE (page gate = hard stop), WAIT_UNTIL, DISMISS_IF_SHOWN, PICK_DATE, CHOOSE_SUGGESTION, CHECK_*; SIDE_EFFECTS steps (blocked on production, `TestRunner(side_effects="ask")` for build replays); BACKUP_LOCATORS (reported, never used) | `engine/actions.py` (handlers after "Safety steps", `side_effect_gate`, `probe_backup_locators`), `engine/checks.py`, `engine/gates.py`, `engine/outcome.py` (`StepOut.check/check_failed/stop/backup`), `selectors/spec.py` (`parse_backup_locators`), `engine/test_runner.py` (`_hard_stop`) | `test_checks.py` (fast), `test_engine_gates.py` (mock site `widgets.html`), `test_outcome.py` |
| Failed-step evidence (detail, diagnosis, full-page screenshot, saved HTML) | `engine/failure_capture.py` | `test_failure_capture.py`, `test_full_page_screenshot.py` |
| Excel formula / function (`VLOOKUP`, `TEXT`, `NUMBERVALUE`...) | `workbook/formula.py` (`@function("NAME")`), `workbook/textfmt.py` | `test_formula.py`, `test_lookup_totp.py` (fast) |
| Workbook reading, token substitution, blnExecute, write-back, Params rows | `workbook/model.py`, `workbook/sheet.py` | `test_model.py` (fast), `test_blank_params.py`, `test_variables_set.py`, `test_real_workbook.py` (fast, skips without the file) |
| Writing workbooks (edit cells/rows/columns, hidden `_rr_*` sheets, save + backup, drafts, lock/external-change checks) | `workbook/writer.py` (`WorkbookEditor`) | `test_workbook_roundtrip.py` (`-k "not real"` = 2 s; the real-workbook cases take ~2.5 min) |
| Workbook Builder model (tests/blocks/steps/variables JSON, ops, undo/draft/save/history/diff), builder problems, `/api/build/*` | `workbook/builder.py`, `lint.py` (`builder_problems`), `web/build_api.py`; the shapes are fixed in `dev/plan/CONTRACT.md` | `test_builder_model.py` (~10 s, real workbooks included), `test_build_api.py` (2 s). **Restart UI** for build_api changes |
| Build tab UI (Run · Build · Results tabs, workbook map, variable map, test editor: block map/cards/inspector/grid/drawer/problems/add-step menu, new-workbook/environments/fingerprint/history/file-changed dialogs) | `web/static/js/views/build/*.js` (state in `state.js`'s `freshBuild`/`freshEditor`), `views/shell.js` (`tabs`, `headerShell`), `views/modals.js` (routes `build-*` modal kinds to `build/dialogs.js`), `main.js` (`#/build...` routes, merges `build/actions.js` into the action tables), `icons.js`, `app.css` ("Build tab" section) | `test_web_build.py`, `test_web_ui.py -k theme`. JS only: reload the page, no UI restart |
| Recording + Check/Save/Wait until in the build window (Rec toggle, steps at the cursor, typed text → variable, password → secret in secrets.env, switch window/frame/Back steps, calendar → PICK_DATE, suggestion → CHOOSE_SUGGESTION, fingerprint + gate proposal, check card with every kind prefilled) | `build/recorder.py` (`Recorder`; pure helpers `check_kinds`/`check_step`/`token_for`/`store_secret` at the top), `build/overlay.js` (recording listeners, page-side locator counts, pill, cards, prompts), `build/session.py` (`_on_call` routing, modes), `web/record_api.py`, `web/static/js/views/build/record.js` | `test_build_recorder.py` (fast), `test_build_recording.py` (mock site `build_record*.html`, `widgets.html`), `test_web_build_record.py`. **Restart UI** for recorder/session/record_api; overlay.js is read at server start |
| Build window (Build tab's live browser: overlay pill/pick/which-one, locator + backups + plain words, word → variable, run up to here / this step / next N, side-effect pause, "earlier steps changed", opens on the environment's DOMAIN, closes when its window is closed) | `build/session.py` (`BuildSession`, `SessionStore`, `BuildAsker`), `build/locators.py` (pure), `build/overlay.js`, `web/build_api.py` (`register_session_routes`), `web/static/js/views/build/session.js`, `engine/test_runner.py` (`prepare_runtime`/`open_session`) | `test_build_locators.py` (fast), `test_build_session.py` (mock site `build_pick.html`), `test_web_build_session.py`. **Restart UI** for session.py/build_api changes; overlay.js is read at server start too |
| Templates: save a section as a template, insert one with variable mapping (Q15-17) | `workbook/templates.py` (new), `web/templates_api.py` (new, `register_templates_routes`; needs `web/app.py`'s `register_build_routes` return value, the shared `BuildStore`), `web/static/js/views/build/dialogs.js` (`templatesLibraryDialog`/`saveTemplateDialog`/`insertTemplateDialog`), `views/build/actions.js` (`openSaveTemplate`/`openInsertTemplate`/...), `formula.py`'s `{?TOKEN}` marker for anything left unmapped | `test_templates.py` (fast), `test_templates_api.py`, `test_web_build_p11.py` |
| Copy/paste a step or block, duplicate a workbook ("what changes?"), workbook-wide find & replace, per-step merge of a change made outside the builder (Q26, Q29) | `workbook/refactor.py` (new: `find_replace_preview`, `duplicate_candidates`, `merge_ops` - all return existing op kinds, never a new one), `web/refactor_api.py` (new, `register_refactor_routes`), `web/static/js/views/build/dialogs.js` (`duplicateWorkbookDialog`/`findReplaceDialog`, the merge picks in `fileChangedDialog`), `views/build/actions.js` (`copySelected`/`pasteClipboard` are pure client-side ops composition, no Python) | `test_refactor.py` (fast), `test_refactor_api.py`, `test_web_build_p11.py` |
| Value builder (computed values: date ± N, unique, pick from list, math, text join - Q23), a new Excel function | `workbook/formula.py` (`@function`), `web/static/js/views/build/dialogs.js` (`valueBuilderDialog`), `views/build/actions.js` (`refreshValueBuilderFormula` builds the formula string; it is written via the existing `update_step`/`set_cell` ops, no new backend) | `test_formula.py` (fast) |
| API (web-service) sheets: WEBSERVICE_URL / Environment_Parameter, InputOutput, templates; `{NAME}` / `REQUEST_BODY` / JSONPath + XPath paths / XML (SOAP) templates / greater_than-between-matches checks | `workbook/api.py`, `workbook/api_template.py`, `workbook/api_paths.py`, `engine/api_runner.py` (`prepare_body`, `fetch`, `read_response`) | `test_api_tests.py`, `test_api_purchase_flavour.py`, `test_api_paths_and_xml.py` |
| Build tab API / XML editor (form, Send now, response tree with "this item" / "item where", cURL, Postman, templates; `api_*` ops) | `build/api_builder.py`, `web/build_apitest.py` (`/api/build/api/*`), `web/static/js/views/build/api_editor.js`; CONTRACT.md 1.6 | `test_api_builder.py` (Send now hits the mock APIs), `test_web_api_builder.py`. **Restart UI** for api_builder/build_apitest changes |
| Concurrency scenarios (Q35/36): `_rr_scenarios` table, lanes (a test, or one test twice with its own data row) run together on one worker, sync lines / order markers, a failed lane releases the others, per-lane results, shared sign-in codes; the Build tab's scenario board; live / finished lanes | `workbook/scenarios.py` (table, board model, problems, deadlock check, `set_scenario`/`delete_scenario` ops), `engine/scenario.py` (`pick`, `LaneCase`, `Coordinator`, `run_scenario`), `engine/runner.py` (`_load_and_plan`, worker → `run_scenario`, `run_one`/`record`, `run_case(lane=)`), `engine/schedule.py` (groups), `engine/test_runner.py` (`lane.before_step`), `web/scenario_api.py`, `views/build/scenario.js`, `views/scenario_lanes.js`, `insight.py` (`scenario_entries`), `web/app.py` (`RunManager._validate`) | `test_scenarios.py` (fast), `test_scenario_run.py` (mock site `scenario_policy.html`, `okta.html`), `test_web_scenario.py`. **Restart UI** for scenario_api / app.py / insight changes |
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
| New run screen (workbook picker, one merged Tests list, Run plan) | `web/static/js/views/newrun.js`, `wbfilter.js`, `browsers.js` | `test_web_ui.py -k <feature>`, `test_web_multi_ui.py`, `test_web_workbook_search.py`, `test_web_run_order.py` |
| Run plan: Order view (chains, arrows) or Timeline view (workers, estimated durations) | `web/static/js/views/newrun.js` (`orderGroup`/`runOrderView`, `planTimeline`/`timelineView`), `web/run_batch.py` (`last-durations`) | `test_web_run_order.py` |
| Run-in-progress screen, banners, live state (yellow "waiting on purpose" banner, lane waitline) | `web/static/js/views/live.js`, `runstate.js` | `test_web_waiting_banner.py`, `test_web_paused_banner.py`, `test_web_variables.py`, `test_web_ask_user.py`, `test_web_ui.py -k "run_from_click"` |
| Batches (a UI label over several runs: batch id/label, live batch view, `/api/batches`) | `src/regrunner/runmeta.py` (`new_batch_id`), `web/app.py` (`StartRun.batch_id/batch_label`, `RunManager._start`), `web/run_batch.py` (new), `web/static/js/views/live.js` (`batchView`), `runstate.js` (batch helpers), `actions.js` (`openBatch`), `main.js` (`#/batch/:id`) | `test_web_batches.py`, `test_web_multi_ui.py`, `test_web_multi_run.py` |
| Results screen for one finished run (opened from Run, `#/run/:id`) | `web/static/js/views/results.js` (`failedStepCard`/`why` exported for the Results tab's test page to reuse) | `test_web_ui.py -k "failed_run or failed_step"` |
| Results tab (history list, batch page: causes/trend/what-changed/re-run-failed, test page: block map/backups/history, compare) | `web/static/js/views/results/*.js` (new), `src/regrunner/web/results_api.py` (new), `history.py` (`last_n_statuses`, `trend_verdict`), `main.js` (`#/results...` routes), `state.js` (`freshResults`) | `test_web_results.py`, `test_history.py` |
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
  history.py    378+  `regrunner history`: all run folders as one record, what-changed markers, compare, CSV (never values typed/read);
                  `last_n_statuses`/`trend_verdict` (P06): one test's recent pass/fail trend, for the Results tab
  capture/review.py 88  console errors / failed requests collected for review
  engine/
    runner.py      823  orchestration: RunOptions, plan_run/open_run/announce_run, Engine (workers, retries, run_case), execute(_many)
    test_runner.py 460  TestRunner: one test row by row; masking; captcha gate; blank params; stop rules
    actions.py    2048  every Method → Playwright (61 @action handlers, P07's gates/waits/widgets/checks included); JS snippets (VISIBLE_TEXT_JS, CURRENT_VALUE_JS...)
    checks.py      237  plain logic of the P07 steps: numbers on a page, GT/GE/.../BETWEEN, date formats (dd/mm/yyyy), PICK_DATE dates, calendar headings
    gates.py        61  `_rr_fingerprints` reader (ASSERT_PAGE), is_production, SIDE_EFFECTS flag
    session.py     870  BrowserSession: context, pages, frames, ensure_ready, navigation/call watches, WAF block detection
    patience.py    180  waits that end on evidence, not a clock (Patience) + WaitNotice (worker_waiting / worker_resumed events)
    timing.py      216  where a step's time went (site / wait / runner / computer / other; SiteClock, spans), run summary, site-version fingerprint
    resources.py   402  resources.jsonl sampler (CPU, free memory, swap, browsers' memory, loop lag; stdlib, psutil if present), machine_info, runner_version
    settle.py 61 · enabled.py 97 · keys.py 87 · outcome.py 94 · order.py 243 · schedule.py 72 · pool.py 100
    inbox.py 115 · throttle.py 71 · captcha.py 65 · ask.py 118 · failure_capture.py 449 · api_runner.py 343 · diagnostics.py 17
    scenario.py    386  concurrency scenarios (P12): pick (named / lane id / Execute=Y), LaneCase ("<scenario> · <lane>"), adjust_order (lanes never
                        wait for each other), Coordinator (sync points / order markers, ended = reached, time limit = no step by the lanes waited
                        for), run_scenario (every lane at once on one worker, never re-run one by one)
  workbook/
    model.py 812 (Workbook, TestCase, TestRuntime, prepare_row, value_of, plan) · sheet.py 262 · formula.py 770 · textfmt.py 156
    variables.py 339 (VariablePool, environment table, secret_value, {NAME} substitute, IF conditions, flow_map of IF/loops)
    writer.py 1400 (WorkbookEditor: patches only the XML an edit touches; row insert/delete/move rewrite every reference)
    builder.py 1850 (Workbook Builder model: build_model, apply_ops, BuildDocument undo/draft/save/history/diff, BuildStore; CONTRACT.md)
    api.py 617 · api_template.py 113 · api_paths.py 236 (JSONPath with [?(@.k=='v')] filters, stdlib XPath + /@attr, text(), prefixes; paths the builder writes)
    templates.py 274 (P11: the shared template library, templates.xlsx; save_as_template, match_variables, insert_template_ops - all
                  compose existing ops, no new op kind) · refactor.py 151 (P11: find_replace_preview, duplicate_candidates, merge_ops -
                  same: hits/candidates the caller turns into set_cell/update_step ops, never writes a workbook itself)
    scenarios.py 526 (P12: `_rr_scenarios` read/write, blocks as anchors (`Title#2`), `resolve` -> Points (rows), `deadlock`, shared sign-in
                  by key hash, `board` = Workbook.scenarios, `scenario_problems`, `set_scenario`/`delete_scenario` in builder.EXTRA_OPS)
  build/        the Build tab's live browser window (P08; the UI server runs it, never a run): session.py (BuildSession: headed browser + overlay
                on every context, pick -> locator checked with the engine's selectors, word -> {VARIABLE}, replays with TestRunner's own steps,
                BuildAsker for the side-effect pause, stale check; SessionStore: one per workbook, 3 max), api_builder.py (P10: API/XML
                editor view, api_* ops registered in builder.EXTRA_OPS, Send now on the draft, JSON/XML response trees, cURL/Postman/template import), locators.py (candidates id -> test id ->
                attribute -> text -> text in container -> class+position, choose, plain words, words_of_locator), overlay.js (pill, hover outline,
                pick, which-one numbers; closed shadow root; presses swallowed in the window capture phase), recorder.py (P09: Record -> steps at the
                cursor, typed -> {VARIABLE} / {SECRET:NAME}, switch window/frame/Back steps, widget collapse, fingerprint proposals, Check / Save / Wait
                until cards; the overlay proves its calls with the session key)
  selectors/  spec.py resolve.py xpath2css.py migrate.py harvest.py
  reporting/  results.py (data model) html_report.py console.py from_events.py
  web/
    app.py 1081   FastAPI: create_app, RunManager, cli_flags(), routes under /api/...
    presence.py   UiPresence: which UI windows are open (/api/ui/hello, /api/ui/goodbye) for serve --exit-when-closed
    build_api.py  /api/build/* routes (register_build_routes: one line in create_app); later builder phases add their own modules
                  (+ register_session_routes: /api/build/session/{name}/* for the build window, P08)
    record_api.py /api/build/session/{name}/record|check|save|prompt (P09; register_record_routes: one line in register_session_routes)
    build_apitest.py  /api/build/api/* (P10): API test view, Send now, cURL / Postman reading, template list + fields (registered from build_api.py)
    run_batch.py  /api/batches/* routes (register_batch_routes: one line in create_app): groups runs that share a run.json batch_id, and
                  last-run-per-test durations for the Run plan's Timeline view. A batch is only a label - it never changes how a run executes.
    results_api.py  /api/results/* routes (register_results_routes: one line in create_app): batch page (causes, trend, what changed,
                  re-run-failed makes a new labelled batch), test page (block map read fresh from the workbook + backup locators + this
                  test's history), compare. The heavy lifting (build_batch_page, rerun_plan, build_test_page, build_compare) takes plain
                  paths/data, so it is unit-tested without a server (test_web_results.py).
    templates_api.py  /api/build/templates* + /api/build/workbooks/{name}/templates/insert (P11, register_templates_routes: one line in
                  create_app, needs register_build_routes's returned BuildStore so an insert shares the workbook's undo/draft with every
                  other edit)
    scenario_api.py  /api/build/workbooks/{name}/scenarios* (P12, register_scenario_routes: one line in create_app, same shared BuildStore):
                  the board and a scenario's last runs per lane (`scenario_runs`, plain paths); edits are set_scenario ops through /edit
    refactor_api.py  duplicate/find-replace/merge routes (P11, register_refactor_routes: one line in create_app, same shared BuildStore);
                  none of it is a new op kind - find/replace and "what changes?" resolve to set_cell ops, merge to update_step ops
    static/index.html, app.css, js/{main,state,api,actions,runstate,morph,util,fmt,icons,theme,browsers,wbfilter,presence}.js
    static/js/views/{shell,newrun,live,results,modals,scenario_lanes}.js   (scenario_lanes: a scenario's lanes side by side, live and finished, P12)
    static/js/views/build/  the Build tab: {api,actions,state (in ../../state.js),rail,workbook (map + variable map),editor,dialogs,index (header+screen dispatcher),
                  session (P08: build window strip, pick panel, which-one, side-effect dialog; polls /api/build/session/<wb>),
                  record (P09: Rec / Check / Save / Wait until buttons, the check card, the recorder's prompts),
                  api_editor (P10: the editor of an api/xml test, dispatched from editor.js's testEditor),
                  scenario (P12: `#/build/<wb>/scenario/<name>` board: lanes x blocks grid split by sync-line columns, order-marker chips,
                  inspector, last runs; the map's Scenarios cards and the rail's Scenarios list)}.js
    static/js/views/results/  the Results tab: {api,actions,history (rail + landing screen),batch,test,compare,index (header+screen dispatcher)}.js;
                  results.js stays the single finished-run page opened from Run (`#/run/:id`); `#/results...` is the separate browsable tab

tests/
  conftest.py          `site` (session mock server URL), `make_cfg(**{"section.key": v})` (fast timeouts), resets totp state
  site/server.py       mock site (AEM-like pages, WAF/FLAKY switches, recaptcha routes, /policy/purchase/v2 API, OKTA once-only code check,
                       /bin/slow?ms= /bin/hang /bin/forever); *.html pages per scenario (slow, cpu, never_load, okta, alert...)
  workbook_factory.py  build_workbook()/build_flow(): synthetic workbooks with the real 26 columns and formula tricks;
                       build_steps_workbook(): flows written by the test (sheet.add rows) with their own Params
  flow_books.py        book(): tiny workbooks as lists of rows (+ Params rows, loop data sheets, `_rr_environments`) for the flow keywords
  web_fixtures.py      `web` fixture: live UI server on a scratch project whose workbooks point only at the mock site
  test_*.py            86 files; see section 5 (test_benchmark_scaling.py is opt-in: RR_BENCHMARK=1)
```

---

## 5. Tests: what to run

Runner: `.venv/bin/pytest` (Python 3.12 venv; editable install; Chromium + WebKit already downloaded on this Mac).
Cloud sessions (claude.ai/code): `.claude/hooks/session-start.sh` builds `.venv` at start and pins Playwright 1.56.0 to the image's Chromium; WebKit is not available there.

| Scope | Command | Size / time |
|---|---|---|
| One file | `.venv/bin/pytest -q tests/test_page_ready.py` | seconds to ~1 min |
| One test | `.venv/bin/pytest -q tests/test_web_ui.py -k theme` | |
| No-browser subset | `.venv/bin/pytest -q -m "not browser"` | 635 tests, ~6 min (2.5 of them: real workbooks in `test_workbook_roundtrip.py`) |
| Full suite (**only if the user asks**) | `.venv/bin/pytest -q` | 988 tests, 40+ min |

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
Speed, precision and staying out of the way · Selectors · Web UI (Run tab, Build tab, Results tab, API) · Evidence (API tests,
Tests that depend on each other, Values set by the tests, publish, Event stream) · Configuration · Extending · Known limits · Tests

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
P04 (Build tab UI) done: Run · Build · Results tabs in the header; the Build tab (workbook map, variable map, test editor with block strip/cards/
Excel grid/inspector/data drawer/problems panel/add-step menu, and the new-workbook/environments/fingerprint/history/file-changed dialogs) is plain
JS views over the P02 model/ops with no browser session yet (add-step menu's "Record"/"Pick an element" are disabled, wired for P08). "Building with"
(which data row the inspector previews) is client-only until a build session exists to replay against. Simplified vs. the design canvas: tests render
as a responsive card grid rather than a hand-positioned graph with bezier "calls"/"needs" lines; block-to-block drag/reorder is not built (bulk "Move
to block" and "Rename block" use a plain prompt()).
P03 (engine I) done: the run-wide variable pool (`RunCtx.pool`; every name a step saves, any test, read as `{NAME}`), Needs/Provides ordering,
SET_VARIABLE / JSON_READ / IF / loops / CALL_TEST (a called test's steps are reported as the caller's steps after the CALL_TEST step, via
`_CallBus`), `_rr_environments` (required vars refuse the run: `EnvironmentMissing` + `env_missing` event, and HTTP 422 `env_missing` from
`/api/runs`), `{SECRET:NAME}` masked in events/results/reports/network.jsonl/review items. `step_skipped` is now emitted (IF sides not taken).
P05 (Run tab: one list, one plan, batch label, live batch) PR open: the New run screen's per-workbook Tests + Run order cards are now one
merged Tests list (fold/unfold, tag filter across workbooks, "after X" wait chip) and one Run plan card (Order view = the old per-workbook
chains, unchanged markup, now under one `#run-order`; Timeline view = `planTimeline`, a small HLFET-style scheduler sized from
`/api/batches/last-durations`, falling back to step counts with no history). A batch is only a label (`batch_id`/`batch_label` in each run's
`run.json`; `web/run_batch.py` groups them): launching several workbooks together gets one automatically, single runs get none unless they
join one ("Add tests to this batch"). Live batch view (`#/batch/<id>`) opens one websocket per run in the batch and combines their
`runstate.js` states client-side; nothing about how a run executes changed. Not built (out of scope for this phase, left for P06/reviewer
judgement): a manual batch-label input, real drag-and-drop reordering in the Order view (kept the existing arrow buttons instead), and
sidebar grouping of a batch's runs (shell.js is P04's; a run instead shows a "part of batch" chip that links to the batch view).
P06 (Results tab) PR open: a new top-level tab (`#/results...`, own header + rail, wired the `tabs()` "Results" button that
`views/build/actions.js` left unimplemented in P04) separate from Run's own `#/run/:id` finished-run page (`results.js`, untouched apart from exporting
`failedStepCard`/`why` for reuse). History (`#/results`) lists every batch (`/api/batches`) and solo run (`/api/runs`) with a text/environment/
failed-only filter, client-side (no new endpoint). Batch page (`#/results/batch/<id>`, `GET /api/results/batches/<id>`) adds: failures grouped
by cause (`web/results_api.py`'s `cause_of`: CONTRACT's kinds via `history.test_error_kind`/`step_error_kind`, plus two of its own - a page-gate
hard stop, and a step that read a variable nothing had set), "what changed since last time" (`history.markers` filtered to this batch's own
runs), every test with a last-10 trend strip and a new/flaky/fixed/failing/stable verdict (`history.last_n_statuses`/`trend_verdict`, new
helpers). "Re-run failed" (`POST .../rerun-failed`) starts one workbook-picks-only-what-failed run per workbook that had a failure, always
under a **fresh** `batch_id` (even for one workbook, which `RunManager._start` would otherwise leave unbatched) labelled `re-run of batch
<id>`; refuses on a still-running batch, nothing failed, or PROD (send that one to New run for its confirmation instead). Test page
(`#/results/test/<runId>/<testId>`, `GET /api/results/runs/<runId>/tests/<testId>`) reads the block map **fresh from the workbook** with
`workbook/builder.py`'s own `build_model` (not a stored copy: read-only, matches this run's step rows to blocks, colours them pass/fail/warn/
pend) plus any `BACKUP_LOCATORS` a step defines (no suggestions yet - P07 has not built the engine side that probes them on a miss) and this
test's own trend. Compare (`#/results/compare`, `GET /api/results/compare`) is a tests x last-N-runs grid per workbook with the same verdicts
and "what changed" markers. The batch/test/compare builders (`build_batch_page`, `rerun_plan`, `build_test_page`, `build_compare`) take plain
paths/data (no `RunManager`), so they are unit-tested directly (`test_web_results.py`, no server). Not built (left for a reviewer/later phase):
a CSV export button on Compare (`history.export_csv` exists but isn't wired to a download route), a real "probe the backups" card (needs P07),
grouping "skipped because a dependency failed" as its own cause distinct from "needs a value that was never set" (today's engine does not
mark a dependency-skip differently from any other unset-variable failure).

P07 (engine II) PR open: ASSERT_PAGE reads `_rr_fingerprints` (`{DOMAIN}` filled in; URL part AND landmark + text, within the step time, patient while the page loads); a failure sets `StepOut.stop` + `hard`, so Ignore_not_existing_object never swallows it and the test stops (`TestRunner._hard_stop`). SIDE_EFFECTS=Y: blocked on any production environment (the table's `#PRODUCTION` row, or a name PROD/PRODUCTION) and the test stops; `TestRunner(side_effects="ask")` (for P08's build replays; runs never set it) asks through `engine/ask.py` first. A step that compares for itself (CHECK_*, WAIT_UNTIL TEXT) sets `StepOut.check`: Exact_Match/Contains are then not applied, a mismatch is "Comparison Failed" with the reason in the notes. BACKUP_LOCATORS are only probed after a non-optional element miss: result in `detail`, `diagnosis.backup` + first summary line, a clipped screenshot `screenshots/<seq>_r<row>_backup.jpg`, and a `backup_locator_suggestion` event. New events (`page_gate`, `popup_dismissed`, `side_effect_*`, `backup_locator_suggestion`) are documented in `events.py`; like P03's, `runstate.js`/`from_events.py` do not reduce them yet (the step's notes carry the same facts). PICK_DATE / CHOOSE_SUGGESTION are heuristics (data-date / aria-label day cells, "Next month" buttons, role=option lists): unverified on the real sites' widgets.

P08 (build session I) PR open: `src/regrunner/build/`. The Build tab's "Open the site" opens a browser in the **UI server's** process (like the
sign-in window) with `overlay.js` on every context (`add_init_script` + `expose_binding("__rrBuildCall")`): pill (Pick · what it does · Done), hover
outline + plain-words label, pick (presses never reach the site: stopped in the window capture phase, registered before any site script). A pick's
candidates (`locators.candidates`) are checked live with the engine's own `legacy_strategy` selectors; the first that finds exactly that element is the
step's `FindBy`/`FindBy_Value`/`Index`, up to 3 others its `BACKUP_LOCATORS`; `words_of_locator` shows the words of any locator in those forms
(`Step.locator.plainWords`). "Run up to here / this step / next N" replay the **draft** (written to `runs/.build/<stem>/`) with `TestRunner` itself
(`prepare_runtime`/`open_session`/`_execute`/`_next_row`), `side_effects="ask"` + `BuildAsker` (the "Run it for real?" dialog); a replay stops at its
first failed step; edits after the window are re-read without a replay (`_shared`/pool carry over), edits at or above it (or to the data row) raise
the stale banner. Decided: a build window is not a run (no run.json/results.json, not in `/api/runs`, not in `busy()`), coexists with a run of the same
workbook (the run reads the saved file in its own process). Not built (P09): record, check/save this, typed text -> variable, widgets, fingerprints,
auto switch-to-frame steps (a pick inside a frame only says so). Unverified: headed Chrome/Edge on the work computer (tests run headless).
Fixed in passing (P04's editor): a block's `start` is inclusive (CONTRACT 2.4), the cards view hid each block's first step.

P09 (build session II: recorder) merged 2026-09-27: `build/recorder.py` + `overlay.js` + `web/record_api.py` + `views/build/record.js`. **Record** (pill ● Rec,
the strip's Rec, the add-step menu's "Record from here"): the person's own actions (`isTrusted` only; a replay's own clicks are dropped) become steps
after the cursor (the selected step, then each recorded one): CLICK / SET / SELECT / TICK / UNTICK / CLEAR / SPECIALKEY {ENTER} / BACK, never a wait.
A clicked element's locator candidates are **counted in the page as the click happens** (the overlay mirrors `locators.candidates`; the server
recounts anything missing and still chooses with `locators.choose`), because a click that navigates takes the page away. An action in another
window/frame first gets SWITCHTOWINDOW (-1) / SWITCHTOMAINWINDOW / SWITCHTOFRAME (name, else Index) / SWITCHTODEFAULT, and the replay's own
session follows them. Typed text / a choice becomes `{TOKEN}` (label -> UPPER_SNAKE; an existing Params column whose "Building with" value is the
same is reused; a new one is added with the value in every data row); a password becomes `{SECRET:NAME}` + `RR_SECRET_<ENV>_<NAME>` in
`secrets.env` (never another value overwritten: a new name instead) + `_rr_variables` Secret=Y. Prompts (`state.record.prompts`, beside the field
and in the Build tab): keep / fixed / rename (taken back with undo when it is still the last edit, so no unused column stays), keep raw clicks,
save fingerprint + gate (ASSERT_PAGE after the step that navigated), unflag a side effect (a click on Pay/Purchase/... is flagged). Calendar clicks
after a read-only field -> one PICK_DATE; typing then a click on a suggestion -> CHOOSE_SUGGESTION. **Check / Save / Wait until** modes: a pick
gets a card with every CHECK_KINDS entry (disabled with a reason when it does not fit), prefilled from the live element; adding writes OUTPUT /
EXIST / NOT_EXIST / CHECK_* / WAIT_UNTIL (after the recorder's cursor while recording, else after the step picked for). Decided: the overlay's calls
carry a per-session key baked into its source (the binding is taken before any site script runs); without it the page can only say hello, switch
a mode and pick. Fixed in passing (P08): the pill's buttons never worked (a window listener cannot see into a closed shadow root: now
`shadowRoot.elementFromPoint`/`activeElement`). Not built: a typed URL in the address bar (not recorded), a "smart action shortlist" on a plain
Pick (Q9), in-page "Edit" of a proposed fingerprint (the Build tab's prompt card edits it). Unverified: real sites' calendars/suggestion lists.

P10 (API/XML building) merged 2026-09-27: an api/xml test opens `views/build/api_editor.js` (steps · request Form/Paste cURL/Postman/From template ·
response tree). It writes only what the runner reads (API sheet row + shared `InputOutput`, CONTRACT.md 1.6) through `api_*` ops; the new runner
also reads `REQUEST_BODY`, `{NAME}`/`{SECRET:NAME}` in URL/headers/body/paths (row -> pool -> environment table), JSONPath/XPath paths
(`workbook/api_paths.py`, stdlib only: lxml is not installed and not needed), XML (SOAP) templates (Replace, XML-escaped) and four new check kinds.
API tests now take part in Needs/Provides (their output columns go into the pool). Send now (`build/api_builder.send_now`) sends the **draft** with
the engine's own `prepare_body`/`fetch`/`read_response`; a production environment needs `confirmProd: "PROD"`. Not built: "Describe a step"
(Q48), a CSV of responses, recorded traffic (not a source by design). Unverified: real APIs through the work computer's proxy.

P11 (templates, copy/paste, duplicate, find/replace, computed values) PR open: `workbook/templates.py` (new) and `workbook/refactor.py`
(new) are pure op-synthesizers - given a model/editor they return `{templates}`/hits/candidates or lists of ops, never write a workbook
themselves - so neither needed a new op kind and `workbook/builder.py` is untouched by this phase. Templates: one sheet per template in a
shared `templates.xlsx` next to the workbooks (every Params reference written as `{TOKEN}`, since a template is not tied to one workbook's
Params layout); inserting maps each token onto the target's own variables (exact/close-match/create a new column, `match_variables`), and
anything left unmapped becomes `{?TOKEN}` (the `unmapped_template_variable` problem CONTRACT.md 1.2 already defines). Duplicate ("what
changes?", Q26) and workbook-wide find & replace share one mechanism (`find_replace_preview`/`duplicate_candidates`): every sheet
including `_rr_*` (a duplicate's domain lives in `_rr_environments`), never row 1 or a result column or a formula's literal text; the hits
become `set_cell` ops sent to the existing `/edit`. Copy/paste of a step or block needed no Python at all: a `Step`'s fields already are
`insert_step`'s fields, so it is entirely `views/build/actions.js` (a client-side clipboard). File-changed-on-disk (Q29) grew a real
per-step merge alongside the reload/save-anyway P02 already had: `merge_ops` re-reads `diff("disk")` and turns a person's per-row
"theirs"/"mine" pick into `update_step` ops - scoped to `kind: "changed"` hits only (an added/removed row still needs reload or
save-anyway; CONTRACT.md documents the split). Value builder (Q23) writes a real formula string into `Value` via the existing
`update_step`/`set_cell`; the only backend change was two new Excel functions, `CHOOSE` and `TEXTJOIN` (`formula.py`), both real Excel
functions so the workbook still opens correctly in Excel. Two new route modules (`web/templates_api.py`, `web/refactor_api.py`) share
`build_api.py`'s `BuildStore` (a one-line change to `create_app` capturing `register_build_routes`'s return value) so a template insert,
a find/replace or a merge goes through the same undo/draft as every other edit. Not built: deleting a template (`WorkbookEditor` has no
way to remove a sheet yet - a real P01 gap, surfaced as a plain 400 `unsupported` rather than faked); copy/paste of a whole test or
workbook (decomposes into existing ops too, but was left to a later session: `add_test` + repeated `insert_step`/`add_variable`/`set_cell`
from the JS side, same pattern as the template insert).

P12 (concurrency scenarios) PR open: a scenario = rows of the hidden `_rr_scenarios` table (CONTRACT.md 1.4 / 2.9): lanes (a test, or one test
again with its own data row), sync lines ("all wait here", after a named block) and order markers ("A before B"). Blocks, not rows, are the
anchors (rows move when steps are inserted; `Title#2` for a repeated title). A run that names the scenario (or one lane id, as "re-run failed"
does; a plain run includes those with Execute=Y) runs every lane as an ordinary test (`LaneCase`, id `"<scenario> · <lane>"`: own events,
evidence folder, result) - but the pool hands them to **one** worker together (`Schedule` groups), each in its own browser context, so a sync can
never wait for a lane that has no worker. `TestRunner(lane=)` calls `before_step(row)` before each step: it waits there on purpose
(`worker_waiting` code `scenario_sync`, `timing.span("wait","scenario")`). A lane that ends counts as reached everywhere (failure never hangs the
others); a wait gives up after the time limit **with no step started/finished by the lanes waited for** (the lane stops, ERROR). Lanes are never
re-run one by one. Two lanes sharing a TOTP key already get different windows (`totp.reserve_window` is per key); the run and the board say so.
The Run tab lists scenarios (`insight.scenario_entries`, `kind: "scenario"`); `RunManager._validate` expands them too. Not built: arrows between
blocks on the board (order markers are chips on both ends, like P04's cards-not-graph simplification), drag to place a sync line (the inspector's
per-lane "after <block>" selects do it), a scenario section in the HTML report (results.json has `lane` + `syncs`; the report lists lanes as
tests), re-running a whole scenario automatically after a crash. Unverified: two headed lanes on the work computer (one Chrome, two contexts).

P13 (fix-in-builder loop, last-run overlay, docs, full suite) closes out the Workbook Builder plan. **Fix in builder**
(Results test page) now opens the Build tab **on the exact failed step**, not just the test: `jumpToStep` (already used
by the variable map) drives it, and `build/actions.js`'s `openBuild` was fixed to keep a staged `pendingSel` across a
workbook switch (it used to be wiped by `freshBuild()` when the Build tab was on a different, or no, workbook - the bug
that made the old header-only link land on the test but never the step). A step that failed on its last run now shows a
passive **"failed last run" badge** on its card (replacing the plain fail-coloured dot) and an evidence card at the top
of its inspector: the error, a screenshot thumbnail (`builder._last_results` now carries `screenshot`/`screenshotFull`
from that run's `results.json`, CONTRACT.md 2.3), and a link to the full Results test page. README gained `### Run tab`
/ `### Build tab` / `### Results tab` under `## Web UI`, documenting the whole Workbook Builder feature set (map,
editor, recorder, build session, API/XML editor, templates, scenarios, results history/batch/test/compare) that had
never been written up outside `dev/plan/`; the endpoint list grew to match. Full suite run: see the PR body for the
count and any listed failures.

**In progress (2026-09-28): the user's feedback on the Build tab, in batches** (the tally with what was found in the code for each item:
`dev/claude/CONTEXT_builder_feedback.md`). Batch 1 (items 1-8) done: "On which element" on every element step (`Step.element`) with a
typed locator and "Pick on the page"; `#/build/all` workbook list; `GET /api/workbooks/{name}/download`; production wording + ticks in
Environments; a hand-closed build window closes its session; the pill's Done stops recording and the Build tab shows what was recorded
(`Recorder.summary`); "Open the site" opens the `DOMAIN` of the environment, and recording an empty test starts with `OPEN {DOMAIN}`;
the "selected" bar wraps. Next: batch 2 (items 9-17).

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
- Runs that share a pool (a batch, or one that joined) share one worker numbering (`engine/pool.py`: one process, one set of workers), so a
  `test_started` event's `worker` is already unique across every run of the batch - no renumbering needed to lay out the live batch view's
  worker cards.
- `tests/test_web_workbook_search.py::test_enter_picks_the_best_match...` can flake under load: Playwright's `.uncheck(force=True)` races a
  checkbox whose row is removed (filtered out) the instant it unchecks. Confirmed pre-existing (identical on the pre-P04 tree); a solo re-run passes.
- `tests/test_web_multi_run.py::test_a_new_run_joins_the_workers_that_are_going_and_the_same_workbook_cannot_run_twice` can flake in the full
  suite (one `pool_changed` event missed a `run_id` under load): failed once in P13's full-suite run, passed alone and unrelated to anything P13
  touched (same pattern as the other documented timing flakes above).
- Mock pages: an element's `id` is also a `window` global (`id="paid"` makes `window.paid` the element), so name JS counters differently.
- `runner.allow_prod` / `--allow-prod` only guards an environment literally named PROD; one the workbook's `_rr_environments` marks production
  (`#PRODUCTION` row) is not guarded there, but its SIDE_EFFECTS steps are still blocked by the engine (`engine/gates.py`).
- Build window: the overlay lives in a **closed** shadow root on `<rr-build-overlay>` (Playwright's `text=`/CSS engines do not see into it), and
  `window.__rrBuild` is non-enumerable; the picked element is `window.__rrBuild.picked()` (never a DOM attribute). Evaluating in a page with a JS
  dialog open hangs: `BuildSession.broadcast`/`_page` check `pending_dialog` first. `build.headless: true` is for tests only.
  A listener outside a closed shadow root never sees the nodes inside it (`composedPath()` stops at the host): the overlay finds what was pressed
  with `shadowRoot.elementFromPoint` and what is typed into with `shadowRoot.activeElement`.
- Recorder: a new variable may not equal a whole cell of its own step (a Params header replaces an equal cell at run time, the legacy rule), so a
  field whose id is `plan` gets `{PLAN_VALUE}`, not `{PLAN}`. Playwright's `select_option`/`dispatchEvent` fire untrusted events (never recorded):
  tests drive selects with the keyboard.
- `InputOutput` rows are shared by every API sheet and keyed by path/header/placeholder (`read_input_output` builds dicts): never add a second
  row for the same key with another column (it takes the key away from the other sheets); reuse the existing row's column (`api_builder`).
- A secret header's value typed straight into a sheet (legacy `DT_apiKey`) is shown as `••••••` by the API editor; the builder writes
  `{SECRET:NAME}` for new ones so the value lives in secrets.env.
- Scenario lanes share one worker's browser (a context each) and one worker number: the live view's worker cards show both lanes on the same W.
  A lane id contains " · " (never "/": ids travel in URL paths); `select_cases` alone does not know scenarios - call `engine/scenario.pick` first.
- Build window: the browser keeps running with no window when the person closes the last one (no "disconnected"); `BuildSession` watches
  every page's `close` and closes itself when none is left `WINDOWLESS_GRACE_S` later. Anything that closes and reopens windows on purpose
  (start/switch) sets `_opening`; a replay runs with status `running`, which the check skips.
- `#/build/all` is matched before `#/build/<workbook>` in `main.js` (workbook names always end in `.xlsx`, so `all` never clashes).
- `headerShell`'s `middle` slot (`views/shell.js`) is a shrinkable flex-1 area with `overflow:hidden`: keep its content short/non-wrapping so a
  narrow window clips it instead of pushing the header wider than the viewport (see the `Run` tab's version tag vs. the `Build` tab's breadcrumb).

---

## 10. Keeping this file useful

Update this file in the same change when you: add/rename a module or test file (sections 3-4), add a config section or rule (1, 4),
finish or start a multi-session piece of work (9), or learn a gotcha the next agent would otherwise rediscover (9).
Keep entries one line; details belong in README (users) or code docstrings (developers).
