// Everything the page can do: loading data, uploading, launching, watching a run, and the button handlers
// (wired by data-act / data-change / data-input attributes in the views).
import { S, rerender, freshForm, freshBook } from './state.js';
import { api, upload, openSocket, ApiError } from './api.js';
import { newRun, applyAll, wbColor } from './runstate.js';
import { buildRequest, chosenTests, formTests, hasProd, allChosen, booksReady, checkName, poolState } from './views/newrun.js';
import { toast, copyText, debounce } from './util.js';
import { filterWorkbooks, PAGE, MORE } from './wbfilter.js';

const enc = encodeURIComponent;
const MB = 1024 * 1024;

// ---- loading ------------------------------------------------------------------------------------------------------
export async function loadConfig() {
  const cfg = await api('/api/config');
  const first = !S.cfg;
  S.cfg = cfg;
  if (first) S.nr = { ...freshForm(cfg), ...S.nr, browser: cfg.browser || '', workers: cfg.workers, shots: cfg.screenshots, retries: cfg.retries, pdf: cfg.pdf, harvest: cfg.harvest, nice: cfg.nice };
}
/** The preflight for the browser picked on the form (its launch check is the one that can block a run). An answer for a browser that is no longer the picked one is dropped. */
export async function loadPreflight({ deep = false } = {}) {
  const asked = S.nr.browser || '';
  const query = [deep ? 'deep=1' : '', asked ? `browser=${enc(asked)}` : ''].filter(Boolean).join('&');
  const pre = await api(`/api/preflight${query ? '?' + query : ''}`);
  if ((S.nr.browser || '') === asked) S.pre = pre;
  return pre;
}
export async function loadRuns() {
  const runs = await api('/api/runs');
  if (JSON.stringify(runs) !== JSON.stringify(S.runs)) S.runs = runs;
}
export async function loadWorkbooks() { S.workbooks = await api('/api/workbooks'); }

export async function refreshEnv() {
  const each = (p) => p.then(rerender).catch((e) => { S.online = e.kind !== 'offline'; });
  await Promise.all([each(loadConfig()), each(loadPreflight()), each(loadRuns()), each(loadWorkbooks())]);
}

// ---- new run form ---------------------------------------------------------------------------------------------------
// Several workbooks can be chosen (S.nr.books, each with its own state in S.nr.bk[name]): every one becomes a run of its own on shared workers.
const defaultsOf = (info) => Object.fromEntries(info.tests.filter((t) => t.enabled && t.runnable).map((t) => [t.id, true]));

function remember() {
  try {
    localStorage.setItem('rr.workbooks', JSON.stringify(S.nr.books));
    localStorage.setItem('rr.workbook', S.nr.books[0] || '');
  } catch (e) { /* storage unavailable */ }
}
export function rememberedWorkbooks() {
  try {
    const list = JSON.parse(localStorage.getItem('rr.workbooks') || 'null');
    if (Array.isArray(list) && list.length) return list.map(String);
    const one = localStorage.getItem('rr.workbook');
    return one ? [one] : [];
  } catch (e) { return []; }
}

/** Choose a workbook (or read it again): it joins the ones already chosen, with its own tests and run order. */
export async function selectWorkbook(name, { quiet = false } = {}) {
  const f = S.nr;
  if (!f.books.includes(name)) f.books = [...f.books, name];
  const b = f.bk[name] = f.bk[name] || freshBook();
  const previous = b.sel;
  b.err = null; f.banner = null;
  if (!quiet) { b.load = 'loading'; b.info = null; b.audit = null; }
  remember();
  rerender();
  try {
    const info = await api(`/api/workbooks/${enc(name)}/tests?env=${enc(f.env)}`);
    if (f.bk[name] !== b) return;
    b.info = info; b.load = 'ok';
    b.chains = (info.chains || []).map((c) => c.slice()); b.chainsSource = info.chains_source || 'none'; b.chainsDirty = false; b.order = null; b.orderKey = ''; b.orderAsked = ''; b.orderError = '';
    const keep = quiet ? Object.fromEntries(info.tests.filter((t) => previous[t.id] && t.runnable).map((t) => [t.id, true])) : {};
    b.sel = Object.keys(keep).length ? keep : defaultsOf(info);
    loadAudit(name);
    refreshCommand();
    refreshOrder(name);
    refreshDurations();
  } catch (e) {
    if (f.bk[name] !== b) return;
    b.load = 'error'; b.info = null;
    b.err = { message: e.message, details: e.data && e.data.details, showDetails: false };
  }
  rerender();
}

/** Take a workbook out of the run. */
export function deselectWorkbook(name) {
  const f = S.nr;
  f.books = f.books.filter((n) => n !== name);
  delete f.bk[name];
  if (f.checkWb === name) f.checkWb = null;
  f.banner = null;
  remember();
  touched();
}

/** Each chosen workbook's most recent finished run, so the Run plan's Timeline view can size tests by how long they actually
 *  took instead of guessing from step counts.  A workbook nobody has run yet is simply left out by the server. */
export const refreshDurations = debounce(async () => {
  const f = S.nr;
  const names = f.books.filter((n) => f.bk[n].load === 'ok');
  if (!names.length) return;
  try {
    const data = await api('/api/batches/last-durations', { method: 'POST', body: { workbooks: names } });
    f.durations = { ...f.durations, ...data };
    rerender();
  } catch (e) { /* the Timeline view falls back to step counts */ }
}, 150);

async function loadAudit(name) {
  const f = S.nr;
  const b = f.bk[name];
  if (!b) return;
  b.audit = 'loading';
  try {
    const a = await api(`/api/workbooks/${enc(name)}/audit`, { method: 'POST', body: { env: f.env || null } });
    if (f.bk[name] === b) b.audit = a;
  } catch (e) { if (f.bk[name] === b) b.audit = null; }
  rerender();
}

export const refreshCommand = debounce(async () => {
  const f = S.nr;
  if (!booksReady(S)) { f.cmd = null; rerender(); return; }
  const req = buildRequest(S);
  const key = JSON.stringify(req);
  try {
    const r = await api('/api/runs/command', { method: 'POST', body: req });
    if (JSON.stringify(buildRequest(S)) === key) { f.cmd = { tokens: r.tokens, text: r.text }; f.cmdKey = key; rerender(); }
  } catch (e) { /* the command preview is a convenience; the Run button still validates */ }
}, 120);

function touched() { rerender(); refreshCommand(); }

/** Which of a workbook's chosen tests wait for which (asked of the server, which reads the workbook's parameters): shown as its Run order card.  It always
 *  describes what is selected *now*: ``ensureOrder`` (called on every render of the New run screen) asks again whenever the workbook, the selection or the
 *  chains are not the ones the last answer was for, so it does not depend on which control changed them - or on nothing having been clicked yet. */
const orderKeyFor = (name) => { const b = S.nr.bk[name]; return JSON.stringify([name, chosenTests(S, name).map((t) => t.id), b ? b.chains : []]); };

const orderTimers = {};
export function refreshOrder(name) {
  clearTimeout(orderTimers[name]);
  orderTimers[name] = setTimeout(() => askOrder(name), 150);
}

async function askOrder(name) {
  const f = S.nr;
  const b = f.bk[name];
  if (!b) return;
  if (b.load !== 'ok') { b.order = null; rerender(); return; }
  const tests = chosenTests(S, name).map((t) => t.id);
  const key = orderKeyFor(name);
  b.orderAsked = key;
  try {
    const o = await api(`/api/workbooks/${enc(name)}/order`, { method: 'POST', body: { tests, chains: b.chains, env: f.env || null } });
    if (f.bk[name] === b && orderKeyFor(name) === key) { b.order = o; b.orderKey = key; b.orderError = ''; rerender(); }
  } catch (e) {
    if (f.bk[name] === b && orderKeyFor(name) === key) { b.orderError = e.message || 'the server did not answer'; rerender(); }      // said in Preflight; asked again when the selection changes
  }
}

export function ensureOrder() {
  const f = S.nr;
  for (const name of f.books) {
    const b = f.bk[name];
    if (!b || b.load !== 'ok' || !b.info) continue;
    const key = orderKeyFor(name);
    if (b.orderKey === key || b.orderAsked === key) continue;
    b.orderAsked = key;
    refreshOrder(name);
  }
}

async function uploadFile(file) {
  const f = S.nr;
  f.uploadErr = null;
  const max = (S.cfg && S.cfg.max_upload_mb) || 50;
  if (!/\.(xlsx|xlsm)$/i.test(file.name)) { f.uploadErr = 'Only .xlsx and .xlsm workbooks can be uploaded.'; rerender(); return; }
  if (file.size > max * MB) { f.uploadErr = `Workbook larger than ${max} MB.`; rerender(); return; }
  const ctrl = new AbortController();
  f.upload = { name: file.name, pct: 0, ctrl };
  rerender();
  try {
    const res = await upload('/api/workbooks', file, { signal: ctrl.signal, onProgress: (p) => { if (f.upload) { f.upload.pct = p; rerender(); } } });
    f.upload = null;
    await loadWorkbooks();
    f.wbq = ''; f.wbLimit = PAGE;                    // show the new file, not a search that may hide it
    await selectWorkbook(res.name);                  // it joins the workbooks already chosen
    toast(`${res.name} uploaded`);
  } catch (e) {
    f.upload = null;
    if (e.name !== 'AbortError') f.uploadErr = e.message;
    rerender();
  }
}
export async function dropFiles(files) {
  if (!files || !files.length) return;
  for (const file of Array.from(files)) await uploadFile(file);       // one after another: each is uploaded, then chosen
}

export async function launch(confirmed = false) {
  const f = S.nr;
  if (f.starting) return;
  if (hasProd(S) && !confirmed) { S.modal = { kind: 'prod', text: '' }; rerender(); return; }
  f.starting = true; f.banner = null; rerender();
  try {
    const req = buildRequest(S, hasProd(S) ? { allow_prod: true, confirm_prod: 'PROD' } : {});
    const res = await api('/api/runs', { method: 'POST', body: req });
    S.modal = null; f.starting = false;
    const joining = f.joinBatch;
    f.joinBatch = null;
    await loadRuns();
    location.hash = res.batch_id ? `#/batch/${res.batch_id}` : `#/run/${res.run_id}`;
    if (joining) toast(`Added to batch ${joining.id}.`, 4000);
    else if (res.runs && res.runs.length > 1) toast(`Started ${res.runs.length} runs on shared workers as batch ${res.batch_id}.`, 5000);
    else if (res.joined) toast('Joined the workers of the run in progress.', 4000);
    if (res.refused && res.refused.length) toast(`Not started: ${res.refused.map((r) => `${r.workbook} (${r.reason})`).join('; ')}`, 9000);
  } catch (e) {
    f.starting = false; S.modal = null;
    f.banner = { kind: e.kind || 'error', message: e.message, run_id: e.data && e.data.run_id };
    rerender();
    if (e.kind === 'busy') loadRuns().then(rerender);
  }
}

// ---- viewing a run ----------------------------------------------------------------------------------------------------
let socket = null;
let retryTimer = null;
let token = 0;

export function closeRun() {
  token += 1;
  clearTimeout(retryTimer);
  if (socket) { socket.onclose = null; try { socket.close(); } catch (e) { /* already closed */ } socket = null; }
  closeBatch();
  S.view = null;
}

const pickMode = (d) => (d.active ? 'live' : d.results && (d.meta.status !== 'INTERRUPTED' || d.results.partial) ? 'results' : 'live');

export async function openRun(id) {
  closeRun();
  const my = token;
  S.view = { kind: 'run', id, loading: true, mode: null, run: newRun(id), results: null, meta: null, files: null, conn: 'idle', expanded: {},
             showAllFails: {}, showAllReview: false, buildingPdf: false, cancelAtMs: null, error: null, notFound: false, askText: {}, askBusy: {} };
  rerender();
  await refreshDetail(id, my);
}

async function refreshDetail(id, my) {
  let d;
  try { d = await api(`/api/runs/${enc(id)}`); } catch (e) {
    if (my !== token) return;
    Object.assign(S.view, { loading: false, error: e, notFound: e.status === 404 });
    rerender();
    return;
  }
  if (my !== token) return;
  const v = S.view;
  Object.assign(v, { meta: d.meta, files: d.files, results: d.results, loading: false, mode: pickMode(d) });
  loadRuns().then(rerender).catch(() => {});             // the sidebar reflects a run's new state straight away
  if (v.mode === 'live' && !socket) connect(id, my, 0);
  rerender();
}

function connect(id, my, attempt) {
  const v = S.view;
  let fresh = newRun(id);
  let first = true;
  v.conn = attempt ? 'reconnecting' : 'live';
  socket = openSocket(id, {
    onEvents: (events) => {
      if (my !== token) return;
      applyAll(fresh, events);
      if (first) { first = false; v.conn = 'live'; }
      v.run = fresh;
      if (events.some((e) => e.type === 'run_finished')) setTimeout(() => { if (my === token) refreshDetail(id, my); }, 400);
      rerender();
    },
    onClose: (byServer) => {
      socket = null;
      if (my !== token) return;
      const running = v.run.status === 'RUNNING';
      if (running && !byServer) {
        v.conn = 'reconnecting';
        retryTimer = setTimeout(() => { if (my === token) connect(id, my, attempt + 1); }, Math.min(500 * 2 ** attempt, 8000));
      } else {
        v.conn = 'closed';
        if (running) setTimeout(() => { if (my === token) refreshDetail(id, my); }, 1000);
      }
      rerender();
    },
  });
}

// ---- viewing a batch (several runs, one per workbook, tracked and shown together) --------------------------------------
// A batch is only a label (dev/plan/CONTRACT.md): each of its runs is tracked exactly as when it is viewed alone (its own
// socket, its own ``runstate.js`` reducer); this only opens one such socket per run and keeps their states side by side.
let batchSockets = [];
let batchToken = 0;

export function closeBatch() {
  batchToken += 1;
  for (const ws of batchSockets) { ws.onclose = null; try { ws.close(); } catch (e) { /* already closed */ } }
  batchSockets = [];
}

function connectBatchEntry(entry, my) {
  const fresh = newRun(entry.id);
  const ws = openSocket(entry.id, {
    onEvents: (events) => {
      if (my !== batchToken) return;
      applyAll(fresh, events);
      entry.run = fresh;
      if (events.some((e) => e.type === 'run_finished')) {
        api(`/api/runs/${enc(entry.id)}`).then((d) => { if (my === batchToken) { entry.meta = d.meta; rerender(); } }).catch(() => {});
      }
      rerender();
    },
    onClose: () => { batchSockets = batchSockets.filter((s) => s !== ws); },
  });
  batchSockets.push(ws);
}

export async function openBatch(id) {
  closeRun();
  closeBatch();
  const my = batchToken;
  S.view = { kind: 'batch', id, loading: true, batch: null, entries: [], error: null, notFound: false, filter: null };
  rerender();
  let detail;
  try { detail = await api(`/api/batches/${enc(id)}`); } catch (e) {
    if (my !== batchToken) return;
    Object.assign(S.view, { loading: false, error: e, notFound: e.status === 404 });
    rerender();
    return;
  }
  if (my !== batchToken) return;
  const names = detail.workbooks;
  const metas = await Promise.all(detail.runs.map((m) => api(`/api/runs/${enc(m.run_id)}`).then((d) => d.meta).catch(() => m)));
  if (my !== batchToken) return;
  const entries = detail.runs.map((m, i) => {
    const meta = metas[i] || m;
    const workbook = String(meta.workbook || '').split(/[\\/]/).pop();
    return { id: m.run_id, workbook, color: wbColor(workbook, names), run: newRun(m.run_id), meta };
  });
  Object.assign(S.view, { batch: detail, entries, loading: false });
  rerender();
  for (const entry of entries) connectBatchEntry(entry, my);
  loadRuns().then(rerender).catch(() => {});
}

async function rerunFailed() {
  const v = S.view;
  const failed = v.results.tests.filter((t) => t.status === 'FAILED' || t.status === 'ERROR' || t.failed).map((t) => t.id);
  const p = (v.meta && v.meta.params) || {};
  const wbName = String((v.meta && v.meta.workbook) || v.results.workbook).split(/[\\/]/).pop();
  const env = (p.environment || v.results.environment || '').toUpperCase();
  if (env === 'PROD') {           // never re-launch a PROD run in one click: send the person through the form and its confirmation
    S.nr = { ...freshForm(S.cfg), env, browser: p.browser || S.cfg.browser, workers: p.workers || S.cfg.workers, shots: p.screenshots || S.cfg.screenshots };
    location.hash = '#/';
    await selectWorkbook(wbName);
    if (S.nr.bk[wbName]) S.nr.bk[wbName].sel = Object.fromEntries(failed.map((id) => [id, true]));
    touched();
    refreshOrder(wbName);
    toast('Review the selection, then confirm the PROD run.');
    return;
  }
  try {
    const res = await api('/api/runs', { method: 'POST', body: {
      workbook: wbName, tests: failed, env: env || null, browser: p.browser || null, workers: p.workers || null, screenshots: p.screenshots || null,
      retries: p.retries ?? null, seed: p.seed ?? null, pdf: p.pdf ?? null, harvest: p.harvest ?? null, headed: p.headless === false,
      nice: p.nice ?? null } });
    await loadRuns();
    location.hash = `#/run/${res.run_id}`;
  } catch (e) { toast(e.message, 6000); }
}

// ---- modals --------------------------------------------------------------------------------------------------------------
async function openLint() {
  const name = checkName(S);
  S.modal = { kind: 'lint', loading: true, filter: 'all', data: null, error: '', wb: name };
  rerender();
  try { S.modal.data = await api(`/api/workbooks/${enc(name)}/lint`, { method: 'POST', body: { env: S.nr.env || null } }); } catch (e) { S.modal.error = e.message; }
  S.modal.loading = false; rerender();
}

async function loadPlan(test) {
  const m = S.modal;
  m.test = test; m.error = '';
  if (!m.data[test]) {
    m.loading = true; rerender();
    try { m.data[test] = await api(`/api/workbooks/${enc(m.wb)}/plan`, { method: 'POST', body: { test, env: S.nr.env || null } }); } catch (e) { m.error = e.message; }
  }
  m.loading = false; rerender();
}
async function openPlan() {
  const name = checkName(S);
  const ids = (chosenTests(S, name).length ? chosenTests(S, name) : formTests(S, name)).map((t) => t.id);
  if (!ids.length) return;
  S.modal = { kind: 'plan', tests: ids, test: ids[0], data: {}, filter: '', loading: true, error: '', wb: name };
  await loadPlan(ids[0]);
}
async function openAudit() {
  const f = S.nr;
  const name = checkName(S);
  const b = f.bk[name];
  S.modal = { kind: 'audit', loading: !b.audit || b.audit === 'loading', data: b.audit && b.audit !== 'loading' ? b.audit : null, error: '', wb: name };
  rerender();
  if (S.modal.data) return;
  try { S.modal.data = await api(`/api/workbooks/${enc(name)}/audit`, { method: 'POST', body: { env: f.env || null } }); b.audit = S.modal.data; } catch (e) { S.modal.error = e.message; }
  S.modal.loading = false; rerender();
}
async function openDoctor() {
  S.modal = { kind: 'doctor', loading: true, data: null, error: '' };
  rerender();
  try { S.modal.data = await loadPreflight({ deep: true }); } catch (e) { S.modal.error = e.message; }
  S.modal.loading = false; rerender();
}
async function openLog(id) {
  S.modal = { kind: 'log', loading: true, lines: [] };
  rerender();
  try { S.modal.lines = (await api(`/api/runs/${enc(id)}/log?tail=400`)).lines; } catch (e) { S.modal.lines = [e.message]; }
  S.modal.loading = false; rerender();
}
async function openSelectors() {
  const id = S.view.id;
  S.modal = { kind: 'selectors', runId: id, loading: true, data: null, picked: {}, applying: false, result: null, error: '' };
  rerender();
  try {
    const d = await api(`/api/runs/${enc(id)}/selectors`);
    S.modal.data = d; S.modal.picked = Object.fromEntries(d.suggestions.map((s) => [s.key, true]));
  } catch (e) { S.modal.error = e.message; }
  S.modal.loading = false; rerender();
}
async function openSignin() {
  S.modal = { kind: 'signin', url: '', stage: 'idle', error: '' };
  rerender();
  try {
    const first = S.nr.books[0];
    const url = first ? (await api(`/api/workbooks/${enc(first)}/start-url?env=${enc(S.nr.env)}`)).url : '';
    if (S.modal && S.modal.kind === 'signin' && !S.modal.url) S.modal.url = url;
  } catch (e) { /* the person can type the address */ }
  rerender();
}

export async function closeModal() {
  const m = S.modal;
  if (m && m.kind === 'prod' && S.nr.starting) return;           // confirmed and starting: closing it would not stop the run from starting, only hide that it is
  S.modal = null;
  if (m && m.kind === 'signin' && (m.stage === 'open' || m.stage === 'saving')) api('/api/auth/cancel', { method: 'POST' }).catch(() => {});
  rerender();
}

// ---- action handlers ---------------------------------------------------------------------------------------------------------
const only = (name, ids) => { S.nr.bk[name].sel = Object.fromEntries(ids.map((id) => [id, true])); touched(); refreshOrder(name); };

export const acts = {
  theme() { window.rrTheme.toggle(); rerender(); },
  'new-run'() { if (location.hash !== '#/' && location.hash !== '') location.hash = '#/'; else rerender(); },
  'open-run'(el) { location.hash = `#/run/${el.dataset.id}`; },
  'open-batch'(el) { location.hash = `#/batch/${el.dataset.id}`; },
  'add-to-batch'(el) { S.nr.joinBatch = { id: el.dataset.id }; location.hash = '#/'; },
  'batch-filter'(el) {                                      // a workbook row in the live batch view: click again to clear
    const v = S.view;
    if (!v || v.kind !== 'batch') return;
    const wb = el.dataset.wb || '';
    v.filter = wb && v.filter !== wb ? wb : null;
    rerender();
  },
  async 'cancel-batch'(el) {
    const v = S.view;
    if (!v || v.kind !== 'batch') return;
    const ids = (v.entries || []).filter((e) => e.run.status === 'RUNNING').map((e) => e.id);
    await Promise.all(ids.map((id) => api(`/api/runs/${enc(id)}/cancel`, { method: 'POST' }).catch((e) => toast(e.message, 5000))));
    toast('Cancelling: running tests finish their current step.');
    loadRuns().then(rerender);
  },
  async 'refresh-runs'() { await loadRuns(); rerender(); toast('Runs refreshed', 1400); },
  'goto-preflight'() {
    S.scrollTo = 'preflight';
    if (S.route.name !== 'new') location.hash = '#/'; else rerender();
  },
  'wb-search-clear'() {
    S.nr.wbq = ''; S.nr.wbLimit = PAGE;
    const box = document.getElementById('wb-search');
    if (box) box.value = '';                       // the page never rewrites a field you are typing in, so empty it ourselves
    rerender();
    setTimeout(() => { const i = document.getElementById('wb-search'); if (i) i.focus(); }, 60);
  },
  'wb-more'() { S.nr.wbLimit += MORE; rerender(); },
  'wb-sort'(el) { S.nr.wbSort = el.getAttribute('data-field') === 'name' ? 'name' : 'new'; rerender(); },
  'ask-delete-wb'(el) { S.modal = { kind: 'delete-wb', name: el.getAttribute('data-field'), busy: false, error: '' }; rerender(); },
  async 'confirm-delete-wb'() {
    const m = S.modal;
    if (!m || m.kind !== 'delete-wb' || m.busy) return;
    m.busy = true; m.error = ''; rerender();
    const fail = (message) => { m.busy = false; m.error = message; rerender(); };
    try {
      await api(`/api/workbooks/${enc(m.name)}`, { method: 'DELETE' });
    } catch (e) {
      if (e.kind !== 'not_found') {          // "not_found" is the server saying the file is already gone; a bare 404 / 405 is a server that predates this button
        return fail(e.status === 404 || e.status === 405
          ? 'The running server does not know how to delete workbooks: it is older than this page. Close the UI (or press Ctrl+C in its window), start it again, then retry.'
          : e.message);
      }
    }
    let refreshed = true;
    try { await loadWorkbooks(); } catch (e) { refreshed = false; }
    if (refreshed && S.workbooks.some((w) => w.name === m.name)) {          // never report a success the folder does not show
      return fail(`${m.name} is still in workbooks/. The server answered, but the file was not removed. Check that nothing else (Excel, a sync client) is holding it.`);
    }
    if (S.modal !== m) { rerender(); return; }
    S.modal = null;
    const f = S.nr;
    if (f.books.includes(m.name)) deselectWorkbook(m.name);
    toast(`${m.name} deleted. A copy is in workbooks/.trash.`);
    rerender();
  },
  'pick-workbook-name'(el) {                                // a "Recently run" chip: adds the workbook to the run, or takes it out again
    const name = el.getAttribute('data-field');
    if (!name) return;
    if (S.nr.books.includes(name)) deselectWorkbook(name); else selectWorkbook(name);
  },
  'choose-another'(el) {                                    // a workbook that could not be read: drop it (and, when it was the only one, offer the file chooser)
    const f = S.nr;
    const alone = f.books.length === 1;
    deselectWorkbook(el.dataset.wb);
    if (alone) { const i = document.getElementById('file-input'); if (i) i.click(); }
  },
  'toggle-details'(el) { const b = S.nr.bk[el.dataset.wb]; if (b && b.err) { b.err.showDetails = !b.err.showDetails; rerender(); } },
  'check-wb'(el) { S.nr.checkWb = el.dataset.wb; rerender(); },
  'match-pool'() {                                          // the run in progress fixes the browser and window mode: take them
    const p = poolState(S).pool;
    if (!p) return;
    S.nr.browser = p.browser; S.nr.headed = !!p.headed;
    touched();
    loadPreflight().then(rerender).catch(() => {});
  },
  'cancel-upload'() { if (S.nr.upload) S.nr.upload.ctrl.abort(); },
  'sel-defaults'(el) { const n = el.dataset.wb; only(n, formTests(S, n).filter((t) => t.enabled && t.runnable).map((t) => t.id)); },
  'sel-all'(el) { const n = el.dataset.wb; only(n, formTests(S, n).filter((t) => t.runnable).map((t) => t.id)); },
  'sel-none'(el) { only(el.dataset.wb, []); },
  'order-move'(el) {                                        // make the tests of a stream run one after another, in the order shown, with this one moved
    const name = el.dataset.wb;
    const b = S.nr.bk[name];
    const id = el.dataset.id;
    const stream = b && b.order && b.order.streams.find((s) => s.tests.includes(id));
    if (!stream) return;
    const list = stream.tests.slice();
    const i = list.indexOf(id);
    const j = i + Number(el.dataset.dir);
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    const inStream = new Set(list);
    b.chains = b.chains.filter((c) => !c.some((t) => inStream.has(t))).concat([list]);
    b.chainsDirty = true;
    touched(); refreshOrder(name);
  },
  'order-reset'(el) { const name = el.dataset.wb; const b = S.nr.bk[name]; b.chains = []; b.chainsDirty = b.chainsSource !== 'none'; touched(); refreshOrder(name); },
  async 'order-save'(el) {
    const name = el.dataset.wb;
    const b = S.nr.bk[name];
    try {
      const r = await api(`/api/workbooks/${enc(name)}/chains`, { method: 'PUT', body: { chains: b.chains } });
      b.chains = r.chains; b.chainsSource = r.chains.length ? 'saved' : 'none'; b.chainsDirty = false;
      toast(r.chains.length ? 'Order saved for this workbook.' : 'Chains cleared.');
    } catch (e) { toast(e.message, 6000); }
    rerender();
  },
  'sel-tag'(el) {                                           // a tag chip in the merged Tests list: picks that tag's tests in every chosen workbook, not just one
    const tag = el.dataset.tag;
    for (const n of S.nr.books) only(n, formTests(S, n).filter((t) => (t.tags || []).includes(tag)).map((t) => t.id));
  },
  'toggle-fold'(el) { const b = S.nr.bk[el.dataset.wb]; if (b) { b.open = !(b.open !== false); rerender(); } },
  'plan-view'(el) { S.nr.planView = el.dataset.val; rerender(); },
  'leave-batch'() { S.nr.joinBatch = null; touched(); },
  set(el) {
    const f = S.nr;
    const { field: key, val } = el.dataset;
    if (f[key] === val) return;
    f[key] = val;
    touched();
    if (key === 'env') for (const name of f.books) selectWorkbook(name, { quiet: true });        // each workbook reads its tests again for the new environment
    if (key === 'browser') loadPreflight().then(rerender).catch(() => {});      // is THIS browser ready? (the answer for the old choice no longer applies)
  },
  step(el) {
    const f = S.nr;
    const key = el.dataset.field;
    const d = Number(el.dataset.d);
    const max = key === 'workers' ? (S.cfg.max_workers || 8) : 3;
    f[key] = Math.min(max, Math.max(key === 'workers' ? 1 : 0, f[key] + d));
    touched();
  },
  'toggle-more'(el, ev) { ev.preventDefault(); S.nr.showMore = !S.nr.showMore; rerender(); },
  launch() { launch(false); },
  'confirm-prod'() { if (S.modal && S.modal.kind === 'prod' && S.modal.text.trim() === 'PROD') launch(true); },
  async 'copy-cmd'() { if (S.nr.cmd) toast((await copyText(S.nr.cmd.text)) ? 'Command copied' : 'Could not copy'); },
  async 'copy-run-cmd'() { const c = S.view && S.view.meta && S.view.meta.command; if (c) toast((await copyText(c)) ? 'Command copied' : 'Could not copy'); },
  lint: openLint,
  plan: openPlan,
  audit: openAudit,
  doctor: openDoctor,
  signin: openSignin,
  'close-modal'(el, ev) {
    if (el.hasAttribute('data-backdrop') && ev.target !== el) return;
    closeModal();
  },
  'lint-filter'(el) { S.modal.filter = el.dataset.val; rerender(); },
  'plan-test'(el) { loadPlan(el.dataset.id); },
  async 'signin-open'() {
    const m = S.modal;
    m.stage = 'opening'; m.error = ''; rerender();
    try { await api('/api/auth/login', { method: 'POST', body: { url: m.url } }); m.stage = 'open'; } catch (e) { m.stage = 'idle'; m.error = e.message; }
    rerender();
  },
  async 'signin-save'() {
    const m = S.modal;
    m.stage = 'saving'; m.error = ''; rerender();
    try {
      await api('/api/auth/save', { method: 'POST' });
      S.modal = null;
      toast('Session saved. Headless tests will reuse it.');
      await loadPreflight();
    } catch (e) { m.stage = 'open'; m.error = e.message; }
    rerender();
  },
  async 'signin-cancel'() { await closeModal(); },
  async 'cancel-run'(el) {
    const id = el.dataset.id;
    try {
      await api(`/api/runs/${enc(id)}/cancel`, { method: 'POST' });
      if (S.view && S.view.id === id) S.view.cancelAtMs = Date.now();
      toast('Cancelling: running tests finish their current step.');
      loadRuns().then(rerender);
    } catch (e) { toast(e.message, 5000); }
    rerender();
  },
  async 'ask-send'(el) {                                    // the answer to a question an ASK_USER step put to the person
    const v = S.view;
    const id = el && el.getAttribute('data-ask');
    if (!v || !id || v.askBusy[id]) return;
    v.askBusy[id] = true; rerender();
    try {
      await api(`/api/runs/${enc(v.id)}/answer`, { method: 'POST', body: { ask: id, answer: v.askText[id] || '' } });
      delete v.askText[id];
      if (v.run && v.run.asks) delete v.run.asks[id];
      toast('Answer sent.');
    } catch (e) { toast(e.message, 6000); }
    delete v.askBusy[id];
    rerender();
  },
  async 'ask-skip'(el) {                                    // give up on a captcha: the test ends with the reason
    const v = S.view;
    const id = el && el.getAttribute('data-ask');
    if (!v || !id || v.askBusy[id]) return;
    v.askBusy[id] = true; rerender();
    try {
      await api(`/api/runs/${enc(v.id)}/answer`, { method: 'POST', body: { ask: id, answer: 'skip' } });
      if (v.run && v.run.asks) delete v.run.asks[id];
    } catch (e) { toast(e.message, 6000); }
    delete v.askBusy[id];
    rerender();
  },
  zoom(el) { S.modal = { kind: 'lightbox', src: el.dataset.src }; rerender(); },
  'toggle-review'() { S.view.showAllReview = !S.view.showAllReview; rerender(); },
  'expand-test'(el) {
    const v = S.view;
    const id = el.dataset.id;
    v.expanded[id] = !(v.expanded[id] ?? true);
    rerender();
  },
  'toggle-fails'(el) { S.view.showAllFails[el.dataset.id] = !S.view.showAllFails[el.dataset.id]; rerender(); },
  async 'build-report'(el) {
    const v = S.view;
    try { await api(`/api/runs/${enc(el.dataset.id)}/report`, { method: 'POST', body: { from_events: v.mode === 'live' || !v.results } }); toast('Report built'); await refreshDetail(v.id, token); }
    catch (e) { toast(e.message, 6000); }
  },
  async 'build-pdf'(el) {
    const v = S.view;
    v.buildingPdf = true; rerender();
    try { await api(`/api/runs/${enc(el.dataset.id)}/report`, { method: 'POST', body: { pdf: true } }); toast('PDF ready'); await refreshDetail(v.id, token); }
    catch (e) { toast(e.message, 6000); }
    v.buildingPdf = false; rerender();
  },
  'rerun-failed': rerunFailed,
  async reveal() { try { await api(`/api/runs/${enc(S.view.id)}/reveal`, { method: 'POST', body: { folder: 'tests' } }); } catch (e) { toast(e.message, 5000); } },
  selectors: openSelectors,
  'show-log'(el) { openLog(el.dataset.id); },
  'replay-events'() { const v = S.view; v.mode = 'live'; if (!socket) connect(v.id, token, 0); rerender(); },
  async 'apply-selectors'() {
    const m = S.modal;
    m.applying = true; rerender();
    try { m.result = await api(`/api/runs/${enc(m.runId)}/selectors/apply`, { method: 'POST', body: { keys: Object.keys(m.picked).filter((k) => m.picked[k]) } }); } catch (e) { m.error = e.message; }
    m.applying = false; rerender();
  },
};

export const changes = {
  'file-picked'(el) { const files = el.files; if (files && files.length) dropFiles(files); el.value = ''; },
  'pick-workbook'(el) {                                     // a workbook's box: ticked = part of the run, unticked = out of it
    const on = S.nr.books.includes(el.value);
    if (el.checked && !on) selectWorkbook(el.value);
    else if (!el.checked && on) deselectWorkbook(el.value);
  },
  'toggle-test'(el) { const name = el.dataset.wb; const b = S.nr.bk[name]; b.sel = { ...b.sel, [el.dataset.id]: el.checked }; touched(); refreshOrder(name); },
  toggle(el) { S.nr[el.dataset.field] = el.checked; touched(); },
  'pick-suggestion'(el) { S.modal.picked[el.dataset.field] = el.checked; rerender(); },
};

export const inputs = {
  seed(el) { const clean = el.value.replace(/[^0-9]/g, '').slice(0, 9); if (clean !== el.value) el.value = clean; S.nr.seed = clean; touched(); },
  'prod-text'(el) { S.modal.text = el.value; rerender(); },
  'signin-url'(el) { S.modal.url = el.value; },
  'plan-filter'(el) { S.modal.filter = el.value; rerender(); },
  'wb-search'(el) { S.nr.wbq = el.value; S.nr.wbLimit = PAGE; rerender(); },
  'ask-text'(el) { if (S.view) S.view.askText[el.getAttribute('data-ask')] = el.value; },
};

export const enters = {
  'confirm-prod': () => acts['confirm-prod'](),
  'ask-send': (el) => acts['ask-send'](el),
  'wb-search-enter'() {                                     // type a few letters, press Enter: the best match is selected
    const top = filterWorkbooks(S.workbooks, S.nr.wbq, S.nr.wbSort)[0];
    if (top && !S.nr.books.includes(top.name)) selectWorkbook(top.name);
  },
};
export const escapes = { 'wb-search-clear': () => acts['wb-search-clear']() };
