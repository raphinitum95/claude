// Recording and "Check this / Save this / Wait until" in the Build tab (P09, build/recorder.py). The build window's strip gets ● Rec and the
// Check / Save / Wait until modes; the inspector shows what the recorder asks (typed text -> variable, a password -> secret, widget steps, a new
// page's fingerprint) and, after a pick in Check / Save / Wait mode, the same card the page shows: every kind, prefilled from the live element.
import { S, rerender } from '../../state.js';
import { html, raw, toast } from '../../util.js';
import { icon } from '../../icons.js';
import { sess, call } from './session.js';
import { selectedStep } from './actions.js';

const NEEDS_EXPECTED = new Set(['text_is', 'text_contains', 'value', 'ticked', 'selected', 'enabled', 'gt', 'lt', 'between', 'regex', 'date_format', 'count', 'wait_text']);
const CHOICE_WORDS = { keep: 'Keep as variable', fixed: 'Use fixed text', rename: 'Rename…', raw: 'Keep raw clicks', gate: 'Save fingerprint + add gate',
  edit: 'Edit', unflag: 'Not a side effect', dismiss: 'OK', ungate: 'Remove the check', regate: 'Save the fingerprint' };

// What is being typed in the card (module state: the card is rebuilt on every poll).
// `source` = where the expected value comes from: 'page' (read from the live page now), 'variable' (`{TOKEN}`, read when the test runs) or 'own' (typed).
const ui = { cardId: null, kind: '', expected: '', source: 'own', variable: '', search: '', insertOpen: false, token: '', alsoSave: '', fp: {} };

const liveOf = (form, kind) => ((form.kinds.find((x) => x.id === kind) || {}).expected || '');

function formOf(st) {
  const card = st && st.pick && st.pick.card;
  const form = card && card.form;
  if (!form) return null;
  if (ui.cardId !== card.id) {
    const live = liveOf(form, form.chosen);
    Object.assign(ui, { cardId: card.id, kind: form.chosen || '', expected: live, source: live ? 'page' : 'own', variable: '', search: '', insertOpen: false, token: form.token || '', alsoSave: '' });
  }
  return form;
}

/** Switch where the expected value comes from; what is typed carries over (page -> own starts from what was read). */
function setSource(form, source) {
  ui.source = source;
  ui.search = '';
  ui.insertOpen = false;
  if (source === 'page') ui.expected = liveOf(form, ui.kind);
  else if (source === 'variable') {
    if (!ui.variable) { const m = (form.variables || []).find((v) => v.match); ui.variable = m ? m.token : ''; }   // (one that equals the page now is the likely one)
    ui.expected = ui.variable ? `{${ui.variable}}` : '';
  }
}

/** Can Add be pressed?  A check that reads a variable needs one chosen; every other case is validated by the server with a plain message. */
const ready = (form) => !!ui.kind && !(NEEDS_EXPECTED.has(ui.kind) && ui.source === 'variable' && !ui.variable);

async function edit(what, body) {
  try {
    const res = await call(what, body);
    if (res && res.model) { S.build.model = res.model; rerender(); }
    return res;
  } catch (e) { return null; }                                         // (call() showed it)
}

// ---- actions ---------------------------------------------------------------------------------------------------------------------------
async function toggleRecord(after) {
  const st = sess();
  const on = !(st && st.record && st.record.on);
  const s = selectedStep();
  try { await call('record', on ? { on, after: after != null ? after : (s ? s.row : undefined) } : { on }); } catch (e) { return; }
  if (on) toast('Recording: your clicks, typing and choices in the build window become steps.', 3500);
}

async function setMode(mode) {
  const st = sess();
  const next = st && st.mode === mode ? 'browse' : mode;
  const s = selectedStep();
  try { await call('pick', { mode: next, row: s ? s.row : undefined }); } catch (e) { return; }
  if (next !== 'browse') toast('Click the element in the build window.', 3000);
}

async function addCheck() {
  const st = sess();
  const form = formOf(st);
  if (!form || !ui.kind) return;
  const body = { kind: ui.kind, expected: ui.expected };
  if (form.purpose === 'save') body.token = ui.token;
  else if (ui.alsoSave.trim()) body.token = ui.alsoSave.trim();
  const res = await edit(form.purpose === 'save' ? 'save' : 'check', form.purpose === 'save' ? { token: ui.token } : body);
  if (res) { ui.cardId = null; toast(`Added step ${form.n}.`, 2500); }
}

async function answer(el) {
  const id = el.dataset.id;
  const choice = el.dataset.choice;
  const body = { id, choice };
  if (choice === 'rename') {
    const token = window.prompt('A name for the variable (letters, digits and _):', el.dataset.token || '');
    if (!token || !token.trim()) return;
    body.token = token.trim().toUpperCase();
  }
  if ((choice === 'gate' || choice === 'regate') && ui.fp[id]) body.fields = ui.fp[id];
  await edit('prompt', body);
  delete ui.fp[id];
}

export const recordActs = {
  'build-rec-toggle'() { toggleRecord(); },
  'build-rec-here'() { S.build.ed.menu = false; toggleRecord(); },
  'build-rec-mode'(el) { setMode(el.dataset.mode); },
  'build-rec-kind'(el) {
    const form = formOf(sess());
    const k = form && form.kinds.find((x) => x.id === el.dataset.kind);
    if (!k || !k.enabled) return;
    ui.kind = k.id;
    if (ui.source === 'variable') setSource(form, 'variable');                // (the variable still applies to the new kind)
    else { ui.expected = k.expected || ''; ui.source = ui.expected ? 'page' : 'own'; }
    rerender();
  },
  'build-rec-use-var'(el) { const form = formOf(sess()); if (form) { ui.variable = el.dataset.token; setSource(form, 'variable'); rerender(); } },
  'build-rec-pick-var'(el) { ui.variable = el.dataset.token; ui.expected = `{${ui.variable}}`; rerender(); },
  'build-rec-insert-var'(el) { ui.expected = `${ui.expected}{${el.dataset.token}}`; ui.insertOpen = false; ui.search = ''; rerender(); },     // (typed text: add one to what is there, e.g. {LOW};{HIGH})
  'build-rec-insert-toggle'() { ui.insertOpen = !ui.insertOpen; ui.search = ''; rerender(); },
  'build-rec-source'(el) { const form = formOf(sess()); if (form && !el.disabled) { setSource(form, el.dataset.source); rerender(); } },
  'build-rec-add': addCheck,
  async 'build-rec-cancel'() { ui.cardId = null; try { await call('pick', { mode: 'browse' }); } catch (e) { /* shown */ } },
  'build-rec-prompt'(el) { answer(el); },
  'build-rec-fp-edit'(el) {
    const st = sess();
    const p = st && st.record && st.record.prompts.find((x) => x.id === el.dataset.id);
    if (!p) return;
    if (ui.fp[p.id]) delete ui.fp[p.id];
    else ui.fp[p.id] = { name: p.name, urlContains: p.urlContains, landmark: p.landmark, landmarkText: p.landmarkText };
    rerender();
  },
};

export const recordInputs = {
  'build-rec-expected'(el) { ui.expected = el.value; },
  'build-rec-var-search'(el) { ui.search = el.value; rerender(); },
  'build-rec-token'(el) { ui.token = el.value; },
  'build-rec-also'(el) { ui.alsoSave = el.value; },
  'build-rec-fp'(el) { const f = ui.fp[el.dataset.id]; if (f) f[el.dataset.field] = el.value; },
};

// ---- rendering ---------------------------------------------------------------------------------------------------------------------------
/** In the build window's strip: ● Rec and the Check / Save / Wait until modes. */
export function recordButtons(st, disabled) {
  const on = !!(st.record && st.record.on);
  const dis = disabled ? raw('disabled') : '';
  return html`<button class="btn btn-sm${on ? ' rec-on' : ''}" data-act="build-rec-toggle" ${dis} title="${on ? 'Stop recording' : 'Record: clicks, typing and choices in the build window become steps after the selected one'}"><span class="rec-dot"></span>${on ? `Recording · ${st.record.count}` : 'Rec'}</button>
${[['check', 'Check'], ['save', 'Save'], ['wait', 'Wait until']].map(([mode, label]) => html`<button class="btn btn-sm ${st.mode === mode ? 'btn-pri' : 'btn-ghost'}" data-act="build-rec-mode" data-mode="${mode}" ${dis} title="${label}: click an element in the build window">${label}</button>`)}`;
}

function promptCard(p) {
  const fp = ui.fp[p.id];
  const page = p.kind === 'fingerprint' || p.kind === 'gate_added';
  const tone = p.kind === 'secret' || p.kind === 'side' ? 'warn' : page ? 'pass' : 'acc';
  const ico = p.kind === 'secret' ? 'lock' : page ? 'gate' : p.kind === 'widget' ? 'bolt' : p.kind === 'side' ? 'bolt' : 'braces';
  return html`<div class="card sess-card" data-key="rp-${p.id}"><div style="display: flex; gap: 8px; align-items: flex-start">${icon(ico, 14, `color: var(--${tone}); margin-top: 2px; flex: none`)}
<div style="display: flex; flex-direction: column; gap: 3px; min-width: 0"><b style="font-size: 12.5px">${p.text}</b>${p.detail ? html`<span style="font-size: 11.5px; color: var(--tx3)">${p.detail}</span>` : ''}
${p.n ? html`<span class="mono" style="font-size: 10.5px; color: var(--tx3)">step ${p.n}${p.tag ? ` · ${p.tag}` : ''}</span>` : ''}</div></div>
${fp ? html`<div style="display: flex; flex-direction: column; gap: 6px">${[['name', 'Name'], ['urlContains', 'URL contains'], ['landmark', 'Landmark'], ['landmarkText', 'Landmark text']].map(([k, label]) => html`<label style="display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--tx3)">${label}
<input class="fld mono" style="height: 28px; font-size: 11.5px" value="${fp[k] || ''}" data-input="build-rec-fp" data-id="${p.id}" data-field="${k}"></label>`)}</div>` : ''}
<div style="display: flex; flex-wrap: wrap; gap: 6px">${(p.choices || []).map((c) => html`<button class="btn btn-sm ${c === 'keep' || c === 'gate' ? 'btn-pri' : ''}" data-act="${c === 'edit' ? 'build-rec-fp-edit' : 'build-rec-prompt'}" data-id="${p.id}" data-choice="${c}" data-token="${p.token || ''}">${c === 'edit' && fp ? 'Close editor' : c === 'dismiss' && p.kind === 'fingerprint' ? 'Not now' : CHOICE_WORDS[c] || c}</button>`)}
${fp && p.kind === 'gate_added' ? html`<button class="btn btn-sm btn-pri" data-act="build-rec-prompt" data-id="${p.id}" data-choice="regate">${CHOICE_WORDS.regate}</button>` : ''}</div></div>`;
}

const SOURCES = [['page', 'From the page'], ['variable', 'From a variable'], ['own', 'Type my own']];
const VAR_GROUPS = { data: 'Test data', saved: 'Saved by earlier steps', environment: 'Environment' };
const COMPARES_TEXT = new Set(['text_is', 'text_contains', 'value', 'selected', 'ticked', 'enabled', 'wait_text']);   // (a check where the page's own value is what should be expected)
const clip = (t, n) => (t.length > n ? `${t.slice(0, n - 1)}…` : t);

/** The variables a search finds: its name or its value contains every word typed ("first na" finds FIRST_NAME); names that start with it come first. */
export function findVariables(vars, query) {
  const words = String(query || '').toLowerCase().split(/[\s_]+/).filter(Boolean);
  if (!words.length) return vars;
  const rank = (v) => {
    const name = v.token.toLowerCase().replace(/_/g, ' ');
    const hay = `${name} ${String(v.value || '').toLowerCase()}`;
    if (!words.every((w) => hay.includes(w))) return -1;
    return name.startsWith(words.join(' ')) ? 0 : words.every((w) => name.includes(w)) ? 1 : 2;
  };
  return vars.map((v, i) => [rank(v), i, v]).filter(([r]) => r >= 0).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(([, , v]) => v);
}

/** What a variable is worth right now, in words (its value is only known for test data and the environment). */
function variableNote(v, live, kind) {
  if (!v) return '';
  const base = v.group === 'saved' ? `Set by step ${v.n}: its value only exists while the test runs.`
    : v.value ? `${v.group === 'environment' ? 'In this environment' : 'In the data row you are building with'} it is “${clip(v.value, 60)}”.`
      : `It is empty ${v.group === 'environment' ? 'in this environment' : 'in the data row you are building with'}.`;
  const differs = v.value && live && v.value !== live && COMPARES_TEXT.has(kind);
  return html`<span style="font-size: 11.5px; color: var(--tx3)">${base}</span>${differs ? html`<span style="font-size: 11.5px; color: var(--warn)">The page shows “${clip(live, 40)}” right now, so this check fails until they agree.</span>` : ''}`;
}

/** A search box over a scrollable list of variables, grouped (Enter takes the first match).  `act` = what choosing one does. */
function variablePicker(vars, act, selected) {
  const hits = findVariables(vars, ui.search);
  const groups = Object.entries(VAR_GROUPS).map(([g, label]) => [label, hits.filter((v) => v.group === g)]).filter(([, list]) => list.length);
  const ranked = ui.search.trim() ? [['Best matches', hits]] : groups;                // (while searching the best match leads, whatever its group)
  return html`<input class="fld mono" style="height: 32px; font-size: 12px" type="search" placeholder="Search ${vars.length} variable${vars.length === 1 ? '' : 's'}…" value="${ui.search}" data-input="build-rec-var-search" data-rec-enter="${act}" data-key="rec-var-search-${ui.cardId}" autocomplete="off" aria-label="Search variables">
<div class="vlist" role="listbox" aria-label="Variables">${hits.length ? ranked.map(([label, list]) => html`<span class="vg">${label}</span>${list.map((v) => html`<button class="vopt ${v.token === selected ? 'on' : ''}" role="option" aria-selected="${String(v.token === selected)}" data-act="${act}" data-token="${v.token}"><span class="tk">${v.token}</span><span class="vv">${v.value ? clip(v.value, 28) : v.group === 'saved' ? `step ${v.n}` : ''}${v.match ? `${v.value ? ' · ' : ''}same as page` : ''}</span></button>`)}`) : html`<span class="vg" style="text-transform: none; letter-spacing: 0; font-weight: 500">No variable matches “${ui.search}”.</span>`}</div>
${ui.search.trim() && hits.length ? html`<span style="font-size: 11px; color: var(--tx3)">${hits.length} of ${vars.length} · Enter takes the first</span>` : ''}`;
}

/** The Expected value of a check: from the live page, from a variable (searchable list of every one this test can read) or typed. */
function expectedBlock(form) {
  const live = liveOf(form, ui.kind);
  const vars = form.variables || [];
  const off = { page: live ? '' : 'Nothing could be read from the page for this check', variable: vars.length ? '' : 'This workbook has no variables yet', own: '' };
  const chosen = vars.find((v) => v.token === ui.variable);
  const same = vars.filter((v) => v.match && v.token !== ui.variable);
  const panel = ui.source === 'page'
    ? html`<div class="fld mono" style="height: auto; min-height: 34px; padding: 7px 10px; font-size: 12px; display: flex; align-items: center; background: var(--surface2); word-break: break-word" data-testid="expected-page">${live}</div>
<span style="font-size: 11.5px; color: var(--tx3)">Read from the page just now and kept as fixed text. To change it, use “Type my own”.</span>
${same.length ? html`<div style="display: flex; flex-wrap: wrap; gap: 5px; align-items: center; font-size: 11.5px; color: var(--tx3)">Same as now: ${same.map((v) => html`<button class="var" data-act="build-rec-use-var" data-token="${v.token}" title="Expect this variable instead of fixed text">${icon('braces', 11)} ${v.token}</button>`)}</div>` : ''}`
    : ui.source === 'variable'
      ? html`${variablePicker(vars, 'build-rec-pick-var', ui.variable)}
${chosen ? variableNote(chosen, live, ui.kind) : html`<span style="font-size: 11.5px; color: var(--tx3)">The step will read the variable when the test runs.</span>`}`
      : html`<input class="fld mono" style="font-size: 12px" value="${ui.expected}" data-input="build-rec-expected" autocomplete="off" aria-label="Expected value">
${vars.length ? html`<button class="btn btn-sm btn-ghost" style="align-self: flex-start" data-act="build-rec-insert-toggle" aria-expanded="${String(ui.insertOpen)}">${icon('braces', 12)} ${ui.insertOpen ? 'Hide variables' : 'Insert a variable'}</button>
${ui.insertOpen ? variablePicker(vars, 'build-rec-insert-var', '') : ''}` : ''}`;
  return html`<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Expected</span>
<div class="seg" role="group" aria-label="Where the expected value comes from">${SOURCES.map(([id, label]) => html`<button class="${ui.source === id ? 'on' : ''}" style="height: 28px; font-size: 12px; padding: 0 6px" aria-pressed="${String(ui.source === id)}" data-act="build-rec-source" data-source="${id}" ${off[id] ? raw('disabled') : ''} title="${off[id]}">${label}</button>`)}</div>
${panel}</div>`;
}

// Enter in a variable search takes the best match.
document.addEventListener('keydown', (ev) => {
  const t = ev.target;
  if (ev.key !== 'Enter' || !(t instanceof Element) || !t.hasAttribute('data-rec-enter')) return;
  ev.preventDefault();
  const form = formOf(sess());
  const first = form && findVariables(form.variables || [], ui.search)[0];
  if (first) recordActs[t.getAttribute('data-rec-enter')]({ dataset: { token: first.token } });
});

function checkForm(st) {
  const form = formOf(st);
  if (!form) return '';
  const p = st.pick;
  if (!p.ok) return '';
  const groups = [];
  for (const k of form.kinds) { let g = groups.find((x) => x.name === k.group); if (!g) { g = { name: k.group, kinds: [] }; groups.push(g); } g.kinds.push(k); }
  const title = { check: 'Check this', save: 'Save this', wait: 'Wait until' }[form.purpose];
  return html`<div class="card sess-card"><div style="display: flex; align-items: center; gap: 8px">${icon(form.purpose === 'save' ? 'braces' : form.purpose === 'wait' ? 'clock' : 'check', 14, 'color: var(--pass)')}<b style="font-size: 13px">${title}</b><span class="trunc" style="font-size: 11.5px; color: var(--tx3)">${p.text}</span></div>
${form.kinds.length > 1 ? groups.map((g) => html`<div style="display: flex; flex-direction: column; gap: 4px"><span class="lbl">${g.name}</span><div style="display: flex; flex-wrap: wrap; gap: 4px">
${g.kinds.map((k) => html`<button class="btn btn-sm ${ui.kind === k.id ? 'btn-pri' : ''}" data-act="build-rec-kind" data-kind="${k.id}" ${k.enabled ? '' : raw('disabled')} title="${k.why || ''}">${k.label}</button>`)}</div></div>`) : ''}
${NEEDS_EXPECTED.has(ui.kind) ? expectedBlock(form) : ''}
${form.purpose === 'save' ? html`<div style="display: flex; flex-direction: column; gap: 5px"><span class="lbl">Save it as the variable</span>
<input class="fld mono" style="font-size: 12px" value="${ui.token}" data-input="build-rec-token" autocomplete="off">${form.text ? html`<span style="font-size: 11.5px; color: var(--tx3)">Now: ${form.text}</span>` : ''}</div>` : ''}
${ui.kind === 'text_is' || ui.kind === 'text_contains' ? html`<div style="display: flex; flex-direction: column; gap: 5px"><span class="lbl">Also save it as a variable (optional)</span>
<input class="fld mono" style="font-size: 12px" value="${ui.alsoSave}" placeholder="e.g. PRICE_SHOWN" data-input="build-rec-also" autocomplete="off"></div>` : ''}
<div style="display: flex; gap: 6px"><button class="btn btn-pri btn-sm" style="flex: 1; justify-content: center" data-act="build-rec-add" ${ready(form) ? '' : raw('disabled')}>${icon('plus', 12)} Add ${form.purpose === 'save' ? 'save' : form.purpose === 'wait' ? 'wait' : 'check'} · step ${form.n}</button>
<button class="btn btn-sm" data-act="build-rec-cancel">Cancel</button></div></div>`;
}

/** In the inspector, above the pick panel: the recording line, the recorder's prompts, the Check / Save / Wait card. */
export function recordPanel(st) {
  if (!st || !st.open) return '';
  const rec = st.record || { on: false, prompts: [] };
  const parts = [];
  if (rec.on) {
    parts.push(html`<div class="bn" style="padding: 8px 10px"><span class="rec-dot live"></span><span style="flex: 1; font-size: 12px">Recording${rec.cursor && rec.cursor.n ? html` after step <b>${rec.cursor.n}</b>` : ''} · ${rec.count} step${rec.count === 1 ? '' : 's'} recorded${rec.widget ? ' · a calendar is open' : ''}</span>
<button class="btn btn-sm" data-act="build-rec-toggle">${icon('stop', 11)} Stop</button></div>`);
  }
  parts.push(checkForm(st));
  for (const p of [...(rec.prompts || [])].reverse()) parts.push(promptCard(p));
  return parts.some((x) => x) ? html`<div style="display: flex; flex-direction: column; gap: 10px">${parts}</div>` : '';
}
