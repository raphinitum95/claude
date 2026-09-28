// Everything the Results tab can do: load the history list / batch page / test page / compare, and re-run a
// batch's failures. Merged into the app's data-act / data-change / data-input tables by main.js.
import { S, rerender } from '../../state.js';
import { api as rawApi } from '../../api.js';
import { loadRuns } from '../../actions.js';
import { toast } from '../../util.js';
import { jumpToStep } from '../build/actions.js';
import * as api from './api.js';

const enc = encodeURIComponent;

export function resultsUrl(screen, a, b) {
  if (screen === 'batch') return `#/results/batch/${enc(a)}`;
  if (screen === 'test') return `#/results/test/${enc(a)}/${enc(b)}`;
  if (screen === 'compare') return '#/results/compare';
  return '#/results';
}

/** Called by main.js on every #/results... route. */
export function openResults(screen, a, b) {
  const r = S.results;
  r.screen = screen;
  if (screen === 'batch') return loadBatch(a);
  if (screen === 'test') return loadTest(a, b);
  if (screen === 'compare') return loadCompare();
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
    location.hash = res.batch_id ? resultsUrl('batch', res.batch_id) : `#/run/${res.run_ids[0]}`;
  } catch (e) { toast(e.message, 6000); }
}

export const acts = {
  'results-tab'() { location.hash = '#/results'; },
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
