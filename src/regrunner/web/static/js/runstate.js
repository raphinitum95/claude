// Turns the runner's event stream into view state.  The same reducer serves a live run and the replay of a
// finished one, so a page reload (or a dropped connection) just re-reads the stream from the start.
import { shortUrl } from './util.js';

const ms = (iso) => Date.parse(iso);
const first = (s) => String(s || '').split('\n')[0];
const title = (s) => { s = String(s || '').toLowerCase().replace(/_/g, ' '); return s.charAt(0).toUpperCase() + s.slice(1); };

export function newRun(id) {
  return {
    id, status: 'RUNNING', workbook: '', environment: '', workers: 1, headless: true, browser: null, seed: null, params: null,
    warnings: [], startedMs: null, lastMs: null, endedMs: null, duration: null, shares: [],
    tests: {}, order: [], log: [], summary: null, artifacts: null, error: '', exitCode: null, started: false, asks: {}, askFocus: null,
    waits: {},                                               // workers waiting on purpose right now (a login code, a slow page, a re-run after a crash)
  };
}

function newTest(id, o = {}) {
  return {
    id, title: o.title || id, description: o.description || '', scenario: o.scenario || '', total: o.total_steps || 0,
    done: 0, failed: 0, status: 'QUEUED', worker: null, startedMs: null, endedMs: null, duration: null, step: null,
    shot: null, box: null, shotStep: 0, fails: [], review: [], attempt: 1, error: '', vars: [], waitsFor: o.waits_for || [],
  };
}

function dropWaits(run, test) { for (const [k, w] of Object.entries(run.waits)) if (w.test === test) delete run.waits[k]; }

function pushLog(run, iso, k, c, m) {
  run.log.push({ t: iso, k, c, m });
  if (run.log.length > 80) run.log.splice(0, run.log.length - 80);
}

export function apply(run, e) {
  const at = ms(e.ts);
  if (!Number.isNaN(at)) run.lastMs = at;
  const t = e.test ? run.tests[e.test] : null;
  switch (e.type) {
    case 'run_started': {
      run.started = true;
      run.startedMs = at;
      run.workbook = e.workbook || '';
      run.environment = e.environment || '';
      run.workers = e.workers || 1;
      run.headless = e.headless !== false;
      run.browser = e.browser || null;                       // which browser every test of this run uses (name, engine, version)
      run.seed = e.seed ?? null;
      run.params = e.params || null;
      run.shares = e.shares || [];                           // the other runs that use the same workers
      run.warnings = e.warnings || [];
      run.tests = {};
      run.order = [];
      run.log = [];
      for (const x of e.tests || []) { run.tests[x.id] = newTest(x.id, x); run.order.push(x.id); }
      pushLog(run, e.ts, 'RUN', 'var(--tx2)', `${e.run_id} · ${run.order.length} test${run.order.length === 1 ? '' : 's'} · ${run.environment}`);
      break;
    }
    case 'test_started':
      if (!t) break;
      dropWaits(run, t.id);
      t.status = 'RUNNING'; t.worker = e.worker ?? null; t.startedMs = at; t.total = e.total_steps || t.total;
      t.attempt = e.attempt || 1;
      if (t.attempt > 1) { t.done = 0; t.failed = 0; t.fails = []; t.review = []; t.shot = null; t.box = null; t.vars = []; }
      pushLog(run, e.ts, 'START', 'var(--acc)', `${t.title} on W${t.worker}${t.attempt > 1 ? ` · attempt ${t.attempt}` : ''}`);
      break;
    case 'step_started':
      if (!t) break;
      t.step = { n: e.step, name: e.name || '', action: e.action || '' };
      t.total = Math.max(t.total, e.total_steps || 0);
      pushLog(run, e.ts, 'STEP', 'var(--tx3)', `${t.id} #${e.step} · ${title(e.action)} · ${e.name || ''}`);
      break;
    case 'step_passed':
    case 'step_failed':
      if (!t) break;
      for (const w of e.sets || []) t.vars.push({ ...w, seq: e.step, row: e.row, step: e.name || '', by_hand: false });      // a step filled in a parameter
      t.done = Math.max(t.done, e.step);
      t.total = Math.max(t.total, t.done);
      if (e.type === 'step_failed' && e.status === 'NOT_RUN') {       // the browser went away during this step: no verdict (the test is run again)
        pushLog(run, e.ts, 'CRASH', 'var(--warn)', `${t.id} #${e.step} · ${first(e.error)}`);
      } else if (e.type === 'step_failed') {
        t.failed += 1;
        t.fails.push({
          seq: e.step, row: e.row, name: e.name || '', action: e.action || '', error: e.error || '', expected: e.expected || '',
          actual: e.actual || '', locator: e.locator || '', origin: e.locator_origin || '', fallback: !!e.fallback,
          comparison: e.comparison || '', screenshot: e.screenshot || null,
        });
        pushLog(run, e.ts, 'FAIL', 'var(--fail)', `${t.id} #${e.step} · ${title(e.action)} "${e.name || ''}"${e.error ? ' · ' + first(e.error) : ''}`);
      }
      break;
    case 'variable_set':                                   // a person supplied an empty parameter
      if (t) t.vars.push({ name: e.name, value: e.value, stored: e.value, cell: e.cell || '', seq: e.step, row: 0, step: '', by_hand: true });
      break;
    case 'screenshot_saved':
      if (!t) break;
      if (e.step >= t.shotStep) { t.shot = e.path; t.box = e.box || null; t.shotStep = e.step; }
      pushLog(run, e.ts, 'SHOT', 'var(--tx3)', `${t.id} #${e.step} saved`);
      break;
    case 'console_error':
    case 'network_error':
    case 'review_item':
      if (t) t.review.push({ ...e });
      break;
    case 'test_finished':
      if (!t) break;
      dropWaits(run, t.id);
      t.status = e.status || 'PASSED'; t.endedMs = at; t.duration = e.duration_s ?? null; t.error = e.error || '';
      t.done = t.total = Math.max(t.done, t.total);
      (e.review_counts || []).forEach((c, i) => { if (t.review[i]) t.review[i].count = c; });
      pushLog(run, e.ts, t.status === 'PASSED' ? 'PASS' : t.status === 'FAILED' ? 'FAIL' : 'END',
        t.status === 'PASSED' ? 'var(--pass)' : t.status === 'NOT_RUN' ? 'var(--warn)' : 'var(--fail)', `${t.id} · ${t.status === 'NOT_RUN' ? 'not run · ' : ''}${t.done}/${t.total} · ${fmtSecs(t.duration)}`);
      break;
    case 'user_input_needed':                              // an ASK_USER step: the run waits for a person (the answer never travels in an event)
      run.asks[e.ask] = { id: e.ask, test: e.test || '', step: e.step || 0, question: e.question || '', secret: !!e.secret, mode: e.mode || 'ui', kind: e.kind || 'text',
        untilMs: at + (e.timeout_s || 0) * 1000, timeoutS: e.timeout_s || 0 };
      run.askFocus = e.ask;
      pushLog(run, e.ts, e.kind === 'captcha' ? 'CAPTCHA' : 'ASK', e.kind === 'captcha' ? 'var(--warn)' : 'var(--acc)', e.kind === 'captcha' ? `${e.test || 'run'}: captcha needs a person. ${e.question || ''}` : `${e.test || 'run'} is asking: ${e.question || ''}`);
      break;
    case 'user_input_waiting':
      if (run.asks[e.ask]) run.asks[e.ask].untilMs = at + (e.seconds_left || 0) * 1000;
      break;
    case 'user_input_received':
    case 'user_input_closed':
      delete run.asks[e.ask];
      pushLog(run, e.ts, 'ASK', 'var(--tx3)', e.type === 'user_input_received' ? `${e.test || 'run'} got its answer`
        : e.reason === 'done' ? `${e.test || 'run'}: solved, carrying on` : `${e.test || 'run'}: the question ended (${e.reason || 'closed'})`);
      break;
    case 'pool_changed':                                   // another run joined the workers this one is on
      run.shares = e.shares || [];
      pushLog(run, e.ts, 'POOL', 'var(--acc)', `sharing the workers with ${run.shares.map((x) => x.workbook).join(', ') || 'no other run'}`);
      break;
    case 'run_paused':                                     // the site blocked us (HTTP 403 / 429): page loads wait, then the test starts again
      run.paused = { until: at + (e.seconds || 0) * 1000, seconds: e.seconds || 0, test: e.test || '', attempt: e.attempt || 1, of: e.of || 1, reason: e.reason || '' };
      pushLog(run, e.ts, 'WAIT', 'var(--warn)', `${e.test || 'run'} blocked by the site · pausing ${e.seconds || 0} s · retry ${e.attempt || 1} of ${e.of || 1}`);
      if (t) { t.status = 'QUEUED'; t.done = 0; t.failed = 0; t.fails = []; t.step = null; }      // the attempt that just ended is run again: it is not finished, and not at 100%
      break;
    case 'worker_waiting':                                 // a worker waits on purpose: the screen says who, why, and for how long (never a secret)
      run.waits[e.wait] = { id: e.wait, test: e.test || '', worker: e.worker ?? null, step: e.step || 0, code: e.code || '', message: e.message || '',
        seconds: e.seconds ?? null, startMs: at, untilMs: e.seconds != null ? at + e.seconds * 1000 : null };
      pushLog(run, e.ts, 'WAIT', 'var(--warn)', `${e.test || 'run'}${e.worker != null ? ' on W' + e.worker : ''}: ${e.message || ''}`);
      if (t && e.code === 'infra_rerun') { t.status = 'QUEUED'; t.done = 0; t.failed = 0; t.fails = []; t.step = null; }     // it starts over: not finished
      break;
    case 'worker_resumed':
      delete run.waits[e.wait];
      pushLog(run, e.ts, 'GO', 'var(--tx3)', `${e.test || 'run'} carries on${e.waited_s != null ? ` after ${fmtSecs(e.waited_s)}` : ''}`);
      break;
    case 'log':
      pushLog(run, e.ts, 'LOG', e.level === 'error' ? 'var(--fail)' : e.level === 'info' ? 'var(--tx3)' : 'var(--warn)', e.message || '');
      break;
    case 'run_finished':
      run.asks = {};
      run.waits = {};
      run.status = e.status || 'PASSED'; run.endedMs = at; run.summary = e.summary || null; run.artifacts = e.artifacts || null;
      run.error = e.error || ''; run.exitCode = e.exit_code ?? null; run.duration = e.duration_s ?? null;
      pushLog(run, e.ts, 'DONE', run.status === 'PASSED' ? 'var(--pass)' : 'var(--warn)', `run ${run.status.toLowerCase()}`);
      break;
    default: break;
  }
}

export function applyAll(run, events) { for (const e of events) apply(run, e); }

function fmtSecs(s) {
  if (s == null) return '';
  s = Math.round(s);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
}

// ---- derived values ----------------------------------------------------------------------------------
export function isDone(run) { return run.status !== 'RUNNING'; }

export function counts(run) {
  const c = { done: 0, total: 0, failedSteps: 0, inFlight: 0, queuedSteps: 0, running: 0, pending: 0, finished: 0,
              passedTests: 0, failedTests: 0, otherTests: 0, notRunTests: 0 };
  for (const id of run.order) {
    const t = run.tests[id];
    c.done += t.done; c.total += Math.max(t.total, t.done); c.failedSteps += t.failed;
    if (t.status === 'RUNNING') { c.running++; c.inFlight += Math.max(0, t.total - t.done); }
    else if (t.status === 'QUEUED') { c.pending++; c.queuedSteps += t.total; }
    else {
      c.finished++;
      if (t.status === 'PASSED') c.passedTests++; else if (t.status === 'FAILED') c.failedTests++; else if (t.status === 'NOT_RUN') c.notRunTests++; else c.otherTests++;
    }
  }
  c.passedSteps = c.done - c.failedSteps;
  c.percent = c.total ? (100 * c.done) / c.total : 0;
  return c;
}

export function timing(run, nowMs, live) {
  const end = run.endedMs ?? (live ? nowMs : run.lastMs);
  const elapsed = run.startedMs && end ? Math.max(0, (end - run.startedMs) / 1000) : 0;
  const c = counts(run);
  const speed = elapsed > 1 && c.done > 0 ? c.done / elapsed : 0;
  const remaining = speed > 0 ? Math.max(0, (c.total - c.done) / speed) : null;
  return { elapsed, speed, remaining };
}

/** The workers that are waiting on purpose right now, oldest wait first. */
export const waitsOf = (run) => Object.values(run.waits || {}).sort((a, b) => (a.startMs || 0) - (b.startMs || 0));

/** What every worker is doing, in one line: "2 running steps · 1 waiting for a login code". */
export function workerSummary(run) {
  const waits = waitsOf(run);
  const waitingTests = new Set(waits.map((w) => w.test));
  const running = lanes(run).filter((t) => !waitingTests.has(t.id)).length;
  const kinds = { login_code: 'for a login code', slow_page: 'for a slow page', infra_rerun: 'to re-run a test after a browser crash' };
  const byKind = {};
  for (const w of waits) byKind[w.code] = (byKind[w.code] || 0) + 1;
  const parts = [];
  if (running) parts.push(`${running} running steps`);
  for (const [code, n] of Object.entries(byKind)) parts.push(`${n} waiting ${kinds[code] || 'on purpose'}`);
  return parts.join(' · ');
}

export const lanes = (run) => run.order.map((id) => run.tests[id]).filter((t) => t.status === 'RUNNING')
  .sort((a, b) => (a.worker || 0) - (b.worker || 0));
export const pending = (run) => run.order.map((id) => run.tests[id]).filter((t) => t.status === 'QUEUED')
  .sort((a, b) => b.total - a.total);
export const finished = (run) => run.order.map((id) => run.tests[id])
  .filter((t) => t.status !== 'QUEUED' && t.status !== 'RUNNING').sort((a, b) => (a.endedMs || 0) - (b.endedMs || 0));

/** A strip of one tick per step: passed (green), failed (red), the step in flight (blue), the rest (dim). */
export function strip(done, total, fails, live) {
  const T = Math.max(total, 1);
  const p = (v) => `${Math.min(100, (100 * v) / T).toFixed(3)}%`;
  const stops = [];
  let cur = 0;
  [...fails].sort((a, b) => a - b).forEach((f) => {
    stops.push(`var(--pass) ${p(cur)} ${p(f - 1)}`, `var(--fail) ${p(f - 1)} ${p(f)}`);
    cur = f;
  });
  stops.push(`var(--pass) ${p(cur)} ${p(done)}`);
  if (done < total) {
    if (live) stops.push(`var(--acc) ${p(done)} ${p(done + 2)}`, `var(--tick) ${p(done + 2)} 100%`);
    else stops.push(`var(--tick) ${p(done)} 100%`);
  }
  return `linear-gradient(90deg, ${stops.join(', ')})`;
}

// ---- things to review ------------------------------------------------------------------------------------
export function reviewRow(it) {
  let cat; let msg; let tone = 'plain'; let rank = 1;
  if (it.type === 'console_error') { cat = it.kind === 'pageerror' ? 'page error' : 'console'; msg = it.message || ''; rank = 3; }
  else if (it.type === 'network_error') {
    cat = it.status ? `http ${it.status}` : 'request failed';
    msg = `${it.method || 'GET'} ${shortUrl(it.url)}${!it.status && it.message ? ` · ${it.message}` : ''}`; rank = 2;
  } else {
    cat = it.category || 'note'; msg = it.message || '';
    if (cat === 'captcha_bypass' || it.severity === 'error') { tone = it.severity === 'error' ? 'fail' : 'warn'; rank = 0; }
  }
  return { key: `${cat}|${msg}`, cat, msg, tone, rank, count: it.count || 1, where: `${it.test} #${it.step}` };
}

/** Group identical items across tests: one row with the summed count and the first place it happened. */
export function groupReview(items) {
  const groups = new Map();
  for (const it of items) {
    const r = reviewRow(it);
    const g = groups.get(r.key);
    if (g) g.count += r.count; else groups.set(r.key, r);
  }
  return [...groups.values()].sort((a, b) => a.rank - b.rank || b.count - a.count);
}

export const reviewOfRun = (run) => run.order.flatMap((id) => run.tests[id].review);
export const reviewTotal = (groups) => groups.reduce((n, g) => n + g.count, 0);

/** The parameters a test set, one per name, with what the cell holds at the end of the test (writes to one parameter add up). */
export function finalVars(list) {
  const latest = new Map();
  for (const v of list || []) latest.set(String(v.name || '').toUpperCase(), v);
  return [...latest.values()];
}

/** [{test, ...variable}] for every test of a live run, in run order. */
export function varsOfRun(run) {
  return run.order.flatMap((id) => finalVars(run.tests[id].vars).map((v) => ({ test: id, ...v })));
}
