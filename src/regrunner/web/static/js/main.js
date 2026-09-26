// Entry point: routing, the render loop and event delegation.
import { S, setRenderer, rerender, freshForm } from './state.js';
import { html } from './util.js';
import { morph } from './morph.js';
import { icon } from './icons.js';
import { counts } from './runstate.js';
import { header, sidebar, banner } from './views/shell.js';
import { newRunView } from './views/newrun.js';
import { liveView } from './views/live.js';
import { resultsView } from './views/results.js';
import { modalView } from './views/modals.js';
import * as A from './actions.js';
import { startPresence } from './presence.js';

const baseTitle = document.title;
const appEl = () => document.getElementById('app');
const modalEl = () => document.getElementById('modal-root');

// ---- rendering -------------------------------------------------------------------------------------------------
function runScreen() {
  const v = S.view;
  if (!v || v.loading) {
    return html`<div class="page"><div class="eyebrow">Run</div><div class="skel" style="height: 46px; width: 420px"></div><div class="skel" style="height: 220px"></div><div class="skel" style="height: 320px"></div></div>`;
  }
  if (v.error) {
    return html`<div class="page"><div class="eyebrow">Run</div><h1 class="disp" style="font-size: 38px; margin: 0">${v.notFound ? 'That run does not exist' : 'Could not open this run'}</h1>
${banner('fail', 'failc', v.error.message, html`<button class="btn btn-sm" data-act="new-run">Back to New run</button>`)}</div>`;
  }
  return v.mode === 'results' && v.results ? resultsView(S) : liveView(S);
}

function render() {
  S.now = Date.now();
  if (!S.cfg) {
    morph(appEl(), html`<div class="page" style="max-width: 640px; margin: 12vh auto"><div class="eyebrow">QA Regression</div>
${S.online ? html`<div class="skel" style="height: 30px; width: 260px; margin-top: 10px"></div>` : banner('fail', 'failc', 'Cannot reach the regrunner server. Is it still running? Start it again, then reload this page.')}</div>`);
    return;
  }
  // The sidebar shows the live percentage of the run being watched, not the last poll.
  if (S.view && S.view.run && S.view.run.status === 'RUNNING') {
    const c = counts(S.view.run);
    const entry = S.runs.find((r) => r.run_id === S.view.id);
    if (entry && entry.active) entry.progress = { done: c.done, total: c.total, percent: c.percent };
  }
  if (S.route.name === 'new') A.ensureOrder();                                              // the run order follows what is selected, whatever changed it
  const content = S.route.name === 'new' ? newRunView(S) : runScreen();
  morph(appEl(), html`${header(S)}<div class="app-body">${sidebar(S)}<main class="main"><div class="gridbg"></div>${content}</main></div>`);
  const run = S.view && S.view.run;
  const waiting = S.route.name === 'run' && run && run.status === 'RUNNING' ? Object.keys(run.asks || {}).length : 0;
  document.title = waiting ? '● Input needed · ' + baseTitle : baseTitle;                  // a run waiting for a person is visible from another tab
  if (waiting && run.askFocus) {                                                          // a new question: put the cursor in its box
    const box = document.getElementById(`ask-${run.askFocus}`);
    if (box) { box.focus(); run.askFocus = null; }
  }
  const before = modalEl().firstElementChild;
  morph(modalEl(), modalView(S));
  if (!before && modalEl().firstElementChild) focusModal();
  if (S.scrollTo) {
    const el = document.getElementById(S.scrollTo);
    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); S.scrollTo = null; }
  }
}

let returnFocus = null;
function focusModal() {
  returnFocus = document.activeElement;
  const root = modalEl();
  const target = root.querySelector('input:not([readonly]):not([type=checkbox])') || root.querySelector('.btn-pri:not([disabled])') || root.querySelector('button');
  if (target) target.focus();
}

// ---- routing ----------------------------------------------------------------------------------------------------------
function route() {
  const m = location.hash.match(/^#\/run\/([A-Za-z0-9._-]+)/);
  if (m) {
    S.route = { name: 'run', id: m[1] };
    A.openRun(m[1]);
  } else {
    S.route = { name: 'new', id: null };
    A.closeRun();
    A.refreshEnv();
  }
  window.scrollTo(0, 0);
  rerender();
}

// ---- event delegation ----------------------------------------------------------------------------------------------------
function on(type, attr, table, pre) {
  document.addEventListener(type, (ev) => {
    const el = ev.target instanceof Element ? ev.target.closest(`[${attr}]`) : null;
    if (!el) return;
    const fn = table[el.getAttribute(attr)];
    if (!fn) return;
    if (pre && pre(el, ev) === false) return;
    const out = fn(el, ev);
    if (out && typeof out.catch === 'function') out.catch((e) => console.error(e));
  });
}
on('click', 'data-act', A.acts);
on('change', 'data-change', A.changes);
on('input', 'data-input', A.inputs);

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && S.modal) { ev.preventDefault(); A.closeModal(); return; }
  if (ev.key === 'Escape' && ev.target instanceof Element && ev.target.hasAttribute('data-esc')) {
    const fn = A.escapes[ev.target.getAttribute('data-esc')];
    if (fn) { ev.preventDefault(); fn(); }
  }
  if (ev.key === 'Enter' && ev.target instanceof Element && ev.target.hasAttribute('data-enter')) {
    ev.preventDefault();
    const fn = A.enters[ev.target.getAttribute('data-enter')];
    if (fn) fn(ev.target);
  }
  if ((ev.key === 'Enter' || ev.key === ' ') && ev.target instanceof Element && ev.target.matches('.shot.zoom')) {
    ev.preventDefault();
    A.acts.zoom(ev.target);
  }
  if (ev.key === 'Tab' && S.modal) {                       // keep focus inside the dialog
    const items = Array.from(modalEl().querySelectorAll('button:not([disabled]), input:not([disabled]):not([readonly]), a[href], [tabindex="0"]'));
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
    else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
  }
});

// A modal that just closed gives focus back to what opened it.
new MutationObserver(() => {
  if (!modalEl().firstElementChild && returnFocus && document.contains(returnFocus)) { returnFocus.focus(); returnFocus = null; }
}).observe(modalEl(), { childList: true });

// drag & drop: dropping a file anywhere on the New run screen uploads it (and never navigates away to the file)
let dragDepth = 0;
const hasFiles = (ev) => ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes('Files');
document.addEventListener('dragenter', (ev) => { if (!hasFiles(ev)) return; ev.preventDefault(); dragDepth += 1; if (S.route.name === 'new' && !S.nr.drag) { S.nr.drag = true; rerender(); } });
document.addEventListener('dragover', (ev) => { if (hasFiles(ev)) ev.preventDefault(); });
document.addEventListener('dragleave', (ev) => { if (!hasFiles(ev)) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth && S.nr.drag) { S.nr.drag = false; rerender(); } });
document.addEventListener('drop', (ev) => {
  if (!hasFiles(ev)) return;
  ev.preventDefault();
  dragDepth = 0; S.nr.drag = false;
  if (S.route.name === 'new') A.dropFiles(ev.dataTransfer.files); else rerender();
});

// ---- boot ----------------------------------------------------------------------------------------------------------------------
async function boot() {
  setRenderer(render);
  startPresence();
  window.addEventListener('hashchange', route);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) A.refreshEnv(); });
  window.addEventListener('focus', () => A.refreshEnv());
  render();
  for (;;) {                                   // the page paints as soon as the server answers; retry until it does
    try { await A.loadConfig(); break; } catch (e) { S.online = e.kind !== 'offline'; rerender(); await new Promise((r) => setTimeout(r, 2000)); }
  }
  S.online = true;
  A.loadPreflight().then(rerender).catch(() => {});        // the browser probe can take a moment; it fills in behind the page
  await Promise.all([A.loadWorkbooks(), A.loadRuns()].map((p) => p.catch(() => {})));
  route();
  // restore the workbooks chosen last time, else the newest one
  const last = A.rememberedWorkbooks().filter((n) => S.workbooks.some((w) => w.name === n));
  const picks = last.length ? last : S.workbooks.slice(0, 1).map((w) => w.name);
  if (S.route.name === 'new' && !S.nr.books.length) picks.forEach((name) => A.selectWorkbook(name));
  setInterval(() => {
    if (document.hidden) return;
    S.now = Date.now();
    const live = S.route.name === 'run' && S.view && S.view.run && S.view.run.status === 'RUNNING' && !(S.view.meta && S.view.meta.active === false);
    if (live || (S.view && S.view.cancelAtMs)) rerender();
  }, 1000);
  setInterval(() => { if (!document.hidden) A.loadRuns().then(rerender).catch(() => {}); }, 4000);
}

boot();
