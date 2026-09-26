// The Build tab's top-level pieces: the shared header content and the screen dispatcher (map / variables / test).
import { html, raw, cx } from '../../util.js';
import { icon } from '../../icons.js';
import { headerShell } from '../shell.js';
import { buildRail } from './rail.js';
import { workbookMap, variableMap } from './workbook.js';
import { testEditor } from './editor.js';
import { buildUrl } from './actions.js';

function envSeg(S, m) {
  const names = m.environments.names;
  if (!names.length) return '';
  return html`<div class="seg" style="width: ${Math.min(280, 70 * names.length)}px" role="group" aria-label="Environment">
${names.map((n) => html`<button class="${cx(m.environment === n && 'on', m.environment === n && m.environments.production.includes(n) && 'prod')}" data-act="build-env-picker" data-val="${n}" aria-pressed="${String(m.environment === n)}">${n}</button>`)}
</div>`;
}

export function buildHeader(S) {
  const b = S.build;
  const m = b.model;
  const dark = document.documentElement.getAttribute('data-theme') !== 'light';
  const newWbBtn = html`<button class="btn btn-sm" data-act="build-new-workbook">${icon('plus', 13)} New workbook</button>`;
  if (!m) {
    return headerShell('Build', html`<span style="color: var(--tx3); font-size: 13px">workbooks/</span>`,
      html`${newWbBtn}<button class="icon-btn" data-act="theme" aria-label="Switch between light and dark">${icon(dark ? 'sun' : 'moon', 16)}</button>`);
  }
  const status = m.status;
  const middle = html`<a href="${buildUrl(b.name, 'map')}" class="trunc" style="font-size: 13px; color: var(--tx3); text-decoration: none">${m.name}</a>
${b.screen === 'test' && b.testId ? html`${icon('chevron', 12, 'transform: rotate(-90deg); color: var(--tx3)')}<span class="disp" style="font-size: 16px; font-weight: 700">${b.testId}</span>` : ''}
${b.screen === 'variables' ? html`${icon('chevron', 12, 'transform: rotate(-90deg); color: var(--tx3)')}<span class="disp" style="font-size: 16px; font-weight: 700">Variables</span>` : ''}
<span style="flex: 1"></span>${envSeg(S, m)}`;
  const right = html`
${status.externalChange ? html`<button class="chip chip-warn" data-act="build-file-changed" title="The file changed on disk since it was opened here">${icon('warn', 13)} Changed on disk</button>` : ''}
${!status.externalChange && status.hasDraft ? html`<span style="display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--tx3)">${icon('check', 13, 'color: var(--pass)')} Draft autosaved${status.draftSaved ? ' ' + new Date(status.draftSaved).toLocaleTimeString() : ''}</span>` : ''}
<button class="icon-btn" data-act="build-undo" aria-label="Undo" title="Undo ⌘Z" ${status.canUndo ? '' : raw('disabled')}>${icon('undo', 15)}</button>
<button class="icon-btn" data-act="build-redo" aria-label="Redo" title="Redo" ${status.canRedo ? '' : raw('disabled')}>${icon('redo', 15)}</button>
${m.problemCounts.error || m.problemCounts.warning ? html`<button class="chip chip-warn" data-act="build-toggle-problems">${icon('warn', 13)} ${m.problemCounts.error + m.problemCounts.warning} problems</button>` : ''}
<button class="icon-btn" data-act="build-history" aria-label="History" title="History">${icon('history', 15)}</button>
<button class="btn btn-pri btn-sm ${b.busy ? 'busy' : ''}" data-act="build-save" title="Save ⌘S">${icon('download', 14)} Save to Excel</button>
${newWbBtn}
<button class="icon-btn" data-act="theme" aria-label="Switch between light and dark">${icon(dark ? 'sun' : 'moon', 16)}</button>`;
  return headerShell('Build', middle, right);
}

export function buildView(S) {
  const b = S.build;
  if (!b.name) {
    return html`<div class="app-body"><main class="main"><div class="page" style="max-width: 640px; margin: 8vh auto; text-align: center">
<div style="color: var(--tx3); display: inline-flex">${icon('grid', 30)}</div><h1 class="disp" style="font-size: 26px; margin-top: 10px">No workbook to build yet</h1>
<p style="color: var(--tx2)">Pick one from the New run screen, or start a new one.</p>
<button class="btn btn-pri" style="margin: 10px auto" data-act="build-new-workbook">${icon('plus', 15)} New workbook</button></div></main></div>`;
  }
  if (b.loading) {
    return html`<div class="app-body">${buildRail(S)}<main class="main"><div class="page"><div class="skel" style="height: 40px; width: 300px"></div><div class="skel" style="height: 400px"></div></div></main></div>`;
  }
  if (b.error) {
    return html`<div class="app-body"><main class="main"><div class="page"><b>Could not open ${b.name}.</b><p style="color: var(--tx2)">${b.error.message}</p></div></main></div>`;
  }
  if (b.screen === 'test') return testEditor(S);
  if (b.screen === 'variables') return html`<div class="app-body">${buildRail(S)}${variableMap(S)}</div>`;
  return html`<div class="app-body">${buildRail(S)}<main class="main scroll" style="overflow: auto">${workbookMap(S)}</main></div>`;
}
