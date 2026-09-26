// Page chrome shared by every screen: header, run sidebar, banners.
import { html, raw, cx } from '../util.js';
import { icon } from '../icons.js';
import { dur, isToday } from '../fmt.js';
import { preflightItems } from './newrun.js';

const LOGO = raw(`<svg width="30" height="30" viewBox="0 0 32 32" fill="none" aria-hidden="true" style="flex:none"><rect x="1" y="1" width="30" height="30" rx="9" style="fill:var(--acc-soft);stroke:var(--acc)" stroke-width="1.5"></rect><path d="M8 11h6M8 16h4M8 21h6" style="stroke:var(--acc)" stroke-width="1.6" stroke-linecap="round" opacity=".55"></path><path d="M15 17l3.6 3.6L25 12" style="stroke:var(--acc)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"></path></svg>`);

const WAITS = { smart: 'Smart waits', legacy: 'Legacy waits', off: 'Waits off' };

/** The three top-level sections. Run and Results navigate with a plain hash; Build remembers the last workbook. */
export function tabs(active) {
  const tab = (name, act) => html`<button class="${cx('tab-btn', active === name && 'on')}" data-act="${act}" aria-current="${active === name ? 'page' : 'false'}">${name}</button>`;
  return html`<nav class="tabnav" aria-label="Sections">${tab('Run', 'run-tab')}${tab('Build', 'build-tab')}${tab('Results', 'results-tab')}</nav>`;
}

/** The shared 60px chrome (logo + section tabs), with room for a screen-specific middle and right side.
 *  `middle` sits in a shrinkable flex-1 slot: keep it empty or short, since its content does not wrap. */
export function headerShell(active, middle = '', right = '') {
  return html`<header class="app-header">
<div style="display: flex; align-items: center; gap: 11px; flex: none">${LOGO}
<div class="disp" style="font-size: 19px; font-weight: 700; letter-spacing: -.015em">QA Regression</div></div>
${tabs(active)}
<div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1; overflow: hidden">${middle}</div>
<div class="hdr-chips">${right}</div>
</header>`;
}

export function header(S) {
  const c = S.cfg || {};
  const warns = preflightItems(S).filter((i) => i.kind === 'warn').length;
  const dark = document.documentElement.getAttribute('data-theme') !== 'light';
  const right = html`
<span class="chip opt">${icon('cpu', 14)} ${c.workers || '–'} workers</span>
<span class="chip opt">${icon(c.headless === false ? 'eye' : 'eyeoff', 14)} ${c.headless === false ? 'Headed' : 'Headless'}</span>
<span class="chip opt">${icon('zap', 14)} ${WAITS[c.waits] || 'Smart waits'}</span>
<span class="chip mono opt">${icon('lock', 14)} ${location.hostname}${location.port ? ':' + location.port : ''} · local only</span>
${warns
    ? html`<button class="chip chip-warn" style="cursor: pointer" data-act="goto-preflight">${icon('warn', 14)} ${warns} preflight warning${warns === 1 ? '' : 's'}</button>`
    : html`<span class="chip">${icon('check', 14)} Ready</span>`}
<button class="icon-btn" data-act="theme" aria-label="Switch between light and dark">${icon(dark ? 'sun' : 'moon', 16)}</button>`;
  return headerShell('Run', html`<span class="tag" style="flex: none">regrunner ${c.version || ''}</span>`, right);
}

function runIcon(r) {
  if (r.active) return html`<span style="width: 18px; height: 18px; display: grid; place-items: center; color: var(--acc); flex: none"><span class="dot pulse" style="width: 10px; height: 10px"></span></span>`;
  const map = { PASSED: ['passc', 'var(--pass)'], FAILED: ['failc', 'var(--fail)'], CANCELLED: ['stopc', 'var(--warn)'],
                ERROR: ['warn', 'var(--warn)'], INTERRUPTED: ['warn', 'var(--warn)'], INCOMPLETE: ['warn', 'var(--warn)'] };
  const [name, color] = map[r.status] || ['dashed', 'var(--tx2)'];
  return html`<span style="display: inline-flex; color: ${color}; flex: none">${icon(name, 18)}</span>`;
}

function testsLabel(r) {
  const ids = r.test_ids || [];
  if (ids.length === 1) return ids[0];
  const n = ids.length || r.tests || (r.summary && r.summary.tests) || 0;
  return `${n} test${n === 1 ? '' : 's'}`;
}

const inBrowser = (r) => (r.browser && r.browser.short ? ` · ${r.browser.short}` : '');       // runs made before the browser was recorded say nothing

/** Runs on shared workers look alike in the list (same time, same environment): say which workbook each one is. */
const bookOf = (r) => ((r.shares && r.shares.length) ? String(r.workbook || '').split(/[\\/]/).pop().replace(/\.(xlsx|xlsm)$/i, '') + ' · ' : '');

function runSub(r) {
  if (r.active) {
    const p = r.progress ? Math.round(r.progress.percent) : 0;
    return html`${bookOf(r)}${testsLabel(r)} · <b style="color: var(--acc)">${p}%</b>${inBrowser(r)}`;
  }
  if (r.status === 'CANCELLED') {
    const done = r.summary ? r.summary.tests : 0;
    return `${done} of ${(r.test_ids || []).length || r.tests || done} tests · stopped`;
  }
  if (r.status === 'INTERRUPTED') return 'process stopped responding';
  if (r.status === 'ERROR') return 'runner stopped early';
  if (r.status === 'INCOMPLETE') return `${testsLabel(r)} · some could not be run`;
  return `${bookOf(r)}${testsLabel(r)}${r.duration_s != null ? ' · ' + dur(r.duration_s) : ''}${inBrowser(r)}`;
}

function runItem(S, r) {
  const on = S.route.name === 'run' && S.route.id === r.run_id;
  return html`<button class="side-run ${on ? 'on' : ''}" data-act="open-run" data-id="${r.run_id}" data-key="${r.run_id}" ${on ? raw('aria-current="page"') : ''}>
<span style="margin-top: 1px">${runIcon(r)}</span>
<span style="min-width: 0; flex: 1"><span class="mono" style="display: block; font-size: 12px; font-weight: 500">${r.run_id}</span>
<span style="display: block; font-size: 12px; color: var(--tx2); margin-top: 1px">${runSub(r)}</span>
${r.active ? html`<div class="bar" style="height: 4px; margin-top: 8px"><div style="width: ${r.progress ? Math.round(r.progress.percent) : 0}%"></div></div>` : ''}</span></button>`;
}

export function sidebar(S) {
  const runs = S.runs;
  const active = runs.filter((r) => r.active);
  const rest = runs.filter((r) => !r.active);
  const today = rest.filter((r) => isToday(r.started_at));
  const earlier = rest.filter((r) => !isToday(r.started_at));
  const group = (label, list) => (list.length ? html`<div><div class="lbl" style="padding: 0 10px 8px">${label}</div>
<div style="display: flex; flex-direction: column; gap: 4px">${list.map((r) => runItem(S, r))}</div></div>` : '');
  return html`<aside class="side" aria-label="Runs">
<button class="btn btn-pri" style="width: 100%; height: 44px; font-size: 14px" data-act="new-run">${icon('plus', 18)} New run</button>
${group(`Active · ${active.length}`, active)}${group('Today', today)}${group('Earlier', earlier)}
${runs.length ? '' : html`<div style="border: 1.5px dashed var(--line2); border-radius: 13px; padding: 20px 14px; text-align: center">
<div style="color: var(--tx3); display: inline-flex">${icon('clock', 24)}</div><div style="font-weight: 650; margin-top: 8px">No runs yet</div>
<div style="font-size: 12.5px; color: var(--tx2); margin-top: 2px">Finished runs collect here and can be replayed any time.</div></div>`}
<div style="margin-top: auto; display: flex; align-items: center; gap: 8px; color: var(--tx3); font-size: 12px; padding: 0 10px">${icon('folder', 14)}
<span class="mono">runs/ · ${runs.length} run${runs.length === 1 ? '' : 's'}</span>
<button aria-label="Refresh runs" data-act="refresh-runs" style="margin-left: auto; color: var(--tx2); display: inline-flex">${icon('refresh', 15)}</button></div>
</aside>`;
}

/** A banner: tone = warn | fail | acc | wait (yellow: a worker is waiting on purpose).  `actions` and `extra` are optional markup. */
export function banner(tone, iconName, body, actions, extra) {
  const color = { warn: 'var(--warn)', fail: 'var(--fail)', acc: 'var(--acc)', wait: 'var(--wait)' }[tone];
  const stacked = !!(actions || extra);
  return html`<div class="bn bn-${tone}" role="${tone === 'fail' ? 'alert' : 'status'}" style="${stacked ? 'flex-direction: column; gap: 10px' : ''}">
<div style="display: flex; gap: 11px"><span style="color: ${color}; display: inline-flex; margin-top: 1px">${icon(iconName, 16)}</span><span style="min-width: 0; overflow-wrap: anywhere">${body}</span></div>
${extra ? html`<div style="padding-left: 27px">${extra}</div>` : ''}
${actions ? html`<div style="display: flex; gap: 8px; padding-left: 27px; flex-wrap: wrap">${actions}</div>` : ''}</div>`;
}

export const btn = (label, act, opts = {}) => html`<button class="${cx('btn btn-sm', opts.cls)}" data-act="${act}" ${opts.id ? html`data-id="${opts.id}"` : ''} ${opts.wb ? html`data-wb="${opts.wb}"` : ''}>${label}</button>`;
