# Workbook Builder: the user's feedback after trying it (2026-09-28)

The user tried the Build tab after P11 and listed what got in the way. They asked for it as a running tally, actioned in batches.
Batch 1 (items 1-8) and batch 2 (items 9-25) are done; item 26 is open. Each line says what the user asked for and
what was found in the code, so the next session does not have to re-derive it.

## Batch 1: done

1. **Element picker you can find.** The inspector shows "On which element" for every step whose method acts on an element (`Step.element`,
   new in CONTRACT.md 2.3), even before it has one: FindBy select, a locator field you can type or paste into (an empty FindBy is guessed
   from the text: `//` = XPath, `#`/`.`/`[`/space = CSS, a bare word = id), and "Pick on the page" (opens the site first when needed).
2. **"All workbooks"** (`#/build/all`): a page of workbook cards (the whole card opens one), reached from the header's grid button and the
   top of the rail. `S.build.listing` shows it over whatever workbook is loaded.
3. **Download** (`GET /api/workbooks/{name}/download`): header button beside Save and on each workbook card; with unsaved edits it asks to
   save first.
4. **"Production" column wording.** No screenshot came, so this is the wording fix: "Is it production?" with "Production" / "Not production"
   beside each tick, in the new-workbook dialog and (new) in the Environments dialog, where it could not be changed before.
5. **Closing the build window by hand** now closes the session (`BuildSession._page_closed` -> `_close_if_windowless` after
   `WINDOWLESS_GRACE_S`); the browser used to keep running with no window, so the Build tab still said "open" and Pick had no page.
6. **Done on the pill** stops picking and recording (`kind: "done"`); `Recorder.finish` keeps a `summary` (count, rows, first/last step);
   the Build tab jumps to the first recorded step and shows "Recorded N steps (steps X-Y)" with Show them / Remove them (one undoable edit).
7. **"Open the site" opens the environment's Domain** (`BuildSession.domain`, the `DOMAIN` row of `_rr_environments`) when the test has no
   Open step; none set = blank page + a notice with a link to Environments. Recording an empty test starts it with `OPEN {DOMAIN}`.
8. **"Selected" bar** wraps inside its column (`.bulk-bar` in app.css) instead of overflowing a narrow window.

## Batch 2: done 2026-09-28 (items 9-25; how each was built: `dev/claude/AGENTS.md` section 9 and the commit messages)

9. **Run plan Timeline** (Run tab, `views/newrun.js` `timelineView`): cut off and unreadable on small screens. Scroll sideways at least, test
   names stay readable.
10. **Page change while recording**: add the ASSERT_PAGE gate + fingerprint automatically (today `Recorder._propose_fingerprint` only
    proposes it as a prompt), shown as a normal step with undo; reuse a known fingerprint. Ask the user first if they never saw the prompt
    at all (that would be a bug of its own).
11. **New page (block)**: "Start new page here" on a step and in the add-step menu (the `split_block` op exists, no UI calls it), "New page"
    at the end of the block strip, recording starts a new block on a page change (goes with 10). Also check: `move_steps` without `before`
    moves the steps to the end of the test, so "Move to block..." into an existing block that is not the last looks wrong (verify first).
12. **Variables tab you can edit**: add / rename / edit / delete variables there (Params columns, environment values per environment,
    secrets). Today `variableMap` in `views/build/workbook.js` is read-only; Environments stays for domains and which one is production.
13. **API headers**: "+ Header" adds an empty row typed into directly (today two `window.prompt`s in `api_editor.js`), and a header's name
    can be changed after it is created.
14. **API checks**: a whole-response check with an "ignore these fields" list (timestamps, ids), as well as the per-value ones (needs an
    engine change in `engine/api_runner.py` as well as the UI); add a check by hand without Send now (type the path and expected); "New
    variable" in Insert variable; a clear warning that Send now is a real request.
15. **Status never checked**: an API test with `RES_STATUS_CD_EXP` but no `compare` row in `InputOutput` never checks the status (seen in
    `qantas-test 2.xlsx` PolicySearch). A builder problem that offers to add the compare row.
16. **One "API test" kind**: no API vs XML choice. `Content-Type` is just a header row, `application/json` by default, edited like any other;
    the builder writes `JSON_FORMAT` from it (or from what the response looks like). Use the `<>` icon, not the cloud. Existing XML tests
    open as API tests with their XML Content-Type.
17. **Test map cards clickable as a whole** (`views/build/workbook.js` `testCard`): today only the title opens the test; the run toggle and
    other buttons on the card keep doing only their own job.
18. **No "default" environment for builder workbooks: the run picks it.** The user was clear: no "Workbook default" choice and no
    Global `Environment` value to fall back on. The Run tab's environment choice lists exactly the environments the workbook's
    `_rr_environments` defines, one must be picked, and the run uses that one. Today `views/newrun.js` `envDefs` is a fixed Workbook
    default / QA / UAT / PROD list, and `new_workbook` (`workbook/builder.py`) writes Global `Environment` = the first environment.
    To settle when building it: what `regrunner run` does for such a workbook without `--env` (refuse with a clear message, like the
    `env_missing` check, rather than guess); the Build tab's environment switch and the scenario board's "Run it on ..." (which fall back to
    the workbook's default today); legacy workbooks (no `_rr_environments`) keep today's behaviour.
19. **Results tab stays the Results tab**: a solo run opened from the Results history (`views/results/history.js` `itemUrl`, also
    `results/batch.js` and `results/test.js` links, `results/actions.js` after a re-run) goes to `#/run/<id>`, which switches to the Run
    tab. Show that run inside the Results tab instead.
20. **Drag to reorder steps** in the test editor's step cards (and across blocks). The `move_steps` op already takes `before` (and `block`),
    so this is UI work in `views/build/editor.js` / `actions.js`; today steps only move through "Move to block..." (which, without
    `before`, sends them to the end of the test: see item 11).
21. **"Selected" bar next to the selection**: show it just below the last ticked step card (above it when there is no room below) instead
    of pinned to the bottom of the column, and let it be dragged by a grip like the build window's pill (`build/overlay.js` `drawPill`,
    `st.pos`); remember where it was dragged for the session. The bar is `bulkBar` in `views/build/editor.js`, `.bulk-bar` in app.css
    (made to wrap in batch 1, item 8).
22. **Grid view is not a readable table**: `.gcell` (app.css) sets `display: flex` on every `<th>`/`<td>` of `gridView`
    (`views/build/editor.js`), so the cells stop being table cells and the columns do not line up. Make them real table cells again
    (fixed height via line-height/padding, borders, sticky header), plus what makes a sheet readable: a row-number column that matches the
    step's Excel row, the selected step's row highlighted, zebra rows, wide columns (FindBy_Value, Value) truncated with the full text on
    hover. Check it with a screenshot.
23. **The Build tab button always opens All workbooks** (`#/build/all`), never the last workbook/test edited. Today `goBuildTab` in
    `views/build/actions.js` goes to `defaultBuildName()`'s map (and plain `#/build` in `main.js` does the same). Links that name a
    workbook or step (Fix in builder, jumpToStep, a workbook card) keep going straight there.
24. **Environments visible in the downloaded file**: `_rr_environments` is a hidden sheet, so someone opening a downloaded workbook in Excel
    only sees Global (`Environment = QA`) and thinks the other environments are gone. Make it visible (maybe renamed so it is obvious,
    e.g. "Environments (builder)": every reader of `_rr_environments` must follow the rename, including `engine/gates.py` and
    `workbook/variables.py`), and have Download say when the workbook uses `{SECRET:NAME}` values, which live in secrets.env, not in the
    file.
25. **API tests wait for every website test even when they are independent.** `engine/order.py` (`plan_order`, `order.after_ui`): an
    API test that no chain names and that no UI test reads from gets a dependency on *every* UI test of the run ("an API test reads what
    those tests produce"), so with 3 workers the user's test-functionality workbook runs the website test first and the API/XML tests
    after it. The real links are already detected separately (an API row's formula reading another sheet's cell, `{NAME}` Needs/Provides).
    Make an API test wait only for the tests it actually reads from; otherwise it runs at once like any other test. Check first why the
    blanket rule was added (legacy runner order? `~/Downloads/TG_Testing_Framework_py3_v4.2.zip` is only on the user's Mac) and whether
    the real workbooks (Qantas PolicySearch reads `AgentPortal_Params` cells) still get their wait from the detected links. Update the
    "starts after every UI test" note, the Run plan Order/Timeline views follow `deps`. Tests: `test_run_order.py`, `test_api_tests.py`.

## Open

26. **A formula pointing into another workbook evaluates to `#NAME?`.** In `UAT DT_Qantas StandAlone_Staff Daily Regression_v1.1.xlsx`,
    AgentStandAlone's payment branch is switched by `blnExecute` formulas like `=IF([4]Global!$B$2="PROD","N",A397)`; `[4]` is an external
    workbook, which `workbook/formula.py` cannot evaluate, so the branch (rows ~398-414 and copies) probably never runs and never captures
    `DT_Policy_Out`. Since item 25, PolicySearch then says "Not run: ... AgentStandAlone should have set it" instead of asking for the value.
    Likely fix: read Excel's cached values of external references from `xl/externalLinks/externalLink4.xml`. Check against the legacy runner.
    Also: the server's own PROD confirmation still only looks at an environment literally named PROD (the UI also asks for one the table marks
    production).

Also told the user: `workbooks/qantas-test 2.xlsx` is saved with Global Environment = PROD.
