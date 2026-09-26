# Context: make test results independent of worker count and machine speed

You are picking up a Python + Playwright regression runner (`regrunner`). This file is everything you need to start. Read it fully, then read the code it points to before changing anything.

## The project in one paragraph

`/Users/raphaeldelossantos/Documents/qa-regression` replaces a legacy Windows/Excel Selenium runner. Test cases live in Excel workbooks (`workbooks/*.xlsx`: one sheet per flow, one row per step, keyword columns such as `Method`, `FindBy_Value`, `Value`, `Output_Value`). The runner (`src/regrunner/`, installed editable in `.venv`) reads a workbook, runs each test in its own isolated Playwright browser context, several tests at once (`runner.workers`), and writes a run folder (`runs/<id>/`: `results.json`, `events.jsonl`, `runner.log`, screenshots, `network.jsonl`, `report.html`). A web UI (`regrunner serve`, FastAPI + vanilla JS in `src/regrunner/web/`) starts runs and shows them live; non-technical QA people use it. `README.md` documents the behaviour in detail. Config is `config.yaml`.

Key code: `engine/runner.py` (run loop, workers, retries), `engine/test_runner.py` (one test, step loop), `engine/actions.py` (one function per keyword), `engine/session.py` (browser session, page-ready gates), `engine/settle.py`, `engine/throttle.py`, `engine/outcome.py` (pass/fail rules), `engine/ask.py` (a step that waits for a person; emits events), `events.py` (event bus), `totp.py`, `config.py`, `reporting/`, `web/app.py`, `web/static/js/{runstate.js,views/live.js,views/results.js}`.

## The goal

**The same test must give the same verdict whether 1 worker or 10 run, and whatever the machine's RAM/CPU.** Time is not a constraint: a test may take 1 minute or 10 hours, but it must be accurate. Be as fast as possible *within* that. Today, results differ between a 1-worker run and a 5-worker run of the same workbook (green alone, sometimes red in parallel).

Two changes are wanted (A and B below), plus a UI change (C).

## What already exists (do not rebuild; extend)

- **One code, one login (`totp.py`, `GET_GOOGLE_TOKEN` in `engine/actions.py`, `tests/test_totp_reuse.py`).** Okta accepts a one-time code once. Every test in these workbooks logs in with the same user and the same authenticator secret. `reserve_window()` hands each login the next unused 30 s window and the action sleeps until it starts; state is in-process plus `.auth/totp_last.json` (a hash of the key, never the key). Origin: run `runs/20260925-010447-PROD` (2 tests at once): Purchase#2 and #1 entered their code at 01:05:02 and 01:05:06 (same window), Okta refused the second ("Each code can only be used once"), and 22 later steps failed "Object was not found". This was fixed at 01:29 the same day. The user's work computer may still run older source: check before assuming the fix is live there.
- **Page-ready and settle gates** (`session.ensure_ready`, `settle_after_input`, `click_and_verify`, typed-field checks, navigation watch). They wait on conditions, not sleeps, but most have a fixed upper cap (list in A).
- **Captcha and WAF handling** (`engine/captcha.py`, `engine/throttle.py`, `run_paused` event, per-site throttle). **Out of scope. Treat captcha and WAF as resolved**: they do not work on this development machine but are resolved in the real environment. Do not touch, extend or test around them. Do not add user-agent or IP rotation.

## A. Patient waiting: a slow machine must never cause a failure

**Problem.** Fixed time limits turn "slow" into "failed". On a busy machine (10 browsers, low OS priority, little RAM) pages load slower than the limits allow, and a step then fails or acts on a half-loaded page. Limits to review (defaults in `config.py`, `config.yaml`):

| Limit | Default | Where used |
|---|---|---|
| `timeouts.element_s` / `optional_s` | 10 s / 3 s | `actions.py` (`act_timeout_s`, `find_timeout_s`), `session.py` (frames, `set_default_timeout`) |
| `timeouts.navigation_s` | 60 s | `session.py` |
| `waits.ready_max_s` | 6 s | `session.ensure_ready` (first action on a fresh page) |
| `waits.input_settle_max_s` | 15 s | `session.settle_after_input` |
| `output.match_timeout_s` | 8 s | `actions.py` Output with Exact_Match/Contains |
| `runner.step_hard_cap_s` / `test_timeout_s` | 180 s / 1800 s | `test_runner.py`, `runner.py` |
| `runner.stop_after_failed_steps` | 5 | `test_runner.py`: a test stops after 5 element-steps in a row fail |

**Wanted behaviour.**
1. A wait ends by **evidence, not by a clock**: while the page is making progress (requests starting or finishing, a navigation, frames loading, DOM changes) the deadline keeps extending. Fail only when nothing has progressed for a long, configurable stall period. Default it generously (minutes); the user accepts hours.
2. An element that is **absent while the page is quiet** is still a real failure and must still fail in bounded time (a page in the wrong state must not wait forever; the existing `optional_mode: quiet` idea). Slow is not the same as wrong.
3. Keep a very generous absolute backstop so a truly hung test cannot block a run forever; it must be progress-based first.
4. `stop_after_failed_steps` must not trip because of slowness alone (it should count steps that failed on a *settled* page).
5. **Infrastructure outcomes are not verdicts.** Add a third outcome ("not run": browser or context crashed / out of memory / disconnected, Playwright driver died, target closed unexpectedly). Such a test is re-run whole from the start (bounded count, e.g. `runner.infra_retries`), every attempt recorded (see how `attempts[]` records blocked/captcha attempts in `runner.run_case`). It is never counted as passed or failed; reports, `summary.txt` (`publish.py`), console and UI show it separately. Classify only when the cause is provably infrastructure. A step that fails because the page is not as expected is a real failure.

**Hard rule from the user: never retry, re-type or re-click a step.** It would hide real site bugs (false passes). Waiting longer is allowed; repeating an action is not. Whole-test re-runs are allowed only for infrastructure outcomes.

## B. Shared account: queue what cannot run in parallel

The tests share one login (same user, same secret, same IP). The TOTP part exists (above). Remaining work:
1. **Verify it under load.** Add a mock login page that accepts each code once and run 5-10 workers against it (see `tests/test_totp_reuse.py`, `tests/site/`).
2. **Reserve-to-verify gap.** The window is reserved at `GET_GOOGLE_TOKEN`, but Okta checks the code when a *later* step clicks Verify. On a slow machine that gap grows and the code can expire before it is checked (`EXPIRY_MARGIN_S = 4` only covers the start). Measure the gap, and make sure a slow gap cannot produce a stale code (e.g. reserve as late as possible, or lengthen the safe margin from the observed gap). Do not guess: instrument it first.
3. **Other TOTP entry points** (`ASK_USER` codes, API tests): confirm none can take a used window.
4. **Two computers with the same secret cannot be coordinated** by a local file. Say so in the README; do not pretend otherwise.
5. Do not assume other per-account limits (single session per user, login rate limits). They are unverified. If evidence shows one, add a generic named gate (per account) rather than special cases. Auth-provider responses are not in `network.jsonl` (first-party calls only): consider recording auth-domain 4xx bodies (never secrets) so the next collision is diagnosable from the run folder.

## C. UI: yellow warning whenever a worker is waiting, and why

Whenever the runner *deliberately* waits (the TOTP wait; anything A or B adds: waiting on a slow page past the old cap, an infrastructure re-run starting), the run screen must show a **yellow warning** saying which test/worker is waiting, **why in plain language for a non-technical person**, and, when known, a countdown. It disappears when the wait ends. Several waits at once: list them.

- Today the TOTP wait is silent: `get_google_token` sleeps and only afterwards appends a step note. The event must be emitted **before** the sleep. Actions have no event bus; `ctx.asker` (`engine/ask.py`) emits events, so use that route or add a small one.
- Precedents to copy: the `run_paused` event, its reducer in `web/static/js/runstate.js`, the `banner('warn', ...)` in `web/static/js/views/live.js`, its test `tests/test_web_paused_banner.py`, and `events.py` / `reporting/from_events.py` (the UI replays the whole event stream from the start after a reload, so new events must be replayable and rebuild correctly).
- Suggested events: `worker_waiting {test, worker, seconds|until, code, message}` and `worker_resumed {test, worker}`. Message example: "Waiting 21 s for the next login code: another test just used this account's current code and the site accepts each code once." Never put a secret or a code in it.
- Use the existing `warn` banner style and check it actually reads yellow/amber and is legible in light and dark themes.
- Also record the wait on the test's step (existing `notes`) so the report shows it afterwards.

## Working rules (from the user; follow them)

- **Accuracy over speed. No OS-level keyboard/mouse anywhere** (guarded by `tests/test_keys_events_config.py`).
- **Never run against real QA/UAT/PROD hosts** (a live run once completed a real UAT purchase). Verify only on the local mock site (`tests/site/server.py`, `tests/web_fixtures.py`, `tests/workbook_factory.py`). Real runs happen on the user's other (Windows, Python 3.9, no 2FA) computer; run folders are copied here to analyse. If real evidence is needed, change the engine to record it and ask the user to re-run there.
- **Never echo secrets** (passwords, authenticator secrets, codes) in events, notes, reports or logs: reports are shared with a QA team.
- **Python 3.9 must keep working** (`requires-python >= 3.9`). Create asyncio primitives inside coroutines only (`tests/test_py39_compat.py` guards it).
- **Run only the tests relevant to your change** (new test files, plus the areas touched: e.g. `test_totp_reuse.py`, `test_page_ready.py`, `test_typed_fields.py`, `test_progress_and_parked_worker.py`, `test_web_paused_banner.py`, `test_keys_events_config.py`, `test_py39_compat.py`). The full suite is ~500 browser tests and ~40 minutes: run it only if the user asks. Say which tests you ran. Browser tests are marked `browser` and use `.venv/bin/pytest`.
- Engine code runs in a subprocess per run (fresh every run). **Changes to server code (`web/app.py` and what it imports) need the user to restart the UI**; JS/CSS are served fresh. Say so when it applies. The user must also copy changed files to the work computer.
- Match the surrounding code's style, comment density and naming.

## Proof that it works (acceptance)

1. On the mock site, the same workbook produces **identical verdicts and step results at 1 worker and at N workers**, including with injected latency (a mock page that answers after 25-60 s must PASS, where the old limits would fail).
2. A page that never finishes, or an element that is genuinely absent on a quiet page, still fails, in bounded time, with a clear reason.
3. A simulated browser crash produces "not run" and a whole-test re-run, not a failure.
4. Two or more tests logging in with one secret against the mock once-only-code login all pass, with visible waits.
5. A UI test shows the yellow warning during a wait (with the reason and countdown), and that it clears afterwards, also after a page reload mid-wait.

## Unverified (say so in your report; do not assume)

- Whether the real Okta/portal has other per-account concurrency limits.
- Whether long waits behave the same on the real sites (only the mock site is testable here).
- Whether the user's work computer has the 2026-09-25 `totp.py` fix.
