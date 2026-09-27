// The build window (P08, build/session.py): the site in a browser of its own that the builder drives. From the test editor: open it,
// pick an element on the page (or "which one?" by text), turn a word of what was picked into a variable, put it on a step, and run up to
// here / this step / the next 5 with the same actions as a real run. Its state is polled from GET /api/build/session/<workbook>.
import { S, rerender } from '../../state.js';
import { html, raw, toast } from '../../util.js';
import { icon } from '../../icons.js';
import { api } from '../../api.js';
import { bm, currentTest, selectedStep, effectiveBuildingWith, applyOps, refreshModel } from './actions.js';

const enc = encodeURIComponent;
const NEXT = 5;

// What this page knows about the build window of the workbook being edited (module state: it follows S.build.name).
const ui = { name: null, st: null, since: 0, timer: null, busy: false, whichText: '', wordMenu: null, log: [] };

const path = (name, what = '') => `/api/build/session/${enc(name)}${what ? '/' + what : ''}`;
export const sess = () => (ui.name === S.build.name ? ui.st : null);
const isOpen = () => { const st = sess(); return !!(st && st.open); };
const running = () => { const st = sess(); return !!(st && st.status === 'running'); };

// ---- talking to the server -----------------------------------------------------------------------------------------------------------
function take(st) {
  if (!st || ui.name !== S.build.name) return;
  const before = ui.st;
  ui.st = st;
  if (st.log && st.log.length) { ui.log = [...ui.log, ...st.log].slice(-60); ui.since = st.seq || ui.since; }
  const m = bm();
  if (m && st.modelVersion != null && st.modelVersion > m.version) refreshModel();       // the window changed a step (Use for step N)
  syncQuestion(st.question);
  if (!before || before.version !== st.version || before.open !== st.open) rerender();
}

function syncQuestion(q) {
  const mine = S.modal && S.modal.kind === 'build-session-question';
  if (q && (!mine || S.modal.q.id !== q.id)) { if (!S.modal || mine) { S.modal = { kind: 'build-session-question', q, answer: '', busy: false }; rerender(); } }
  else if (!q && mine) { S.modal = null; rerender(); }
}

async function poll() {
  ui.timer = null;
  const name = ui.name;
  if (!name || name !== S.build.name || S.route.name !== 'build') { ui.name = S.route.name === 'build' ? ui.name : null; return; }
  try { take(await api(`${path(name)}?since=${ui.since}`)); } catch (e) { /* the next poll tries again */ }
  const st = sess();
  if (st && st.open) ui.timer = setTimeout(poll, st.status === 'running' || st.mode !== 'browse' ? 500 : 1500);
}

/** Called while the editor renders: follow the workbook on screen, and keep polling while its window is open. Idempotent. */
export function watchSession() {
  const name = S.build.name;
  if (!name) return;
  if (ui.name !== name) { ui.name = name; ui.st = null; ui.since = 0; ui.log = []; ui.wordMenu = null; if (ui.timer) clearTimeout(ui.timer); ui.timer = null; }
  if (!ui.timer) ui.timer = setTimeout(poll, ui.st ? 800 : 0);
}

async function call(what, body, { quiet = false } = {}) {
  const name = S.build.name;
  if (!name || ui.busy) return null;
  ui.busy = true; rerender();
  try {
    const st = await api(path(name, what), { method: 'POST', body: body || {} });
    ui.busy = false;
    if (st && st.session) take(st.session); else take(st);
    if (!ui.timer) ui.timer = setTimeout(poll, 300);
    rerender();
    return st;
  } catch (e) {
    ui.busy = false;
    if (!quiet) toast(e.message, 6000);
    rerender();
    throw e;
  }
}

// ---- actions ---------------------------------------------------------------------------------------------------------------------------
async function openWindow() {
  const t = currentTest();
  if (!t) return;
  const body = { test: t.id, dataRow: effectiveBuildingWith(t), env: S.build.env || undefined };
  try { await call('start', body, { quiet: true }); }
  catch (e) {
    if (e.kind === 'prod_confirm') {
      const typed = window.prompt(`${e.message}\n\nType PROD to open the build window on it:`);
      if (typed && typed.trim() === 'PROD') { try { await call('start', { ...body, confirmProd: 'PROD' }); } catch (err) { /* shown */ } }
    } else toast(e.message, 6000);
  }
}

const selRow = () => { const s = selectedStep(); return s ? s.row : null; };

async function runTo(row) { if (row) { try { await call('run-to-here', { row }); } catch (e) { /* shown */ } } }
async function runStep() { const row = selRow(); if (row) { try { await call('run-step', { row }); } catch (e) { /* shown */ } } }
async function runNext() { try { await call('run-next', { count: NEXT }); } catch (e) { /* shown */ } }

async function pick() {
  const st = sess();
  const mode = st && st.mode === 'pick' ? 'browse' : 'pick';
  try { await call('pick', { mode, row: selRow() }); } catch (e) { /* shown */ }
  if (mode === 'pick') toast('Click the element in the build window.', 3000);
}

async function findMatches() {
  const text = ui.whichText.trim();
  if (!text) { toast('Type the text of the element to look for.'); return; }
  try { await call('which', { text, row: selRow() }); } catch (e) { /* shown */ }
}

/** The word becomes a variable: an existing one, or a new Params column that starts with the word as its value in every row. */
async function makeVariable(role, token, isNew) {
  ui.wordMenu = null;
  const t = currentTest();
  const st = sess();
  const word = st && st.pick ? (st.pick.words.find((w) => w.role === role) || {}).text : '';
  if (isNew) {
    if (!t || !t.paramSheet) { toast('This test has no parameter sheet to hold a variable.', 5000); rerender(); return; }
    const label = window.prompt('A name for the new variable (for example: Plan)', word || '');
    if (!label || !label.trim()) { rerender(); return; }
    token = label.trim().toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^(\d)/, '_$1');
    if (!token) { rerender(); return; }
    const applied = await applyOps([{ op: 'add_variable', token, label: label.trim(), sheet: t.paramSheet, value: word }]);
    if (!applied) return;
  }
  try { await call('variable', { role, token }); } catch (e) { /* shown */ }
}

async function useForStep() {
  const st = sess();
  const row = (st && st.pick && st.pick.for) || selRow();
  try {
    const res = await call('use', { row });
    if (res && res.model) { S.build.model = res.model; rerender(); }
  } catch (e) { /* shown */ }
}

async function answer(value) {
  const m = S.modal;
  if (!m || m.kind !== 'build-session-question') return;
  m.busy = true; rerender();
  try { await api(path(S.build.name, 'answer'), { method: 'POST', body: { id: m.q.id, answer: value } }); S.modal = null; }
  catch (e) { m.busy = false; toast(e.message, 5000); }
  rerender();
}

export const acts = {
  'build-sess-open': openWindow,
  async 'build-sess-close'() { try { await call('close'); } catch (e) { /* shown */ } },
  'build-sess-run-to'() { runTo(selRow()); },
  'build-sess-replay'() { const st = sess(); runTo(st && st.cursor ? st.cursor.row : selRow()); },
  'build-sess-run-step': runStep,
  'build-sess-run-next': runNext,
  async 'build-sess-stop'() { try { await call('stop'); } catch (e) { /* shown */ } },
  'build-sess-pick': pick,
  'build-sess-which': findMatches,
  async 'build-sess-choose'(el) { try { await call('choose', { i: Number(el.dataset.i) }); } catch (e) { /* shown */ } },
  async 'build-sess-which-close'() { try { await call('pick', { mode: 'browse', row: selRow() }); } catch (e) { /* shown */ } },
  'build-sess-word'(el) { ui.wordMenu = ui.wordMenu === el.dataset.role ? null : el.dataset.role; rerender(); },
  'build-sess-var'(el) { makeVariable(el.dataset.role, el.dataset.token, false); },
  'build-sess-var-new'(el) { makeVariable(el.dataset.role, '', true); },
  'build-sess-use': useForStep,
  'build-sess-yes'() { answer('yes'); },
  'build-sess-no'() { answer('no'); },
  'build-sess-send'() { answer(S.modal ? S.modal.answer : ''); },
};

export const inputs = {
  'build-sess-which-text'(el) { ui.whichText = el.value; },
  'build-sess-answer'(el) { if (S.modal) S.modal.answer = el.value; },
};

// R = run up to here (Q39), while the window is open and nobody is typing.
document.addEventListener('keydown', (ev) => {
  if (S.route.name !== 'build' || S.build.screen !== 'test' || S.modal || !isOpen() || running() || ev.metaKey || ev.ctrlKey || ev.altKey) return;
  const t = ev.target;
  if (t instanceof Element && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
  if (ev.key === 'r' || ev.key === 'R') { ev.preventDefault(); runTo(selRow()); }
});

// ---- rendering ---------------------------------------------------------------------------------------------------------------------------
const nOf = (row) => { const t = currentTest(); const s = t && t.steps.find((x) => x.row === row); return s ? s.n : null; };

function replayLine(st) {
  const r = st.replay;
  if (!r) return '';
  const results = r.results || [];
  const failed = results.filter((x) => x.status !== 'PASSED');
  if (r.running) {
    const cur = r.current && r.current.row ? nOf(r.current.row) : null;
    return html`<span class="sess-line">${icon('play', 12, 'color: var(--acc)')} Running${cur ? html` step <b>${cur}</b>` : ''}… ${results.length} done</span>`;
  }
  if (r.stopped) return html`<span class="sess-line" style="color: var(--fail)">${icon('warn', 12)} <span class="trunc" title="${r.stopped}">${r.stopped}</span></span>`;
  return html`<span class="sess-line" style="color: var(--pass)">${icon('check', 12)} ${results.length} step${results.length === 1 ? '' : 's'} ran${failed.length ? html`, <b style="color: var(--fail)">${failed.length} failed</b>` : ''}</span>`;
}

/** The strip under the editor's sub-header: open / run / pick controls and what the window is doing. */
export function sessionBar(S0) {
  watchSession();
  const t = currentTest();
  const st = sess();
  const s = selectedStep();
  if (!t || t.kind !== 'web') return '';
  if (!st || !st.open) {
    return html`<div class="sess-bar">
<button class="btn btn-sm ${ui.busy ? 'busy' : ''}" data-act="build-sess-open">${icon('globe', 13)} Open the site</button>
<span style="font-size: 12px; color: var(--tx3)">${st && st.error ? st.error + ' ' : ''}A browser window of its own: pick elements on the page and run steps with row ${effectiveBuildingWith(t) || '–'}'s data.</span></div>`;
  }
  const want = effectiveBuildingWith(t);
  const other = st.test !== t.id || (want != null && st.dataRow !== want);          // the window follows another test or data row
  const busy = st.status === 'running';
  const sel = s ? s.n : null;
  return html`<div class="sess-bar${st.stale ? ' stale' : ''}">
<span class="pdot" style="background: var(--${busy ? 'acc' : 'pass'})" title="Build window open"></span>
<b style="font-size: 12.5px">Build window</b><span class="mono" style="font-size: 11px; color: var(--tx3)">${st.environment || ''} · row ${st.dataRow || '–'}${st.cursor ? ` · at step ${st.cursor.n}` : ''}</span>
${other ? html`<span class="tag tag-warn" title="The window is on another test or data row">on ${st.test} · row ${st.dataRow || '–'}</span>
<button class="btn btn-sm" data-act="build-sess-open" ${busy ? raw('disabled') : ''} title="Start this test from its beginning in the window">${icon('refresh', 12)} Switch to ${t.id} · row ${want || '–'}</button>` : ''}
<span style="width: 1px; height: 18px; background: var(--line2)"></span>
${busy ? html`<button class="btn btn-sm" data-act="build-sess-stop">${icon('stop', 12)} Stop</button>` : html`
<button class="btn btn-sm" data-act="build-sess-run-to" ${sel && !other ? '' : raw('disabled')} title="Replay steps 1 to ${sel || '…'} from the start (R)">${icon('play', 12)} Run up to here</button>
<button class="btn btn-sm btn-ghost" data-act="build-sess-run-step" ${sel && !other ? '' : raw('disabled')} title="Run only the selected step, in the window as it is">Run this step</button>
<button class="btn btn-sm btn-ghost" data-act="build-sess-run-next" ${st.next && !other ? '' : raw('disabled')} title="${st.next ? `Carry on from step ${st.next.n || '…'}` : 'Run up to a step first'}">Run next ${NEXT}</button>`}
<button class="btn btn-sm ${st.mode === 'pick' ? 'btn-pri' : ''}" data-act="build-sess-pick" ${busy || other ? raw('disabled') : ''} title="Click an element in the build window">${icon('target', 12)} ${st.mode === 'pick' ? 'Picking…' : 'Pick'}</button>
<span style="flex: 1"></span>${replayLine(st)}
<button class="icon-btn" style="width: 28px; height: 28px" data-act="build-sess-close" aria-label="Close the build window" title="Close the build window">${icon('x', 13)}</button>
</div>
${st.stale && !busy ? html`<div class="bn bn-warn" style="margin: 8px 16px 0; padding: 9px 12px">${icon('warn', 14, 'color: var(--warn)')}<span style="flex: 1"><b>Earlier steps changed since they ran.</b> The window may not be where the next step expects: replay from the start to be sure.</span>
<button class="btn btn-sm" data-act="build-sess-replay">${icon('refresh', 12)} Replay from the start</button></div>` : ''}
${st.error ? html`<div class="bn bn-fail" style="margin: 8px 16px 0; padding: 9px 12px">${icon('warn', 14, 'color: var(--fail)')}<span>${st.error}</span></div>` : ''}`;
}

/** A dot on a step card: how the step went in the build window (and where the window is). */
export function sessionMark(row) {
  const st = sess();
  if (!st || !st.open || !st.replay) return '';
  const res = [...(st.replay.results || [])].reverse().find((x) => x.row === row);
  const here = st.cursor && st.cursor.row === row;
  if (!res && !here) return '';
  const color = !res ? 'tx3' : res.status === 'PASSED' ? 'pass' : 'fail';
  return html`<span class="tag" style="color: var(--${color}); border-color: currentColor" title="${res ? `${res.status} in the build window${res.error ? ': ' + res.error : ''}` : 'The build window is here'}">${here ? icon('play', 9) : ''}${res ? (res.status === 'PASSED' ? 'ran' : 'failed') : 'here'}</span>`;
}

function wordButtons(st, t) {
  const p = st.pick;
  const vars = (bm().variables || []).filter((v) => v.kind === 'data' && (v.sources || []).some((src) => t.paramSheet && src.sheet.toUpperCase() === t.paramSheet.toUpperCase()));
  return html`<div style="display: flex; flex-wrap: wrap; gap: 5px; align-items: center">
${p.words.map((w) => (w.role === 'name' || w.role === 'context')
    ? html`<span style="position: relative"><button class="${w.variable ? 'var' : 'btn btn-sm'}" data-act="build-sess-word" data-role="${w.role}" title="Make it a variable">${w.variable ? html`${icon('braces', 11)} ${w.variable}` : `“${w.text}”`}</button>
${ui.wordMenu === w.role ? html`<div class="menu" style="position: absolute; left: 0; top: 30px; width: 250px; padding: 6px; z-index: 7">
<span class="lbl" style="display: block; padding: 4px 8px">Make “${w.text}” a variable</span>
${vars.map((v) => html`<button class="mitem" data-act="build-sess-var" data-role="${w.role}" data-token="${v.token}">${icon('braces', 13)}<span style="flex: 1">${v.label} <span class="mono" style="color: var(--tx3); font-size: 11px">{${v.token}}</span></span></button>`)}
<button class="mitem" data-act="build-sess-var-new" data-role="${w.role}">${icon('plus', 13)}<span style="flex: 1">New variable…</span></button></div>` : ''}</span>`
    : html`<span class="tag">${w.text}</span>`)}
</div>`;
}

/** In the inspector: what was picked in the window, its locator, and "Use for step N". */
export function pickPanel(S0, t, s) {
  const st = sess();
  if (!st || !st.open) return '';
  const blocks = [];
  if (st.which) {
    const w = st.which;
    blocks.push(html`<div class="card sess-card"><div style="display: flex; align-items: center; gap: 8px"><b style="font-size: 13px">${w.matches.length} match${w.matches.length === 1 ? '' : 'es'} “${w.text}”${w.matches.length > 1 ? '. Which one?' : ''}</b>
<span style="flex: 1"></span><button class="icon-btn" style="width: 24px; height: 24px" data-act="build-sess-which-close" aria-label="Close">${icon('x', 11)}</button></div>
<span style="font-size: 11.5px; color: var(--tx3)">Pick one here or click it in the build window (numbered there).</span>
${w.matches.map((m) => html`<button class="mitem" data-act="build-sess-choose" data-i="${m.i}" data-key="wm-${m.i}"><span class="which-num">${m.i + 1}</span><span class="trunc" style="flex: 1">${m.text}</span>${m.inFrame ? html`<span class="tag">frame</span>` : ''}</button>`)}
</div>`);
  }
  const p = st.pick;
  if (p) {
    const loc = p.locator || {};
    const forN = p.for ? nOf(p.for) : null;
    blocks.push(html`<div class="card sess-card"><div style="display: flex; align-items: center; gap: 8px"><span class="lbl">Picked in the window</span><span style="flex: 1"></span>
${p.url ? html`<span class="mono trunc" style="font-size: 10.5px; color: var(--tx3); max-width: 150px" title="${p.url}">${p.url}</span>` : ''}</div>
${wordButtons(st, t)}
${p.ok ? html`<div class="field mono" style="align-items: flex-start; font-size: 11px; color: var(--tx2); flex-direction: column; gap: 4px">
<span style="display: flex; gap: 6px; align-items: center"><span class="tag">${loc.findBy}</span><span class="tag ${loc.matches === 1 ? 'tag-acc' : 'tag-warn'}">${loc.matches} match${loc.matches === 1 ? '' : 'es'}${loc.index ? ` · #${loc.index + 1}` : ''}</span><span style="color: var(--tx3)">${loc.how}</span></span>
<span style="word-break: break-all">${loc.value}</span></div>`
    : html`<div class="bn bn-fail" style="padding: 8px 10px">${icon('warn', 13, 'color: var(--fail)')}<span>No locator finds only this element. Pick the element around it, or the one you meant.</span></div>`}
${(p.rows || []).length ? html`<div style="display: flex; flex-direction: column; gap: 3px">${p.rows.map((r) => html`<span style="font-size: 11.5px; color: var(--${r.matches === 1 ? 'pass' : r.matches === 0 || r.matches > 1 ? 'fail' : 'tx3'})">${icon(r.matches === 1 ? 'check' : 'warn', 11)} Row ${r.row} (${Object.values(r.values).join(', ') || 'empty'}): ${r.matches == null ? 'no value to check' : `${r.matches} match${r.matches === 1 ? '' : 'es'} on this page`}</span>`)}</div>` : ''}
${(loc.backups || []).length ? html`<span style="font-size: 11.5px; color: var(--tx3)">${loc.backups.length} backup locator${loc.backups.length === 1 ? '' : 's'} stored with the step. If the main one breaks, the step still fails; the backups only suggest a fix.</span>` : ''}
${p.frame ? html`<span style="font-size: 11.5px; color: var(--warn)">${icon('frame', 11)} Inside frame ${p.frame}: the step needs a “Switch to frame” step before it.</span>` : ''}
${p.ok ? html`<button class="btn btn-pri btn-sm" style="justify-content: center" data-act="build-sess-use" ${forN || s ? '' : raw('disabled')}>${icon('check', 12)} Use for step ${forN || (s ? s.n : '…')}</button>` : ''}
</div>`);
  }
  blocks.push(html`<div style="display: flex; gap: 6px"><div style="flex: 1; min-width: 0; display: flex; align-items: center; gap: 7px; height: 30px; padding: 0 10px; border: 1px solid var(--line2); border-radius: 8px; background: var(--surface); color: var(--tx3)">${icon('search', 13)}<input class="fld" style="flex: 1; min-width: 0; width: auto; border: 0; height: auto; padding: 0; background: transparent; font-size: 12.5px" placeholder="Which one? Text of a button, link…" value="${ui.whichText}" data-input="build-sess-which-text" autocomplete="off"></div>
<button class="btn btn-sm" data-act="build-sess-which">Find</button></div>`);
  return html`<div style="display: flex; flex-direction: column; gap: 10px">${blocks}</div>`;
}

/** The side-effect pause (Q13) and every other question a replayed step asks (ASK_USER, an empty parameter). */
export function sessionQuestionDialog(m) {
  const q = m.q;
  const side = q.sideEffect;
  const inner = side
    ? html`<div class="bn bn-warn">${icon('bolt', 16, 'color: var(--warn)')}<span><b>Step “${side.name}” has real consequences</b> (it is flagged “has side effects”: a purchase, a payment, an order). Running it here does it for real on ${side.environment || 'this environment'}.</span></div>
<span style="font-size: 13px; color: var(--tx2)">Don't run it and the replay stops before it; the steps after it are not run.</span>`
    : html`<span style="font-size: 13px">${q.text}</span>
<input class="fld" type="${q.secret ? 'password' : 'text'}" value="${m.answer}" data-input="build-sess-answer" autocomplete="off" autofocus>`;
  const footer = side
    ? html`<button class="btn" data-act="build-sess-no" ${m.busy ? raw('disabled') : ''}>Don't run it</button><span style="flex: 1"></span><button class="btn btn-pri" data-act="build-sess-yes" ${m.busy ? raw('disabled') : ''}>${icon('bolt', 13)} Run it for real</button>`
    : html`<span style="flex: 1"></span><button class="btn btn-pri" data-act="build-sess-send" ${m.busy ? raw('disabled') : ''}>Send</button>`;
  return html`<div class="modal-back"><div class="card modal" role="dialog" aria-modal="true" aria-label="${side ? 'Run it for real?' : 'The replay asks'}" style="width: min(520px, 100%)">
<span class="ttl">${side ? 'Run it for real?' : 'The replay needs an answer'}</span>
<div style="margin-top: 14px; display: flex; flex-direction: column; gap: 12px">${inner}</div>
<div style="margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--line); display: flex; align-items: center; gap: 8px">${footer}</div></div></div>`;
}

export const sessionOpen = isOpen;
