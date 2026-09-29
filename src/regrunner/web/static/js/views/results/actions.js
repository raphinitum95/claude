// Everything the Results tab can do: load the history list / batch page / test page / compare, and re-run a
// batch's failures. Merged into the app's data-act / data-change / data-input tables by main.js.
import { S, rerender } from '../../state.js';
import { api as rawApi } from '../../api.js';
import { loadRuns, openBatch } from '../../actions.js';
import { toast } from '../../util.js';
import { jumpToStep } from '../build/actions.js';
import * as api from './api.js';

const enc = encodeURIComponent;

export function resultsUrl(screen, a, b) {
  if (screen === 'batch') return `#/results/batch/${enc(a)}`;
  if (screen === 'test') return `#/results/test/${enc(a)}/${enc(b)}`;
  if (screen === 'compare') return '#/results/compare';
  if (screen === 'run') return `#/results/run/${enc(a)}`;
  return '#/results';
}

/** Called by main.js on every #/results... route. */
export function openResults(screen, a, b) {
  const r = S.results;
  r.screen = screen;
  if (screen === 'batch') return loadBatch(a);
  if (screen === 'test') return loadTest(a, b);
  if (screen === 'compare') return loadCompare();
  if (screen === 'run') return null;                      // (main.js opens the run itself: the same page as Run's, shown in this tab)
  return loadHistory();
}

async function loadHistory() {
  const h = S.results.history;
  h.loading = true; h.error = null; rerender();
  try {
    const [batches] = await Promise.all([api.batches(), loadRuns()]);
    h.batches = batches; h.loading = false;
  } catch (e) { h.error = e; h.loading = false; }
  rerender();
}

async function loadBatch(id) {
  const b = S.results.batch;
  if (b.id !== id) b.data = null;
  b.id = id; b.loading = true; b.error = null; rerender();
  try { b.data = await api.batchPage(id); } catch (e) { b.error = e; }
  b.loading = false; rerender();
}

async function loadTest(runId, testId) {
  const t = S.results.test;
  t.runId = runId; t.testId = testId; t.run = null; t.page = null; t.showAllFails = false;
  t.loading = true; t.error = null; rerender();
  try {
    const [run, page] = await Promise.all([rawApi(`/api/runs/${enc(runId)}`), api.testPage(runId, testId)]);
    t.run = run; t.page = page;
  } catch (e) { t.error = e; }
  t.loading = false; rerender();
}

export async function loadCompare() {
  const c = S.results.compare;
  c.loading = true; c.error = null; rerender();
  try { c.data = await api.compare(c.workbooks, c.n); } catch (e) { c.error = e; }
  c.loading = false; rerender();
}

async function rerunBatchFailed(id) {
  try {
    const res = await api.rerunFailed(id);
    await loadRuns();
    if (res.skipped_no_failures && res.skipped_no_failures.length) toast(`Nothing of ${res.skipped_no_failures.join(', ')} failed: not re-run.`, 5000);
    location.hash = res.batch_id ? resultsUrl('batch', res.batch_id) : resultsUrl('run', res.run_ids[0]);
  } catch (e) { toast(e.message, 6000); }
}

// ---- delete a run, or a whole batch -----------------------------------------------------------------------------------
// Deleting moves the run folders to runs/.trash/ (the server's DELETE /api/runs/<id>, DELETE /api/batches/<id>). A batch is only a label, so
// deleting one run of it just leaves the batch with one run fewer, and the batch goes away with its last run.
function askDeleteRun(id, batchId) {
  const run = S.runs.find((r) => r.run_id === id);
  S.modal = { kind: 'delete-runs', scope: 'run', id, batchId: batchId || (run && run.batch_id) || '', runIds: [id], label: id,
              detail: run ? String(run.workbook || '').split(/[\\/]/).pop() : '', busy: false, error: '' };
  rerender();
}

function askDeleteBatch(id) {
  const runs = S.runs.filter((r) => r.batch_id === id);
  if (runs.some((r) => r.active)) { toast('This batch is still running. Stop it before deleting it.', 5000); return; }
  const label = (runs.find((r) => r.batch_label) || {}).batch_label;
  S.modal = { kind: 'delete-runs', scope: 'batch', id, batchId: id, runIds: runs.map((r) => r.run_id), label: label ? `${label} (${id})` : `Batch ${id}`,
              detail: '', busy: false, error: '' };
  rerender();
}

/** Where to go once the runs are gone: off a page that was about them, or refresh the one that listed them. */
async function afterDelete(m) {
  await loadRuns().catch(() => {});
  const gone = new Set(m.runIds);
  const inResults = S.route.name === 'results';
  const bid = m.batchId;
  const left = bid ? S.runs.filter((r) => r.batch_id === bid).length : 0;
  const home = inResults ? '#/results' : '#/';
  const v = S.view;
  const viewingDeletedRun = v && v.kind === 'run' && gone.has(v.id);
  const viewingBatch = bid && ((v && v.kind === 'batch' && v.id === bid) || (inResults && S.results.screen === 'batch' && S.results.batch.id === bid));
  const viewingDeletedTest = inResults && S.results.screen === 'test' && gone.has(S.results.test.runId);
  if (viewingDeletedRun) { location.hash = left ? (inResults ? resultsUrl('batch', bid) : `#/batch/${enc(bid)}`) : home; return; }
  if (viewingDeletedTest || (viewingBatch && !left)) { location.hash = home; return; }
  if (viewingBatch) { if (inResults) await loadBatch(bid); else await openBatch(bid); return; }
  if (inResults && S.results.screen === 'compare') { await loadCompare(); return; }
  if (inResults && S.results.screen === 'history') { await loadHistory(); return; }
  rerender();
}

async function confirmDeleteRuns() {
  const m = S.modal;
  if (!m || m.kind !== 'delete-runs' || m.busy) return;
  m.busy = true; m.error = ''; rerender();
  const url = m.scope === 'batch' ? `/api/batches/${enc(m.id)}` : `/api/runs/${enc(m.id)}`;
  try {
    await rawApi(url, { method: 'DELETE' });
  } catch (e) {
    if (e.kind !== 'not_found') {          // "not_found" = already gone (deleted in another window): carry on and refresh; a bare 405 is a server older than this page
      m.busy = false;
      m.error = e.status === 405 ? 'The running server does not know how to delete runs: it is older than this page. Close the UI (or press Ctrl+C in its window), start it again, then retry.' : e.message;
      if (e.data && e.data.deleted && e.data.deleted.length) { m.runIds = m.runIds.filter((id) => !e.data.deleted.includes(id)); loadRuns().then(rerender).catch(() => {}); }
      rerender();
      return;
    }
  }
  if (S.modal === m) S.modal = null;
  toast(m.scope === 'batch' ? `${m.label} deleted (${m.runIds.length} run${m.runIds.length === 1 ? '' : 's'}). A copy is in runs/.trash.` : `${m.label} deleted. A copy is in runs/.trash.`, 5000);
  await afterDelete(m);
}

export const acts = {
  'results-tab'() { location.hash = '#/results'; },
  'ask-delete-run'(el) { askDeleteRun(el.dataset.id, el.dataset.batch); },
  'ask-delete-batch'(el) { askDeleteBatch(el.dataset.id); },
  'confirm-delete-runs': confirmDeleteRuns,
  async 'results-rerun-failed'(el) { await rerunBatchFailed(el.dataset.id); },
  /** Opens the Build tab on this test, with the given step (a failed one, usually) selected - the "Fix in builder" button. */
  'results-fix-in-builder'(el) { jumpToStep(el.dataset.wb, el.dataset.test, el.dataset.row ? Number(el.dataset.row) : null); },
  'results-toggle-fails'() { S.results.test.showAllFails = !S.results.test.showAllFails; rerender(); },
  'results-toggle-filter'(el) {
    const h = S.results.history;
    const { field, val } = el.dataset;
    h[field] = h[field] === val ? '' : val;
    rerender();
  },
  'results-compare-toggle'(el) {
    const c = S.results.compare;
    const name = el.dataset.wb;
    c.workbooks = c.workbooks.includes(name) ? c.workbooks.filter((n) => n !== name) : [...c.workbooks, name];
    loadCompare();
  },
};

export const inputs = {
  'results-filter'(el) { S.results.history[el.dataset.field] = el.value; rerender(); },
};
