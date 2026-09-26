// Everything the Build tab can do: load a workbook, apply ops, undo/redo/save, and the screen/step/selection state
// that drives views/build/*.js. Merged into the app's data-act / data-change / data-input tables by main.js.
import { S, rerender, freshBuild, freshEditor } from '../../state.js';
import * as buildApi from './api.js';
import { toast, debounce } from '../../util.js';
import { loadWorkbooks } from '../../actions.js';

const enc = encodeURIComponent;

// ---- small readers ---------------------------------------------------------------------------------------------
export const bm = () => S.build.model;
export const currentTest = () => { const m = bm(); return m && S.build.testId ? m.tests.find((t) => t.id === S.build.testId) : null; };
export const currentBlock = () => { const t = currentTest(); const ed = S.build.ed; return t && t.blocks.length ? t.blocks[Math.min(ed.block, t.blocks.length - 1)] : null; };
export const selectedStep = () => { const t = currentTest(); return t && S.build.ed.sel != null ? t.steps.find((s) => s.row === S.build.ed.sel) : null; };
export const blockIndexForN = (test, n) => Math.max(0, test.blocks.findIndex((b) => n >= b.start && n <= b.end));

export function buildUrl(name, screen, testId) {
  const n = enc(name);
  if (screen === 'variables') return `#/build/${n}/variables`;
  if (screen === 'test' && testId) return `#/build/${n}/test/${enc(testId)}`;
  return `#/build/${n}`;
}

function ensureSelection() {
  const t = currentTest();
  const ed = S.build.ed;
  if (!t) return;
  if (S.build.pendingSel != null) {
    if (t.steps.some((s) => s.row === S.build.pendingSel)) ed.sel = S.build.pendingSel;
    S.build.pendingSel = null;
  }
  ed.multi = ed.multi.filter((row) => t.steps.some((s) => s.row === row));
  if (ed.sel != null && !t.steps.some((s) => s.row === ed.sel)) ed.sel = null;
  if (ed.sel == null && t.steps.length) ed.sel = t.steps[0].row;
  if (ed.sel != null) { const s = t.steps.find((x) => x.row === ed.sel); if (s) ed.block = blockIndexForN(t, s.n); }
  ed.block = Math.min(ed.block, Math.max(0, t.blocks.length - 1));
}

// ---- loading ----------------------------------------------------------------------------------------------------
function remember(name) { try { localStorage.setItem('rr.build.workbook', name); } catch (e) { /* storage unavailable */ } }
export function rememberedBuildWorkbook() { try { return localStorage.getItem('rr.build.workbook') || ''; } catch (e) { return ''; } }

/** Open (or switch screen within) a workbook. Called by main.js on every #/build... route. */
export async function openBuild(name, screen = 'map', testId = null) {
  const b = S.build;
  const switching = b.name !== name;
  if (switching) { const kw = b.keywords; Object.assign(b, freshBuild(), { name, keywords: kw }); }
  const prevTest = b.testId;
  b.screen = screen; b.testId = testId;
  if (screen === 'test' && testId !== prevTest) b.ed = freshEditor();
  b.error = null;
  remember(name);
  const wasLoaded = !switching && b.model;
  b.loading = !wasLoaded;
  rerender();
  if (wasLoaded) { ensureSelection(); rerender(); return; }
  try {
    const m = await buildApi.model(name, b.env || undefined);
    if (S.build.name !== name) return;
    b.model = m; b.loading = false;
    ensureSelection();
  } catch (e) {
    if (S.build.name !== name) return;
    b.loading = false; b.error = e;
  }
  rerender();
}

/** Where the "Build" tab goes: the workbook last open there, else the newest workbook in the folder. */
export function defaultBuildName() {
  const remembered = S.build.name || rememberedBuildWorkbook();
  if (remembered && S.workbooks.some((w) => w.name === remembered)) return remembered;
  return S.workbooks[0] ? S.workbooks[0].name : null;
}

export async function refreshModel() {
  const b = S.build;
  if (!b.name) return;
  try {
    const m = await buildApi.model(b.name, b.env || undefined);
    if (S.build.name !== b.name) return;
    b.model = m;
    ensureSelection();
  } catch (e) { /* the next explicit action will surface the error */ }
  rerender();
}

export function setEnv(env) {
  S.build.env = env;
  refreshModel();
}

// ---- ops ---------------------------------------------------------------------------------------------------------
/** Send one edit call (one or more ops = one undo step). Refreshes the model from the server's answer. */
export async function applyOps(ops, { quiet = false } = {}) {
  const b = S.build;
  if (!b.name || !b.model || b.busy) return null;
  b.busy = true; rerender();
  try {
    const res = await buildApi.edit(b.name, ops, b.model.version, b.env || undefined);
    if (S.build.name !== b.name) return null;
    b.model = res.model; b.busy = false;
    ensureSelection();
    rerender();
    return res.applied;
  } catch (e) {
    if (S.build.name === b.name) b.busy = false;
    if (e.kind === 'stale') { toast('The workbook changed since this edit; reloaded the latest version.', 5000); await refreshModel(); }
    else if (!quiet) toast(e.message, 6000);
    rerender();
    return null;
  }
}

export async function undo() {
  const b = S.build;
  if (!b.name || !b.model || !b.model.status.canUndo || b.busy) return;
  b.busy = true; rerender();
  try { b.model = (await buildApi.undo(b.name, b.env || undefined)).model; ensureSelection(); }
  catch (e) { toast(e.message, 5000); }
  b.busy = false; rerender();
}

export async function redo() {
  const b = S.build;
  if (!b.name || !b.model || !b.model.status.canRedo || b.busy) return;
  b.busy = true; rerender();
  try { b.model = (await buildApi.redo(b.name, b.env || undefined)).model; ensureSelection(); }
  catch (e) { toast(e.message, 5000); }
  b.busy = false; rerender();
}

export async function saveToExcel(force = false) {
  const b = S.build;
  if (!b.name || b.busy) return;
  b.busy = true; rerender();
  try {
    const r = await buildApi.save(b.name, force);
    b.busy = false;
    toast(r.backup ? `Saved. Previous version kept as ${r.backup}.` : 'Saved.');
    await refreshModel();
  } catch (e) {
    b.busy = false;
    if (e.kind === 'changed_outside') { openFileChanged(); }
    else if (e.kind === 'locked') { S.modal = { kind: 'build-locked', message: e.message }; rerender(); }
    else toast(e.message, 6000);
    rerender();
  }
}

// ---- navigation ---------------------------------------------------------------------------------------------------
export function gotoMap(name) { location.hash = buildUrl(name, 'map'); }
export function gotoVariables(name) { location.hash = buildUrl(name, 'variables'); }
export function gotoTest(name, testId) { location.hash = buildUrl(name, 'test', testId); }
export function jumpToStep(name, testId, row) { S.build.pendingSel = row; gotoTest(name, testId); }

// ---- test editor: selection, blocks, view mode -----------------------------------------------------------------
export function selectStep(row) {
  const t = currentTest();
  const ed = S.build.ed;
  ed.sel = row; ed.menu = false;
  const s = t && t.steps.find((x) => x.row === row);
  if (s) ed.block = blockIndexForN(t, s.n);
  rerender();
}
export function toggleMultiStep(row) {
  const ed = S.build.ed;
  const i = ed.multi.indexOf(row);
  if (i >= 0) ed.multi.splice(i, 1); else ed.multi.push(row);
  rerender();
}
export function clearMulti() { S.build.ed.multi = []; rerender(); }
export function setBlock(i) {
  const t = currentTest();
  if (!t) return;
  const ed = S.build.ed;
  ed.block = Math.max(0, Math.min(i, t.blocks.length - 1));
  const b = t.blocks[ed.block];
  const s = t.steps.find((x) => x.n === b.start + 1) || t.steps.find((x) => x.n > b.start && x.n <= b.end);
  if (s) ed.sel = s.row;
  ed.menu = false;
  rerender();
}
export function stepBlock(d) { setBlock(S.build.ed.block + d); }
export function setMode(mode) {
  const ed = S.build.ed;
  ed.mode = mode;
  if (mode === 'grid' && !ed.grid) loadGrid();
  rerender();
}
export async function loadGrid() {
  const t = currentTest();
  const b = S.build;
  if (!t) return;
  b.ed.grid = 'loading'; rerender();
  try { const g = await buildApi.sheet(b.name, t.sheet); if (currentTest() === t) b.ed.grid = g; }
  catch (e) { if (currentTest() === t) b.ed.grid = null; }
  rerender();
}
export function effectiveBuildingWith(t) { return S.build.ed.buildingWith != null ? S.build.ed.buildingWith : t.buildingWith; }
export function useDataRow(row) { S.build.ed.buildingWith = row; rerender(); }

export async function loadDrawerGrid() {
  const t = currentTest();
  const ed = S.build.ed;
  if (!t || !t.paramSheet) return;
  if (ed.drawerSheetName === t.paramSheet && ed.drawerGrid !== undefined) return;
  ed.drawerSheetName = t.paramSheet; ed.drawerGrid = undefined; rerender();
  try { const g = await buildApi.sheet(S.build.name, t.paramSheet); if (S.build.ed.drawerSheetName === t.paramSheet) S.build.ed.drawerGrid = g; }
  catch (e) { if (S.build.ed.drawerSheetName === t.paramSheet) S.build.ed.drawerGrid = null; }
  rerender();
}
export function setDataCell(row, column, value) { const t = currentTest(); if (t && t.paramSheet) applyOps([{ op: 'set_cell', sheet: t.paramSheet, row, column, value }]); }
export const setDataCellDebounced = debounce((row, column, value) => setDataCell(row, column, value), 500);

export function toggleDrawer() { S.build.ed.drawer = !S.build.ed.drawer; if (S.build.ed.drawer) loadDrawerGrid(); rerender(); }
export function toggleProblems() { S.build.ed.problems = !S.build.ed.problems; rerender(); }
export function toggleMenu() {
  S.build.ed.menu = !S.build.ed.menu;
  if (S.build.ed.menu && !S.build.keywords) buildApi.keywords().then((k) => { S.build.keywords = k; rerender(); }).catch(() => {});
  rerender();
}
export function closeMenu() { S.build.ed.menu = false; rerender(); }

// ---- step edits ------------------------------------------------------------------------------------------------
export async function insertStep(method, opts = {}) {
  const t = currentTest();
  const ed = S.build.ed;
  if (!t) return;
  const b = t.blocks[ed.block];
  const after = ed.sel != null ? ed.sel : (b ? (t.steps.find((s) => s.n === b.end) || {}).row : undefined);
  const applied = await applyOps([{ op: 'insert_step', test: t.id, after, step: { method, ...opts } }]);
  if (applied && applied[0] && applied[0].row != null) selectStep(applied[0].row);
  ed.menu = false;
}
export function updateStep(row, set) { const t = currentTest(); if (t) applyOps([{ op: 'update_step', test: t.id, row, set }]); }
export const updateStepDebounced = debounce((row, set) => updateStep(row, set), 500);
export function deleteSteps(rows) {
  const t = currentTest();
  if (!t || !rows.length) return;
  applyOps([{ op: 'delete_steps', test: t.id, rows }]);
  S.build.ed.multi = [];
}
export function deleteSelected() {
  const ed = S.build.ed;
  const rows = ed.multi.length ? ed.multi.slice() : (ed.sel != null ? [ed.sel] : []);
  deleteSteps(rows);
}
export function bulkEdit(set) {
  const t = currentTest();
  const ed = S.build.ed;
  const rows = ed.multi.length ? ed.multi : (ed.sel != null ? [ed.sel] : []);
  if (!t || !rows.length) return;
  applyOps([{ op: 'bulk_edit', test: t.id, rows, set }]);
}
export function moveToBlock(title) {
  const t = currentTest();
  const ed = S.build.ed;
  const rows = ed.multi.length ? ed.multi : (ed.sel != null ? [ed.sel] : []);
  if (!t || !rows.length) return;
  applyOps([{ op: 'move_steps', test: t.id, rows, block: title }]);
}
export function renameBlock(row, title) { const t = currentTest(); if (t) applyOps([{ op: 'rename_block', test: t.id, row, title }]); }
function firstRowOfBlock(t, b) { const s = t.steps.find((x) => x.n > b.start && x.n <= b.end); return s ? s.row : null; }

// ---- variable map ------------------------------------------------------------------------------------------------
export function selectVariable(key) { S.build.selVariable = key; rerender(); }

// ---- dialogs -----------------------------------------------------------------------------------------------------
export function openNewWorkbook() {
  S.modal = { kind: 'build-new-workbook', name: '', envs: [{ name: 'QA', domain: '', production: false }, { name: 'UAT', domain: '', production: false }, { name: 'PROD', domain: '', production: true }], busy: false, error: '' };
  rerender();
}
export function openEnvironments() {
  const m = bm();
  if (!m) return;
  const e = m.environments;
  S.modal = { kind: 'build-environments', names: e.names.slice(), production: e.production.slice(),
    rows: e.rows.map((r) => ({ ...r, values: { ...r.values } })), busy: false, error: '' };
  rerender();
}
export function openFingerprint(name) {
  const m = bm();
  const existing = name ? m.fingerprints.find((f) => f.name === name) : null;
  S.modal = { kind: 'build-fingerprint', rename: existing ? existing.name : '', name: existing ? existing.name : '',
    urlContains: existing ? existing.urlContains : '', landmark: existing ? existing.landmark : '',
    landmarkText: existing ? existing.landmarkText : '', notes: existing ? existing.notes : '', busy: false, error: '' };
  rerender();
}
export async function deleteFingerprint(name) {
  await applyOps([{ op: 'delete_fingerprint', name }]);
  toast(`${name} deleted.`);
}
export async function openHistory() {
  const b = S.build;
  if (!b.name) return;
  S.modal = { kind: 'build-history', loading: true, items: [], sel: null, diff: null, error: '', busy: false };
  rerender();
  try {
    const items = await buildApi.history(b.name);
    S.modal.items = items;
    S.modal.sel = items[0] ? items[0].id : null;
    if (S.modal.sel) S.modal.diff = await buildApi.diff(b.name, S.modal.sel);
  } catch (e) { S.modal.error = e.message; }
  S.modal.loading = false; rerender();
}
export async function pickHistoryDiff(id) {
  const m = S.modal;
  if (!m || m.kind !== 'build-history') return;
  m.sel = id; m.diff = null; rerender();
  try { m.diff = await buildApi.diff(S.build.name, id); } catch (e) { m.error = e.message; }
  rerender();
}
export async function restoreHistory(id) {
  const m = S.modal;
  if (!m) return;
  m.busy = true; rerender();
  try {
    S.build.model = (await buildApi.restore(S.build.name, id, S.build.env || undefined)).model;
    ensureSelection();
    S.modal = null;
    toast('Restored. Nothing is lost: undo brings the draft back.');
  } catch (e) { m.busy = false; m.error = e.message; }
  rerender();
}
export function openFileChanged() {
  const b = S.build;
  S.modal = { kind: 'build-file-changed', loading: true, changes: [], error: '', busy: false };
  rerender();
  buildApi.diff(b.name, 'disk').then((d) => { if (S.modal && S.modal.kind === 'build-file-changed') { S.modal.changes = d.changes; S.modal.loading = false; rerender(); } })
    .catch((e) => { if (S.modal && S.modal.kind === 'build-file-changed') { S.modal.error = e.message; S.modal.loading = false; rerender(); } });
}
export function openGrid(sheetName, title) {
  S.modal = { kind: 'build-grid', title: title || sheetName, sheetName, loading: true, grid: null, error: '' };
  rerender();
  buildApi.sheet(S.build.name, sheetName).then((g) => { if (S.modal && S.modal.kind === 'build-grid' && S.modal.sheetName === sheetName) { S.modal.grid = g; S.modal.loading = false; rerender(); } })
    .catch((e) => { if (S.modal && S.modal.kind === 'build-grid' && S.modal.sheetName === sheetName) { S.modal.error = e.message; S.modal.loading = false; rerender(); } });
}

export async function reloadFromDisk() {
  const m = S.modal;
  if (!m) return;
  m.busy = true; rerender();
  try {
    S.build.model = (await buildApi.reload(S.build.name, S.build.env || undefined)).model;
    ensureSelection();
    S.modal = null;
    toast('Reloaded from disk. Your draft is gone.');
  } catch (e) { m.busy = false; m.error = e.message; }
  rerender();
}

// ---- keyboard shortcuts (⌘ on Mac, Ctrl elsewhere) ----------------------------------------------------------------
const typingIn = (el) => el instanceof Element && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);

document.addEventListener('keydown', (ev) => {
  if (S.route.name !== 'build' || S.modal) return;
  const mod = ev.metaKey || ev.ctrlKey;
  if (mod && !ev.shiftKey && ev.key.toLowerCase() === 'z') { ev.preventDefault(); undo(); return; }
  if (mod && (ev.key.toLowerCase() === 'y' || (ev.shiftKey && ev.key.toLowerCase() === 'z'))) { ev.preventDefault(); redo(); return; }
  if (mod && ev.key.toLowerCase() === 's') { ev.preventDefault(); saveToExcel(); return; }
  if (S.build.screen !== 'test' || typingIn(ev.target)) return;
  if ((ev.key === 'Delete' || ev.key === 'Backspace') && (S.build.ed.multi.length || S.build.ed.sel != null)) { ev.preventDefault(); deleteSelected(); }
  if (ev.key === 'Escape') { if (S.build.ed.menu) closeMenu(); else if (S.build.ed.multi.length) clearMulti(); }
});

// ---- new workbook / new test ---------------------------------------------------------------------------------------
async function createWorkbook() {
  const m = S.modal;
  const name = m.name.trim();
  if (!name) { m.error = 'Give the workbook a name.'; rerender(); return; }
  m.busy = true; m.error = ''; rerender();
  try {
    const envs = m.envs.filter((e) => e.name.trim()).map((e) => ({ name: e.name.trim(), domain: e.domain.trim(), production: e.production }));
    const r = await buildApi.newWorkbook({ name, environments: envs });
    S.modal = null;
    loadWorkbooks().catch(() => {});
    location.hash = buildUrl(r.name, 'map');
  } catch (e) { m.busy = false; m.error = e.message; rerender(); }
}

function openNewTest() { S.modal = { kind: 'build-new-test', name: '', busy: false, error: '' }; rerender(); }
async function createTest() {
  const m = S.modal;
  const name = m.name.trim();
  if (!name) { m.error = 'Give the test a name.'; rerender(); return; }
  m.busy = true; m.error = ''; rerender();
  const before = bm().tests.map((t) => t.id);
  const applied = await applyOps([{ op: 'add_test', name, kind: 'web' }]);
  if (!applied) { m.busy = false; rerender(); return; }
  S.modal = null;
  const added = bm().tests.map((t) => t.id).find((id) => !before.includes(id));
  if (added) gotoTest(S.build.name, added);
}

// ---- results tab (no dedicated screen until P06: jump to the latest finished run) ------------------------------
function goResults() {
  const done = S.runs.find((r) => !r.active);
  if (done) location.hash = `#/run/${done.run_id}`;
  else toast('No results yet. Run a test first.');
}

function goBuildTab() {
  const name = defaultBuildName();
  location.hash = name ? buildUrl(name, 'map') : '#/build';
}

// ---- environments dialog: local edits, applied together on Done -------------------------------------------------
function envAddColumn() {
  const m = S.modal;
  let n = 1;
  while (m.names.includes(`ENV${n}`)) n += 1;
  m.names.push(`ENV${n}`);
  m.rows.forEach((r) => { r.values[`ENV${n}`] = ''; });
  rerender();
}
function envAddRow() {
  const m = S.modal;
  m.rows.push({ variable: '', required: false, secret: false, values: Object.fromEntries(m.names.map((n) => [n, ''])) });
  rerender();
}
async function envSave() {
  const m = S.modal;
  m.busy = true; m.error = ''; rerender();
  const rows = m.rows.filter((r) => r.variable.trim()).map((r) => ({ variable: r.variable.trim(), required: !!r.required, secret: !!r.secret, values: r.values }));
  const applied = await applyOps([{ op: 'set_environments', names: m.names, production: m.production, rows }]);
  if (applied) { S.modal = null; toast('Environments saved.'); } else { m.busy = false; rerender(); }
}

async function fpSave() {
  const m = S.modal;
  const name = m.name.trim();
  if (!name) { m.error = 'Give the page a name.'; rerender(); return; }
  if (!m.urlContains.trim() && !m.landmark.trim()) { m.error = 'Add the address or a landmark (or both).'; rerender(); return; }
  m.busy = true; m.error = ''; rerender();
  const op = { op: 'set_fingerprint', name, urlContains: m.urlContains.trim(), landmark: m.landmark.trim(), landmarkText: m.landmarkText.trim(), notes: m.notes.trim() };
  if (m.rename && m.rename !== name) op.rename = m.rename;
  const applied = await applyOps([op]);
  if (applied) { S.modal = null; toast('Fingerprint saved.'); } else { m.busy = false; rerender(); }
}

export const acts = {
  'build-tab': goBuildTab,
  'run-tab'() { location.hash = '#/'; },
  'results-tab': goResults,
  'build-open-wb'(el) { gotoMap(el.dataset.name); },
  'build-goto-map'() { gotoMap(S.build.name); },
  'build-goto-variables'() { gotoVariables(S.build.name); },
  'build-goto-test'(el) { gotoTest(S.build.name, el.dataset.test); },
  'build-undo': undo,
  'build-redo': redo,
  'build-save'() { saveToExcel(false); },
  'build-history': openHistory,
  'build-toggle-problems': toggleProblems,
  'build-new-workbook': openNewWorkbook,
  'build-new-test': openNewTest,
  'build-nw-create': createWorkbook,
  'build-nw-add-env'(el) { const m = S.modal; m.envs.push({ name: '', domain: '', production: false }); rerender(); },
  'build-nw-remove-env'(el) { const m = S.modal; m.envs.splice(Number(el.dataset.i), 1); rerender(); },
  'build-nt-create': createTest,
  'build-open-environments': openEnvironments,
  'build-env-add-row': envAddRow,
  'build-env-add-col': envAddColumn,
  'build-env-remove-row'(el) { S.modal.rows.splice(Number(el.dataset.i), 1); rerender(); },
  'build-env-save': envSave,
  'build-open-fingerprints'() { S.modal = { kind: 'build-fingerprints' }; rerender(); },
  'build-fp-new'() { openFingerprint(null); },
  'build-fp-edit'(el) { openFingerprint(el.dataset.name); },
  'build-fp-save': fpSave,
  'build-fp-delete'(el) { deleteFingerprint(el.dataset.name); S.modal = null; rerender(); },
  'build-open-settings'() { openGrid('Global', 'Settings (Global)'); },
  'build-open-grid'(el) { openGrid(el.dataset.sheet); },
  'build-hist-pick'(el) { pickHistoryDiff(el.dataset.id); },
  'build-hist-restore'(el) { restoreHistory(el.dataset.id); },
  'build-file-changed': openFileChanged,
  'build-fc-reload': reloadFromDisk,
  'build-fc-save-anyway'() { saveToExcel(true); },
  'build-env-picker'(el) { setEnv(el.dataset.val); },
  'build-prev-block'() { stepBlock(-1); },
  'build-next-block'() { stepBlock(1); },
  'build-pick-block'(el) { setBlock(Number(el.dataset.i)); },
  'build-mode-cards'() { setMode('cards'); },
  'build-mode-grid'() { setMode('grid'); },
  'build-toggle-drawer': toggleDrawer,
  'build-toggle-menu': toggleMenu,
  'build-pick-step'(el) { selectStep(Number(el.dataset.row)); },
  'build-toggle-multi'(el, ev) { ev.stopPropagation(); toggleMultiStep(Number(el.dataset.row)); },
  'build-clear-multi': clearMulti,
  'build-insert'(el) { const method = el.dataset.method; if (method) insertStep(method); },
  'build-add-here'(el) { selectStep(Number(el.dataset.row)); toggleMenu(); },
  'build-delete-selected': deleteSelected,
  'build-toggle-enabled-step'(el) { const s = currentTest().steps.find((x) => x.row === Number(el.dataset.row)); updateStep(s.row, { enabled: !s.enabled }); },
  'build-toggle-side'(el) { const s = currentTest().steps.find((x) => x.row === Number(el.dataset.row)); updateStep(s.row, { sideEffects: !s.sideEffects }); },
  'build-set-onfail'(el) { updateStep(Number(el.dataset.row), { onFail: el.dataset.val }); },
  'build-drow-use'(el) { useDataRow(Number(el.dataset.row)); },
  'build-name-auto'(el) { updateStep(Number(el.dataset.row), { nameAuto: true }); },
  'build-bulk-enable'() { bulkEdit({ enabled: true }); },
  'build-bulk-disable'() { bulkEdit({ enabled: false }); },
  'build-bulk-stop'() { bulkEdit({ onFail: 'stop' }); },
  'build-bulk-continue'() { bulkEdit({ onFail: 'continue' }); },
  'build-move-block'() {
    const t = currentTest();
    if (!t || !t.blocks.length) return;
    const title = window.prompt(`Move to which block?\n(${t.blocks.map((b) => b.title).join(', ')})`, '');
    if (title && title.trim()) moveToBlock(title.trim());
  },
  'build-rename-block'() {
    const t = currentTest();
    const b = currentBlock();
    if (!t || !b) return;
    const title = window.prompt('Rename this block', b.title);
    const row = firstRowOfBlock(t, b);
    if (title && title.trim() && title.trim() !== b.title && row != null) renameBlock(row, title.trim());
  },
  'build-toggle-test'(el) { applyOps([{ op: 'set_test', test: el.dataset.test, enabled: el.dataset.val === '1' }]); },
  'build-select-variable'(el) { selectVariable(el.dataset.field); },
  'build-jump-step'(el) { jumpToStep(S.build.name, el.dataset.test, Number(el.dataset.row)); },
};

export const changes = {
  'build-nw-env-prod'(el) { S.modal.envs[Number(el.dataset.i)].production = el.checked; rerender(); },
  'build-env-prod'(el) { const n = el.dataset.env; const m = S.modal; m.production = el.checked ? [...new Set([...m.production, n])] : m.production.filter((x) => x !== n); rerender(); },
  'build-env-required'(el) { S.modal.rows[Number(el.dataset.i)].required = el.checked; rerender(); },
  'build-env-secret'(el) { S.modal.rows[Number(el.dataset.i)].secret = el.checked; rerender(); },
  'build-step-onfail'(el) { updateStep(Number(el.dataset.row), { onFail: el.value }); },
  'build-step-match'(el) { updateStep(Number(el.dataset.row), { match: el.value }); },
};

export const inputs = {
  'build-nw-name'(el) { S.modal.name = el.value; },
  'build-nw-env-name'(el) { S.modal.envs[Number(el.dataset.i)].name = el.value; },
  'build-nw-env-domain'(el) { S.modal.envs[Number(el.dataset.i)].domain = el.value; },
  'build-nt-name'(el) { S.modal.name = el.value; },
  'build-env-var'(el) { S.modal.rows[Number(el.dataset.i)].variable = el.value; },
  'build-env-cell'(el) { S.modal.rows[Number(el.dataset.i)].values[el.dataset.env] = el.value; },
  'build-fp-name'(el) { S.modal.name = el.value; },
  'build-fp-url'(el) { S.modal.urlContains = el.value; },
  'build-fp-landmark'(el) { S.modal.landmark = el.value; },
  'build-fp-landmark-text'(el) { S.modal.landmarkText = el.value; },
  'build-fp-notes'(el) { S.modal.notes = el.value; },
  'build-step-name'(el) { updateStepDebounced(Number(el.dataset.row), { name: el.value, nameAuto: false }); },
  'build-step-value'(el) { updateStepDebounced(Number(el.dataset.row), { value: el.value }); },
  'build-step-expected'(el) { updateStepDebounced(Number(el.dataset.row), { expected: el.value }); },
  'build-step-saveas'(el) { updateStepDebounced(Number(el.dataset.row), { saveAs: el.value }); },
  'build-step-timeout'(el) { const n = Number(el.value); updateStepDebounced(Number(el.dataset.row), { timeout: Number.isFinite(n) && el.value !== '' ? n : null }); },
  'build-step-notes'(el) { updateStepDebounced(Number(el.dataset.row), { notes: el.value }); },
  'build-menu-query'(el) { S.build.ed.menuQuery = el.value; rerender(); },
  'build-drow-cell'(el) { setDataCellDebounced(Number(el.dataset.row), el.dataset.col, el.value); },
};
