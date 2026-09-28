// Everything the Build tab can do: load a workbook, apply ops, undo/redo/save, and the screen/step/selection state
// that drives views/build/*.js. Merged into the app's data-act / data-change / data-input tables by main.js.
import { S, rerender, freshBuild, freshEditor } from '../../state.js';
import * as buildApi from './api.js';
import { toast, debounce } from '../../util.js';
import { loadWorkbooks } from '../../actions.js';
import { api } from '../../api.js';

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
  if (screen === 'scenario' && testId) return `#/build/${n}/scenario/${enc(testId)}`;
  if (screen === 'test' && testId) return `#/build/${n}/test/${enc(testId)}`;
  return `#/build/${n}`;
}

function ensureSelection() {
  const m = S.build.model;
  // A workbook with its own environment table has no default environment: the Build tab works in the one the model says (the one picked,
  // else the table's first) and every later call names it, so the build window, Send now and "Run it on" never fall back to Global.
  if (m && m.environments && m.environments.source === 'rr' && m.environment && S.build.env !== m.environment) S.build.env = m.environment;
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

/** Open (or switch screen within) a workbook. Called by main.js on every #/build... route. */
export async function openBuild(name, screen = 'map', testId = null) {
  const b = S.build;
  b.listing = false;
  const switching = b.name !== name;
  const stagedSel = b.pendingSel;                            // jumpToStep may have staged this just before the workbook switched
  if (switching) { const kw = b.keywords; Object.assign(b, freshBuild(), { name, keywords: kw, pendingSel: stagedSel }); }
  const prevTest = b.testId;
  b.screen = screen; b.testId = screen === 'scenario' ? null : testId;
  b.scenario = screen === 'scenario' ? testId : null;       // (P12: the scenario board's scenario name)
  if (screen === 'test' && testId !== prevTest) b.ed = freshEditor();
  b.error = null;
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

/** The "All workbooks" page: every workbook in the folder, to open another one (the one open stays loaded behind it). */
export function openWorkbookList() { S.build.listing = true; rerender(); }

/** Download a workbook as it is saved on disk. The one being edited with unsaved changes can be saved first (Save to Excel). */
export async function downloadWorkbook(name) {
  const b = S.build;
  if (!name) return;
  if (b.name === name && b.model && b.model.status && b.model.status.modified) {
    if (window.confirm('This workbook has changes that are not saved to Excel yet.\n\nOK: save them, then download.\nCancel: download the last saved version.')) {
      await saveToExcel(false);
      if (S.build.model && S.build.model.status && S.build.model.status.modified) return;       // (the save did not go through: it said why)
    }
  }
  let secrets = [];
  try { secrets = (await api(`/api/workbooks/${enc(name)}/download-info`)).secrets || []; } catch (e) { /* (an older server: download as before) */ }
  if (secrets.length) { S.modal = { kind: 'build-download-secrets', name, secrets }; rerender(); return; }        // say it first: the file has no secret values
  startDownload(name);
}

/** Hand the saved file to the browser as a download. */
export function startDownload(name) {
  const a = document.createElement('a');
  a.href = `/api/workbooks/${encodeURIComponent(name)}/download`;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
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
  const s = t.steps.find((x) => x.n >= b.start && x.n <= b.end);
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
  if (b.ed.gridLoading) return;
  b.ed.gridLoading = true;
  if (!b.ed.grid || b.ed.grid === 'loading') { b.ed.grid = 'loading'; rerender(); }      // (a reload after an edit keeps showing the old one)
  const version = b.model ? b.model.version : null;
  try { const g = await buildApi.sheet(b.name, t.sheet); if (currentTest() === t) b.ed.grid = { ...g, version }; }
  catch (e) { if (currentTest() === t) b.ed.grid = null; }
  b.ed.gridLoading = false;
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
  let after = ed.sel != null ? ed.sel : (b ? (t.steps.find((s) => s.n === b.end) || {}).row : undefined);
  const step = { method, ...opts };
  if (ed.pendingBlock) {                                          // the first step of a new page: at the end of the test, on that page
    step.block = ed.pendingBlock;
    after = t.steps.length ? t.steps[t.steps.length - 1].row : undefined;
  }
  const applied = await applyOps([{ op: 'insert_step', test: t.id, after, step }]);
  if (applied) ed.pendingBlock = null;
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
  // into an existing block: land at its end (before the next block's first step), not at the end of the test
  const target = t.blocks.find((b) => b.title === title);
  const next = target ? t.steps.find((s) => s.n === target.end + 1 && !rows.includes(s.row)) : null;
  applyOps([{ op: 'move_steps', test: t.id, rows, block: title, ...(next ? { before: next.row } : {}) }]);
}

/** Where the "selected" bar was dragged to, kept for the browser session (per viewer; nothing to lose if storage is off). */
export function rememberBulkPos(pos) { try { sessionStorage.setItem('rr.build.bulkPos', JSON.stringify(pos)); } catch (e) { /* storage unavailable */ } }
export function forgetBulkPos() { try { sessionStorage.removeItem('rr.build.bulkPos'); } catch (e) { /* storage unavailable */ } }
export function rememberedBulkPos() {
  try { const p = JSON.parse(sessionStorage.getItem('rr.build.bulkPos') || 'null'); return p && Number.isFinite(p.x) && Number.isFinite(p.y) ? p : null; }
  catch (e) { return null; }
}

/** Drag and drop (dragsort.js): ``rows`` go before ``before`` (null = after the test's last step); ``block`` = the block they land in, when
 * that is not the block they come from. */
export function moveSteps(rows, before, block) {
  const t = currentTest();
  if (!t || !rows.length) return;
  const from = new Set(t.steps.filter((s) => rows.includes(s.row)).map((s) => s.block));
  const op = { op: 'move_steps', test: t.id, rows };
  if (before != null) op.before = before;
  if (block && (from.size !== 1 || !from.has(block))) op.block = block;
  applyOps([op]);
}

/** "Start a new page at this step": the step and the rest of its block become a new block (the split_block op). */
export function startPageAt(row) {
  const t = currentTest();
  const s = t && t.steps.find((x) => x.row === row);
  if (!s) return;
  const b = t.blocks.find((x) => s.n >= x.start && s.n <= x.end);
  if (b && b.start === s.n) { toast(`Step ${s.n} already starts the page “${b.title}”. Rename that page instead (the pencil next to its name).`, 6000); return; }
  const title = window.prompt(`A name for the new page starting at step ${s.n}:`, '');
  if (!title || !title.trim()) return;
  applyOps([{ op: 'split_block', test: t.id, row, title: title.trim() }]).then((applied) => { if (applied) selectStep(row); });
}

/** "New page": the next step added goes on a new page at the end of the test (a block exists only through its steps). */
export function newPage() {
  const t = currentTest();
  if (!t) return;
  const title = window.prompt('A name for the new page (its first step comes next):', '');
  if (!title || !title.trim()) return;
  const ed = S.build.ed;
  ed.pendingBlock = title.trim();
  ed.menu = true; ed.menuQuery = '';
  if (!S.build.keywords) buildApi.keywords().then((k) => { S.build.keywords = k; rerender(); }).catch(() => {});
  rerender();
}
export function renameBlock(row, title) { const t = currentTest(); if (t) applyOps([{ op: 'rename_block', test: t.id, row, title }]); }
function firstRowOfBlock(t, b) { const s = t.steps.find((x) => x.n >= b.start && x.n <= b.end); return s ? s.row : null; }

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
  S.modal = { kind: 'build-file-changed', loading: true, changes: [], picks: {}, error: '', busy: false };
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

export async function mergeFromDisk() {
  const m = S.modal;
  if (!m || m.kind !== 'build-file-changed') return;
  const picks = Object.fromEntries(Object.entries(m.picks).filter(([, v]) => v === 'theirs'));
  if (!Object.keys(picks).length) return;
  m.busy = true; m.error = ''; rerender();
  try {
    const r = await buildApi.merge(S.build.name, picks, bm().version, S.build.env || undefined);
    S.build.model = r.model;
    ensureSelection();
    S.modal = null;
    toast(`Merged ${r.applied.length} step${r.applied.length === 1 ? '' : 's'} from Excel.`);
  } catch (e) { m.busy = false; m.error = e.message; rerender(); }
}

// ---- copy / paste steps (client-side clipboard; P11) ---------------------------------------------------------------
function stepToClipboard(s) {
  const f = { method: s.method, page: s.page, findBy: s.locator.findBy, locator: s.locator.value, locatorName: s.locator.name,
    value: s.value, expected: s.expected, match: s.match, output: s.output, outputProperty: s.outputProperty,
    onFail: s.onFail, timeout: s.timeout, enabled: s.enabled !== false, sideEffects: s.sideEffects,
    backups: (s.locator.backups || []).slice(), notes: s.notes };
  if (s.locator.index) f.index = s.locator.index;
  if (!s.nameAuto && s.name) f.name = s.name; else f.nameAuto = true;
  return f;
}
export function copySelected() {
  const t = currentTest();
  const ed = S.build.ed;
  const rows = ed.multi.length ? ed.multi.slice() : (ed.sel != null ? [ed.sel] : []);
  if (!t || !rows.length) return;
  const steps = t.steps.filter((s) => rows.includes(s.row)).sort((a, b) => a.n - b.n).filter((s) => !s.legacy);
  if (!steps.length) { toast('Legacy rows cannot be copied.', 5000); return; }
  S.build.clip = { steps: steps.map(stepToClipboard) };
  toast(`Copied ${steps.length} step${steps.length === 1 ? '' : 's'}.`);
}
export function pasteClipboard() {
  const clip = S.build.clip;
  const t = currentTest();
  const ed = S.build.ed;
  if (!clip || !t) return;
  const anchor = ed.sel != null ? ed.sel : (t.steps.length ? t.steps[t.steps.length - 1].row : 1);
  applyOps(clip.steps.map((step, i) => ({ op: 'insert_step', test: t.id, after: anchor + i, step: { ...step } })));
}

// ---- templates: browse, save a selection, insert with mapping (Q15-17) ---------------------------------------------
export function openTemplatesLibrary() {
  S.modal = { kind: 'build-templates', loading: true, items: [], error: '' };
  rerender();
  buildApi.templates().then((r) => { if (S.modal && S.modal.kind === 'build-templates') { S.modal.items = r.templates; S.modal.loading = false; rerender(); } })
    .catch((e) => { if (S.modal && S.modal.kind === 'build-templates') { S.modal.error = e.message; S.modal.loading = false; rerender(); } });
}

export function openSaveTemplate() {
  const t = currentTest();
  const ed = S.build.ed;
  const rows = ed.multi.length ? ed.multi.slice() : (ed.sel != null ? [ed.sel] : []);
  if (!t || !rows.length) return;
  const sorted = rows.slice().sort((a, b) => a - b);
  S.modal = { kind: 'build-save-template', name: '', description: '', fromRow: sorted[0], toRow: sorted[sorted.length - 1],
    count: t.steps.filter((s) => s.row >= sorted[0] && s.row <= sorted[sorted.length - 1]).length, busy: false, error: '' };
  rerender();
}
async function saveTemplateNow() {
  const m = S.modal;
  const name = m.name.trim();
  if (!name) { m.error = 'Give the template a name.'; rerender(); return; }
  m.busy = true; m.error = ''; rerender();
  const t = currentTest();
  try {
    await buildApi.saveTemplate({ workbook: S.build.name, test: t.id, fromRow: m.fromRow, toRow: m.toRow, name, description: m.description.trim() });
    S.modal = null;
    toast(`Saved "${name}" to the template library.`);
  } catch (e) { m.busy = false; m.error = e.message; rerender(); }
}

export function openInsertTemplate() {
  if (!currentTest()) return;
  S.build.ed.menu = false;
  S.modal = { kind: 'build-insert-template', step: 'pick', loading: true, items: [], error: '', busy: false };
  rerender();
  buildApi.templates().then((r) => { if (S.modal && S.modal.kind === 'build-insert-template' && S.modal.step === 'pick') { S.modal.items = r.templates; S.modal.loading = false; rerender(); } })
    .catch((e) => { if (S.modal && S.modal.kind === 'build-insert-template') { S.modal.error = e.message; S.modal.loading = false; rerender(); } });
}
async function chooseTemplateToInsert(name) {
  const m = S.modal;
  if (!m) return;
  const t = currentTest();
  const ed = S.build.ed;
  const after = ed.sel != null ? ed.sel : (t.steps.length ? t.steps[t.steps.length - 1].row : null);
  const afterN = after != null ? (t.steps.find((s) => s.row === after) || {}).n || 0 : 0;
  Object.assign(m, { step: 'map', busy: false, error: '', after, afterN, template: null, mapping: [] });
  rerender();
  try {
    const r = await buildApi.templateMapping(name, S.build.name);
    if (S.modal !== m) return;
    m.template = r.template; m.mapping = r.mapping;
  } catch (e) { m.error = e.message; }
  rerender();
}
async function insertTemplateNow() {
  const m = S.modal;
  const t = currentTest();
  m.busy = true; m.error = ''; rerender();
  const mapping = {};
  m.mapping.forEach((r) => { mapping[r.templateVar] = r.mine; });
  try {
    const res = await buildApi.insertTemplate(S.build.name, { template: m.template.name, test: t.id, after: m.after, mapping,
      version: bm().version }, S.build.env || undefined);
    S.build.model = res.model; ensureSelection(); S.modal = null;
    toast(`Inserted ${m.template.count} step${m.template.count === 1 ? '' : 's'}.`);
  } catch (e) { m.busy = false; m.error = e.message; rerender(); }
}

// ---- duplicate workbook: "what changes?" + find and replace (Q26) --------------------------------------------------
export function openDuplicateWorkbook() {
  const b = S.build;
  if (!b.name) return;
  S.modal = { kind: 'build-duplicate', source: b.name, name: '', loading: true, rows: [], find: '', replace: '', busy: false, error: '' };
  rerender();
  buildApi.duplicateCandidates(b.name, '').then((r) => {
    if (!S.modal || S.modal.kind !== 'build-duplicate') return;
    S.modal.rows = r.rows.map((x) => ({ ...x, on: x.kind !== 'text' }));
    S.modal.loading = false; rerender();
  }).catch((e) => { if (S.modal && S.modal.kind === 'build-duplicate') { S.modal.error = e.message; S.modal.loading = false; rerender(); } });
}
function dupAddPair() {
  const m = S.modal;
  if (!m.find.trim()) return;
  m.rows.push({ kind: 'custom', label: `“${m.find.trim()}”`, find: m.find.trim(), replace: m.replace.trim(), whole: true, on: true });
  m.find = ''; m.replace = ''; rerender();
}
async function runDuplicate() {
  const m = S.modal;
  const name = m.name.trim();
  if (!name) { m.error = 'Give the new workbook a name.'; rerender(); return; }
  m.busy = true; m.error = ''; rerender();
  try {
    const created = await buildApi.newWorkbook({ name, from: m.source });
    const pairs = m.rows.filter((r) => r.on && r.replace.trim()).map((r) => ({ find: r.find, replace: r.replace.trim(), whole: r.whole !== false }));
    if (pairs.length) {
      const preview = await buildApi.findPreview(created.name, pairs);
      if (preview.hits.length) await buildApi.findApply(created.name, preview.hits, created.model.version);
    }
    S.modal = null;
    loadWorkbooks().catch(() => {});
    location.hash = buildUrl(created.name, 'map');
    toast(`Duplicated as ${created.name}.`);
  } catch (e) { m.busy = false; m.error = e.message; rerender(); }
}

// ---- find & replace across the whole workbook ----------------------------------------------------------------------
export function openFindReplace() {
  if (!S.build.name) return;
  S.modal = { kind: 'build-find-replace', find: '', replace: '', whole: true, hits: [], searched: false, loading: false, busy: false, error: '' };
  rerender();
}
async function findPreviewNow() {
  const m = S.modal;
  if (!m.find.trim()) { m.error = 'Say what to find.'; rerender(); return; }
  m.loading = true; m.error = ''; rerender();
  try {
    const r = await buildApi.findPreview(S.build.name, [{ find: m.find.trim(), replace: m.replace, whole: m.whole }]);
    m.hits = r.hits.map((h) => ({ ...h, on: true })); m.searched = true;
  } catch (e) { m.error = e.message; }
  m.loading = false; rerender();
}
async function findApplyNow() {
  const m = S.modal;
  const chosen = m.hits.filter((h) => h.on);
  if (!chosen.length) return;
  m.busy = true; m.error = ''; rerender();
  try {
    const r = await buildApi.findApply(S.build.name, chosen, bm().version, S.build.env || undefined);
    S.build.model = r.model; ensureSelection();
    toast(`Replaced ${chosen.length}.`);
    S.modal = null;
  } catch (e) { m.busy = false; m.error = e.message; rerender(); }
}

// ---- value builder: writes a real Excel formula (Q23) ----------------------------------------------------------------
function quoteText(text) { return `"${String(text).trim().replace(/"/g, '""')}"`; }
function mathOperand(text) {
  const t = String(text).trim();
  return /^\{[?A-Za-z_][A-Za-z0-9_:]*\}$/.test(t) || /^-?\d+(\.\d+)?$/.test(t) ? t : quoteText(t);
}
function refreshValueBuilderFormula() {
  const m = S.modal;
  if (!m || m.kind !== 'build-value-builder') return;
  if (m.tab === 'date') {
    const off = Number(m.offset) || 0;
    const expr = off ? `TODAY()${off > 0 ? '+' : ''}${off}` : 'TODAY()';
    m.formula = `=TEXT(${expr},"${(m.fmt || 'mm/dd/yyyy').replace(/"/g, '')}")`;
  } else if (m.tab === 'unique') {
    m.formula = m.suffix.trim() ? `=CONCAT(${quoteText(m.prefix)},RANDBETWEEN(100000,999999),${quoteText(m.suffix)})`
      : `=CONCAT(${quoteText(m.prefix)},TEXT(NOW(),"yyyymmddhhmmss"),"-",RANDBETWEEN(1,999))`;
  } else if (m.tab === 'pick') {
    const items = m.list.split('\n').map((x) => x.trim()).filter(Boolean);
    m.formula = items.length ? `=CHOOSE(RANDBETWEEN(1,${items.length}),${items.map(quoteText).join(',')})` : '';
  } else if (m.tab === 'math') {
    m.formula = m.a.trim() && m.b.trim() ? `=${mathOperand(m.a)}${m.op}${mathOperand(m.b)}` : '';
  } else {
    const parts = m.parts.split('\n').map((x) => x.trim()).filter(Boolean);
    m.formula = parts.length ? `=TEXTJOIN(${quoteText(m.delim || '')},TRUE,${parts.map(quoteText).join(',')})` : '';
  }
}
export function openValueBuilder(row) {
  S.modal = { kind: 'build-value-builder', row, tab: 'date', offset: 0, fmt: 'mm/dd/yyyy', prefix: 'qa+', suffix: '@example.com',
    list: 'Basic\nPlus\nMax', a: '', op: '+', b: '', parts: '', delim: ' ', formula: '', error: '' };
  refreshValueBuilderFormula();
  rerender();
}
function useValueBuilder() {
  const m = S.modal;
  if (!m.formula) { m.error = 'Fill in the value builder first.'; rerender(); return; }
  updateStep(m.row, { value: m.formula });
  S.modal = null; rerender();
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

function openNewTest() { S.modal = { kind: 'build-new-test', name: '', testKind: 'web', busy: false, error: '' }; rerender(); }
async function createTest() {
  const m = S.modal;
  const name = m.name.trim();
  if (!name) { m.error = 'Give the test a name.'; rerender(); return; }
  m.busy = true; m.error = ''; rerender();
  const before = bm().tests.map((t) => t.id);
  const k = m.testKind || 'web';
  const applied = await applyOps([k === 'web' ? { op: 'add_test', name, kind: 'web' } : { op: 'api_add_test', name, format: k === 'xml' ? 'xml' : 'json' }]);
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

/** The Build tab button always starts from every workbook (a link that names a workbook or a step still goes straight there). */
function goBuildTab() { location.hash = '#/build/all'; }

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
  'build-download'(el) { downloadWorkbook(el.dataset.name || S.build.name); },
  'build-download-go'(el) { const name = el.dataset.name; S.modal = null; rerender(); startDownload(name); },
  'build-history': openHistory,
  'build-toggle-problems': toggleProblems,
  'build-new-workbook': openNewWorkbook,
  'build-new-test': openNewTest,
  'build-nt-kind'(el) { if (S.modal) { S.modal.testKind = el.dataset.val; rerender(); } },
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
  'build-start-page'(el) { S.build.ed.menu = false; startPageAt(Number(el.dataset.row) || S.build.ed.sel); },
  'build-new-page'() { newPage(); },
  'build-new-page-cancel'() { S.build.ed.pendingBlock = null; rerender(); },
  'build-bulk-home'() { forgetBulkPos(); rerender(); },
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
  // ---- templates / copy-paste / duplicate / find-replace / merge / value builder (P11) ----------------------------
  'build-open-templates': openTemplatesLibrary,
  'build-save-template': openSaveTemplate,
  'build-tpl-save': saveTemplateNow,
  'build-open-insert-template': openInsertTemplate,
  'build-tpl-choose'(el) { chooseTemplateToInsert(el.dataset.name); },
  'build-tpl-back'() { S.modal.step = 'pick'; rerender(); },
  'build-tpl-insert': insertTemplateNow,
  'build-copy-steps': copySelected,
  'build-paste-steps': pasteClipboard,
  'build-open-duplicate': openDuplicateWorkbook,
  'build-dup-add': dupAddPair,
  'build-dup-run': runDuplicate,
  'build-open-find-replace': openFindReplace,
  'build-fr-preview': findPreviewNow,
  'build-fr-apply': findApplyNow,
  'build-fr-whole'(el) { S.modal.whole = el.dataset.val === '1'; rerender(); },
  'build-fc-pick'(el) { const m = S.modal; m.picks[el.dataset.key] = el.dataset.val === 'theirs' ? 'theirs' : 'mine'; rerender(); },
  'build-fc-merge': mergeFromDisk,
  'build-open-value-builder'(el) { openValueBuilder(Number(el.dataset.row)); },
  'build-vb-tab'(el) { S.modal.tab = el.dataset.val; refreshValueBuilderFormula(); rerender(); },
  'build-vb-op'(el) { S.modal.op = el.dataset.val; refreshValueBuilderFormula(); rerender(); },
  'build-vb-use': useValueBuilder,
};

export const changes = {
  'build-env-select'(el) { setEnv(el.value); },
  'build-nw-env-prod'(el) { S.modal.envs[Number(el.dataset.i)].production = el.checked; rerender(); },
  'build-env-prod'(el) { const n = el.dataset.env; const m = S.modal; m.production = el.checked ? [...new Set([...m.production, n])] : m.production.filter((x) => x !== n); rerender(); },
  'build-env-required'(el) { S.modal.rows[Number(el.dataset.i)].required = el.checked; rerender(); },
  'build-env-secret'(el) { S.modal.rows[Number(el.dataset.i)].secret = el.checked; rerender(); },
  'build-step-onfail'(el) { updateStep(Number(el.dataset.row), { onFail: el.value }); },
  'build-step-match'(el) { updateStep(Number(el.dataset.row), { match: el.value }); },
  'build-step-findby'(el) { if (el.value) updateStep(Number(el.dataset.row), { findBy: el.value }); },
  'build-dup-toggle'(el) { S.modal.rows[Number(el.dataset.i)].on = el.checked; rerender(); },
  'build-fr-toggle'(el) { S.modal.hits[Number(el.dataset.i)].on = el.checked; rerender(); },
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
  'build-step-locator'(el) {
    const value = el.value.trim();
    // a step with no FindBy yet gets the one the text looks like: //… or (//…) is XPath, #/./[ or a space is CSS, a bare word an id
    const findBy = el.dataset.findby || (!value ? '' : /^\(*\//.test(value) ? 'BY_XPATH' : /[#.[\s>:]/.test(value) ? 'BY_CSSSELECTOR' : 'BY_ID');
    updateStepDebounced(Number(el.dataset.row), findBy ? { locator: value, findBy } : { locator: value });
  },
  'build-step-expected'(el) { updateStepDebounced(Number(el.dataset.row), { expected: el.value }); },
  'build-step-saveas'(el) { updateStepDebounced(Number(el.dataset.row), { saveAs: el.value }); },
  'build-step-timeout'(el) { const n = Number(el.value); updateStepDebounced(Number(el.dataset.row), { timeout: Number.isFinite(n) && el.value !== '' ? n : null }); },
  'build-step-notes'(el) { updateStepDebounced(Number(el.dataset.row), { notes: el.value }); },
  'build-menu-query'(el) { S.build.ed.menuQuery = el.value; rerender(); },
  'build-drow-cell'(el) { setDataCellDebounced(Number(el.dataset.row), el.dataset.col, el.value); },
  'build-tpl-name'(el) { S.modal.name = el.value; },
  'build-tpl-desc'(el) { S.modal.description = el.value; },
  'build-dup-name'(el) { S.modal.name = el.value; },
  'build-dup-replace'(el) { S.modal.rows[Number(el.dataset.i)].replace = el.value; rerender(); },
  'build-dup-find'(el) { S.modal.find = el.value; },
  'build-dup-repl'(el) { S.modal.replace = el.value; },
  'build-fr-find'(el) { S.modal.find = el.value; },
  'build-fr-repl'(el) { S.modal.replace = el.value; },
  'build-vb-offset'(el) { S.modal.offset = el.value; refreshValueBuilderFormula(); rerender(); },
  'build-vb-fmt'(el) { S.modal.fmt = el.value; refreshValueBuilderFormula(); rerender(); },
  'build-vb-prefix'(el) { S.modal.prefix = el.value; refreshValueBuilderFormula(); rerender(); },
  'build-vb-suffix'(el) { S.modal.suffix = el.value; refreshValueBuilderFormula(); rerender(); },
  'build-vb-list'(el) { S.modal.list = el.value; refreshValueBuilderFormula(); rerender(); },
  'build-vb-a'(el) { S.modal.a = el.value; refreshValueBuilderFormula(); rerender(); },
  'build-vb-b'(el) { S.modal.b = el.value; refreshValueBuilderFormula(); rerender(); },
  'build-vb-parts'(el) { S.modal.parts = el.value; refreshValueBuilderFormula(); rerender(); },
  'build-vb-delim'(el) { S.modal.delim = el.value; refreshValueBuilderFormula(); rerender(); },
};
