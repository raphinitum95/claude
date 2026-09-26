> **AI agents: start with [AGENTS.md](AGENTS.md)** (project map, where to change what, which tests to run). This README is the user manual.

# regrunner

A Playwright-based runner for the existing keyword-driven Excel regression workbooks (the ones the old
Selenium/Excel-COM framework ran). **The workbooks are not modified and keep working**; what changes is
the engine underneath: headless, concurrent, adaptive waits, generic locators, screenshots after every
step, and an HTML/PDF evidence report.

```
workbooks/*.xlsx ──► loader + formula engine ──► step engine (Playwright) ──► events ──► console │ web UI │ JSONL
                                                        │                                        │
                                                 selectors.yaml                            runs/<id>/  (screenshots, results.json, report.html/pdf)
```

## Quick start

**No terminal needed:** double-click `Start QA Regression.command` (macOS) or `Start QA Regression.bat` (Windows). A
browser tab opens with the UI (see *Web UI* below): pick a workbook, tick the tests, press Run. Everything the
command line can do is a control there, and the command it is equivalent to is shown next to the Run button.

**From a terminal:**

```bash
cd /Users/raphaeldelossantos/Documents/qa-regression
source .venv/bin/activate            # already created; `pip install -e ".[dev]"` recreates it
regrunner doctor                     # checks the browser, config, secrets
regrunner list "UAT_AEM_Travelex Regression_v9.1.xlsx"
regrunner run  "UAT_AEM_Travelex Regression_v9.1.xlsx" --tests CW       # one test
regrunner run  "UAT_AEM_Travelex Regression_v9.1.xlsx"                  # the tests flagged Y in DataSheets
regrunner run  "UAT_AEM_Travelex Regression_v9.1.xlsx" --tests CW,Travelkore --env QA --workers 2 --pdf
regrunner run  A.xlsx --tests CW  B.xlsx --all --workers 4              # two workbooks at once: one run each, four shared workers (see below)
regrunner serve --open               # the web UI on http://127.0.0.1:8765, opened in your browser
```

Console output while running:

```
CW: step 15/151 passed (9%) | overall 4%
Travelkore: step 40/268 passed (14%) | overall 12%
```

Exit code: `0` passed, `1` a test failed or errored, `2` bad selection, `130` cancelled.

**Several workbooks at once.** Name more than one workbook and each becomes a run of its own (its own `runs/<id>/` folder, events, results and report)
on **one set of workers**. A workbook's own options follow it (`--tests`, `--tag`, `--all`, `--chain`, `--no-chains`); everything else (`--env`,
`--workers`, `--browser`, `--screenshots`, ...) is shared by all of them, wherever you put it:

```bash
regrunner run "Travelex.xlsx" --tests CW,Travelkore --chain CW,Travelkore   "Qantas.xlsx" --all   --env UAT --workers 4
```

A free worker goes to the workbook that has the fewest tests going (they take turns; a workbook whose tests are waiting for one another, or that is
finished, leaves its share to the others), so 4 workers over 2 workbooks is 2 + 2 until one runs out. The page-load spacing, the cool-down after a
WAF block and the "one worker fewer" that follows it are kept **per site** (the host the workbook opens; workbooks on the same host share them): a block by one
site's WAF slows only the runs on that site, and the workers it cannot use go to the other runs. Output lines are prefixed with the workbook name; the exit code is `0` only
when every run passed.

## Set up (once, by whoever maintains this)

```bash
python3 -m venv .venv                      # Windows: py -m venv .venv
.venv/bin/python -m pip install --upgrade pip    # Windows: .venv\Scripts\python -m pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\pip install -e ".[dev]"   (use "." instead of ".[dev]" if you won't run the tests)
.venv/bin/playwright install chromium
.venv/bin/regrunner doctor                 # or open the UI: the Preflight card shows the same checks
```

**If `playwright install chromium` is blocked** (locked-down network), skip it: with no browser named in `config.yaml`, the runner
uses the Chrome or Edge that is already installed (the Chromium download is only used when it is there), and the New run screen
only offers Chromium when it has been downloaded. Everything else works the same, including the sign-in window and PDF reports;
`regrunner doctor` and the Preflight card say which browser is used. To pin one, pick it under **Browser** on the New run
screen, or set it in `config.yaml` (`browser:` → `name: chrome`, or `name: msedge` for Edge; the older `channel: chrome`
spelling still works).

## Which browser a run uses

Chrome, Edge, Safari and Chromium can all be chosen, and every run records which one it used.

| Where | How |
|---|---|
| Web UI | **Run settings → Browser**: *Chrome · Edge · Safari · Chromium*. One that is not on this computer is greyed out and says why (and, for Safari, the command that fixes it). |
| Terminal | `regrunner run … --browser chrome\|msedge\|safari\|chromium` |
| Default for everyone | `config.yaml` → `browser:` → `name: chrome`. Nothing set = the Chromium Playwright downloaded, and on a computer that has none, the installed Chrome, else Edge. A browser you name or pick is never swapped for another: if it cannot start, the run says so |

The browser is chosen **per run** (all tests of a run use the same one) and is shown wherever the run is: a chip on the New run screen
next to the Run button, on the run screen while it runs, on the results screen, in the run list, at the top of `report.html`
(name, version, headless/headed, and the exact user-agent under *Run settings*), in the terminal's first line and in the shared
`summary.txt`. A run whose browser was not recorded (made before this existed) says so instead of guessing a version.

**About Safari.** Playwright cannot drive the Safari application. What it can run is **WebKit, the engine Safari is built on**, in its
own build. So *Safari* here means "Safari's engine", and it is labelled **Safari (WebKit 26.x)** everywhere, never plain "Safari":
a page that behaves differently in the real Safari app (its own privacy settings, extensions, a newer or older WebKit) can still behave
differently from this. It is still the right check for "does the site work on Safari's engine". To turn it on, download it once:

```bash
.venv/bin/python -m playwright install webkit      # Windows: .venv\Scripts\python -m playwright install webkit
```

(It is a separate download from the same place as Chromium, so it needs the same network access.) Two jobs are always done by a
Chromium-based browser even in a Safari run, because WebKit cannot do them: the **Sign in…** window (a WebKit window has no address bar)
and the **PDF** export. The tests themselves, including the window opened to solve a captcha, use the browser you chose.

Python 3.9 or newer is required (the copy that ships with macOS is 3.9.6 and works; the full test suite passes on it).
Build `.venv` on the machine that will use it; never copy one between computers. Do the `--upgrade pip` step first:
an older pip (the one bundled with some Python 3.10 installs) stops with *"setup.py or setup.cfg not found … editable
mode currently requires a setuptools-based build"* because it cannot install a `pyproject.toml`-only project in editable mode.

## Before the first real run

| Step | Command / action |
|---|---|
| Captcha bypass cookie | Copy `secrets.env.example` → `secrets.env` and fill `RECAPTCHA_BYPASS_TOKEN_QA/UAT/PROD`. The cookie is named `recaptchaBypassToken` (`config.yaml → captcha_bypass`) and is set on **every** test, whatever the workbook says (the "w/ captcha" note in `DataSheets` is informational only). Without a value the run still starts and flags it; a captcha that then appears stops the test and, from the UI, opens a window for you to solve it (see *Captchas*). Editing `secrets.env` takes effect on the next run, no restart. |
| Zscaler / Okta SSO | In the UI: Preflight → **Sign in…** (or `regrunner auth login --url <UAT url>`). **One** visible browser opens; you sign in yourself, then press *I'm signed in, save*. The session is saved to `.auth/state.json` (owner-only) and reused by every headless test. (MFA-only logins are not automated.) |
| First test | **Every run of the real workbook is a live transaction** (purchases, confirmation emails). `CW` worked without a token or SSO session. `--env PROD` is refused unless `--allow-prod`. |
| Learn stable selectors | Add `--harvest`, then `regrunner selectors apply <run-id>` (see *Selectors*). |

## How the workbook is interpreted (verified against the legacy source)

* **A test = an action sheet + one enabled parameter row.** `DataSheets` picks the sheets (`blnExecute` Y/N) and
  their `Params_N` sheet. An optional `Tags` column in `DataSheets` (or `tags:` in `config.yaml`) enables `--tag`.
* **Rows run in order.** For each row, every cell (except `Status/Error_Check/Output_Value/times`) whose text
  equals a Params column header is replaced by that value; formulas that reference the cell see the new value.
  `blnExecute` may be `Y`/`N`, a formula, or a *flag column name* that must be `Y` in the Params row.
* **Formulas are evaluated by regrunner** (`workbook/formula.py`), not by Excel and not from Excel's cache, so
  `TODAY()`, `RANDBETWEEN()` and `IFS(Global!B2=…)` are always current. It is verified against Excel's own
  saved results for every deterministic formula in the real workbook (`tests/test_formula.py`).
  Volatile values are frozen per test (Excel re-rolled them on every recalculation); `--seed` makes them reproducible.
  Functions understood: string/logic/date basics (`IF IFS AND OR NOT IFERROR TEXT DATE TODAY NOW LEFT/MID/RIGHT SUBSTITUTE …`), `SUM/MIN/MAX/ROUND/COUNTA`,
  `VLOOKUP` (URLs picked from an environment table) and `NUMBERVALUE` (price text → number for the points calculations); `TEXT` pads (`"000"`).
  A function it does not know (`OFFSET`, external-workbook links `[3]Sheet!A1`, …) gives `#NAME?`; `lint` reports it as an error, and a step
  whose *Value* or *FindBy_Value* is `#NAME?` fails with the reason instead of acting on the text "#NAME?". (`OFFSET` in `Step_Number` is harmless:
  step numbers are not evaluated.)
* **A step whose `blnExecute` cell is empty does not run** (only Y / 1 / Yes / True does; the legacy runner did the same), and nothing says so: it simply
  is not in the report. So that this cannot hide a forgotten login step, a **failed step is annotated with the nearby rows that were skipped for an empty
  cell** ("Not run, just above this step: rows 8-10 - Get Okta PW (get_google_token); Google PW (Set); Click Verify (Click) - because blnExecute (column A) is
  empty. If they should run, put Y there."). An explicit `N` is a decision and is not reported.
* **Results are written back into the sheet state**, so `=S49` ("what step 49 captured") and
  `=IF($D$13="PASSED",…)` work, and an `Output_Value` that names a Params column stores the value there.
* **Pass/fail** (`engine/outcome.py`): any error fails a step *unless* `Ignore_not_existing_object=Y` (which swallows
  every error). `Exact_Match=Y` means text equals expected exactly; with neither `Exact_Match` nor `Contains` the
  value is only *captured*, not compared (`regrunner lint` counts these). A failed step never stops the test unless
  `Global!QuitBreakOnFailure=Y`.

### Actions

All 23 actions in your workbook are implemented (55 names/aliases: `Open Quit Wait Set Write Type SendKeys Click js_click
Exist Output Select Tick MoveToElement Mouse_Scroll SwitchToFrame/Default/Window/MainWindow Back Screenshot
Get_Current_URL …`), plus the rest of the legacy web vocabulary (`Refresh Navigate Alert_* ExecuteScript Clear DoubleClick …`).
`GET_GOOGLE_TOKEN` (Okta / Google Authenticator code): *Value* is the base32 secret, the six-digit code becomes the step's *Output_Value*
(a later `Set` with `=S<row>` types it; the code is masked in reports and events, like a password).
**A code is handed out once per secret and 30 s window**: Okta accepts a code once, so when two tests log in with the same authenticator secret (or a run is started a
few seconds after another) the second one waits for the next window (up to ~30 s each) instead of being refused with "Each code can only be used once". A different
account never waits. What was handed out is remembered in `.auth/totp_last.json` as a hash of the key (never the key itself). The wait is shown on the run screen
**before** it starts (yellow *waiting* banner with a countdown) and noted on the step.
**A code is only handed out with enough time left to reach the Verify click.** Okta checks the code when a *later* step clicks Verify, and on a busy computer the
steps in between take longer. So the runner measures, for every login, how long it took from handing the code out to the click / Enter that submitted it (noted on that
step: *"submitted 3.2 s after it was generated, 18.1 s before it expired"*; one that arrived too late is flagged under *Things to review*). The next code is handed
out only if more than the slowest recent gap + 3 s of its 30 s is left (at least 4 s, at most 25 s; 10 s until this computer has measured anything), else the
runner waits for the next window. The measurements are kept (per secret, as a hash) in `.auth/totp_last.json`.
**Two computers using the same secret at the same time are not coordinated**: the record is a file on each computer, so a run on your work computer and one here can
still be handed the same code. Run logins for one account from one computer at a time. (A code a *person* types in - `ASK_USER`, or `GET_GOOGLE_TOKEN` with no key -
cannot be coordinated either: the question tells them to wait for the next code if another test just used the one on screen.)
Sign-in services' refusals are kept for the record: a 4xx answer from an Okta / OAuth / SSO address (`waits.auth_url_patterns`) is written to the test's
`network.jsonl` with its body (codes and secret-looking values masked), so the next *"Each code can only be used once"* is explainable from the run folder.
Keep the secret out of the workbook if you like: leave the Params cell blank and set `RR_VAR_DT_KEY=…` in `secrets.env`. With **no usable key** (empty cell, or
the `DT_Key` token still unreplaced) and a person to ask, the step **asks for the code** instead of failing (see `ASK_USER` below).

**`ASK_USER`** (aliases `PROMPT`, `ASK`) stops the run and asks a person, then carries on. How the Excel row says where the answer goes:

| Column | Meaning |
|---|---|
| `Method` | `ASK_USER` |
| `Value` | the question shown to the person (empty = the Step_Name is used) |
| `FindBy` / `FindBy_Value` / `Index` | **optional**. Filled in: the answer is typed into that field right away, like a `Set` (the field is found *before* anyone is asked, so a missing field is reported without wasting the person's time). Empty: the answer only goes to `Output_Value` |
| `Output_Property` | empty = plain text; `SECRET` = hidden while typed, and never shown or stored |
| `Timeout` | seconds to wait for the answer (default `ask.timeout_s`, 300); then the step fails |
| result `Output_Value` (column S) | always receives the answer, so a later row can use it: `Value` of a `Set` = `=S<row of the ask>` |

Two ways to write it: **one row** (`ASK_USER` + `FindBy_Value` of the field: "ask and enter here"), or **two rows** (`ASK_USER` with no locator, then a `Set` on the
field with `Value` `=S<that row>`, which also lets you type it into several fields or use it in a URL). Where the question appears: on the **run screen** for a run started
from the web UI (a box with *Send answer*, Enter works, the browser tab title shows "● Input needed", and the New run screen warns before you start), or **at the terminal**
for `regrunner run ...` (`--ask terminal|ui|off`; the default is the terminal when there is one, else nobody, and then the step fails at once instead of hanging).
Other tests keep running while one waits; the step's time limit does not apply to the wait. What is typed as a `SECRET` is masked in the report, the events, the console and
the shared copy (including the later `Set` that types it), travels through a file that is deleted as soon as it is read, and is never in an event. `lint` lists these steps.
Actions that only make sense for the old Windows/Excel stack (`DB_*`, `SEND_EMAIL`, `FILE_COMPARE`, `SET_VARIABLE`,
`SNAGIT_SCREENSHOT`, `PDF/WORD/OUTLOOK/SERVICE` pages …) fail with a clear message.

Behaviour worth knowing:

* `Set` clears then types; `Write`/`Type` append. Typing uses real key events (like Selenium `send_keys`).
* `SendKeys` was *operating-system keystrokes* in the old runner. Now it is delivered to the page through Playwright,
  so the user's keyboard is never used. `^-`/`^{+}` (browser zoom) are ignored in headless; named screenshots are full-page.
* `js_click` clicks through overlays like before, but **waits for a disabled control to become enabled** instead of
  silently doing nothing, and **only clicks what a person could see**: an element that is `display:none`, `visibility:hidden` or has no size
  fails the step ("Element is not visible, so a person could not click it") instead of being clicked behind the scenes. (A styled radio button /
  checkbox whose native `<input>` is hidden counts when its `<label>` is shown - that is what a person clicks. An optional row,
  `Ignore_not_existing_object=Y`, stays optional.)
* **A step that names an empty parameter does not type the parameter's name.** When `Value`, `FindBy_Value` or `Expected_Value` is the name of a
  Params column whose cell is empty (and no earlier step of that test filled it in - a step whose `Output_Value` names the column does), the old runner
  left the name in place and typed it (`DT_Policy_Out` into the policy number field) and reported a pass. Now the step **fails** with the cell to fill
  (`Parameter DT_Policy_Out is empty: its cell AgentPortal_Params!R3 has no value ... Purchase fills it in when it runs`), even on a row with
  `Ignore_not_existing_object=Y`. Started from the web UI or a terminal, the run **asks you for the value** instead (used for this run only, the
  workbook is not changed). `regrunner lint` and the new-run screen warn about it before the run. Values one test writes are visible to tests that start
  after it *for the same Params row*, and the runner starts them in the right order: see *Tests that depend on each other*.
* **`Output_Property = value`** returns what a field holds *right now*, one property for every kind of field: a text field or textarea gives what is in it;
  a `<select>` gives the visible text of the selected option (several: joined with `;`); a radio button gives the value of the checked button of its group
  (point it at any button of the group; empty when none is checked); a check box gives `true` / `false`. Use it to check what was *selected*: an `Output` /
  `innertext` on an `<option>` reads its label, which is the same whether or not it is selected (`regrunner lint` warns, and the step says so in its notes).
  `Output_Property = attribute` (name in `Value`) follows Selenium's `getAttribute`: the live property when the element has one (what was typed into a field, `checked`,
  a link's full `href`), else the HTML attribute. The 16 `attribute` / `value` rows of `ViewPolicy` read a textarea this way.
* **`SwitchToWindow -1` fails when no popup opened.** After waiting `waits.window_grace_s` (3 s) for the window the step before it should have
  opened, one window is not "a new window": the step fails with "No new window opened" (the old runner "switched" to the window it was already in
  and the steps after it ran against the wrong page).
* **A test with no browser window left stops** at the first step that needs one, with the reason (`step N "Close window" closed the last one`),
  instead of running the rest of the sheet against nothing. Closing the last window at the very end (`Close`, `Wait`, `Quit`) is fine.
* **A click on a radio button / checkbox (or its label) is checked to have worked.** It must show the new state within 1 s and
  keep it for ~0.4 s. The click is **never repeated**: if the page ignores or undoes it, the step fails and says so. (The old
  runner reported a pass with nothing selected.)
* **A click is not held up by `aria-disabled="true"`, like the old Selenium driver.** Playwright calls a link, button or field "not enabled" when
  it, or anything around it, says `aria-disabled="true"`, and waits for it to become enabled; Selenium never looked at that attribute. The agent
  portal writes it around a block of links people click every day (`Click Australia` waited its 30 s and failed). `Click`, `DoubleClick`,
  `ContextClick`, `Tick`, `Untick` and `Click_SendKeys` now go through it: the element is hovered first (which checks it is **visible, standing
  still and not covered** - everything a click checks except "enabled"), then clicked, and the step notes which element said
  `aria-disabled` (*"…has aria-disabled="true": … Clicked anyway after checking…"*). A control that really is `disabled` (the attribute, or a
  disabled fieldset) is still waited for and fails as before. `behaviour.click_ignores_aria_disabled: false` restores Playwright's behaviour.
* **Page loads are followed, like the old Selenium driver did.** The runner watches the browser's own navigation events, so a
  page load that has started is finished before the next step touches the page, whatever caused it (a link, a submit, a
  script-triggered reload). After a click on something that can load a page (a link, button or submit; not a radio,
  checkbox or plain element) it watches for `waits.nav_grace_ms` (400 ms) because a JS click returns before the load
  starts; if one starts, the click step waits for it and ends on the new page (noted on the step, and its screenshot
  shows the new page). Then a freshly loaded document is given time to start up: `complete`, and no requests or DOM
  changes for `waits.ready_quiet_ms` (1 s), at most `waits.ready_max_s` (6 s, `0` = switch all of this off); a page that
  never settles is noted under *Things to review* and the run carries on. Cost: ~0.4 s per click on a button/link, ~1 s
  per new page. (This is what fixed a consent button that reloads the page: the next step used to click the dying page.)
* **Set / Write / Type click into the field first, like a person.** Sites rely on it: Owner_CRVD's zip field only loses its red
  error message on a *click* (the site's `text-validation` script), and its zip check skips a field that still shows an error - so
  typing a corrected zip without clicking never re-validated it, and Submit stayed blocked. The runner dispatches the events of a
  click (mousedown, mouseup, click) on the field - not a mouse click at its coordinates, which an open date picker can cover -
  and the mousedown also closes an open jQuery UI date picker, as a person's click would. `behaviour.click_before_typing: false`
  switches it off.
* **Every test writes `tests/<id>/network.jsonl`**: the site's own XHR/fetch calls (path and query with secret-looking values
  hidden, status, milliseconds, the step that was running, whether it counts as a servlet call). Use it to answer "did the page call
  the server, and what did it say?" - e.g. the zip check answering 500 for an invalid zip and 200 for a valid one.
* **A WAF that answers 403 / 429 is handled, not mistaken for a broken test.** A refused call is a different thing from the
  application saying no (this site answers an *invalid* zip with 500). When a click's own servlet call (or the page load it
  caused), or the call an input started, is answered 403 or 429 (`runner.block_statuses`), the step **fails with the reason**
  ("Blocked by the site: HTTP 403 to the POST /bin/...") instead of passing on a click that did nothing, and the test stops
  there. The run then **pauses every page load for `runner.block_cooldown_s` (60 s), takes one worker out of service for the rest
  of the run, and runs the blocked test again** (`runner.block_retries`, 2; separate from `behaviour.retries`). The run screen shows a
  **"Paused: the site blocked this machine" banner with a countdown** while it waits, so it never looks hung. If **nothing has loaded from
  this machine yet in the run** (the first page of the run is refused), the block is more likely a standing rule than rate limiting, so there is
  only **one** retry, and the error says so ("looks like a standing access rule (allow-list, VPN, country) ... retrying will not help"). An AWS
  **CloudFront** error page is named as such (from its response headers). To avoid
  triggering it: workers start `runner.stagger_s` (4 s) apart, and page loads (and clicks that may load one) are spaced
  `runner.min_page_load_gap_s` (1 s) apart across all tests. If it still happens, use fewer `--workers`.
* **A server call started by an input is waited for.** Leaving a field usually asks the server (a zip code, an e-mail, a
  voucher) and the answer changes the form. After typing and after a key press (`SendKeys`, e.g. `{TAB}`) the runner checks
  whether the site made a servlet call because of it - a first-party XHR/fetch whose URL contains `/bin/`
  (`waits.call_url_patterns`; `call_ignore_patterns` excludes noise; third-party traffic never counts) - and if so waits for
  those calls only, then lets the page show the answer. No call started (it watches `waits.input_call_grace_ms`, 0.3 s):
  nothing to wait for. A call is never abandoned as "background" - a slow one is waited for up to `waits.input_settle_max_s`
  (15 s, `0` = off; noted under *Things to review* if it is still running). Clicks and page loads are not affected: a Submit
  that takes long is simply what the following steps wait for. This is what makes `Set zip` + `{TAB}` + `Submit`
  (Owner_CRVD rows 156-158) work: the old runner was slow enough between steps to hide that the zip check had not answered.
* **Typed text has to stay, and nothing is ever re-typed.** Every field typed in the current run of typing steps is looked
  at again for ~0.4 s. If one has been emptied the step fails and names the field ("'First Name' was typed earlier and is
  now empty: the page cleared it when 'Last Name' was typed"). Repeating the typing would hide a real defect in the site,
  so it is not done. A click, selection or navigation between typing steps ends the run being checked, because those can
  reset a form on purpose. Cost: about 0.4 s per typed field.
* **`Open` fails when the site answers HTTP 4xx/5xx**, and a test whose first page never loaded stops there as `ERROR` with
  the reason (blocked / rate-limited / bypass token / SSO / down). Before, rows marked `Ignore_not_existing_object=Y`
  passed silently on the error page and the first strict step blamed its XPath ("Object was not found").
* `Output` **retries until the expected text appears** (up to `output.match_timeout_s`) and, when only capturing, waits for
  the text to stop changing. Text is Selenium-compatible (hidden → empty, NBSP → space, trimmed).
* `SwitchToFrame` to a frame that does not exist is a silent no-op in the legacy runner (the shared `aemFormFrame` row exists on sheets whose pages have no such frame), so it
  continues in the current document and is flagged in *Things to review* (`behaviour.missing_frame: fail` makes it a failure).
* `getAttribute("value")` (8 rows in `Owner_RVD`) was never implemented in the old runner: it only checked that the
  element exists. It is ported as-is and flagged by `regrunner lint` so you can decide whether to make it a real check.

### Slow is not wrong: waits end on evidence, not on a clock

A fixed time limit turns "slow" into "failed": ten browsers on a busy laptop load pages slower than any limit sized for a quiet one, so the same test
passed alone and failed with five workers. Every wait of a step (the page finishing its load, an element appearing, a button becoming usable, a spinner
going away, the expected text, a window or frame, the answer to what was typed) now works like this (`patience:` in `config.yaml`):

* **While the page is visibly still working, the wait goes on.** Working = a page load in flight, the document not complete, the site's *own* requests
  (same site as the frame that makes them) still going, or the computer so busy the page answers late (`patience.lag_ms`). Advertising / analytics
  requests do not count, nor does an address the page keeps asking for again and again (`repeat_after`: polling, a chat widget), nor a page that only
  animates.
* **An element missing from a finished page still fails in the step's normal time** (`timeouts.element_s`, 10 s, or the row's *Timeout*): slow is not the
  same as wrong. The step's notes say which: *"the page had finished loading and the element did not appear within 10 s"*.
* **A page that is stuck fails too**: nothing moved at all (no request started or answered, no page load) for `patience.stall_s` (**10 minutes**), e.g. a
  request the server never answers; or it kept itself busy for `patience.max_wait_s` (30 minutes). The note names what it was waiting for.
* **Nothing is ever repeated**: no retry, no re-typing, no second click - waiting longer is allowed, repeating an action would hide real site bugs.
* A wait that goes on past `patience.tell_after_s` (10 s, the old fixed limit) is shown on the run screen (yellow banner: which test and worker, why, how
  long so far) and noted on the step (*"waited 42 s for the element: the page was slow (the site has not answered yet (GET /bin/quote ...))"*).
* `runner.stop_after_failed_steps` only counts steps that failed on a page that had finished loading (a failure on a page still loading says nothing about
  where it is). `runner.step_hard_cap_s` (2 h) and `runner.test_timeout_s` (12 h) are last-resort backstops only.
* A dialog (alert / confirm) that the next step (`ALERT_OK` / `ALERT_CANCEL` / `ALERT_TEXT_OUT`, looking past `Wait` rows) is there to answer is answered as it
  opens, the way that step says, and the step reads its text: before, a slow computer reached the step after the 1.5 s auto-dismiss and failed "no dialog".
* `patience.enabled: false` brings back the fixed limits exactly as they were.

### Not run: the machine, not the site

When the **browser tab crashes** (the computer ran out of memory), **the browser closes or disconnects** under a test, or **the browser driver dies**, the attempt
proves nothing about the application. Such a test is **`NOT_RUN`** - never passed, never failed - and is **run again from the start** after
`runner.infra_pause_s` (10 s) up to `runner.infra_retries` (2) times; every attempt is kept (`attempts[]`, shown in the report). Only provable causes count (a crash
event, a browser that is no longer connected, a dead driver); an element that is not where the test expects is a real failure. A test that still could not be run
ends `NOT_RUN`, and a run where nothing failed but something was not run ends **`INCOMPLETE`** (not `PASSED`). The run screen, the report, `summary.txt` and the
terminal show "not run" separately from failures. Usual cure: fewer `--workers` on that computer.

### Captchas (a challenge that needs a person)

After **every step** the runner looks for a captcha *challenge* on screen (reCAPTCHA / hCaptcha asking to pick pictures; the small v3 badge and the hidden copy
of the frame that every reCAPTCHA page carries do not count). What happens when it finds one:

| Situation | Result |
|---|---|
| Run started from a script / CI (`--ask off`) | The test **stops at that step** (marked failed) and ends as `ERROR`; the steps after it are *not run* and never reported as passed. The message says what the captcha asked, after which step, and why it is there: **no `recaptchaBypassToken` configured** for that environment (expected: set `RECAPTCHA_BYPASS_TOKEN_<ENV>`), or **the cookie was sent and the site showed one anyway** (the bypass is not working there - a site-side problem). |
| Run started from the **web UI** or a **terminal** (default) | The test stops as above, then is **run again from the start in a visible browser window** (a headless browser cannot be turned into a visible one, so the steps before the captcha are replayed). When the captcha shows again the run screen says **"Captcha detected in <test>"**, the window is brought to the front, and the test **carries on by itself as soon as you have solved it**. *Skip: fail this test* gives up; nobody solving it within `captcha.timeout_s` (300 s) also ends the test. Other tests keep running headless meanwhile; only one window is open at a time. |
| `regrunner run --headed` | No replay: the test waits in place in the window you are already looking at. |

`config.yaml`: `captcha: {detect: true, solve: ask, timeout_s: 300}`. `solve: fail` never opens a window; `detect: false` restores the old behaviour (carry on behind it).
A step that failed only because the captcha was covering its element is done once more after you solve it.

## Speed, precision and staying out of the way

| Topic | What happens |
|---|---|
| Concurrency | Tests run **across** tests, never within one. Default 3 workers (`runner.workers`, ceiling 8), each test in its own isolated browser context, longest test first. Several workbooks share the workers (one run each); see *Several workbooks at once*. |
| Your machine | Headless only (never takes focus; the one exception is the window a captcha is solved in, see *Captchas*), runner + browsers run at lowered OS priority, **no OS-level keyboard or mouse anywhere** (guarded by `tests/test_keys_events_config.py::test_no_os_level_input_anywhere_in_the_package`). |
| Waits | `Wait N` no longer sleeps N seconds: in `waits.mode: smart` it returns as soon as the page is quiet (no in-flight requests or DOM changes for `quiet_ms`), never later than N. Real workbooks contain 106–256 s of sleeps per test. Use `legacy` for the old behaviour. |
| Finding elements | Polls every 100 ms and waits for the element to be actionable; timeouts are per-action (`timeouts.*`), not page-load guesses. |
| Optional elements | Rows with `Ignore_not_existing_object=Y` (the cookie banner, ~190 rows) count as absent once the page has gone quiet instead of waiting out a timeout. Set `timeouts.optional_mode: full` for a fixed wait. |
| Screenshots | JPEG after every step (~20 ms each) in `runs/<id>/tests/<test>/screenshots/`; `screenshots.mode: on_failure|off` to reduce. |
| Why a step failed | A failed step keeps **the browser's whole error** (`detail`; Playwright's call log says why a click could not happen, e.g. `<div> intercepts pointer events`) and a **`diagnosis`** read from the page at that moment, without touching it: is the element visible / enabled / standing still, **what is on top of it at the click point** (in its frame *and* on the page around the frame), how many elements the locator matches **in every frame** (an element in a frame the step did not switch to), the frames' state, and the page's and frame's HTML (scripts removed) in `runs/<id>/tests/<test>/dom/`. It is shown as *Why it failed* in the report and the results screen, and lives in `results.json` / `events.jsonl`, so a run copied from another computer explains itself. Comparison failures and steps that passed carry none. Tune it with `failure_capture:` in `config.yaml` (`enabled`, `dom_snapshot`, `dom_max_kb`, `dom_max_per_test`); gathering is capped at `budget_s` (8 s) and never fails a step. |
| A lost page stops the test | After `runner.stop_after_failed_steps` (default 5) steps **in a row** that act on an element and could not find or use it *on a page that had finished loading*, the test stops and says so (*"Stopped after 5 steps in a row could not find or use their element…"*) instead of waiting out every remaining step's timeout - a refused login or a form that never opened used to cost minutes of failed steps. A step that works, or reads its element and only differs from the expected text, starts the count again; `Wait`, `Switch…`, key presses and optional (`Ignore_not_existing_object`) elements neither count nor reset it. `0` = never stop. |
| Reliability | Popup windows and re-created iframes are re-resolved; `behaviour.retries` can re-run a failed test (all attempts are recorded). |

## Selectors: replacing XPath without touching the workbook

Each step resolves through an ordered chain, tried on every poll (a stale primary never delays a working fallback):

1. **`Locator` column** (optional, add it next to `FindBy`): `id=age || css=input[name=age] || xpath=//x`
   – accepts `css= xpath= id= name= testid= text= role= placeholder=`, bare CSS (`#id`, `input[name=x]`) or bare XPath.
2. **`selectors.yaml`** – maps a *legacy XPath* to generic locators (project-wide, no workbook edits).
3. **The legacy `FindBy`/`FindBy_Value`** – kept as the last resort (`selectors.legacy_fallback: false` to make generic locators mandatory).

Whenever a generic locator misses and the XPath is needed, the step is flagged in *Things to review* (`selector_fallback`).

```bash
regrunner selectors audit   "UAT_AEM_Travelex Regression_v9.1.xlsx"   # how brittle is each locator? (score 0-100)
regrunner selectors migrate "UAT_AEM_Travelex Regression_v9.1.xlsx"   # write provably-equivalent CSS to selectors.yaml
regrunner run … --harvest                                             # learn id/name/data-* from the live DOM
regrunner selectors apply <run-id>                                    # merge the harvested, unique, agreed-on locators
```

`selectors.yaml` already contains 92 conversions generated from your workbook. Conversion is deliberately
conservative: only attribute-based XPaths whose CSS matches exactly the same elements (checked in a real browser by
`tests/test_selectors.py`). Text-based (`text()`, `contains(.,…)`), positional and case-sensitive-attribute
(`@type='SUBMIT'`) XPaths are left alone. In your workbook 77 % of locator uses have such an equivalent; the rest
(the cookie button by text, `//p[contains(.,'$')]`, `(//button[@type='button'])[1]`, …) are what `--harvest` is for.

## Web UI

Start it with the double-click launcher or `regrunner serve --open`. The design is the *QA Regression UI* canvas (four
screens plus a states sheet); nothing in it needs the command line.

**1 · New run.** *Workbook*: drop Excel files on the page (or browse) or **tick one or more** already in `workbooks/` (each ticked workbook becomes a run of its own, all on shared workers; the page opens with the newest one ticked and remembers your last choice); with more than five in the folder a **search box** appears (several words, any order, `_ - .` count as spaces; **Enter** picks the best match, **Esc** clears), the list shows six at a time with *Show more*, can be sorted *Newest* or *A–Z*, keeps your choice pinned above the results, and offers the workbooks you ran lately as *Recently run* chips; the **trash icon** on a row deletes a workbook after a confirmation (it is moved to `workbooks/.trash/`, not erased; past runs keep their own copy; refused while a run is using it); it is read
immediately and shows how many test sheets it has, which are flagged Y, its `Global!Environment` and any warnings. *Tests*:
tick what to run (*Workbook defaults*, *All*, *None*, or a tag chip); each row shows its step count. With several workbooks ticked there is a **Tests card and a Run order card per workbook**, because what runs, and in what order, is decided for each workbook on its own (a workbook with nothing ticked blocks the run until you tick something or untick the workbook). *Run settings*: every
option of `regrunner run` is a control, and **the command line beside the Run button is built by the server from the very
request the button sends**, so they cannot disagree:

| Control | Command-line equivalent |
|---|---|
| Tests ticked / *All* (per workbook) | `--tests A,B` / `--all` after that workbook's name (tag chips just tick their tests) |
| Several workbooks ticked | `regrunner run A.xlsx --tests X B.xlsx --all ...` (each workbook keeps its own tests and `--chain`s; the settings below are shared) |
| Environment | `--env QA\|UAT\|PROD` (default: the workbook's own) |
| PROD confirmation dialog (type `PROD`) | `--allow-prod` |
| Workers | `--workers N` |
| Screenshots | `--screenshots every_step\|on_failure\|off` |
| Retries | `--retries N` |
| Seed | `--seed N` |
| PDF report / Harvest selectors | `--pdf` / `--harvest` (and `--no-pdf` / `--no-harvest` to override `config.yaml`) |
| Browser (Chrome / Edge / Safari / Chromium) | `--browser chrome\|msedge\|safari\|chromium` |
| Show browsers | `--headed` |
| Low OS priority | `--nice` / `--no-nice` |
| More options → Skip the HTML report | `--no-report` |

Only flags that differ from `config.yaml` are listed. *Check the workbook first* offers **Lint**, a **Dry-run plan** of every
step, and a **Locator health** audit; none of them opens a browser. *Preflight* shows the chosen browser (started once to prove it works), the token for the chosen
environment (set/missing only - the value never reaches the page), the SSO session (with the **Sign in…** flow) and folders.

**2 · Run in progress.** Global percentage ring, elapsed / estimated remaining / speed, passed-failed-in-flight-queued,
one lane per worker with its **latest screenshot** (the element acted on is outlined) and a tick per step, the queue, finished
tests, *Things to review* and an event log. **Cancel run** finishes the current steps; after 45 s the runner is told to stop now, and after ~12 s more it is killed, so a stuck browser can never keep a run alive. Closing a window, a browser or the report has a time limit too (`runner.close_timeout_s: 15`, `runner.report_timeout_s: 300`), and a run with no activity for longer than any step may take writes where everything is waiting to `runner.log`. Reloading the
page or losing the connection replays the event stream from the start, so nothing is missed.

**3 · Run finished.** Verdict, test/step/wall-time summary (with the speed-up from running in parallel), tests sorted failed
first with each failing step's expected vs actual (differences underlined, invisible characters made visible), locator and
screenshot, the run's parameters, evidence files (HTML report, PDF on demand, `results.json`, workbook copy, screenshots
folder), *Things to review*, **Re-run failed tests** (same settings; PROD sends you back through the confirmation) and
**Review and merge locators** after a `--harvest` run.

**4 · States.** Uploads are checked before saving (type, size, content) and unreadable workbooks say why. **A run started while others are going joins them**:
it is added to the workers that are already running and shares them (they split between the runs, and the total stays what was asked for: a pool
that began with fewer tests than workers grows up to `--workers` as runs join). The run screens say who shares the workers (*Sharing workers with*, each a link).
Because the workers are shared, a joining run must use the same **browser** and the same **headed / headless** choice as the runs going (the page
says so and offers *Use their settings*); its other settings (environment, screenshots, retries, seed, PDF...) are its own. The same workbook cannot be run twice at once (two runs of it would place
the same orders twice: *Open run* / *Cancel it*). When a run cannot join (another browser or window mode) and `runner.max_concurrent_runs` (default 1, counted in sets of workers, not in runs) is
used up, it is refused and the page says why. **Cancel run** stops that run only; the others carry on. A crashed runner shows its log and a **Run doctor** button. A run
whose process died is shown as *Interrupted*, and **Build report from what ran** rebuilds `results.json` and the report from
the event log.

Runs are background processes at low priority (one process per set of workers, however many workbooks share it), so the UI stays responsive and you keep your machine (no OS keyboard
or mouse is used anywhere). Light and dark themes follow your system; the fonts come from Google Fonts (system fonts are the
fallback when offline).

**Security.** It listens on `127.0.0.1` only and has no login, so instead every state-changing request must come from the
page itself: the `Host` must be local (blocks DNS rebinding), the `Origin` must match, and a custom header is required (a
different website in your browser cannot send it). PROD runs are also refused *by the server* unless the request carries the
typed confirmation. Uploads cannot escape `workbooks/`, run files cannot escape their run folder, and the page runs under a
strict Content-Security-Policy with everything from the workbook escaped. Do not expose the port to a network.

### API (what the page uses)

`GET /api/config` `GET /api/preflight[?deep=1]` `GET|POST /api/workbooks` `DELETE /api/workbooks/{name}` `GET /api/workbooks/{name}/tests[?env=]`
`POST /api/workbooks/{name}/lint|plan|audit` `GET /api/workbooks/{name}/start-url` `POST /api/runs/command` `POST /api/runs`
`GET /api/runs` `GET /api/runs/{id}` `POST /api/runs/{id}/cancel|answer|report|reveal` `GET /api/runs/{id}/events|log|selectors`
`POST /api/runs/{id}/selectors/apply` `GET /api/auth` `POST /api/auth/login|save|cancel` `WS /ws/runs/{id}`

## Evidence (`runs/<run-id>/`)

`events.jsonl` (the live stream) · `results.json` (everything, machine readable) · `report.html` (single
self-contained file: every step with result, timestamps, locator used, expected/actual, embedded screenshot, plus the
*Things to review* section) · `report.pdf` (`--pdf`) · `tests/<test>/screenshots/*.jpg` and `named/*` (explicit
`SCREENSHOT` steps) · `workbook.xlsx` (a copy of what ran). Console errors, uncaught page exceptions, failed requests and
HTTP 4xx/5xx are tagged with test + step and **never affect pass/fail**.

### API tests (web service sheets)

A sheet with a `WEBSERVICE_URL` column (like `PolicySearch`) plus the workbook's `InputOutput` sheet is run as an **API test**, no browser
involved. Each data row with `blnExecute=Y` is one test; it shows up in the test list (and `regrunner list|plan|lint`) with an **API** tag and
reports through the same console, UI, report and shared copy. Step 1 is the request; every check the workbook asks for is a step of its own with
the expected and actual value.

| Where in the workbook | What it is |
|---|---|
| API sheet (`PolicySearch`), one row per test, `blnExecute = Y` | the test; `WEBSERVICE_URL` (usually `=VLOOKUP(Global!$B$2, Global!$E$1:$G$4, 3, FALSE) & <policy number cell>`: the base URL per environment from the `Global` sheet, then the policy number), `WEBSERVICE_METHOD` (GET / POST ...), `JSON_FORMAT` |
| `XML_LOCATION` + `XML_REQUESTFILE` columns of that sheet | **the request body**: a JSON template file (POST / PUT / PATCH only; a GET has no body, so `PolicySearch` leaves them empty) |
| `InputOutput` sheet, `addHeader` rows | request headers: header name -> the column holding its value (`Authorization` -> `DT_bearerToken`, `apiKey` -> `DT_apiKey`) |
| `InputOutput` sheet, `update_json` rows | fills the body template: JSON path -> the column holding the value (`searchCriteria.searchParameters.[0].value` -> `policyNumber_IN`) |
| `InputOutput` sheet, `output_json` rows | reads the response: JSON path -> the `..._OUT` column it is copied to |
| `InputOutput` sheet, `compare` / `contains` rows | the checks: `..._EXP` column (expected) against `..._OUT` column (actual); `compareX` = switched off |

* **Request.** `WEBSERVICE_URL` (formulas such as the `VLOOKUP` on the Environment table work), `WEBSERVICE_METHOD` (default POST),
  `JSON_FORMAT=Y` (sends `Content-Type: application/json`). `InputOutput`: `addHeader` (header name → the column holding its value, e.g.
  `Authorization` → `DT_bearerToken`).
* **Body (POST/PUT/PATCH).** The JSON template named by `XML_LOCATION` + `XML_REQUESTFILE`, with `update_json` (JSON path → column) filled in.
  The template is looked for **on the workbook's own path first (the L: drive on the QA machines), then in `api.templates_dir`, then in the folder
  named by `RR_API_TEMPLATES_DIR` in `secrets.env`, then beside the workbook** (`templates/`). If none has it, the step fails and lists every place tried.
* **Response.** `output_json` (dotted path such as `detailResponse.policyDetail.travelers.[0].customElements.[1].value` → column) copies values
  into columns, `RES_STATUS_CD_OUT` and `ELAPSEDTIME_OUT` are filled automatically. The response is saved as `tests/<id>/response.json` in the run.
* **Checks.** `compare` (text equal after trimming; numbers to 4 decimals), `compare_ignore_case`, `contains`, `contains_ignore_case`: expected column →
  actual column. Exactly as the legacy runner: a row with **no function name is ignored**, `compareX` (and anything unknown) is off, and
  `DisableCheckpoint` (test name → `col;col`) skips those checks for that test name. `lint` says which rows were ignored.
* **Secrets.** Header values are never written to any file, report or log (`tests/<id>/request.txt` shows `••••••`). Instead of keeping the API key and bearer
  token in the sheet, put `RR_VAR_DT_APIKEY=…` / `RR_VAR_DT_BEARERTOKEN=…` (`RR_VAR_<COLUMN>`) in `secrets.env`; when set they win over the cell.
* **Order.** An API test reads what UI tests of the run produced (`=AgentStandAlone_Params!E2`, the policy number a UI test captured): it waits for the test that sets that cell, and unless
  chained it starts after every UI test of the run (see *Tests that depend on each other*). Run only the API test and such a cell is empty: you are asked for the value.
* **HTTP status.** An answer is an answer: a 500 does not fail step 1 by itself, the checks then show what came back. **401 / 403 from the API itself** (its own JSON
  answer, e.g. API Gateway's `{"message": "Invalid key=value pair ... Authorization header"}`) **fail step 1 at once** with what the API said, which headers were sent
  and from which columns, where `RR_VAR_<COLUMN>` can override them, and the usual cause (an expired token; a URL that ends in `/` because the policy number is empty)
  - unless the test *expects* a status (an active `compare` on `RES_STATUS_CD_OUT`: a negative test). **429, CloudFront's own error page and any HTML / plain-text
  refusal** are a firewall block instead: cool-down, one worker fewer, retry (see *Staying out of the way*).
* **Empty inputs.** When the URL is built from a cell that is empty (`&Q3`, where `Q3` is `=AgentPortal_Params!R3`, the policy number a Purchase test produces) the request is
  **not sent**: the step fails with `Not sent: policyNumber_IN is empty (AgentPortal_Params!R3 (DT_Policy_Out)) ...`, or, started from the web UI or a terminal, you are asked
  for the value (this run only). In a run that includes the test that sets it, the API test simply waits for it (see *Tests that depend on each other*).
* **Limits.** JSON over HTTP only: XML / SOAP / WAATS / DB / SFTP / multipart features of the legacy web-service runner, `clone_json`, JSONPath (`$..x`)
  and `[BLANK]`-style tricks beyond `addHeader` are not implemented (`lint` warns). The request is sent with Playwright's HTTP client, not the browser: behind a
  network that re-signs HTTPS (Zscaler) set `NODE_EXTRA_CA_CERTS` to the company root certificate (or `api.ignore_https_errors: true` for testing).
  Not yet run against the real UAT API from here.

### Tests that depend on each other

Tests run side by side, but one may need what another produces: `Purchase` writes `DT_Policy_Out` (a step whose `Output_Value` names a Params column) and
`ViewPolicy` / `Cancellation` type it. The runner works this out before the run (a dry run of every test, no browser):

* **Data.** A test that reads a parameter which another test *of the run* sets, in the **same Params row**, and which comes earlier in the DataSheets list (the
  order the legacy runner ran them in), **waits for it** and then uses its value. A waiting test is held in the queue, not started and paused, so it never takes a
  worker from the test it waits for. Purchase#1 / ViewPolicy#1 use row 3 and the #2 tests use row 5, so the two streams run in parallel and never see each other's value.
  If a test it waited for ends without setting the value, the waiting test is **not run** (`Not run: ViewPolicy#1 needs DT_Policy_Out, which Purchase#1 should have set
  (Purchase#1 ended FAILED) and did not. Nothing was typed in its place.`); an old value left in the workbook is never used in its place.
* **Nothing sets it.** A test uses an empty parameter and no test of the run sets it: the new-run screen (and `regrunner lint`) says so and names
  the test that does ("Purchase#1 does: add it to the run"); at run time you are asked for the value, or the step fails. Nothing is typed in its place.
* **Chains.** Data cannot say that ViewPolicy comes before Cancellation (both only read the policy number). A chain does: `Purchase#1, ViewPolicy#1, Cancellation#1` means each
  waits for the one before it, whatever happened to it. On the new-run screen the **Run order** card lists the streams; the arrows put a test earlier or later and make the
  stream a chain, *Save this order* remembers it for the workbook (a hidden file beside it, `workbooks/.chains/<name>.json`, never inside the workbook), *Clear chains*
  forgets it. From a terminal: `regrunner run wb.xlsx --chain Purchase#1,ViewPolicy#1,Cancellation#1 --chain Purchase#2,ViewPolicy#2,Cancellation#2` (`--no-chains` ignores
  the saved ones), or in `config.yaml`: `chains: {qantas-test.xlsx: [[Purchase#1, ViewPolicy#1, Cancellation#1]]}` (`*` = any workbook). A chain that contradicts the data
  (a test before the one that sets its value) is reported and the person's order wins.
* **API tests are part of it.** An API row that reads a cell of another sheet (`policyNumber_IN` = `=AgentPortal_Params!R3`, the `DT_Policy_Out` of its stream) waits for the UI test that
  sets that cell, appears in that stream on the Run order card (tagged *API*), and can be moved with the arrows or put in a chain like any other test
  (`Purchase#1, PolicySearch#1, Cancellation#1`). An API test nobody chained still starts after **every** UI test of the run (the card says so), because what it checks - a policy's
  final status, say - is what the whole stream leaves behind; put it in a chain to choose where it runs. If the test that should set its cell fails, it is not run either.
* **The order is always current.** The Run order card and the *Run order* line under Preflight are worked out the moment the page shows a workbook, from the tests selected *at that
  moment* (the defaults included), and again whenever the workbook, the selection or the chains change - whichever control changed them - and when you come back to the New run screen.
  While it is being worked out Preflight says so.

### Values set by the tests

A step whose `Output_Value` names a Params column (`DT_Policy_Out`, `Quote_OUT`) *sets* that parameter. Every such value is listed in the report (**Values set by the tests**: test,
variable, value, the step that set it, the Params cell it went to, and a `sets ...` line on the step), in the web UI (a **Values set** card on the run screen, live and after
the run), in `results.json` (`variables` per test, `sets` per step) and in the shared `summary.txt`. A value a person typed in for an empty parameter is listed as *entered by hand*;
a secret typed in (`ASK_USER` with `Output_Property=SECRET`) shows as `••••••` everywhere.

### Sharing results with the team (`publish`)

Where runs are stored is `runs_dir` (default `runs/`, next to `config.yaml`; the UI lists whatever is in it). To give the team a
copy as well, without moving the runs out from under the UI, set a shared folder in `config.yaml`:

```yaml
publish:
  dir: /Volumes/QA-Share/regression-runs      # Windows: '\\server\share\regression-runs' (single quotes); ~ and ${ENV_VAR} work
  screenshots: failures                       # failures (default) | all | none - what is embedded in the shared report
```

When a run finishes, `<dir>/<run id>/` gets **`report.html`** (one self-contained file) and **`summary.txt`** (result, counts,
each test's pass/fail, the failing steps and their errors). Nothing else is copied: no screenshots folder, no events, no
`results.json`. `screenshots: failures` embeds only the failed steps' screenshots, which keeps the file small; `all` embeds every
step's screenshot and is about as large as the whole screenshots folder (a full 9-suite sweep is ~200 MB).

* The run always finishes and stays in `runs/`; the shared copy is best effort. If the share is offline or slow the run says so in
  its log (and up front, as a warning, when the run starts), waits at most `publish.timeout_s` (60), and the run is copied
  automatically after the next run that can reach the share. To do it by hand: `python -m regrunner publish <run id>`
  (`--to <folder>` for a one-off, `--screenshots all`).
* Cancelled runs are not copied (they are not a result to hand over); `python -m regrunner publish <run id>` copies one anyway.
* `doctor` and the UI's readiness list show whether the shared folder can be written to right now.
* Untested on a real network share so far (only local folders); it writes to temporary names and renames, which SMB supports.

### Event stream

`run_started` (with the run's `params`) `test_started` (with its `worker`) `step_started step_passed step_failed step_skipped`
(with `locator_origin`) `screenshot_saved` (with the element's `box`, % of the viewport) `console_error network_error review_item`
`pool_changed` (another run joined the workers this run is on; `run_started` carries `shares`) `test_finished` (with final `review_counts`; `step_passed` / `step_failed` carry `sets`) `variable_set` `captcha_detected` (`waiting`: true when a person is being waited for) `run_progress run_paused user_input_needed` (`kind`: `text` or `captcha`) `user_input_waiting user_input_received user_input_closed`
`worker_waiting` (a worker waits on purpose: `test worker step wait code message [seconds]`, `code` = `login_code` / `slow_page` / `infra_rerun`; never a secret or
a code in `message`) `worker_resumed` (`wait`, `waited_s`) `run_finished log` – see `src/regrunner/events.py` for fields. Add your own listener:

```python
bus = EventBus(); bus.subscribe(lambda e: print(e["type"]))
await execute(RunOptions(workbook=Path("workbooks/x.xlsx"), tests=["CW"]), load_config(), bus)
# several workbooks on one set of workers: one run (and one bus) each
await execute_many([RunOptions(workbook=a), RunOptions(workbook=b, tests=["CW"])], load_config(), [bus_a, bus_b])
```

## Configuration

`config.yaml` (every key documented inline) + `secrets.env` (git-ignored; never put tokens in YAML or Excel).
Workbook tokens that must not live in Excel, such as `DT_ZScalerUser`, are supplied as `RR_VAR_DT_ZSCALERUSER=…`.
Things you are most likely to change: `publish.dir` (shared copy of each run for the team), `runner.workers`, `waits.mode`, `timeouts.element_s`, `screenshots.mode`,
`browser.name` (which browser runs use by default, see *Which browser a run uses*), `browser.timezone` (the workbook's `TODAY()+1` dates use *your* machine's date), `browser.channel: chromium`
(full Chromium instead of the headless shell, e.g. if links to PDFs must open in a viewer tab).

## Extending

* **New action**: add an `@action("NAME", element=True)` async function in `engine/actions.py`; it is immediately
  usable from the `Method` column, listed by `regrunner lint`, and covered by the outcome rules.
* **New Excel function**: `@function("NAME")` in `workbook/formula.py`.
* **New report/consumer**: subscribe to the event bus, or read `results.json`.

## Known limits

* **Real-site evidence so far is a single run**: `CW` against UAT (`runs/20260923-190216-UAT/report.html`, 151 steps in 53 s, 150 passed - the one failure, a missing `aemFormFrame`, is a silent no-op in the legacy runner and is now ported that way). That run also placed a real UAT purchase, so treat any run of the real workbook as a live transaction. Not yet exercised on the real sites: the tests marked "w/ captcha" in `DataSheets` (`Owner_*`, `PostDeparture`, `Preview`), QA, PROD (refused unless confirmed), and the SSO session (the sign-in flow itself is tested against the mock site). Everything else is verified against a mock of the same page structure, the real workbook's plans/lint, and Excel's own formula results.
* The browser is chosen for the whole run (UI / `--browser` / `browser.name`), not by the workbook's `Page` column; a `Page` value that names another browser is flagged in the run's review items.
* *Safari* is Playwright's WebKit build (Safari's engine), not the Safari application, which Playwright cannot drive. Only Chromium-based browsers and WebKit are supported (no Firefox).
* Timer-only banners (no request, no DOM change before they appear) can be missed by `optional_mode: quiet`;
  use `full` if a consent banner behaves that way.
* Patient waiting, the not-run outcome and the login-code margin are verified on the mock site only (a server answering after 25 s, a tab kept busy for 15 s,
  a renderer crash, a killed browser, five logins sharing one secret against a once-only code check). Not verified: whether the real sites wait the same way
  (their polling and third-party traffic), whether Okta has other per-account limits (one session per user, login rate limits) - nothing here assumes one -
  and how long real logins take from code to Verify (the first real runs will measure it: see the step notes).
* Not supported: DB/API/Word/PDF/Outlook steps, BrowserStack, iteration rows (`ITERATION_START`, `GO_TO_ROW`).

## Tests

```bash
pytest                       # ~190 tests, ~4 min (real Chromium against a local mock site; the UI is driven in a browser)
pytest -m "not browser"      # fast, no browser
```
