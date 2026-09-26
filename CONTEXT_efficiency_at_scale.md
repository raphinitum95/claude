# Context: the same speed at 1 or 20 tests, on an ordinary laptop

Hand-off brief from a design discussion with the user (2026-09-26). Nothing here is built yet. Read `AGENTS.md` first (rules, router, which
tests to run), then this file. This work builds on `CONTEXT_accurate_at_any_worker_count.md` (evidence-based waiting in `engine/patience.py`,
`runner.infra_retries`, `worker_waiting`/`worker_resumed` events): check `git status` and that brief for what of it has landed before starting.

## The goal (the user's words, made measurable)

"If one test alone takes 5 minutes, the same test in a run of 20 should still take about 5. 8 is acceptable; 15 or 20 is not."
The ideal the user described: every test takes the same time whatever the number of tests, the machine, the network.

There are two separate gaps; do not confuse them:
1. **Load penalty** (solo 5 min, in a crowd 10). Phases 0-4 below target this. Target: a test's time in a run of N <= 1.6 x its solo time.
2. **The floor** (solo 5 min vs the user's dream of 1 min). Only Phase 5 targets this. The site's own response time and the one-code-per-30-s
   login are floors no code can go below. Do not promise a number: Phase 0 tells how much of the 5 minutes is our overhead.

**Accepted trade-off:** when the laptop is full, extra tests wait in the queue *before they start* (the whole run gets longer); the tests that
are running stay fast. A test's own duration is measured from its start, and the report should show queue time separately.

## The machines

Standard-issue mid-range Dell work laptops (Windows, Python 3.9, installed Chrome/Edge, cannot download Playwright browsers; assume ~16 GB RAM,
sometimes 8, 4-6 cores, Teams/Outlook open). Realistically 6-10 browsers at once, not 20; the governor (Phase 2) must find the number per
machine at run time, never assume it. Real runs happen there; run folders are copied into `runs/` here. The mock site here is too light to
measure JavaScript memory: memory/CPU comparisons come from the user's normal runs, recorded by Phase 0, copied here and compared.

## Decisions the user made (do not re-open)

| Topic | Decision |
|---|---|
| Extra test accounts | **None.** All tests share one login and one authenticator secret (one code per 30 s window: see `totp.py`). |
| "Log in once, share the session with other tests" | **Opt-in option only, never the default.** |
| Screenshots | **Keep them.** Smaller / lower quality is fine (quality is already `screenshots.quality`; add a size/scale setting). Never remove. |
| Blocking analytics / ads / trackers | **Blocked by default**; a test can opt out (some tests check the cookie consent manager). The opt-out marker lives in the workbook, which the user edits, not you. |
| Caching site files between tests | **Never cache application JavaScript**: anything under `/etc.clientlibs/` (and treat all first-party JS the same). Caching it caused real "old code" problems. Images, fonts and third-party files only, and low priority. |
| Windows settings (memory compression, antivirus exclusions, power plan) | The runner may **check and warn** (`doctor`); it never changes them. IT's call. |
| Your queue idea | Adopted: tests line up; a free slot takes the next one; a test that must wait (and has no browser open yet) goes back in line and costs nothing. See Phase 2 for the memory caveat. |

Rejected (do not build): changing the viewport size (changes the site's responsive layout = what is tested); "hibernating" a test to disk and
reopening it (loses page state, and the reload hits the site again); retrying/re-clicking steps (hard rule, AGENTS.md section 1).

## Key insight for the design

The scarce resource is **memory, not CPU**. A test waiting inside a page keeps its page open (roughly 200-400 MB, unmeasured): asyncio already
gives its CPU to others, but its RAM stays. So "workers" really means "browsers open at once", and what limits it is free memory. Swap is the
cliff: once the laptop swaps, every test slows at once. Everything below is about (a) never reaching that cliff, (b) making each page smaller,
(c) making waiting pages cheap.

---

## Phase 0: measure (do first; everything else is decided from its numbers)

1. **Where each test's time went.** Per step and per test, split the duration into: site time (first-party responses, from the session's call
   watches), deliberate waits (login-code slot, `min_page_load_gap_s` pacing, stagger, ASK_USER), computer time (page slow to answer while the
   site had answered; `patience.lag_ms` is a related signal), and runner overhead (settle/quiet windows, screenshot capture, failure capture).
   Also queue time before the test started. Into `results.json` per step/test, and a summary line in the report.
2. **Resource sampler.** Every few seconds during a run: CPU %, free memory, swap/pagefile use, total memory of the browser process tree,
   worker count, and **asyncio event-loop lag** (a heartbeat task: all workers share one loop; a blocked loop freezes every test).
   Written to the run folder (e.g. `resources.jsonl`). A dependency like `psutil` must install on the work computer and support Python 3.9;
   confirm with the user before adding one.
3. **Third-party domain tally.** `network.jsonl` holds first-party calls only. Record per test which third-party hostnames were loaded
   (host, count, bytes; no URLs with query strings, no bodies). This is the input for the tracker block list (Phase 4).
4. **Benchmark on the mock site.** Same synthetic workbook (`tests/workbook_factory.py`) at 1, 5, 10, 20 workers; assert the per-test
   ratio target. Keep it a marked, opt-in test (it is slow); never add it to the default subset without asking.

## Phase 1: history and "what changed" log

One record across all runs, **built from the run folders** (so the user copies nothing extra), exportable to CSV for Excel:
- per test and per step: duration and its Phase 0 split, status, error kind (site said no / element missing / infra "not run" / WAF / captcha),
  resources at that moment, worker count, browser + version, machine (RAM, cores; memory compression state if readable).
- **"what changed" markers**: runner version (git hash or source hash), settings that affect speed, browser version, and the **site version**:
  fingerprint the `/etc.clientlibs/` file names/hashes a test loaded, so "the site deployed new code on Tuesday" is detected automatically.
- a compare view/command: "step X of test Y got 3x slower since <marker>", "failures started after <site version>".
- Uses: a longest-test-first order (Phase 5), expected durations per test (Phase 2 login pipelining), and future agents diagnosing regressions.
- Never record secrets, codes, passwords or typed values of masked fields (reports and history may be shared).

## Phase 2: adaptive worker count (admission control) + the queue

- Replace the fixed `runner.workers` as the effective count with a governor, capped by `runner.max_workers`: add a slot while free memory,
  swap, CPU and loop lag are healthy; stop **starting** tests when they are not (think TCP congestion control: add slowly, back off fast).
  **Never pause, kill or slow a running test.** Keep a memory reserve so the laptop never swaps and the user's own apps stay usable.
- Estimate a test's memory from history (Phase 1) when available.
- The user's queue model: a test that must wait **before it needs a browser** (e.g. waiting for its login-code slot) waits in the queue,
  holding no browser and no slot. Tests waiting *inside* a page keep their slot (memory); Phase 3 makes that cheap.
- **Login pipelining** (no extra accounts): 20 logins need 20 x 30 s windows, so the last login cannot happen before ~10 min. Start tests so
  each reaches its login step as its window opens (time-to-login from history, else a simple stagger aligned to 30 s). This keeps each test's
  own time flat; the run as a whole still takes >= (logins x 30 s).
- Where: `engine/pool.py` (it already has a `gate`), `engine/runner.py`, `engine/throttle.py`. Tell the user on the run screen why fewer
  workers are running (reuse the `worker_waiting` banner pattern; plain language for non-technical QA people).
- Option (opt-in, never default): "log in once, share the session" via storage state for tests that are not about login.
- Also consider: **browser sharding** (one browser per ~4 workers instead of one for all: a crash then loses 4 tests, not 20) and **recycling**
  a browser every N tests to reclaim leaked memory. Today one browser serves all tests (`cfg.browser.launch` in `runner.py`).

## Phase 3: "cold storage" for tests in a deliberate wait (Chromium only)

When a test enters a wait *the runner chose* that will last more than a few seconds (login-code slot, ASK_USER), make its page cheap:
freeze it (CDP `Page.setWebLifecycleState` = `frozen`), ask Chromium to release memory (CDP `Memory.simulatePressureNotification` critical,
`HeapProfiler.collectGarbage`), so Windows memory compression / the pagefile take its now-idle memory. Unfreeze (`active`) before the next step.
- **Never freeze a page during a patience wait on a slow page** (the page is working; freezing would stall it and change the result).
- Unverified: whether freezing for ~30 s affects the site (session timers, Okta). Test on the mock site, then have the user compare real runs.
- WebKit ("Safari"): no CDP; skip there.

## Phase 4: smaller pages

1. **Tracker blocking, default on, per-test opt-out.** Block list in `config.yaml` (domains of analytics, tag managers, ads, chat widgets),
   seeded from the Phase 0 domain tally of real runs, reviewed by the user. **Do not block the consent manager itself** (OneTrust/Cookiebot
   style): other tests click its banner; blocking it would break them. Block what it loads, not it. Never block payment, sign-in (Okta),
   captcha, or first-party hosts.
   - Must be per test (for the opt-out), so not `--host-resolver-rules` (browser-wide). Use CDP `Network.setBlockedURLs` per page/context on
     Chromium (keeps the HTTP cache). Avoid `page.route` for this: it turns off the browser cache. WebKit: decide with the user (route or none).
   - Opt-out marker: propose a design to the user (e.g. a step keyword such as `ALLOW_TRACKING` before the first navigation, or a Params
     column); the user adds it to the workbooks. Record in results/report that a test ran with blocking on/off.
2. **JavaScript engine "optimize for size"** (V8 flags via `browser.args`, config.py `BrowserCfg.args`). Same page behaviour, some CPU cost.
   Measure with an A/B across the user's normal runs (Phase 0 data), then decide the default.
3. **Background-work switches** (`--disable-extensions`, `--disable-background-networking`, `--disable-component-update`, `--mute-audio`):
   measure; also check that nice'd headless pages never get their timers throttled (a throttled page looks like a slow page). Unverified.
4. **Lighter headless build**: installed Chrome/Edge run "new headless" (full Chrome); Playwright's `chromium-headless-shell` is lighter.
   Whether it can be copied onto the work computer by hand is unverified: ask the user.
5. `doctor`: warn when Windows memory compression is off (read-only check, e.g. `Get-MMAgent`; confirm it works without admin) and when on
   battery / power saver. Never change the setting.
6. Streams instead of lists: `session.network` (and anything else per test) grows for the whole test; for 2000-step tests stream to disk.
   The web UI replays the whole event stream; check its cost with 20 x 2000 steps (the user's own UI tab must not become the heavy part).

## Phase 5: lower the floor (the solo time), guided by Phase 0

- **Per-step overhead**: quiet windows after steps (`waits.quiet_ms`, `ready_quiet_ms`), screenshot capture, failure capture. Smarter "done"
  detection (the requests this step triggered have answered) instead of waiting for general quiet. Never at the cost of acting on a half-ready
  page (accuracy first).
- **Screenshots from the screencast** (CDP `Page.startScreencast`): take the frame current at each step instead of pausing for a screenshot;
  plus `screenshots.scale` (e.g. 0.5) and the existing `quality`. Keep the element highlight box working. Failure screenshots stay full size.
- **Keep connections warm**: pre-open the next test's context and preconnect to the site's hosts before it needs them.
- **Longest-first order** from history (within the order/dependency rules of `engine/order.py`, `engine/schedule.py`).
- **Shared cache** for images, fonts and third-party files only; never `/etc.clientlibs/` or any first-party JS. Low priority.
- Out of left field, not code: one dedicated machine (office PC/VM) running scheduled runs, laptops only viewing results. Raise with IT.

---

## Order and acceptance

Build in this order: Phase 0 -> 1 -> 2 -> 4.1 -> 3 -> rest of 4 -> 5. Show the user Phase 0 numbers from a real run before building Phase 2+;
the user wants to review before things are actioned.

Proof that it works:
1. Mock-site benchmark: per-test duration at N workers <= 1.6 x solo, on this Mac, up to the governor's chosen count; queue time reported separately.
2. The governor never lets the machine swap in the benchmark, and never touches a running test.
3. Tracker blocking: a test is blocked by default and the opt-out test loads the tracker (mock site: add a fake third-party host/script).
4. Cold storage: a frozen-then-thawed page continues with identical results; a patience wait is never frozen.
5. History: built from existing `runs/` folders, exports CSV, detects a changed `/etc.clientlibs/` fingerprint between two runs.
6. No secrets anywhere in the new files (check sampler, history, domain tally).

## Rules (from AGENTS.md; they apply in full)

Never run a real workbook against a real site (mock site only; ask before any live run). Never retry/re-click a step. No OS-level
keyboard/mouse, no captcha/WAF evasion, no UA/IP rotation. Never echo secrets. Python 3.9 must keep working (asyncio primitives inside
coroutines). Run only the tests your change touches and say which. Do not edit `workbooks/*.xlsx`. Say when the UI needs a restart and list
changed files (the user copies them to the work computer). Update `AGENTS.md` (sections 3, 4, 9) as modules/config/tests are added.

## Unverified (say so; do not assume)

Memory per test on the real sites; whether freezing pages affects real sessions; whether the headless shell can be installed on the work
computer; whether `Get-MMAgent` needs admin; how much of a solo test's 5 minutes is runner overhead vs the site (Phase 0 answers it).
