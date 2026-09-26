# Context: design the Workbook Builder (the "Build" tab of the regrunner UI)

You are picking up a **UI design task**. The user has already answered 53 clarifying questions, one at a time. The decisions below are final unless the user reopens one. Read this file fully before designing. Build the design as a Claude **Design canvas** (Artifact type "Design"). There is a companion file for the engineering work: `dev/claude/CONTEXT_workbook_builder_engineering.md`.

## The project in one paragraph

`/Users/raphaeldelossantos/Documents/qa-regression` replaces a legacy Windows/Excel Selenium runner with a Python + Playwright runner (`src/regrunner/`). Test cases live in Excel workbooks (`workbooks/*.xlsx`). Each workbook has one sheet per test (one row per step, with keyword columns such as `Step_Name`, `Method`, `Page`, `FindBy`, `FindBy_Value`, `Value`, `Expected_Value`, `Exact_Match`, `Contains`, `Output_Value`, `blnExecute`, `Ignore_not_existing_object`, `Timeout`, `Locator`), plus `Params_N` sheets (data rows), `DataSheets` (which tests run, with which Params sheet, tags, comments) and `Global` (Environment, etc.). A web UI (`regrunner serve`, vanilla ES modules in `src/regrunner/web/static/`) already has **Run** and **Results** screens. The **Build** tab you are designing is new.

## Goal

A GUI where a **semi-technical QA person** builds and edits tests intuitively, covering every part of a workbook: the workbook name, tests, variables, values, expected values, locators (generated for them, never hand-written XPath), and every way of chaining steps (page to page, jumping to an API test and back, new windows, frames). This person knows the vocabulary but isn't a developer. It must scale to **300-step tests** and leave room for future test types (XML, email, PDF, SQL, SOAP/queues).

## Existing artifacts

- **Round-1 canvas: "Workbook Builder"**: https://claude.ai/artifact/De4rnxZdsa3GBu88BCaSoV (private). It has three interactive boards drawing the same 300-step Travelex purchase test:
  - `Cards.dc.html`: A · step cards plus an Excel-grid toggle.
  - `Flowchart.dc.html`: B · every step is a box (rejected: too much panning at 300 steps).
  - `Main.dc.html`: C · **the chosen layout**. A subway-style **block map** across the top; detours (API, XML, new window) drop below the line and rejoin it. Clicking a block shows its steps as cards below. The inspector sits on the right and the workbook rail on the left.
  - Read its files (`Artifact` read with `path: project/Main.dc.html` etc.) and revise that canvas, or start a new one. The boards are generated from embedded data (300 rows, 18 blocks) inside each file's script.
  - Round 1 still shows IF lanes and a traveler loop. Both are kept (see D6), but they now branch only on variables.
- **Run/Results UI design canvas** (already implemented): https://claude.ai/artifact/A2VZ9CEdWh7z3Q97vnFvNf.
- **Visual language (D40): match the Run/Results UI, and design both dark and light themes.** The tokens come from `src/regrunner/web/static/app.css`:
  - Dark: `--bg #090C12`, `--rail #0D1119`, `--surface #121722`, `--surface2 #171E2C`, `--surface3 #1E2839`, `--line #212B3D`, `--line2 #2F3B54`, `--tx #E9EDF5`, `--tx2 #A6B0C5`, `--tx3 #8791A8`, `--acc #5CC8FF`, `--pass #43D69B`, `--fail #FF7062`, `--warn #F4B84A`, `--pend #5A6784`.
  - Light: `--bg #F2F0EA`, `--surface #FFFFFF`, `--tx #161A23`, `--acc #0A6FB0`, `--pass #11704F`, `--fail #BE3427`, `--warn #8C5A00`.
  - Fonts: Bricolage Grotesque (display), Instrument Sans (body), JetBrains Mono (code).
  - Build is the third tab: **Run · Build · Results**.
- The user runs this on **Mac and Windows**. Every shortcut hint shows ⌘ on Mac and Ctrl on Windows.

## Decisions (Q# = the question number in the interview)

### Storage and structure
- **Q1 Excel round-trip.** The builder opens and edits the existing sheets in existing workbooks, creates new tests and workbooks, and always saves as `.xlsx` in the same `workbooks/` folder.
- **Q3** Flow the sheet can't express today is added as **new METHOD keywords plus a few new columns**, so Excel stays the single source of truth.
- **Q20 One type per test; a workbook mixes test types.** Example: in the Qantas workbook, `purchase#1` is a website test and `policySearch#1` is an API test. They are two tests in one workbook.
  - A test can **call another test mid-way**: purchase#1 reaches step 100, runs policySearch#1 to completion, then continues at step 101.
  - Tests can also just depend on each other's variables.
  - On the block map, a call to another test is a detour node that rejoins the line.
- **Q21 Variables are shared across the whole workbook run.** Each test declares what it **Needs** and what it **Provides**. The builder warns when something is needed but nothing earlier provides it, and dependent tests are ordered automatically.
- **Q14 Blocks** (the map nodes) are generated automatically from the `PAGE` column when an old sheet opens. Users can then split, merge and rename them, and the result is stored in a new `BLOCK` column.

### Editor layout (Q4, chosen after comparing the three boards)
- The **mix layout**: block map on top, the selected block's step cards below, the inspector on the right, and the workbook rail on the left. Keep an **Excel-grid view toggle** for the semi-technical users.
- **Q2 persona:** semi-technical QA.
- **Q38 Step names:** an automatic sentence ("Type {FIRST_NAME} into First name") that updates itself; the user can override it, with a "reset to auto" option.
- **Q39 Editing:**
  - Drag to reorder, including across blocks via the map, and multi-select.
  - **Bulk edit** of timeout, on/off, "if fails", page and block.
  - **Keyboard shortcuts** (↑↓, Enter, ⌘/Ctrl+D/C/V/Z, Delete, `/` search, R = run up to here).
  - **Disable instead of delete** (greyed card, `blnExecute = N`).
- **Q26 Copy and paste at every level**: steps, blocks, whole tests, whole workbooks. **Duplicate** opens an optional **"What changes?"** panel listing the base URL/domain, environment, workbook name and most-used text values, plus a workbook-wide find-and-replace with a preview of every hit.
- **Q15–17 Templates, not shared blocks.** Saving a section as a template is an enhanced copy-paste ("the quote screen section is the same in 20 tests"). Inserting one copies its steps, and later edits do not spread to other tests.
  - Templates live in **one shared library file** next to the workbooks.
  - Inserting a template opens a **variable-mapping dialog**: it auto-matches identical names, suggests close ones (DESTINATION → DEST), and offers "create new column" for the rest.

### Interactive building (the heart of it)
- **Q5** The live site opens in a **separate real browser window** controlled by the builder; real sites refuse to be embedded in an iframe.
- **Q50 Page overlay.** A small draggable **floating pill** is injected into the site window: `● Rec · Pick · Check · Save · Wait until · step 211 of 300 · Done`.
  - Hovering outlines an element and shows its friendly name.
  - In Pick mode, clicking opens a **hover card** beside the element with the smart action shortlist, the element's current value, and the Check/Save options.
- **Q6 Record toggle.** While it's on, clicks, typing and choices become steps, inserted at the builder's cursor. While it's off, the user can browse freely, and only explicit Pick/Check/Save actions add steps.
- **Q7** Typed text is **offered as a variable**. The name is guessed from the field label ({FIRST_NAME}), the value goes into the active Params row, and a small prompt offers "Keep as variable · Use fixed text · Rename". An existing variable is reused when the value matches.
- **Q8 "Check this" offers every check the engine supports**:
  - text is / contains;
  - shown / gone;
  - control state (field value, ticked, selected, enabled);
  - numbers and patterns (greater/less than, between, regex, date format, item count);
  - "save as variable".
  - The expected value is prefilled from the live page and can be swapped for a variable.
- **Q9 Action menu:** a **smart shortlist** of 4–6 actions that fit the element, then a search box and "All actions" grouped Do · Type · Check · Save · Wait · Window & frames · Advanced. The engine has about 55 actions.
- **Q10 Locators are generated, never written by the user.**
  - A direct pick on the page targets **that exact element**, using whatever is unique and unlikely to change (id, test id, stable attribute, class plus position).
  - A generic "click button" action highlights **every match** and asks which one, then still builds a direct locator.
- **Q11 Data-driven targets.** After a pick, the inspector describes the element in plain words: button "Choose" · inside card "Max". Clicking a word turns it into a variable ({PLAN}); the tool rewrites the locator and re-checks it on the live page.
- **Q49 Locator backups.** Backup locators are stored with each step. On a later break the step still **fails**, with no silent healing. The failure shows "a backup found 1 likely match" with a screenshot, and the builder offers **"Accept new locator"** in one click.
- **Q51 Widgets collapse into one smart step**: "Pick date {DEPART_DATE} in Departure date" and "Choose {DESTINATION} from the suggestions". Raw clicks are kept only if the user declines.
- **Q41 Waits.** The recorder never adds fixed waits. The only wait offered is **"Wait until [element] shows / is gone / text is…"**, picked on the page. A fixed "Wait N s" sits under Advanced. Old fixed waits are kept, with a hint that the engine already covers them.
- **Q34 Windows, frames and Back.** The recorder adds switch-window, switch-frame and back steps by itself.
  - Cards carry a context tag ("Tab 2 · Policy details", "inside frame: card").
  - A new window becomes its own block on the map, with a "back to …" return line.
- **Q53 plus the user's addition: the page-arrival gate.**
  - Clicks and links usually load a new page. Many tests fail because they *assume* they're on the next page. Each page block can start with an optional **"Arrived at: Payment page"** gate. **A failed gate is always a hard stop.**
  - Pages are identified by a **page fingerprint defined once per workbook**: for example, URL contains `/purchase/payment` AND the heading "Payment details" shows. Both parts are picked on the live page.
  - When a click loads a new URL, the recorder proposes a fingerprint.
  - Design this visibly: a gate chip at the top of each page block, a fingerprint editor, and a clear hard-stop state in results.

### Running while building
- **Q12 "Run up to here"** replays steps 1..N. The session then **stays open**, so new or edited steps run from that point ("Run this step", "Run next 5"). A banner warns when earlier steps changed: "replay from the start to be sure".
- **Q13 Steps with real consequences.** Steps can be flagged **"has side effects"**; the tool suggests the flag for buttons named Purchase, Pay, Submit order and similar.
  - Build-mode replays stop before a flagged step and ask "Run it for real?".
  - PROD always blocks flagged steps.
  - Full runs are unaffected.

### Data and variables
- **Q24 Data drawer.** A bottom drawer shows the Params spreadsheet: rows = scenarios, columns = variables, with on/off per row.
  - A **"Building with: Row 1 · NE · Basic"** switch decides which row the preview and replays use.
- **Q23 Computed values.** A value builder offers Date (today ± N, format), Unique (run id, random email), Pick from list, Math (A − B) and Text join. It **writes a normal Excel formula**, shown in a Formula tab.
- **Q37 Variable names.** The user types a friendly label ("Traveler first name"); the builder creates an UPPER_SNAKE token (FIRST_NAME) and shows the label everywhere. Renaming updates every use across the workbook.
- **Q42 Secrets.**
  - Typing into a password field, or marking a value by hand, makes it a **secret variable**.
  - The workbook stores only `{SECRET:UAT_PASSWORD}`; the value goes to `secrets.env`, per environment.
  - Secrets show as •••• everywhere; "reveal" works only on the local machine.
- **Q43/Q44 Environments.**
  - A test should be identical across environments. Each workbook has an **environment-variables table**: rows = variables (DOMAIN is required, then API keys and anything else that differs), columns = environments (QA/UAT/PROD by default, editable, with renames and additions).
  - The run settings choose the environment, which fills these variables.
  - The recorder swaps the domain it sees for `{DOMAIN}`/`{BASE_URL}`.
  - Values and expected values normally don't differ, but the user can make any variable environment-specific.
  - **If a required environment variable is missing for the chosen environment, the run shows an error and refuses to start.**
  - Any environment marked "production" keeps the typed-confirmation guard and blocks danger steps.

### Flow control (Q25, Q27; reversed and then settled)
- **IF blocks branch on variables only.** They exist for data variants such as "with and without a promo code", where the same 290 steps would otherwise be duplicated.
- There is also one narrow **"If this popup shows, close it"** step for known interruptions. It is **always logged** in results ("appeared / did not").
- There is **no branching on step results.**
- **Loops repeat per data row only** ("for each row of Params_2", shown ×N on the map), mapped to ITERATION_START/END.
- **Q28 Legacy rows** the builder won't create (GO_TO_ROW, formula-driven blnExecute, SNAGIT_SCREENSHOT…) appear as locked **"legacy" cards** with a plain-language explanation. They can be moved or deleted, and edited in the Excel-grid view. They are kept byte-for-byte on save.

### API / XML and future types
- **Q18** There are three ways to create an API test step:
  - a **Postman-style form** (method, URL, headers, and a body with a variable picker);
  - **pasting cURL or importing a Postman collection**;
  - **choosing from the existing API template files** (the Replace/Output system).
  - Not from the site's recorded traffic.
- **Q19** "Send now" shows the real response as a **clickable tree**. Clicking a value opens the same Check/Save pop-up; the JSON path or XPath is written for the user but **stays visible and editable**. For arrays, the pop-up asks "this item" or "the item where plan = {PLAN}".
- **Q47** Leave slots in the design for future test types: **Email inbox, Documents (PDF/files), Database/SQL, SOAP/message queues.** Adding one should just mean a new kind of test or block.
- **Q48** There is no AI assistant yet, but leave a spot for one: a "Describe a step…" entry in the add-step menu.

### Workbook level
- **Q22 The first screen is the workbook map.**
  - Every test is a card: type icon, step count, last result, whether it runs.
  - Lines show "calls" and "needs a value from".
  - The workbook name, environment and settings sit at the top.
- **Plus a variable map.** Every variable is listed; clicking one shows **who sets it and who uses it**, and clicking any of those jumps straight to that step.
- **Q46 DataSheets settings live on the workbook map**: each card has an on/off switch, its Params sheet, tags and a comment. Run order follows dependencies (left to right), with manual order where no dependency exists.
- **Q45 New workbook** is one setup screen: the name (shown as the .xlsx filename), environments plus DOMAIN per environment, and optionally "start from" an existing workbook or templates. It then lands on an empty workbook map with "+ New test" and "Record a test".
- **Q35/Q36 Concurrency scenarios.** These are a new workbook item, a **scenario board with lanes**.
  - Each lane is an existing test, or the same test twice with its own data row.
  - **Sync lines** across the lanes mean "all wait here"; order markers mean "A before B".
  - A scenario runs as one unit and reports per lane.
  - The purpose is concurrency cases (two users editing one policy), not throughput.

### Safety, problems and results
- **Q31** Problems (variable used but never set, missing expected value, locator not found last run, unmapped template variable, danger step on PROD, missing environment value) appear **live** as red or amber dots on cards and map blocks, plus a "Problems (N)" panel. **Saving is never blocked.**
- **Q32/Q33** Every failed step in Results gets **"Fix in builder"**. It opens that step with the failure screenshot and error beside the inspector, plus "Replay up to here" and "Re-pick element". Cards show a last-run pass/fail dot.
  - The builder also flags failures from recent runs **on its own** ("step 211 failed on the last run").
  - That flag is a **passive badge**: there is no Ignore button, the user can simply do nothing, and it never blocks saving.
- **Q29** If the file changes on disk or is open in Excel, the builder detects it and offers reload or merge with a per-step diff. If Excel holds a lock, saving waits with the message "Close it in Excel to save".
- **Q30 Saving.** Every edit **autosaves to a draft**. **"Save to Excel"** writes the real `.xlsx` and keeps a timestamped backup. A **History** panel restores any save, with a diff.

## Screens to design (Q52: all of them)

1. **Test editor (mix layout)**, updated with every decision above: gate chips, the data drawer, the problems panel, failure badges, side-effect flags, context tags, legacy cards, the IF lane (variables only) and the loop block. Show the grid toggle and the inspector for web, API and check steps.
2. **Workbook map + variable map.**
3. **Recording window**: the site with the floating pill, hover outline, action shortlist card, the "Check this" pop-up (all check kinds + save as), the "which one?" multi-match highlight, the data-target "make this part a variable" step, and the typed-value → variable prompt.
4. **API/XML test editor** (form, cURL import, templates, clickable response tree) **+ concurrency scenario board.**
5. **Setup and dialogs**:
   - new workbook;
   - the environment-variables table;
   - template insert with variable mapping;
   - Duplicate → "What changes?" plus find-and-replace;
   - the run-blocked error for a missing DOMAIN;
   - the page-fingerprint editor;
   - "Run it for real?" for side-effect steps;
   - file changed on disk;
   - History.
6. **Run-section enhancements** (see the engineering file, "Run section"): design the Run/Results changes they need, including scenario runs per lane, the missing-environment-variable block, Fix in builder, gate hard-stop display, and the locator-suggestion card on failures.
7. Light theme variants of at least the editor and the workbook map.

Use a realistic example throughout, such as the Travelex purchase flow in round 1 or a Qantas workbook with `purchase#1` calling `policySearch#1`. Don't use lorem ipsum.
