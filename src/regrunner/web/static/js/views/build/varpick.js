// "Use a variable" beside a step's Value and Expected (inspector), and the copy choice of a unique variable (brief:
// dev/claude/CONTEXT_unique_variables.md). A unique variable's steps name a copy: {LASTNAME#2}. Where a step types the value it gets
// "an existing one" (#1, #2... every number the workbook already uses) or "a new one" (the next free number, so the numbering is the same on
// every run); where a step only reads it (Expected, a check) it gets first / last / #N. The person picks words, never types the #.
// copyChoices / makesCopies are shared with the check card (record.js).
import { rerender } from '../../state.js';
import { html } from '../../util.js';
import { icon } from '../../icons.js';
import { bm, currentTest, updateStep } from './actions.js';

const CHECKING = new Set(['OUTPUT', 'EXIST', 'NOT_EXIST', 'WAIT_UNTIL', 'ASSERT_PAGE', 'IF', 'DISMISS_IF_SHOWN']);   // (variables.py CHECKING_METHODS)
const COPY_RE = /\{([A-Za-z_][A-Za-z0-9_]*)#(\d+|first|last)\}/gi;

/** Does a {NAME#2} in this field of this step make the copy (a step that types it), or only read it (a check)? Same rule as variables.makes_copies. */
export function makesCopies(method, field) {
  const m = String(method || '').toUpperCase();
  return field === 'value' && !CHECKING.has(m) && !m.startsWith('CHECK_');
}

/** The choices for a unique variable `v`: [{token, label, hint, warn}]. `makes`: the step types it (existing numbers + a new one), else it reads
 *  it (first / last / every number). With only one number in the workbook a read is pinned to #1 and says so. */
export function copyChoices(v, makes) {
  const nums = (v.copies || []).slice().sort((a, b) => a - b);
  const made = new Set(v.copiesMade || []);
  const next = (nums.length ? nums[nums.length - 1] : 0) + 1;
  const tok = (w) => `{${v.token}#${w}}`;
  if (makes) {
    return [...nums.map((n) => ({ token: tok(n), label: `${v.label} #${n}`, hint: made.has(n) ? 'the same value as the other steps that use it' : 'only checked so far: this step makes it' })),
      { token: tok(next), label: `A new one (#${next})`, hint: 'a fresh value, made the first time a run reaches this step' }];
  }
  if (nums.length <= 1) {
    return [{ token: tok(nums[0] || 1), label: `${v.label} #${nums[0] || 1}`, hint: '',
      warn: nums.length ? `Only one ${v.label} exists, so this uses #${nums[0]}. If more get added later, it stays on #${nums[0]}.`
        : `No step makes a ${v.label} yet: this check fails until one types ${tok(1)}.` }];
  }
  return [{ token: tok('first'), label: `The first ${v.label}`, hint: `the lowest number made in the run (#${nums[0]})` },
    { token: tok('last'), label: `The last ${v.label}`, hint: `the highest number made in the run (#${nums[nums.length - 1]} when every step ran)` },
    ...nums.map((n) => ({ token: tok(n), label: `${v.label} #${n}`, hint: made.has(n) ? '' : 'no step types it', warn: made.has(n) ? '' : `No step types ${tok(n)}: this check fails.` }))];
}

const vp = { row: null, field: '', token: '' };      // the open picker: which step, which field, which unique variable (after the first choice)

/** The "Use a variable" button for `field` ('value' | 'expected') of step `s`; its panel (`varPickPanel`) goes under the field's label row. */
export function varPick(s, field) {
  const open = vp.row === s.row && vp.field === field;
  return html`<button class="btn btn-ghost btn-sm" style="height: 22px; font-size: 11px; padding: 0 6px" data-act="build-varpick-open" data-row="${s.row}" data-field="${field}" aria-expanded="${String(open)}">${icon('braces', 11)} Use a variable</button>`;
}

export function varPickPanel(s, field) {
  return vp.row === s.row && vp.field === field ? panel(s, field) : '';
}

function panel(s, field) {
  const m = bm();
  const makes = makesCopies(s.method, field);
  const v = vp.token && m.variables.find((x) => x.key === vp.token);
  if (v) {
    const choices = copyChoices(v, makes);
    return html`<div class="card" style="padding: 10px; display: flex; flex-direction: column; gap: 6px; width: 100%" id="build-varpick">
<div style="display: flex; align-items: center; gap: 8px"><b style="font-size: 12.5px">${makes ? `Which ${v.label} does this step type?` : `Which ${v.label} should it be?`}</b><span style="flex: 1"></span>
<button class="lnk" data-act="build-varpick-back">Other variable</button></div>
${choices.map((c) => html`<button class="card" style="text-align: left; padding: 8px 10px; display: flex; flex-direction: column; gap: 2px" data-act="build-varpick-copy" data-val="${c.token}">
<span style="font-size: 12.5px; font-weight: 600">${c.label}</span>${c.hint ? html`<span style="font-size: 11.5px; color: var(--tx3)">${c.hint}</span>` : ''}
${c.warn ? html`<span style="font-size: 11.5px; color: var(--warn)">${icon('warn', 11)} ${c.warn}</span>` : ''}</button>`)}</div>`;
  }
  const list = m.variables.filter((x) => !x.secret);
  return html`<div class="card" style="padding: 10px; display: flex; flex-direction: column; gap: 4px; width: 100%; max-height: 260px; overflow: auto" id="build-varpick">
${list.length ? list.map((x) => html`<button class="rail-item" style="height: auto; padding: 6px 8px" data-act="build-varpick-var" data-val="${x.key}">
<span style="display: flex; flex-direction: column; min-width: 0; flex: 1; text-align: left"><span style="font-weight: 600">${x.label}${x.unique ? html` <span class="tag" style="margin-left: 4px">new each run</span>` : ''}</span>
<span class="mono trunc" style="font-size: 10.5px; color: var(--tx3)">{${x.token}${x.unique ? '#…' : ''}}</span></span></button>`)
    : html`<span style="font-size: 12px; color: var(--tx3)">No variables yet: add one on the Variables screen.</span>`}</div>`;
}

/** Warnings under a step's fields: a read pinned to the only copy that exists (it will not follow copies added later). */
export function copyNotes(s) {
  const m = bm();
  const out = [];
  for (const [field, text] of [['value', s.value], ['expected', s.expected]]) {
    if (makesCopies(s.method, field)) continue;
    for (const [, name, which] of String(text || '').matchAll(COPY_RE)) {
      const v = m.variables.find((x) => x.key === name.toUpperCase());
      if (v && v.unique && /^\d+$/.test(which) && (v.copies || []).length === 1) {
        out.push(`Only one ${v.label} exists, so this uses #${which}. If more get added later, it stays on #${which}.`);
      }
    }
  }
  return out.length ? html`${[...new Set(out)].map((w) => html`<div class="bn bn-warn" style="font-size: 12px">${icon('warn', 13, 'color: var(--warn)')}<span>${w}</span></div>`)}` : '';
}

function insert(token) {
  const t = currentTest();
  const s = t && t.steps.find((x) => x.row === vp.row);
  if (!s) return;
  const el = document.querySelector(`[data-input="build-step-${vp.field}"][data-row="${s.row}"]`);
  const now = el ? el.value : (s[vp.field] || '');
  const next = /^\s*(\{[^{}]*\})?\s*$/.test(now) ? token : now + token;     // (a field holding one variable gets the new one instead; text keeps it)
  if (el) el.value = next;
  updateStep(s.row, { [vp.field]: next });
  vp.row = null; vp.field = ''; vp.token = '';
  rerender();
}

export const acts = {
  'build-varpick-open'(el) {
    const row = Number(el.dataset.row);
    const same = vp.row === row && vp.field === el.dataset.field;
    vp.row = same ? null : row; vp.field = same ? '' : el.dataset.field; vp.token = '';
    rerender();
  },
  'build-varpick-var'(el) {
    const v = bm().variables.find((x) => x.key === el.dataset.val);
    if (!v) return;
    if (v.unique) { vp.token = v.key; rerender(); return; }
    insert(`{${v.token}}`);
  },
  'build-varpick-copy'(el) { insert(el.dataset.val); },
  'build-varpick-back'() { vp.token = ''; rerender(); },
};
