// The Build tab's top-level pieces: the shared header content and the screen dispatcher (map / variables / test).
import { html, raw, cx } from '../../util.js';
import { icon } from '../../icons.js';
import { headerShell } from '../shell.js';
import { buildRail } from './rail.js';
import { workbookMap } from './workbook.js';
import { variableMap } from './variables.js';
import { testEditor } from './editor.js';
import { buildUrl } from './actions.js';
import { modified, bytes } from '../../fmt.js';
import { scenarioBoard } from './scenario.js';

/** The environment the Build tab shows values for and replays in: always named (a workbook with its own environment table has no default,
 *  so this starts on the table's first one).  A compact picker: the header's middle slot is narrow once the draft status shows. */
function envSeg(S, m) {
  const names = m.environments.names;
  if (!names.length) return '';
  const prod = m.environments.production.includes(m.environment);
  return html`<label class="chip" style="flex: none; height: 30px; gap: 5px; padding: 0 6px 0 10px; ${prod ? 'color: var(--fail); border-color: var(--fail-line); background: var(--fail-soft)' : 'color: var(--tx)'}" title="The environment the Build tab shows values for and replays in">
${icon('globe', 13)}<select id="build-env" data-key="env-${names.join('|')}-${m.environment}" data-change="build-env-select" aria-label="Environment" style="border: 0; background: transparent; color: inherit; font: inherit; font-weight: 650; cursor: pointer; padding: 0 2px">
${names.map((n) => html`<option value="${n}" ${n === m.environment ? raw('selected') : ''}>${n}</option>`)}</select></label>`;
}

export function buildHeader(S) {
  const b = S.build;
  const m = b.model;
  const dark = document.documentElement.getAttribute('data-theme') !== 'light';
  const newWbBtn = html`<button class="btn btn-sm" data-act="build-new-workbook" aria-label="New workbook">${icon('plus', 13)}<span class="btn-label"> New workbook</span></button>`;
  if (!m || b.listing) {
    return headerShell('Build', html`<span style="color: var(--tx3); font-size: 13px">All workbooks</span>`,
      html`${newWbBtn}<button class="icon-btn" data-act="theme" aria-label="Switch between light and dark">${icon(dark ? 'sun' : 'moon', 16)}</button>`);
  }
  const status = m.status;
  const middle = html`<a href="#/build/all" class="icon-btn" style="flex: none; width: 30px; height: 30px" aria-label="All workbooks" title="All workbooks: open another one">${icon('grid', 14)}</a>
<a href="${buildUrl(b.name, 'map')}" class="trunc" style="font-size: 13px; color: var(--tx3); text-decoration: none; min-width: 24px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap" title="${m.name}">${m.name}</a>
${b.screen === 'test' && b.testId ? html`${icon('chevron', 12, 'transform: rotate(-90deg); color: var(--tx3)')}<span class="disp trunc" style="font-size: 16px; font-weight: 700; min-width: 24px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">${b.testId}</span>` : ''}
${b.screen === 'scenario' && b.scenario ? html`${icon('chevron', 12, 'transform: rotate(-90deg); color: var(--tx3)')}<span class="disp trunc" style="font-size: 16px; font-weight: 700; min-width: 24px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">${b.scenario}</span>` : ''}
${b.screen === 'variables' ? html`${icon('chevron', 12, 'transform: rotate(-90deg); color: var(--tx3)')}<span class="disp trunc" style="font-size: 16px; font-weight: 700; min-width: 24px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">Variables</span>` : ''}
<span style="flex: 1"></span>${envSeg(S, m)}`;
  const right = html`
${status.externalChange ? html`<button class="chip chip-warn" data-act="build-file-changed" title="The file changed on disk since it was opened here">${icon('warn', 13)} Changed on disk</button>` : ''}
${!status.externalChange && status.hasDraft ? html`<span class="hdr-opt" style="display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--tx3)">${icon('check', 13, 'color: var(--pass)')} Draft autosaved${status.draftSaved ? ' ' + new Date(status.draftSaved).toLocaleTimeString() : ''}</span>` : ''}
<button class="icon-btn" data-act="build-undo" aria-label="Undo" title="Undo ⌘Z" ${status.canUndo ? '' : raw('disabled')}>${icon('undo', 15)}</button>
<button class="icon-btn" data-act="build-redo" aria-label="Redo" title="Redo" ${status.canRedo ? '' : raw('disabled')}>${icon('redo', 15)}</button>
${m.problemCounts.error || m.problemCounts.warning ? html`<button class="chip chip-warn" data-act="build-toggle-problems">${icon('warn', 13)} ${m.problemCounts.error + m.problemCounts.warning} problems</button>` : ''}
<button class="icon-btn" data-act="build-history" aria-label="History" title="History">${icon('history', 15)}</button>
<button class="btn btn-pri btn-sm ${b.busy ? 'busy' : ''}" data-act="build-save" title="Save ⌘S" aria-label="Save to Excel">${icon('check', 14)}<span class="btn-label"> Save to Excel</span></button>
<button class="icon-btn" data-act="build-download" aria-label="Download the workbook" title="Download the workbook (.xlsx) to share it">${icon('download', 15)}</button>
${newWbBtn}
<button class="icon-btn" data-act="theme" aria-label="Switch between light and dark">${icon(dark ? 'sun' : 'moon', 16)}</button>`;
  return headerShell('Build', middle, right);
}

/** The "All workbooks" page (#/build/all): every workbook in the folder as a card; the whole card opens it. */
function workbookList(S) {
  const open = S.build.name;
  if (!S.workbooks.length) {
    return html`<div class="app-body"><main class="main"><div class="page" style="max-width: 640px; margin: 8vh auto; text-align: center">
<div style="color: var(--tx3); display: inline-flex">${icon('grid', 30)}</div><h1 class="disp" style="font-size: 26px; margin-top: 10px">No workbook to build yet</h1>
<p style="color: var(--tx2)">Start a new one, or add one on the New run screen.</p>
<button class="btn btn-pri" style="margin: 10px auto" data-act="build-new-workbook">${icon('plus', 15)} New workbook</button></div></main></div>`;
  }
  return html`<div class="app-body"><main class="main scroll" style="overflow: auto"><div class="page" style="display: flex; flex-direction: column; gap: 16px">
<div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap"><h1 class="disp" style="font-size: 22px; margin: 0; flex: 1; min-width: 0">All workbooks</h1>
<button class="btn btn-sm" data-act="build-new-workbook">${icon('plus', 13)} New workbook</button></div>
<div class="wb-grid">${S.workbooks.map((w) => html`<div class="card wb-card ${w.name === open ? 'on' : ''}" data-key="wb-${w.name}">
<a class="wb-card-open" href="${buildUrl(w.name, 'map')}" aria-label="Open ${w.name}"></a>
<span style="color: var(--acc); display: inline-flex">${icon('grid', 18)}</span>
<div style="display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0"><b class="trunc" style="font-size: 14px" title="${w.name}">${w.name}</b>
<span style="font-size: 12px; color: var(--tx3)">${w.name === open ? 'Open now · ' : ''}saved ${modified(w.modified)} · ${bytes(w.size)}</span></div>
<button class="icon-btn wb-card-btn" data-act="build-download" data-name="${w.name}" aria-label="Download ${w.name}" title="Download (.xlsx)">${icon('download', 14)}</button>
</div>`)}</div></div></main></div>`;
}

export function buildView(S) {
  const b = S.build;
  if (!b.name || b.listing) return workbookList(S);
  if (b.loading) {
    return html`<div class="app-body">${buildRail(S)}<main class="main"><div class="page"><div class="skel" style="height: 40px; width: 300px"></div><div class="skel" style="height: 400px"></div></div></main></div>`;
  }
  if (b.error) {
    return html`<div class="app-body"><main class="main"><div class="page"><b>Could not open ${b.name}.</b><p style="color: var(--tx2)">${b.error.message}</p></div></main></div>`;
  }
  if (b.screen === 'test') return testEditor(S);
  if (b.screen === 'scenario') return scenarioBoard(S);
  if (b.screen === 'variables') return html`<div class="app-body">${buildRail(S)}${variableMap(S)}</div>`;
  return html`<div class="app-body">${buildRail(S)}<main class="main scroll" style="overflow: auto">${workbookMap(S)}</main></div>`;
}
