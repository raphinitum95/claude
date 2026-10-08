// Carrie mode: the unicorn scorekeeper in the corner of the live run screen. Her widget (unicorn/js/carrie.js) knows nothing about this app;
// this file is the only place that does: the on/off preference, loading her scripts on demand, and turning the open run into a snapshot
// of numbers ({id, passed, failed, total, running, done}) she can follow. With the toggle off nothing of hers is ever requested.
import { S, rerender } from './state.js';
import { counts } from './runstate.js';

const KEY = 'rr.carrie';
const BASE = '/static/unicorn';
const SCRIPTS = ['idle.js', 'fx.js', 'mood.js', 'carrie.js'];        // in this order: the widget needs the other three

/** The saved preference (a per-person UI setting, so it lives in this browser; it is not part of a run's command or request). */
export function carrieSaved() {
  try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; }
}

export function setCarrie(on) {
  S.carrieOn = !!on;
  try { localStorage.setItem(KEY, on ? '1' : '0'); } catch (e) { /* private mode: it just lasts until reload */ }
  rerender();
}

/** One run's numbers. A run watched live (or just finished) is read from its event reducer; one opened after it ended has no events replayed,
 *  its numbers are in the saved results. Both count tests only: a cancelled or not-run test is neither a pass nor a fail. */
function runNumbers(run, results) {
  if (run && run.order && run.order.length) {
    const c = counts(run);
    return { passed: c.passedTests, failed: c.failedTests, total: run.order.length, running: run.status === 'RUNNING' };
  }
  if (results && Array.isArray(results.tests)) {
    const of = (status) => results.tests.filter((t) => t.status === status).length;
    return { passed: of('PASSED'), failed: of('FAILED'), total: results.tests.length, running: false };
  }
  return null;
}

/** How the open run (or batch) stands, or null when there is nothing for her to follow. */
export function carrieSnapshot(state = S) {
  const v = state.view;
  if (state.route.name !== 'run' || !v || v.loading || v.error) return null;
  const parts = v.kind === 'batch' ? (v.entries || []).map((e) => runNumbers(e.run, null)) : [runNumbers(v.run, v.results)];
  if (!parts.length || parts.some((p) => !p)) return null;
  const sum = (key) => parts.reduce((n, p) => n + p[key], 0);
  const running = parts.some((p) => p.running);
  return { id: (v.kind === 'batch' ? 'batch:' : 'run:') + v.id, passed: sum('passed'), failed: sum('failed'), total: sum('total'), running, done: !running };
}

let loading = null, widget = null, broken = false;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const el = document.createElement('script');
    el.src = src; el.async = false;
    el.onload = resolve;
    el.onerror = () => reject(new Error('Carrie: could not load ' + src));
    document.head.appendChild(el);
  });
}

function load() {
  if (!loading) {
    loading = SCRIPTS.reduce((p, name) => p.then(() => loadScript(`${BASE}/js/${name}`)), Promise.resolve()).then(() => {
      widget = window.UnicornCarrie.create({ base: BASE, onClose: () => setCarrie(false) });
      return widget;
    });
    loading.catch((e) => { broken = true; console.error(e); });
  }
  return loading;
}

/** Called after every render: show her with the latest numbers, or put her away. */
export function syncCarrie() {
  const snap = S.carrieOn ? carrieSnapshot() : null;
  if (!snap) { if (widget) widget.hide(); return; }
  if (broken) return;
  load().then((w) => {
    const latest = S.carrieOn ? carrieSnapshot() : null;                // the page may have moved on while her scripts were loading
    if (latest) w.update(latest); else w.hide();
  }).catch(() => {});
}

export const changes = {
  carrie(el) { setCarrie(el.checked); },
};
