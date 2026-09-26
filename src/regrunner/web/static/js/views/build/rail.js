// The Build tab's left rail: this workbook's tests, its data sheets, and workbook-wide settings.
// Shown on every Build screen (map, variables, test editor) so switching tests never needs a trip back to the map.
import { html } from '../../util.js';
import { icon } from '../../icons.js';
import { buildUrl, bm } from './actions.js';

const KIND_ICON = { web: 'grid', api: 'api', xml: 'xml' };

function lastDot(t) {
  if (!t.lastRun) return 'var(--pend)';
  return t.lastRun.status === 'PASSED' ? 'var(--pass)' : t.lastRun.status === 'FAILED' ? 'var(--fail)' : 'var(--pend)';
}

function testRow(S, t) {
  const on = S.build.screen === 'test' && S.build.testId === t.id;
  return html`<button class="rail-item ${on ? 'on' : ''}" data-key="t-${t.id}" data-act="build-goto-test" data-test="${t.id}" aria-current="${on ? 'page' : 'false'}">
<span style="color: var(--tx3); display: inline-flex">${icon(KIND_ICON[t.kind] || 'grid', 14)}</span>
<span class="trunc" style="flex: 1">${t.id}</span>
<span class="mono" style="font-size: 11px; color: var(--tx3)">${t.steps.length || ''}</span>
<span class="pdot" style="background: ${lastDot(t)}" title="${t.lastRun ? t.lastRun.status : 'Not run'}"></span></button>`;
}

export function buildRail(S) {
  const m = bm();
  if (!m) {
    return html`<aside class="b-rail scroll" aria-label="Workbook"><div class="lbl" style="padding: 6px">Workbooks</div>
${S.workbooks.map((w) => html`<button class="rail-item" data-act="build-open-wb" data-name="${w.name}">${icon('grid', 14)} <span class="trunc">${w.name}</span></button>`)}
<button class="btn btn-sm" style="margin-top: 8px" data-act="build-new-workbook">${icon('plus', 13)} New workbook</button></aside>`;
  }
  const params = m.sheets.filter((s) => s.role === 'params');
  const dataRowsOf = (sheetName) => { const t = m.tests.find((x) => x.paramSheet === sheetName); return t ? t.dataRows.length : null; };
  return html`<aside class="b-rail scroll" aria-label="Workbook">
<a href="${buildUrl(S.build.name, 'map')}" style="display: flex; flex-direction: column; gap: 5px; padding: 2px 6px; color: inherit; text-decoration: none">
<span class="lbl" style="display: flex; align-items: center; gap: 5px">${icon('chevl', 11)} Workbook map</span>
<span class="disp trunc" style="font-size: 14.5px; font-weight: 700">${m.name}</span>
<span style="display: flex; gap: 5px; flex-wrap: wrap"><span class="tag tag-acc">${m.environment}</span><span class="tag">${m.tests.length} tests</span><span class="tag">${m.variables.length} variables</span></span></a>
<div style="display: flex; flex-direction: column; gap: 2px">
<div style="display: flex; align-items: center; justify-content: space-between; padding: 0 6px 2px"><span class="lbl">Tests</span>
<button class="btn btn-ghost btn-sm" style="height: 22px; padding: 0 5px" data-act="build-new-test" aria-label="New test">${icon('plus', 12)}</button></div>
${m.tests.map((t) => testRow(S, t))}</div>
<div style="display: flex; flex-direction: column; gap: 2px"><span class="lbl" style="padding: 6px 6px 2px">Data</span>
${params.map((p) => html`<button class="rail-item" data-act="build-open-grid" data-sheet="${p.name}">${icon('table', 14)}<span class="trunc" style="flex: 1">${p.name}</span>
${dataRowsOf(p.name) != null ? html`<span class="mono" style="font-size: 11px; color: var(--tx3)">${dataRowsOf(p.name)}</span>` : ''}</button>`)}
<button class="rail-item" data-act="build-goto-variables"><span aria-hidden="true">${icon('braces', 14)}</span><span style="flex: 1">Variables</span><span class="mono" style="font-size: 11px; color: var(--tx3)">${m.variables.length}</span></button>
<button class="rail-item" data-act="build-open-environments"><span aria-hidden="true">${icon('globe', 14)}</span><span style="flex: 1">Environments</span><span class="mono" style="font-size: 11px; color: var(--tx3)">${m.environments.names.length}</span></button></div>
<div style="display: flex; flex-direction: column; gap: 2px"><span class="lbl" style="padding: 6px 6px 2px">Workbook</span>
<button class="rail-item" data-act="build-open-fingerprints">${icon('gate', 14)}<span style="flex: 1">Page fingerprints</span><span class="mono" style="font-size: 11px; color: var(--tx3)">${m.fingerprints.length}</span></button>
<button class="rail-item" data-act="build-history">${icon('history', 14)}<span style="flex: 1">History</span></button>
<button class="rail-item" data-act="build-open-settings">${icon('settings', 14)}<span style="flex: 1">Settings (Global)</span></button></div>
</aside>`;
}
