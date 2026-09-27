// The API / XML test editor (P10; design Q18/Q19): steps on the left (send, checks, saves), the request in the middle (Form · Paste cURL ·
// Postman collection · From template), the response on the right as a clickable tree. Clicking a value opens the Check / Save pop-up with the
// JSON path or XPath written out (and editable); inside a list it asks "this item" or "the item where ...". Everything it changes is an api_*
// op sent through applyOps (one undo step each); what it shows comes from GET /api/build/api/<workbook>/tests/<test> (build/api_builder.py).
import { S, rerender } from '../../state.js';
import { html, raw, cx, toast } from '../../util.js';
import { icon } from '../../icons.js';
import { api } from '../../api.js';
import { buildRail } from './rail.js';
import { bm, currentTest, applyOps, buildUrl } from './actions.js';

const enc = encodeURIComponent;
const KIND_OF = { json: 'output_json', xml: 'output' };
const CHECKS = [['compare', 'Is'], ['contains', 'Contains'], ['greater_than', 'Greater than'], ['less_than', 'Less than'], ['between', 'Between'], ['matches', 'Matches pattern']];

// What this page knows about the API test on screen (module state: it follows S.build.name + test + model version).
const ui = {
  key: '', testKey: '', view: null, loading: false, error: null, row: null,
  tab: 'form', sel: 'send', resp: null, respMode: 'tree', sending: false, sendError: '', missing: [], values: {},
  pop: null, closed: new Set(), varMenu: false,
  curl: { text: '', result: null, busy: false }, postman: { requests: null, picked: new Set(), busy: false, error: '' },
  tpl: { list: null, folders: [], pick: null, fields: null, maps: {}, busy: false },
};

const wbName = () => S.build.name;
const keyOf = (t) => `${wbName()}|${t.id}|${ui.row || ''}|${S.build.env || ''}|${bm() ? bm().version : 0}`;

async function load(t) {
  const key = keyOf(t);
  if (ui.key === key || ui.loading) return;
  const sameTest = ui.testKey === `${wbName()}|${t.id}`;
  ui.testKey = `${wbName()}|${t.id}`;
  if (!sameTest) Object.assign(ui, { resp: null, sel: 'send', pop: null, missing: [], values: {}, sendError: '', tab: 'form', row: null, closed: new Set(),
    curl: { text: '', result: null, busy: false }, postman: { requests: null, picked: new Set(), busy: false, error: '' },
    tpl: { list: null, folders: [], pick: null, fields: null, maps: {}, busy: false } });
  ui.loading = true;
  try {
    const q = new URLSearchParams();
    if (ui.row) q.set('row', ui.row);
    if (S.build.env) q.set('env', S.build.env);
    ui.view = await api(`/api/build/api/${enc(wbName())}/tests/${enc(t.id)}?${q}`);
    ui.error = null;
    ui.row = ui.view.row;
    ui.key = key.replace(/\|[^|]*\|([^|]*\|[^|]*)$/, `|${ui.row}|$1`);        // (the row the server chose: no second read for it)
  } catch (e) {
    ui.error = e; ui.key = key;
  }
  ui.loading = false;
  rerender();
}

async function op(ops) {
  const applied = await applyOps(ops);
  if (applied) ui.key = '';                       // the model moved on: the view is read again on the next render
  return applied;
}
const V = () => ui.view;
const base = () => ({ test: V().test, row: V().row });

// ---- text with {NAME} shown as chips ---------------------------------------------------------------------------------------------------
function chips(text) {
  const out = [];
  let last = 0;
  const re = /\{(SECRET:)?([A-Za-z_][A-Za-z0-9_]*)\}/g;
  let m;
  const envs = new Set((V() && V().environmentVariables || []).map((x) => x.toUpperCase()));
  while ((m = re.exec(text || ''))) {
    if (m.index > last) out.push(html`${text.slice(last, m.index)}`);
    out.push(html`<span class="var ${m[1] ? 'secret' : envs.has(m[2].toUpperCase()) ? 'env' : ''}">${m[1] ? '•••• ' : ''}${m[2]}</span>`);
    last = re.lastIndex;
  }
  if (last < (text || '').length) out.push(html`${text.slice(last)}`);
  return out;
}

// ---- toolbar ---------------------------------------------------------------------------------------------------------------------
function toolbar(t, v) {
  const rows = v.dataRows || [];
  return html`<div style="flex: none; display: flex; align-items: center; gap: 10px; padding: 0 16px; height: 48px; border-bottom: 1px solid var(--line); background: var(--rail)">
<span class="chip" style="height: 26px; color: var(--k-${v.format === 'json' ? 'api' : 'xml'})">${icon(v.format === 'json' ? 'api' : 'xml', 13)} ${v.format === 'json' ? 'API' : 'XML'} test</span>
<span class="mono" style="font-size: 11.5px; color: var(--tx3)">${v.steps.length} steps</span>
<span style="width: 1px; height: 20px; background: var(--line)"></span>
<span class="chip" title="${v.needs.length ? v.needs.join(', ') : 'Nothing'}">${icon('arrowr', 12)} Needs ${v.needs.length}</span>
<span class="chip" title="${v.provides.length ? v.provides.join(', ') : 'Nothing'}">${icon('arrowl', 12)} Provides ${v.provides.length}</span>
<span style="flex: 1"></span>
<label style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--tx3)">Building with
<select class="fld" style="height: 30px; width: auto; font-size: 12px" data-change="build-api-row" aria-label="Data row">
${rows.map((r) => html`<option value="${r.row}" ${r.row === v.row ? raw('selected') : ''}>Row ${r.row}${r.label ? ' · ' + r.label : ''}${r.enabled === false ? ' (off)' : ''}</option>`)}
</select></label>
<div class="seg" role="group" aria-label="Format" style="width: 150px">
<button class="${cx(v.format === 'json' && 'on')}" data-act="build-api-format" data-val="json" aria-pressed="${String(v.format === 'json')}">JSON</button>
<button class="${cx(v.format === 'xml' && 'on')}" data-act="build-api-format" data-val="xml" aria-pressed="${String(v.format === 'xml')}">XML</button></div>
</div>`;
}

// ---- steps column --------------------------------------------------------------------------------------------------------------
function resultOf(step) {
  if (!ui.resp || !ui.resp.checks || step.kind !== 'check') return null;
  const c = V().checks.find((x) => x.ioRow === step.ioRow);
  const r = c && ui.resp.checks.find((x) => x.actual.toUpperCase() === c.actual.toUpperCase() && x.expected.toUpperCase() === c.expected.toUpperCase());
  return r ? r.passed : null;
}

function stepsCol(v) {
  const badge = { send: ['api', 'Send'], check: ['check', 'Check'], save: ['save', 'Save'] };
  return html`<div class="scroll" style="width: 280px; flex: none; border-right: 1px solid var(--line); padding: 14px 12px; display: flex; flex-direction: column; gap: 5px; overflow: auto">
<div style="display: flex; align-items: center; justify-content: space-between; padding: 0 2px 6px"><span class="lbl">Steps</span></div>
${v.steps.map((s) => {
    const on = s.kind === 'send' ? ui.sel === 'send' : ui.sel === s.ioRow;
    const res = resultOf(s);
    return html`<button class="scard" data-key="api-step-${s.kind}-${s.ioRow || 0}" data-act="build-api-sel" data-io="${s.ioRow || ''}" style="min-height: 38px; font-size: 12.5px; padding: 5px 10px; ${on ? 'border-color: var(--acc); background: var(--sel-bg)' : ''}">
<span class="mono" style="width: 16px; font-size: 11px; color: var(--tx3)">${s.n}</span><span class="badge k-${badge[s.kind][0]}">${badge[s.kind][1]}</span>
<span class="trunc mono" style="font-size: 11.5px; flex: 1; text-align: left">${s.label}</span>
${res === true ? html`<span class="pdot" style="background: var(--pass)" title="Passed on the last send"></span>` : res === false ? html`<span class="pdot" style="background: var(--fail)" title="Failed on the last send"></span>` : ''}</button>`;
  })}
<span style="font-size: 11.5px; color: var(--tx3); padding: 8px 4px">Checks and saves are added by clicking values in the response →</span>
${ui.resp ? html`<button class="btn btn-sm" data-act="build-api-check-status">${icon('check', 12)} Check status is ${ui.resp.response ? ui.resp.response.status : ''}</button>` : ''}
</div>`;
}

// ---- request panel: form -----------------------------------------------------------------------------------------------------------
function varMenu(v) {
  if (!ui.varMenu) return '';
  const names = [...new Set([...(v.columns || []).filter((c) => !/^(blnExecute|TCID|TC_Name|WEBSERVICE_|JSON_FORMAT|REQUEST_BODY|XML_|ENVIRONMENT_PARAMETER)/i.test(c)),
    ...(v.environmentVariables || [])])];
  return html`<div class="menu" style="padding: 6px; display: flex; flex-wrap: wrap; gap: 4px; max-height: 180px; overflow: auto">
${names.length ? names.map((n) => html`<button class="btn btn-sm" data-act="build-api-insert-var" data-name="${n}">${icon('braces', 11)} ${n}</button>`) : html`<span style="font-size: 12px; color: var(--tx3); padding: 4px">No columns yet: type {NAME} and set its value in the Excel grid.</span>`}
<button class="btn btn-sm" data-act="build-api-insert-var" data-name="SECRET:">${icon('lock', 11)} {SECRET:…}</button></div>`;
}

function formPanel(v) {
  const env = v.environment || 'the workbook\'s environment';
  const body = v.body;
  return html`<div style="display: flex; gap: 8px">
<select class="fld" style="width: 104px; height: 34px; font-size: 12.5px; color: var(--k-api)" data-change="build-api-method" aria-label="Method">
${v.methods.map((m) => html`<option ${m === v.method ? raw('selected') : ''}>${m}</option>`)}</select>
${v.urlFormula ? html`<div class="fld mono" style="height: 34px; display: flex; align-items: center; font-size: 12px; color: var(--tx2); overflow: hidden" title="A formula: edit it in the Excel grid">${v.url}</div>`
    : html`<input class="fld mono" style="height: 34px; font-size: 12.5px" value="${v.url}" placeholder="${v.environmentParameter ? 'from the Environments sheet: ' + v.environmentParameter : '{DOMAIN}/path'}" data-change="build-api-url" aria-label="Address">`}
<button class="btn btn-pri ${ui.sending ? 'busy' : ''}" data-act="build-api-send" ${ui.sending ? raw('disabled') : ''}>${icon('play', 12)} Send now</button></div>
<span style="font-size: 12px; color: var(--tx3)">Sends a real request with ${env} values and row ${v.row}. {NAME}s come from this row, then the environment table; nothing is saved to the workbook.</span>
${ui.missing.length ? html`<div class="bn bn-warn" style="flex-direction: column; gap: 8px"><b>Only an earlier test of a run would give these. Type a value to send with (not saved):</b>
${ui.missing.map((n) => html`<label style="display: flex; align-items: center; gap: 8px"><span class="var">${n}</span><input class="fld mono" style="height: 30px; font-size: 12px" value="${ui.values[n] || ''}" data-input="build-api-missing" data-name="${n}"></label>`)}
<button class="btn btn-sm btn-pri" style="align-self: flex-start" data-act="build-api-send">Send with these</button></div>` : ''}
${ui.sendError ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${ui.sendError}</span></div>` : ''}
<div style="display: flex; flex-direction: column; gap: 6px"><div style="display: flex; align-items: center; gap: 8px"><span class="lbl">Headers</span><span style="flex: 1"></span>
<button class="btn btn-ghost btn-sm" data-act="build-api-add-header">${icon('plus', 12)} Header</button></div>
<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><tbody>
${v.headers.length ? v.headers.map((h) => html`<tr data-key="hdr-${h.ioRow}"><td class="mono" style="width: 34%">${h.name}</td>
<td><input class="fld mono" style="height: 28px; font-size: 12px" value="${h.value}" data-change="build-api-header" data-name="${h.name}" aria-label="${h.name} value"
${h.secret && h.value === '••••••' ? raw('placeholder="typed in the sheet (hidden)"') : ''}></td>
<td style="width: 34px"><button class="icon-btn" style="width: 26px; height: 26px" data-act="build-api-remove-header" data-name="${h.name}" aria-label="Stop sending ${h.name}">${icon('x', 12)}</button></td></tr>`)
    : html`<tr><td style="color: var(--tx3)">No headers. ${v.format === 'json' ? 'Content-Type: application/json is sent for JSON.' : ''}</td></tr>`}
</tbody></table></div>
${v.headers.some((h) => h.secret) ? html`<span style="font-size: 11.5px; color: var(--tx3)">For a key, type {SECRET:NAME}: the value then comes from secrets.env (RR_SECRET_NAME), never the sheet.</span>` : ''}</div>
<div style="display: flex; flex-direction: column; gap: 6px; position: relative"><div style="display: flex; align-items: center; gap: 8px"><span class="lbl">Body · ${v.format.toUpperCase()}</span>
${body.kind === 'template' ? html`<span class="tag">from ${body.template.file}</span>` : ''}<span style="flex: 1"></span>
<button class="btn btn-ghost btn-sm" data-act="build-api-var-menu" aria-expanded="${String(ui.varMenu)}">${icon('braces', 13)} Insert variable</button></div>
${varMenu(v)}
${body.kind === 'template' && !body.text ? html`<div class="bn">${icon('filetext', 15, 'color: var(--tx3)')}<span>The body is the template <b>${body.template.file}</b>${body.template.location ? ' in ' + body.template.location : ''}, with
${body.template.replace.length} placeholders filled from this row. Typing a body below replaces it (the template stays named in the sheet).</span></div>` : ''}
<textarea class="fld mono" style="height: 170px; padding: 10px 12px; font-size: 12.5px; line-height: 1.6; resize: vertical" data-change="build-api-body" spellcheck="false"
placeholder="${v.format === 'json' ? '{ "plan": "{PLAN}" }' : '<Request><Plan>{PLAN}</Plan></Request>'}" aria-label="Body">${body.text}</textarea>
${body.text && /\{/.test(body.text) ? html`<div style="font-size: 12px; color: var(--tx3); display: flex; flex-wrap: wrap; gap: 4px; align-items: center">Uses ${chips((body.text.match(/\{(SECRET:)?[A-Za-z_][A-Za-z0-9_]*\}/g) || []).filter((x, i, a) => a.indexOf(x) === i).join(' '))}</div>` : ''}
</div>`;
}

// ---- request panel: step editor (a check or a save) --------------------------------------------------------------------------------------
function stepEditor(v) {
  const c = v.checks.find((x) => x.ioRow === ui.sel);
  const s = v.saves.find((x) => x.ioRow === ui.sel);
  if (!c && !s) return formPanel(v);
  if (c) {
    return html`<div class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 10px">
<div style="display: flex; align-items: center; gap: 8px"><span class="badge k-check">Check</span><b>${c.what || c.path || c.actual}</b></div>
<label style="display: flex; flex-direction: column; gap: 4px"><span class="lbl">How</span>
<select class="fld" style="height: 32px; font-size: 12.5px" data-change="build-api-check-kind" data-io="${c.ioRow}">
${v.checkKinds.map((k) => html`<option value="${k.kind}" ${k.kind === c.kind ? raw('selected') : ''}>${k.label}</option>`)}</select></label>
<label style="display: flex; flex-direction: column; gap: 4px"><span class="lbl">Expected <span class="mono" style="text-transform: none; letter-spacing: 0">(${c.expected})</span></span>
<input class="fld mono" style="height: 32px; font-size: 12.5px" value="${c.expectedValue}" data-change="build-api-expected" data-column="${c.expected}"
placeholder="${c.kind === 'between' ? '100;200' : c.kind === 'matches' ? '^Q-\\d+$' : ''}"></label>
${c.outputRow ? html`<label style="display: flex; flex-direction: column; gap: 4px"><span class="lbl">${v.format === 'json' ? 'JSON path' : 'XPath'}, written for you (you can edit it)</span>
<input class="fld mono" style="height: 32px; font-size: 12px" value="${c.path}" data-change="build-api-path" data-io="${c.outputRow}"></label>` : ''}
${c.disabled ? html`<span class="tag tag-warn">switched off for this test (DisableCheckpoint)</span>` : ''}
<div style="display: flex; gap: 8px"><button class="btn btn-sm" data-act="build-api-sel" data-io="">${icon('chevl', 12)} Request</button><span style="flex: 1"></span>
<button class="btn btn-sm" data-act="build-api-delete" data-io="${c.ioRow}">${icon('trash', 12)} Remove check</button></div></div>`;
  }
  return html`<div class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 10px">
<div style="display: flex; align-items: center; gap: 8px"><span class="badge k-save">Save</span><b>as</b><span class="var">${s.column}</span></div>
<span style="font-size: 12.5px; color: var(--tx2)">Later tests of the run use it as {${s.column}}.${s.lastValue ? html` Last value: <span class="mono">${s.lastValue}</span>` : ''}</span>
<label style="display: flex; flex-direction: column; gap: 4px"><span class="lbl">${s.function === 'output_json' ? 'JSON path' : 'XPath'}, written for you (you can edit it)</span>
<input class="fld mono" style="height: 32px; font-size: 12px" value="${s.path}" data-change="build-api-path" data-io="${s.ioRow}"></label>
<div style="display: flex; gap: 8px"><button class="btn btn-sm" data-act="build-api-sel" data-io="">${icon('chevl', 12)} Request</button><span style="flex: 1"></span>
<button class="btn btn-sm" data-act="build-api-delete" data-io="${s.ioRow}">${icon('trash', 12)} Remove save</button></div></div>`;
}

// ---- request panel: the ways in --------------------------------------------------------------------------------------------------
function curlPanel() {
  const r = ui.curl.result;
  return html`<span style="font-size: 12.5px; color: var(--tx2)">Copy as cURL from the browser (bash or cmd) or a colleague. It replaces this test's request; nothing is saved until you choose it.</span>
<textarea class="fld mono" style="height: 150px; padding: 10px 12px; font-size: 12px; resize: vertical" data-input="build-api-curl" spellcheck="false" placeholder="curl 'https://…' -H 'Content-Type: application/json' --data-raw '{…}'">${ui.curl.text}</textarea>
<button class="btn btn-sm ${ui.curl.busy ? 'busy' : ''}" style="align-self: flex-start" data-act="build-api-curl-read">Read it</button>
${r ? html`<span class="lbl">We found</span><div style="display: flex; flex-direction: column; gap: 6px; font-size: 12.5px">
<span class="mono">${r.request.method} ${chips(r.request.url)}</span>
${r.found.map((f) => html`<span style="display: flex; gap: 8px; align-items: center">${icon('check', 13, 'color: var(--pass)')} ${f.text}</span>`)}
${r.request.headers.map((h) => html`<span class="mono" style="font-size: 11.5px; color: var(--tx2)">${h.name}: ${chips(h.value)}</span>`)}
${r.request.body ? html`<pre class="mono" style="margin: 0; font-size: 11.5px; white-space: pre-wrap; word-break: break-all; color: var(--tx2); max-height: 140px; overflow: auto">${r.request.body}</pre>` : ''}</div>
<button class="btn btn-pri btn-sm" style="align-self: flex-start" data-act="build-api-curl-use">Use for this test</button>` : ''}`;
}

function postmanPanel() {
  const p = ui.postman;
  return html`<span style="font-size: 12.5px; color: var(--tx2)">Pick a collection file (v2.0 / v2.1). Each request you tick becomes a test of its own; {{variables}} become {variables}.</span>
<input type="file" accept=".json,application/json" data-change="build-api-postman-file" aria-label="Postman collection file">
${p.error ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${p.error}</span></div>` : ''}
${p.requests ? html`<div style="display: flex; flex-direction: column; gap: 4px">
${p.requests.map((r, i) => html`<label class="mitem" data-key="pm-${i}" style="height: auto; min-height: 32px; cursor: pointer">
<input type="checkbox" ${p.picked.has(i) ? raw('checked') : ''} data-change="build-api-postman-pick" data-i="${i}">
<span class="badge k-api" style="width: 50px">${r.request.method}</span><span style="flex: 1; min-width: 0; display: flex; flex-direction: column">
<span class="trunc" style="font-weight: 600">${r.folder ? r.folder + ' / ' : ''}${r.name}</span><span class="mono trunc" style="font-size: 11px; color: var(--tx3)">${r.request.url}</span></span></label>`)}</div>
<button class="btn btn-pri btn-sm ${p.busy ? 'busy' : ''}" style="align-self: flex-start" data-act="build-api-postman-import" ${p.picked.size ? '' : raw('disabled')}>Import ${p.picked.size} request${p.picked.size === 1 ? '' : 's'}</button>` : ''}`;
}

function templatePanel(v) {
  const t = ui.tpl;
  if (!t.list) return html`<div class="skel" style="height: 120px"></div>`;
  const cols = v.columns.filter((c) => !/^(blnExecute|TCID|WEBSERVICE_|JSON_FORMAT|REQUEST_BODY|XML_)/i.test(c));
  return html`<span style="font-size: 12.5px; color: var(--tx2)">The Replace / Output files the runner already uses. Looked in: ${t.folders.join(' · ') || 'no template folder found (api.templates_dir, RR_API_TEMPLATES_DIR, templates/ beside the workbook)'}</span>
<div style="display: flex; flex-direction: column; gap: 4px; max-height: 200px; overflow: auto">
${t.list.length ? t.list.map((f, i) => html`<button class="mitem ${t.pick === i ? 'on' : ''}" data-key="tpl-${i}" data-act="build-api-tpl-pick" data-i="${i}">${icon('filetext', 14)}
<span class="mono trunc" style="font-size: 12px; flex: 1; text-align: left">${f.file}</span><span class="tag">${f.format.toUpperCase()}</span></button>`) : html`<span style="font-size: 12px; color: var(--tx3)">No .json / .xml / .txt files there.</span>`}</div>
${t.fields ? html`<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th>Template field</th><th>Filled with</th></tr></thead><tbody>
${t.fields.fields.map((f) => {
    const m = t.maps[f.placeholder] || { column: f.column, value: '' };
    return html`<tr data-key="tf-${f.placeholder}"><td class="mono">${f.placeholder}${f.count > 1 ? html` <span class="tag">×${f.count}</span>` : ''}</td><td style="display: flex; gap: 6px">
<select class="fld" style="height: 28px; font-size: 12px" data-change="build-api-tpl-col" data-ph="${f.placeholder}">
<option value="" ${!m.column ? raw('selected') : ''}>type a value…</option>
${cols.map((c) => html`<option value="${c}" ${c === m.column ? raw('selected') : ''}>{${c}}</option>`)}</select>
${!m.column ? html`<input class="fld mono" style="height: 28px; font-size: 12px" value="${m.value || ''}" placeholder="choose…" data-input="build-api-tpl-val" data-ph="${f.placeholder}">` : ''}</td></tr>`;
  })}</tbody></table></div>
<button class="btn btn-pri btn-sm ${t.busy ? 'busy' : ''}" style="align-self: flex-start" data-act="build-api-tpl-use">Use template</button>` : ''}`;
}

function requestPanel(t, v) {
  const tabs = [['form', 'Form'], ['curl', 'Paste cURL'], ['postman', 'Postman collection'], ['template', 'From template']];
  const editingStep = ui.sel !== 'send' && ui.tab === 'form';
  return html`<div class="scroll" style="flex: 1; min-width: 0; padding: 16px 18px; display: flex; flex-direction: column; gap: 14px; overflow: auto">
<div style="display: flex; align-items: center; gap: 8px"><span class="mono" style="font-size: 12px; color: var(--tx3)">Step 1</span><span class="badge k-api">Send</span>
<span class="disp trunc" style="font-size: 19px; font-weight: 700">${t.id}</span></div>
<div class="seg" role="tablist" aria-label="Request source">${tabs.map(([k, label]) => html`<button role="tab" class="${cx(ui.tab === k && 'on')}" aria-selected="${String(ui.tab === k)}" data-act="build-api-tab" data-val="${k}">${label}</button>`)}</div>
${ui.tab === 'curl' ? curlPanel() : ui.tab === 'postman' ? postmanPanel() : ui.tab === 'template' ? templatePanel(v) : editingStep ? stepEditor(v) : formPanel(v)}
</div>`;
}

// ---- response panel -------------------------------------------------------------------------------------------------------------------
function visibleNodes(tree) {
  const out = [];
  let hideBelow = null;
  for (const n of tree) {
    if (hideBelow != null && n.depth > hideBelow) continue;
    hideBelow = null;
    out.push(n);
    if (ui.closed.has(n.id) && n.count != null) hideBelow = n.depth;
  }
  return out;
}

function nodeRow(n, fmt) {
  const leaf = n.count == null;
  const color = { string: 'var(--k-check)', number: 'var(--k-api)', bool: 'var(--k-nav)', null: 'var(--tx3)', text: 'var(--k-check)', attribute: 'var(--k-save)' }[n.type] || 'var(--tx2)';
  const sel = ui.pop && ui.pop.id === n.id;
  const label = fmt === 'json' ? (n.depth === 0 ? '' : typeof n.key === 'number' ? `${n.key}:` : `${n.key}:`) : `${n.key}${leaf ? ':' : ''}`;
  const summary = leaf ? n.value : n.type === 'array' ? `[ ${n.count} items ]` : n.type === 'object' ? `{ ${n.count} }` : `‹${n.count}›`;
  return html`<button class="mono" data-key="n-${n.id}" data-act="${leaf ? 'build-api-node' : 'build-api-fold'}" data-id="${n.id}" title="${n.path}"
style="display: flex; align-items: center; gap: 6px; width: 100%; min-height: 24px; padding: 0 8px 0 ${8 + n.depth * 16}px; border-radius: 6px; text-align: left; ${sel ? 'background: var(--acc-soft); box-shadow: inset 0 0 0 1px var(--acc-line);' : ''}">
${leaf ? '' : html`<span style="color: var(--tx3); font-size: 11px; width: 10px">${ui.closed.has(n.id) ? '▸' : '▾'}</span>`}
<span style="color: var(--tx3); font-size: 12px; white-space: nowrap">${label}</span><span class="trunc" style="font-size: 12px; color: ${leaf ? color : 'var(--tx3)'}">${summary}</span></button>`;
}

function popup(v, n) {
  const p = ui.pop;
  const arr = n.array;
  const next = v.steps.length + 1;
  return html`<div class="menu" data-key="pop" style="margin: 4px 0 8px ${8 + n.depth * 16}px; padding: 12px; display: flex; flex-direction: column; gap: 10px">
<div style="display: flex; align-items: center; gap: 8px"><b class="mono trunc" style="font-size: 12.5px">${n.key} = ${n.text}</b><span style="flex: 1"></span><span class="tag">${n.type}</span></div>
<div style="display: flex; flex-wrap: wrap; gap: 4px">
${CHECKS.map(([k, label]) => html`<button class="btn btn-sm ${p.mode === 'check' && p.kind === k ? 'btn-pri' : ''}" style="font-weight: 500" data-act="build-api-pop-kind" data-val="${k}">${label}</button>`)}
<button class="btn btn-sm ${p.mode === 'save' ? 'btn-pri' : ''}" style="font-weight: 500" data-act="build-api-pop-kind" data-val="save">Save as variable</button></div>
${p.mode === 'save' ? html`<label style="display: flex; flex-direction: column; gap: 4px"><span style="font-size: 12px; color: var(--tx2)">Variable name (later tests use {NAME})</span>
<input class="fld mono" style="height: 30px; font-size: 12px" value="${p.variable}" data-input="build-api-pop-var"></label>`
    : html`<label style="display: flex; flex-direction: column; gap: 4px"><span style="font-size: 12px; color: var(--tx2)">Expected${p.kind === 'between' ? ' (low;high)' : p.kind === 'matches' ? ' (a pattern)' : ''}</span>
<input class="fld mono" style="height: 30px; font-size: 12px" value="${p.expected}" data-input="build-api-pop-expected"></label>
${p.suggest ? html`<button class="lnk" style="align-self: flex-start" data-act="build-api-pop-use-var">Expect {${p.suggest}} instead (the row's value)</button>` : ''}`}
${arr ? html`<div style="display: flex; flex-direction: column; gap: 4px"><b style="font-size: 12.5px">You clicked an item in a list. Which do you mean?</b>
<button class="mitem ${p.pathChoice === 'this' ? 'on' : ''}" data-act="build-api-pop-path" data-val="this">${icon('target', 14)}<span style="flex: 1; text-align: left">This item <span class="mono" style="color: var(--tx3); font-size: 11px">#${arr.index + 1} of ${arr.count}</span></span></button>
${arr.where.map((w, i) => html`<button class="mitem ${p.pathChoice === 'w' + i ? 'on' : ''}" style="height: auto; min-height: 32px" data-act="build-api-pop-path" data-val="w${i}">${icon('braces', 14)}
<span style="flex: 1; text-align: left">The item where ${w.field} = ${w.variable ? html`<span class="var">${w.variable}</span>` : html`<span class="mono">${w.value}</span>`}${w.unique ? '' : html` <span class="tag tag-warn">not unique</span>`}</span></button>`)}</div>` : ''}
<span style="font-size: 12px; color: var(--tx2)">Path, written for you (you can edit it)</span>
<input class="fld mono" style="height: 30px; font-size: 11.5px" value="${p.path}" data-input="build-api-pop-path-text" aria-label="Path">
<div style="display: flex; gap: 8px"><button class="btn btn-sm btn-pri" data-act="build-api-pop-add">Add as step ${next}</button><button class="btn btn-sm btn-ghost" data-act="build-api-pop-close">Cancel</button></div></div>`;
}

function responsePanel(v) {
  const r = ui.resp && ui.resp.response;
  const head = html`<div style="padding: 12px 16px; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 10px; flex-wrap: wrap"><span class="ttl" style="font-size: 16px">Response</span>
${r ? html`<span class="pill ${r.status < 400 ? 'p-pass' : 'p-fail'}">${r.status}</span><span class="mono" style="font-size: 11.5px; color: var(--tx3)">${r.ms} ms · ${ui.resp.environment} · ${ui.resp.when}</span>` : ''}
<span style="flex: 1"></span>
${r ? html`<div class="seg" style="width: 140px"><button class="${cx(ui.respMode === 'tree' && 'on')}" data-act="build-api-resp-mode" data-val="tree">Tree</button><button class="${cx(ui.respMode === 'raw' && 'on')}" data-act="build-api-resp-mode" data-val="raw">Raw</button></div>` : ''}</div>`;
  let bodyHtml;
  if (!ui.resp) {
    bodyHtml = html`<div style="padding: 24px 16px; color: var(--tx3); font-size: 13px; display: flex; flex-direction: column; gap: 8px">${icon('play', 18)}<span>Press <b>Send now</b> to see the real answer here, then click any value to check it or save it.</span></div>`;
  } else if (!r) {
    bodyHtml = html`<div style="padding: 16px"><div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${ui.resp.error || 'No response.'}</span></div></div>`;
  } else if (ui.respMode === 'raw' || !r.tree.length) {
    bodyHtml = html`<pre class="mono scroll" style="flex: 1; margin: 0; padding: 12px 16px; font-size: 12px; white-space: pre-wrap; word-break: break-all; overflow: auto">${r.text}</pre>`;
  } else {
    const nodes = visibleNodes(r.tree);
    bodyHtml = html`<span style="padding: 10px 16px 0; font-size: 12px; color: var(--tx3)">Click any value to check it or save it.${r.treeCut ? ' (Very long: only the start is shown.)' : ''}</span>
<div class="scroll" style="flex: 1; overflow: auto; padding: 8px 10px">${nodes.map((n) => html`${nodeRow(n, r.format)}${ui.pop && ui.pop.id === n.id ? popup(v, n) : ''}`)}</div>`;
  }
  const checks = ui.resp && ui.resp.checks && ui.resp.checks.length ? html`<div style="padding: 8px 16px; border-top: 1px solid var(--line); display: flex; flex-wrap: wrap; gap: 6px">
${ui.resp.checks.map((c) => html`<span class="tag ${c.passed ? '' : 'tag-fail'}" title="expected ${c.expectedValue} · got ${c.actualValue}">${c.passed ? '✓' : '✗'} ${c.actual}</span>`)}</div>` : '';
  return html`<div style="width: 480px; flex: none; border-left: 1px solid var(--line); background: var(--rail); display: flex; flex-direction: column; min-height: 0">${head}${bodyHtml}${checks}</div>`;
}

// ---- top-level -----------------------------------------------------------------------------------------------------------------------------
export function apiEditor(S_) {
  const t = currentTest();
  load(t);
  const v = ui.view && ui.view.test === t.id ? ui.view : null;
  let body;
  if (ui.error && !v) body = html`<div class="page"><b>Could not open ${t.id}.</b><p style="color: var(--tx2)">${ui.error.message}</p></div>`;
  else if (!v) body = html`<div class="page"><div class="skel" style="height: 40px; width: 300px"></div><div class="skel" style="height: 400px"></div></div>`;
  else body = html`${toolbar(t, v)}<div style="flex: 1; display: flex; min-height: 0">${stepsCol(v)}${requestPanel(t, v)}${responsePanel(v)}</div>`;
  return html`<div class="app-body">${buildRail(S_)}<main class="main" style="display: flex; flex-direction: column; min-width: 0; min-height: 0">${body}</main></div>`;
}

// ---- actions ---------------------------------------------------------------------------------------------------------------------------------
async function send(confirmProd = '') {
  const v = V();
  if (!v || ui.sending) return;
  ui.sending = true; ui.sendError = ''; rerender();
  try {
    const out = await api('/api/build/api/send', { method: 'POST', body: { workbook: wbName(), test: v.test, row: v.row, env: S.build.env || undefined,
      values: ui.values, ...(confirmProd ? { confirmProd } : {}) } });
    ui.missing = out.missing && !out.response ? out.missing : [];
    if (out.response) { ui.resp = { ...out, when: new Date().toLocaleTimeString() }; ui.pop = null; ui.closed = new Set(); }
    else if (out.error) ui.sendError = out.error;
  } catch (e) {
    if (e.kind === 'prod_confirm') {
      ui.sending = false;
      const typed = window.prompt(`${e.message}\n\nType PROD to send it anyway.`);
      if (typed && typed.trim() === 'PROD') { send('PROD'); return; }
    } else ui.sendError = e.message;
  }
  ui.sending = false;
  rerender();
}

function nodeById(id) { return ui.resp && ui.resp.response ? ui.resp.response.tree.find((n) => n.id === id) : null; }

function openPop(n) {
  const arr = n.array;
  let pathChoice = 'this';
  let path = n.path;
  if (arr) {
    const i = arr.where.findIndex((w) => w.variable);
    if (i >= 0) { pathChoice = 'w' + i; path = arr.where[i].variablePath; }
  }
  const rv = V().rowValues || {};
  const suggest = Object.keys(rv).find((k) => rv[k] && rv[k] === n.text && !/^(blnExecute|TCID|TC_Name)$/i.test(k)) || '';
  const variable = String(n.key).startsWith('@') ? String(n.key).slice(1) : String(n.key);
  ui.pop = { id: n.id, mode: 'check', kind: 'compare', expected: n.text, variable: variable.replace(/[^A-Za-z0-9]+/g, '_').toUpperCase(), path, pathChoice, suggest };
  rerender();
}

async function addFromPop() {
  const p = ui.pop;
  const v = V();
  if (!p || !p.path.trim()) { toast('The path is empty.'); return; }
  const fn = KIND_OF[v.format];
  const o = p.mode === 'save'
    ? { op: 'api_add_save', ...base(), path: p.path.trim(), function: fn, variable: p.variable || 'VALUE' }
    : { op: 'api_add_check', ...base(), path: p.path.trim(), function: fn, kind: p.kind, expected: p.expected };
  const applied = await op([o]);
  if (!applied) return;
  const a = applied[0];
  ui.pop = null;
  if (a.reused && a.op === 'api_add_save') toast(`That value is already read into {${a.column}}: use that name.`, 5000);
  rerender();
}

async function readPostmanFile(el) {
  const file = el.files && el.files[0];
  if (!file) return;
  ui.postman = { requests: null, picked: new Set(), busy: true, error: '' }; rerender();
  try {
    const text = await file.text();
    const out = await api('/api/build/api/postman', { method: 'POST', body: { workbook: wbName(), collection: text, env: S.build.env || undefined } });
    ui.postman.requests = out.requests;
    ui.postman.picked = new Set(out.requests.map((_, i) => i));
  } catch (e) { ui.postman.error = e.message; }
  ui.postman.busy = false;
  rerender();
}

function sheetName(name, taken) {
  let base = String(name || 'Request').replace(/[[\]:*?/\\']/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 28) || 'Request';
  let out = base, n = 2;
  while (taken.has(out.toUpperCase())) { out = `${base.slice(0, 27)} ${n}`; n += 1; }
  taken.add(out.toUpperCase());
  return out;
}

async function importPostman() {
  const p = ui.postman;
  const m = bm();
  const taken = new Set(m.sheets.map((s) => s.name.toUpperCase()));
  const ops = [...p.picked].sort((a, b) => a - b).map((i) => {
    const r = p.requests[i];
    return { op: 'api_add_test', name: sheetName(r.name, taken), format: r.request.format, method: r.request.method, url: r.request.url,
      headers: r.request.headers.map((h) => [h.name, h.value]), body: r.request.body, comment: r.folder ? `Postman: ${r.folder}` : 'Postman' };
  });
  if (!ops.length) return;
  p.busy = true; rerender();
  const applied = await op(ops);
  p.busy = false;
  if (!applied) { rerender(); return; }
  toast(`${applied.length} API test${applied.length === 1 ? '' : 's'} added. Secrets go in secrets.env as RR_SECRET_<NAME>.`, 6000);
  location.hash = buildUrl(wbName(), 'test', applied[0].test);
}

async function loadTemplates() {
  const v = V();
  try {
    const out = await api(`/api/build/api/${enc(wbName())}/templates?location=${enc(v.body.template.location || '')}`);
    ui.tpl.list = out.templates; ui.tpl.folders = out.folders;
  } catch (e) { ui.tpl.list = []; toast(e.message, 5000); }
  rerender();
}

async function pickTemplate(i) {
  const v = V();
  const f = ui.tpl.list[i];
  ui.tpl.pick = i; ui.tpl.fields = null; ui.tpl.maps = {}; rerender();
  try {
    const q = new URLSearchParams({ folder: f.folder, file: f.file, test: v.test, row: v.row, location: v.body.template.location || '' });
    ui.tpl.fields = await api(`/api/build/api/${enc(wbName())}/templates/fields?${q}`);
    for (const fl of ui.tpl.fields.fields) ui.tpl.maps[fl.placeholder] = { column: fl.column, value: '' };
  } catch (e) { toast(e.message, 5000); }
  rerender();
}

async function useTemplate() {
  const t = ui.tpl;
  const v = V();
  const f = t.list[t.pick];
  const location = f.folder === (v.body.template.location || '') ? f.folder : '';     // (a fallback folder is found by the runner without it)
  const mappings = t.fields.fields.map((fl) => ({ placeholder: fl.placeholder, column: (t.maps[fl.placeholder] || {}).column || '',
    value: (t.maps[fl.placeholder] || {}).value || '' }));
  t.busy = true; rerender();
  const applied = await op([{ op: 'api_use_template', ...base(), location, file: f.file, format: f.format, mappings }]);
  t.busy = false;
  if (applied) { ui.tab = 'form'; toast(`${applied[0].filled.length} template fields filled from this row.`); }
  rerender();
}

async function curlRead() {
  const v = V();
  ui.curl.busy = true; rerender();
  try {
    ui.curl.result = await api('/api/build/api/curl', { method: 'POST', body: { workbook: wbName(), text: ui.curl.text, test: v.test, row: v.row, env: S.build.env || undefined } });
  } catch (e) { ui.curl.result = null; toast(e.message, 6000); }
  ui.curl.busy = false;
  rerender();
}

async function curlUse() {
  const r = ui.curl.result.request;
  const ops = [{ op: 'api_set_request', ...base(), method: r.method, url: r.url, format: r.format, body: r.body }];
  for (const h of r.headers) {
    if (h.name.toLowerCase() === 'content-type' && r.format === 'json' && /json/i.test(h.value)) continue;
    ops.push({ op: 'api_set_header', ...base(), name: h.name, value: h.value });
  }
  const applied = await op(ops);
  if (applied) { ui.tab = 'form'; ui.curl = { text: '', result: null, busy: false }; toast('The request now comes from that cURL command.'); rerender(); }
}

function insertVariable(name) {
  const token = name === 'SECRET:' ? '{SECRET:NAME}' : `{${name}}`;
  const el = document.querySelector('[data-change="build-api-body"]');
  const text = el ? el.value : V().body.text;
  const at = el && typeof el.selectionStart === 'number' ? el.selectionStart : text.length;
  const next = text.slice(0, at) + token + text.slice(el && typeof el.selectionEnd === 'number' ? el.selectionEnd : at);
  ui.varMenu = false;
  op([{ op: 'api_set_request', ...base(), body: next }]);
}

export const acts = {
  'build-api-send'() { send(); },
  'build-api-format'(el) { if (V() && V().format !== el.dataset.val) op([{ op: 'api_set_request', ...base(), format: el.dataset.val }]); },
  'build-api-tab'(el) { ui.tab = el.dataset.val; if (ui.tab === 'template' && !ui.tpl.list) loadTemplates(); rerender(); },
  'build-api-sel'(el) { ui.sel = el.dataset.io ? Number(el.dataset.io) : 'send'; ui.tab = 'form'; rerender(); },
  'build-api-add-header'() {
    const name = window.prompt('Header name (for example x-api-key):');
    if (!name || !name.trim()) return;
    const value = window.prompt(`Value of ${name.trim()} (a key: {SECRET:NAME}, kept in secrets.env):`, '') ?? '';
    op([{ op: 'api_set_header', ...base(), name: name.trim(), value }]);
  },
  'build-api-remove-header'(el) { op([{ op: 'api_remove_header', ...base(), name: el.dataset.name }]); },
  'build-api-var-menu'() { ui.varMenu = !ui.varMenu; rerender(); },
  'build-api-insert-var'(el) { insertVariable(el.dataset.name); },
  'build-api-delete'(el) {
    const io = Number(el.dataset.io);
    const c = V().checks.find((x) => x.ioRow === io);
    const others = c && c.outputRow ? V().checks.filter((x) => x.outputRow === c.outputRow && x.ioRow !== io).length : 1;
    const rows = c && c.outputRow && !others ? [io, c.outputRow] : [io];            // the output row goes too when nothing else reads it
    ui.sel = 'send';
    op([{ op: 'api_delete_io', ioRows: rows }]);
  },
  'build-api-node'(el) { const n = nodeById(Number(el.dataset.id)); if (n) { if (ui.pop && ui.pop.id === n.id) { ui.pop = null; rerender(); } else openPop(n); } },
  'build-api-fold'(el) { const id = Number(el.dataset.id); if (ui.closed.has(id)) ui.closed.delete(id); else ui.closed.add(id); rerender(); },
  'build-api-pop-kind'(el) { if (!ui.pop) return; if (el.dataset.val === 'save') ui.pop.mode = 'save'; else { ui.pop.mode = 'check'; ui.pop.kind = el.dataset.val; } rerender(); },
  'build-api-pop-use-var'() { if (ui.pop) { ui.pop.expected = `{${ui.pop.suggest}}`; ui.pop.suggest = ''; rerender(); } },
  'build-api-pop-path'(el) {
    const p = ui.pop;
    const n = p && nodeById(p.id);
    if (!n || !n.array) return;
    p.pathChoice = el.dataset.val;
    if (el.dataset.val === 'this') p.path = n.array.thisItem;
    else { const w = n.array.where[Number(el.dataset.val.slice(1))]; p.path = w.variablePath || w.path; }
    rerender();
  },
  'build-api-pop-add'() { addFromPop(); },
  'build-api-pop-close'() { ui.pop = null; rerender(); },
  'build-api-resp-mode'(el) { ui.respMode = el.dataset.val; rerender(); },
  'build-api-check-status'() { if (ui.resp && ui.resp.response) op([{ op: 'api_add_check', ...base(), path: 'status', kind: 'compare', expected: String(ui.resp.response.status) }]); },
  'build-api-curl-read'() { curlRead(); },
  'build-api-curl-use'() { curlUse(); },
  'build-api-postman-import'() { importPostman(); },
  'build-api-tpl-pick'(el) { pickTemplate(Number(el.dataset.i)); },
  'build-api-tpl-use'() { useTemplate(); },
};

export const changes = {
  'build-api-row'(el) { ui.row = Number(el.value); ui.key = ''; ui.resp = null; ui.pop = null; rerender(); },
  'build-api-method'(el) { op([{ op: 'api_set_request', ...base(), method: el.value }]); },
  'build-api-url'(el) { if (el.value !== V().url) op([{ op: 'api_set_request', ...base(), url: el.value }]); },
  'build-api-body'(el) { if (el.value !== V().body.text) op([{ op: 'api_set_request', ...base(), body: el.value }]); },
  'build-api-header'(el) { op([{ op: 'api_set_header', ...base(), name: el.dataset.name, value: el.value }]); },
  'build-api-expected'(el) { op([{ op: 'api_set_value', ...base(), column: el.dataset.column, value: el.value }]); },
  'build-api-path'(el) { if (el.value.trim()) op([{ op: 'api_update_io', ioRow: Number(el.dataset.io), parameter: el.value.trim() }]); },
  'build-api-check-kind'(el) { op([{ op: 'api_update_io', ioRow: Number(el.dataset.io), function: el.value }]); },
  'build-api-postman-file'(el) { readPostmanFile(el); },
  'build-api-postman-pick'(el) { const i = Number(el.dataset.i); if (el.checked) ui.postman.picked.add(i); else ui.postman.picked.delete(i); rerender(); },
  'build-api-tpl-col'(el) { ui.tpl.maps[el.dataset.ph] = { column: el.value, value: '' }; rerender(); },
};

export const inputs = {
  'build-api-missing'(el) { ui.values[el.dataset.name] = el.value; },
  'build-api-curl'(el) { ui.curl.text = el.value; },
  'build-api-pop-expected'(el) { if (ui.pop) ui.pop.expected = el.value; },
  'build-api-pop-var'(el) { if (ui.pop) ui.pop.variable = el.value; },
  'build-api-pop-path-text'(el) { if (ui.pop) { ui.pop.path = el.value; ui.pop.pathChoice = ''; } },
  'build-api-tpl-val'(el) { ui.tpl.maps[el.dataset.ph] = { column: '', value: el.value }; },
};

/** For tests and the debugger: what the editor holds. */
export const apiEditorState = () => ui;
