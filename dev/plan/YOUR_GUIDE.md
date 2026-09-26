# Your guide: building the Workbook Builder, one chat at a time

You don't manage branches or pull requests. Each chat makes its own, and a review chat checks and merges it and cleans up the branch.
Your job is to **start the chats in the order below and paste the text**.

---

## One-time setup (5 minutes, do this once)

1. On GitHub, open the repository **raphinitum95/claude** → **Settings** → **General** → **Default branch** → switch it to **qa-regression**.
   (It currently points at an old branch, `claude/sharp-lovelace-elfypo`. After switching, you can delete that old branch on the **Branches** page.)
2. That's it. Every new chat sets up its own tools automatically.

---

## How to start a chat (same every time)

1. Go to **claude.ai/code** and start a **new session**.
2. Repository: **raphinitum95/claude**. Branch: **qa-regression**.
3. Model: pick the one the step says (**Opus** or **Sonnet**) in the model menu.
4. Paste the text from the step. Press Enter.
5. Leave it alone until it says it opened a pull request (PR). If it asks you something, answer in a sentence.

**Two kinds of chats:**
- A **work chat** builds one piece and opens a PR.
- A **review chat** (always **Sonnet**) checks that PR, merges it and deletes its branch. Start one after every work chat finishes.

---

## The steps, in order

Steps marked **"can run together"** can be open in separate chats at the same time. Everything else: wait until the previous
review chat says it merged.

### Step 1 · Excel writer (Opus)
Work chat:
```
Build phase P01 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P01-excel-writer.md and follow them exactly. Open a PR into qa-regression when done.
```
Then review chat (Sonnet):
```
Review phase P01 of the Workbook Builder. Follow the "Review session" section of dev/plan/PLAN.md: check the open PR for P01, run its tests, fix small problems, then merge it into qa-regression and delete its branch.
```

### Step 2 · The builder model and the contract (Opus)
```
Build phase P02 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P02-builder-model.md and follow them exactly. Open a PR into qa-regression when done.
```
Review (Sonnet): same review text as step 1, with **P02** instead of P01.

### Step 3 · three pieces that can run together
Open three chats at once (or one after the other, your choice):

- **Opus:**
  ```
  Build phase P03 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P03-engine-variables-flow.md and follow them exactly. Open a PR into qa-regression when done.
  ```
- **Sonnet:**
  ```
  Build phase P04 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P04-build-ui.md and follow them exactly. Open a PR into qa-regression when done.
  ```
- **Sonnet:**
  ```
  Build phase P05 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P05-run-tab.md and follow them exactly. Open a PR into qa-regression when done.
  ```
Review each one separately (Sonnet), **one review at a time**, using the review text with P03, then P04, then P05.

### Step 4 · two pieces that can run together
- **Sonnet:** `Build phase P06 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P06-results-tab.md and follow them exactly. Open a PR into qa-regression when done.`
- **Opus:** `Build phase P07 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P07-engine-gates-checks.md and follow them exactly. Open a PR into qa-regression when done.`

Review each (P06, then P07).

### Step 5 · The live browser for building (Opus)
`Build phase P08 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P08-build-session.md and follow them exactly. Open a PR into qa-regression when done.`
Review P08.

### Step 6 · three pieces that can run together
- **Opus:** `Build phase P09 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P09-recorder.md and follow them exactly. Open a PR into qa-regression when done.`
- **Opus:** `Build phase P10 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P10-api-xml.md and follow them exactly. Open a PR into qa-regression when done.`
- **Sonnet:** `Build phase P11 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P11-templates-refactor.md and follow them exactly. Open a PR into qa-regression when done.`

Review each (P09, P10, P11).

### Step 7 · Scenarios (Opus)
`Build phase P12 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P12-scenarios.md and follow them exactly. Open a PR into qa-regression when done.`
Review P12.

### Step 8 · Finish and full test run (Sonnet)
`Build phase P13 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P13-polish.md and follow them exactly. Open a PR into qa-regression when done.`
Review P13. Done.

---

## When something goes off track

**A chat stopped halfway, got very long or seems stuck.** Stop it. Start a new chat with the same model and paste
(change the phase number and file name):
```
Continue phase P03 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P03-engine-variables-flow.md, including its Progress section, and pick up where the last session stopped. Open a PR into qa-regression when done (or update the existing one).
```

**The review chat didn't merge and left notes on the PR.** Start a new work chat (same model as the phase) and paste:
```
Fix the review notes on the open PR for phase P03 of the Workbook Builder. Read dev/plan/PLAN.md and dev/plan/phases/P03-engine-variables-flow.md first. Push the fixes to the same PR.
```
Then run the review chat again.

**It asks you a real question** (for example, how something should behave): answer in one or two sentences. It's in the plan to only ask
when the decision is yours.

**Where am I?** Open `dev/plan/PLAN.md` on GitHub: the **Status** table at the bottom shows what's merged.

---

## Keeping it cheap

- **One chat per step.** Don't reuse an old chat for the next step: a fresh chat is much cheaper than a long one.
- **Don't chat with a work chat while it works**, unless it asks you something.
- Use the model the step says. Sonnet costs less; Opus is only used for the hard engine and browser parts.
- Don't ask a chat to "check everything" or run all tests. Each step already says which tests to run (step 8 runs everything once).
