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
  edit: 'Edit', unflag: 'Not a side effect', dismiss: 'OK' };

// What is being typed in the card (module state: the card is rebuilt on every poll).
const ui = { cardId: null, kind: '', expected: '', token: '', alsoSave: '', fp: {} };

function formOf(st) {
  const card = st && st.pick && st.pick.card;
  const form = card && card.form;
  if (!form) return null;
  if (ui.cardId !== card.id) {
    const k = form.kinds.find((x) => x.id === form.chosen) || {};
    Object.assign(ui, { cardId: card.id, kind: form.chosen || '', expected: k.expected || '', token: form.token || '', alsoSave: '' });
  }
  return form;
}

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
  if (choice === 'gate' && ui.fp[id]) body.fields = ui.fp[id];
  await edit('prompt', body);
  delete ui.fp[id];
}

export const recordActs = {
  'build-rec-toggle'() { toggleRecord(); },
  'build-rec-here'() { S.build.ed.menu = false; toggleRecord(); },
  'build-rec-mode'(el) { setMode(el.dataset.mode); },
  'build-rec-kind'(el) { const form = formOf(sess()); const k = form && form.kinds.find((x) => x.id === el.dataset.kind); if (k && k.enabled) { ui.kind = k.id; ui.expected = k.expected || ''; rerender(); } },
  'build-rec-var'(el) { ui.expected = `{${el.dataset.token}}`; rerender(); },
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
  const tone = p.kind === 'secret' || p.kind === 'side' ? 'warn' : p.kind === 'fingerprint' ? 'pass' : 'acc';
  const ico = p.kind === 'secret' ? 'lock' : p.kind === 'fingerprint' ? 'gate' : p.kind === 'widget' ? 'bolt' : p.kind === 'side' ? 'bolt' : 'braces';
  return html`<div class="card sess-card" data-key="rp-${p.id}"><div style="display: flex; gap: 8px; align-items: flex-start">${icon(ico, 14, `color: var(--${tone}); margin-top: 2px; flex: none`)}
<div style="display: flex; flex-direction: column; gap: 3px; min-width: 0"><b style="font-size: 12.5px">${p.text}</b>${p.detail ? html`<span style="font-size: 11.5px; color: var(--tx3)">${p.detail}</span>` : ''}
${p.n ? html`<span class="mono" style="font-size: 10.5px; color: var(--tx3)">step ${p.n}${p.tag ? ` · ${p.tag}` : ''}</span>` : ''}</div></div>
${fp ? html`<div style="display: flex; flex-direction: column; gap: 6px">${[['name', 'Name'], ['urlContains', 'URL contains'], ['landmark', 'Landmark'], ['landmarkText', 'Landmark text']].map(([k, label]) => html`<label style="display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--tx3)">${label}
<input class="fld mono" style="height: 28px; font-size: 11.5px" value="${fp[k] || ''}" data-input="build-rec-fp" data-id="${p.id}" data-field="${k}"></label>`)}</div>` : ''}
<div style="display: flex; flex-wrap: wrap; gap: 6px">${(p.choices || []).map((c) => html`<button class="btn btn-sm ${c === 'keep' || c === 'gate' ? 'btn-pri' : ''}" data-act="${c === 'edit' ? 'build-rec-fp-edit' : 'build-rec-prompt'}" data-id="${p.id}" data-choice="${c}" data-token="${p.token || ''}">${c === 'edit' && fp ? 'Close editor' : c === 'dismiss' && p.kind === 'fingerprint' ? 'Not now' : CHOICE_WORDS[c] || c}</button>`)}</div></div>`;
}

function checkForm(st) {
  const form = formOf(st);
  if (!form) return '';
  const p = st.pick;
  if (!p.ok) return '';
  const groups = [];
  for (const k of form.kinds) { let g = groups.find((x) => x.name === k.group); if (!g) { g = { name: k.group, kinds: [] }; groups.push(g); } g.kinds.push(k); }
  const chosen = form.kinds.find((k) => k.id === ui.kind) || {};
  const vars = (form.variables || []).filter((v) => v.value === chosen.expected);
  const title = { check: 'Check this', save: 'Save this', wait: 'Wait until' }[form.purpose];
  return html`<div class="card sess-card"><div style="display: flex; align-items: center; gap: 8px">${icon(form.purpose === 'save' ? 'braces' : form.purpose === 'wait' ? 'clock' : 'check', 14, 'color: var(--pass)')}<b style="font-size: 13px">${title}</b><span class="trunc" style="font-size: 11.5px; color: var(--tx3)">${p.text}</span></div>
${form.kinds.length > 1 ? groups.map((g) => html`<div style="display: flex; flex-direction: column; gap: 4px"><span class="lbl">${g.name}</span><div style="display: flex; flex-wrap: wrap; gap: 4px">
${g.kinds.map((k) => html`<button class="btn btn-sm ${ui.kind === k.id ? 'btn-pri' : ''}" data-act="build-rec-kind" data-kind="${k.id}" ${k.enabled ? '' : raw('disabled')} title="${k.why || ''}">${k.label}</button>`)}</div></div>`) : ''}
${NEEDS_EXPECTED.has(ui.kind) ? html`<div style="display: flex; flex-direction: column; gap: 5px"><span class="lbl">Expected · from the live page</span>
<input class="fld mono" style="font-size: 12px" value="${ui.expected}" data-input="build-rec-expected" autocomplete="off">
${vars.length ? html`<div style="display: flex; flex-wrap: wrap; gap: 5px; align-items: center; font-size: 11.5px; color: var(--tx3)">Swap for a variable: ${vars.map((v) => html`<button class="var" data-act="build-rec-var" data-token="${v.token}">${icon('braces', 11)} ${v.token}</button>`)}</div>` : ''}</div>` : ''}
${form.purpose === 'save' ? html`<div style="display: flex; flex-direction: column; gap: 5px"><span class="lbl">Save it as the variable</span>
<input class="fld mono" style="font-size: 12px" value="${ui.token}" data-input="build-rec-token" autocomplete="off">${form.text ? html`<span style="font-size: 11.5px; color: var(--tx3)">Now: ${form.text}</span>` : ''}</div>` : ''}
${ui.kind === 'text_is' || ui.kind === 'text_contains' ? html`<div style="display: flex; flex-direction: column; gap: 5px"><span class="lbl">Also save it as a variable (optional)</span>
<input class="fld mono" style="font-size: 12px" value="${ui.alsoSave}" placeholder="e.g. PRICE_SHOWN" data-input="build-rec-also" autocomplete="off"></div>` : ''}
<div style="display: flex; gap: 6px"><button class="btn btn-pri btn-sm" style="flex: 1; justify-content: center" data-act="build-rec-add" ${ui.kind ? '' : raw('disabled')}>${icon('plus', 12)} Add ${form.purpose === 'save' ? 'save' : form.purpose === 'wait' ? 'wait' : 'check'} · step ${form.n}</button>
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
