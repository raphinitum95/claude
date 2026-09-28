// Workbook map (tests as cards). The Variables screen lives in variables.js.
import { html, raw } from '../../util.js';
import { icon } from '../../icons.js';
import { buildUrl, bm } from './actions.js';
import { scenarioCards } from './scenario.js';

const KIND_ICON = { web: 'grid', api: 'xml', xml: 'xml' };            // (an API test gets the <> icon, JSON or XML alike)
const KIND_LABEL = { web: 'Website', api: 'API', xml: 'API' };
const LAST = { PASSED: ['p-pass', 'check', 'Passed'], FAILED: ['p-fail', 'x', 'Failed'] };

function testCard(S, t) {
  const last = t.lastRun && LAST[t.lastRun.status];
  return html`<div class="card tcard" data-key="tc-${t.id}" style="padding: 14px; display: flex; flex-direction: column; gap: 9px; ${t.enabled ? '' : 'opacity: .6'}">
<div style="display: flex; align-items: center; gap: 8px">
<span style="color: var(--k-${t.kind === 'web' ? 'nav' : t.kind}); display: inline-flex">${icon(KIND_ICON[t.kind] || 'grid', 16)}</span>
<a href="${buildUrl(S.build.name, 'test', t.id)}" class="disp trunc tcard-open" style="font-size: 16px; font-weight: 700; color: var(--tx)">${t.id}</a>
<span style="flex: 1"></span>
<input type="checkbox" class="sw" ${t.enabled ? raw('checked') : ''} data-change="build-toggle-test" data-test="${t.id}" aria-label="Run ${t.id} in this workbook">
</div>
<div style="display: flex; align-items: center; gap: 6px">
${last ? html`<span class="pill ${last[0]}">${icon(last[1], 11)} ${last[2]}</span>` : html`<span class="pill p-pend">${icon('dashed', 11)} Not run</span>`}
<span class="mono" style="font-size: 11.5px; color: var(--tx3)">${KIND_LABEL[t.kind] || t.kind} · ${t.steps.length} steps</span>
<span style="flex: 1"></span>
${t.paramSheet ? html`<button class="chip" style="height: 22px; font-size: 11px" data-act="build-open-grid" data-sheet="${t.paramSheet}">${icon('table', 11)} ${t.paramSheet}</button>` : ''}
</div>
<div style="display: flex; align-items: center; gap: 5px; flex-wrap: wrap">${(t.tags || []).map((g) => html`<span class="tag">${g}</span>`)}
<span style="flex: 1"></span><span style="font-size: 11px; color: var(--tx3)">needs ${(t.needs || []).length} · gives ${(t.provides || []).length}</span></div>
${t.comment ? html`<span class="trunc" style="font-size: 12px; color: var(--tx2)">${t.comment}</span>` : ''}
${!t.listed ? html`<span class="tag tag-warn" title="No DataSheets row: nothing runs this sheet on its own">not listed</span>` : ''}
</div>`;
}

export function workbookMap(S) {
  const m = bm();
  const web = m.tests.filter((t) => t.kind === 'web');
  const other = m.tests.filter((t) => t.kind !== 'web');
  return html`<div class="page" style="max-width: none">
<div style="display: flex; align-items: center; gap: 10px"><h1 class="ttl" style="font-size: 20px">Tests</h1>
<span class="chip mono">${m.tests.length} tests</span>
${m.problemCounts.error ? html`<span class="chip chip-warn">${icon('warn', 13)} ${m.problemCounts.error} problem${m.problemCounts.error === 1 ? '' : 's'}</span>` : ''}
<span style="flex: 1"></span>
<button class="btn btn-ghost btn-sm" data-act="build-open-templates">${icon('layers', 13)} Templates</button>
<button class="btn btn-ghost btn-sm" data-act="build-open-find-replace">${icon('search', 13)} Find & replace</button>
<button class="btn btn-ghost btn-sm" data-act="build-open-duplicate">${icon('copy', 13)} Duplicate</button>
<button class="btn btn-sm" data-act="build-new-test">${icon('plus', 13)} New test</button></div>
${m.tests.length === 0 ? html`<div style="border: 1.5px dashed var(--line2); border-radius: 13px; padding: 30px; text-align: center">
<div style="color: var(--tx3); display: inline-flex">${icon('grid', 26)}</div><div style="font-weight: 650; margin-top: 8px">No tests yet</div>
<div style="font-size: 12.5px; color: var(--tx2); margin-top: 2px">Add one to start building.</div></div>` : ''}
<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px">${web.map((t) => testCard(S, t))}${other.map((t) => testCard(S, t))}</div>
${m.tests.length ? scenarioCards(S) : ''}
</div>`;
}

