// "Session, step by step" on the Results test page: for each step of a test, what the page wrote to its console, which of its own server calls ran
// (with what was sent and answered), which form fields changed (and every field as it stood), and any switched-off field that held nothing.
// The data is what the run recorded (tests/<test>/console.jsonl, network.jsonl, state.jsonl; GET /api/results/runs/<run>/tests/<test>/session).
import { html } from '../../util.js';
import { icon } from '../../icons.js';
import { runFileUrl } from '../../api.js';

/** The page as it stood after step `upto`: the state lines applied in order (the JS twin of capture/state.py `replay`). */
export function replay(lines, upto) {
  let fields = {}, storage = {}, cookies = [], messages = [], url = '';
  for (const line of lines) {
    if (line.step > upto) break;
    url = line.url || url;
    if (line.full) { fields = { ...(line.fields || {}) }; storage = { ...(line.storage || {}) }; cookies = [...(line.cookies || [])]; }
    else {
      fields = { ...fields, ...(line.fields || {}) };
      storage = { ...storage, ...(line.storage || {}) };
      for (const k of line.gone || []) delete fields[k];
      for (const k of line.storage_gone || []) delete storage[k];
      cookies = cookies.filter((c) => !(line.cookies_gone || []).includes(c)).concat(line.cookies_added || []);
    }
    if (line.messages) messages = [...line.messages];
  }
  return { url, fields, storage, cookies, messages };
}

const LEVEL = { error: 'fail', pageerror: 'fail', warning: 'warn', warn: 'warn' };
const pretty = (text) => { try { return JSON.stringify(JSON.parse(text), null, 2); } catch (e) { return String(text || ''); } };
const lockedHow = (f) => (f.disabled ? 'disabled' : f.readonly ? 'read-only' : f.ariaDisabled ? 'not editable' : '');

function stepFacts(sess, s) {
  const group = sess.steps[String(s.seq)] || { console: [], calls: [] };
  const line = sess.state.find((l) => l.step === s.seq);
  const noisy = group.console.filter((c) => LEVEL[c.level]);
  const badCalls = group.calls.filter((c) => c.status == null || c.status >= 400);
  const warns = (line && line.warnings) || [];
  return { group, line, noisy, badCalls, warns, changed: line && line.fields ? Object.keys(line.fields).length : 0,
           notable: s.status === 'FAILED' || warns.length > 0 || noisy.length > 0 || badCalls.length > 0 };
}

function badge(text, tone) {
  return html`<span class="tag ${tone ? `tag-${tone}` : ''}" style="font-size: 10.5px; padding: 0 6px">${text}</span>`;
}

function stepRow(sess, s, on) {
  const f = stepFacts(sess, s);
  const dot = s.status === 'PASSED' ? 'var(--pass)' : s.status === 'FAILED' ? 'var(--fail)' : 'var(--tx3)';
  return html`<button data-act="results-session-step" data-seq="${s.seq}" aria-pressed="${String(on)}" data-key="sess-${s.seq}"
style="display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; padding: 7px 10px; border-radius: 9px; border: 1px solid ${on ? 'var(--acc-line)' : 'transparent'}; background: ${on ? 'var(--acc-soft)' : 'transparent'}">
<span class="mono" style="width: 28px; font-size: 11.5px; color: var(--tx3)">${s.seq}</span><span class="pdot" style="background: ${dot}"></span>
<span class="trunc" style="flex: 1; min-width: 0; font-size: 12.5px">${s.name || s.action}</span>
${f.warns.length ? badge(`⚠ ${f.warns.length}`, 'warn') : ''}${f.noisy.length ? badge(`console ${f.noisy.length}`, f.noisy.some((c) => LEVEL[c.level] === 'fail') ? 'fail' : 'warn') : ''}${f.badCalls.length ? badge(`calls ${f.badCalls.length}`, 'fail') : ''}</button>`;
}

function fieldRow(key, f, flag) {
  const how = lockedHow(f);
  const empty = f.empty && f.type !== 'checkbox' && f.type !== 'radio';
  const bad = flag && how && f.visible && empty;
  return html`<tr style="${bad ? 'background: var(--warn-soft, rgba(255, 190, 0, .12))' : ''}">
<td style="padding: 4px 8px; vertical-align: top"><div style="font-size: 12.5px">${f.label || key}</div><div class="mono" style="font-size: 10.5px; color: var(--tx3)">${key}</div></td>
<td class="mono" style="padding: 4px 8px; font-size: 12px; overflow-wrap: anywhere; vertical-align: top">${f.value === '' || f.value == null
    ? html`<span style="color: var(--tx3)">${f.placeholder ? `(empty, shows "${f.placeholder}")` : '(empty)'}</span>` : f.value}</td>
<td style="padding: 4px 8px; vertical-align: top; white-space: nowrap">${how ? badge(how, bad ? 'warn' : '') : ''}${f.visible === false ? badge('not shown') : ''}</td></tr>`;
}

function fieldsTable(rows, flag) {
  return html`<table style="width: 100%; border-collapse: collapse; font-size: 12.5px; table-layout: fixed"><colgroup><col style="width: 38%"><col><col style="width: 120px"></colgroup><tbody>${rows.map(([k, f]) => fieldRow(k, f, flag))}</tbody></table>`;
}

function section(title, count, body) {
  return html`<div style="display: flex; flex-direction: column; gap: 6px"><div style="display: flex; align-items: center; gap: 8px"><span class="lbl">${title}</span>
${count != null ? html`<span class="mono" style="font-size: 11px; color: var(--tx3)">${count}</span>` : ''}</div>${body}</div>`;
}

function consoleBlock(items) {
  if (!items.length) return html`<span style="font-size: 12.5px; color: var(--tx3)">Nothing written to the console during this step.</span>`;
  return html`<div style="display: flex; flex-direction: column; gap: 4px">${items.map((c) => html`<div style="display: flex; gap: 8px; align-items: baseline">
${badge(c.level, LEVEL[c.level] || '')}<div style="min-width: 0; flex: 1"><div class="mono" style="font-size: 12px; overflow-wrap: anywhere; white-space: pre-wrap">${c.text}</div>
${c.where ? html`<div class="mono" style="font-size: 10.5px; color: var(--tx3)">${c.where}</div>` : ''}
${c.stack ? html`<details><summary style="font-size: 11.5px; color: var(--tx2); cursor: pointer">stack</summary><pre class="mono" style="font-size: 11px; white-space: pre-wrap; overflow-wrap: anywhere; margin: 4px 0">${c.stack}</pre></details>` : ''}</div></div>`)}</div>`;
}

function callsBlock(calls) {
  if (!calls.length) return html`<span style="font-size: 12.5px; color: var(--tx3)">No calls to the site's own servers during this step.</span>`;
  return html`<div style="display: flex; flex-direction: column; gap: 6px">${calls.map((c) => html`<div>
<div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap">${badge(c.method)}${badge(c.status == null ? 'failed' : c.status, c.status == null || c.status >= 400 ? 'fail' : '')}
<span class="mono" style="font-size: 12px; overflow-wrap: anywhere; flex: 1; min-width: 0">${c.url}</span><span class="mono" style="font-size: 11px; color: var(--tx3)">${c.ms == null ? '' : `${c.ms} ms`}</span></div>
${c.error ? html`<div style="font-size: 12px; color: var(--fail)">${c.error}</div>` : ''}
${c.request_body || c.response_body ? html`<details><summary style="font-size: 11.5px; color: var(--tx2); cursor: pointer">what was sent and answered</summary>
${c.request_body ? html`<div class="lbl" style="margin-top: 6px">Sent</div><pre class="mono" style="font-size: 11px; white-space: pre-wrap; overflow-wrap: anywhere; margin: 2px 0">${pretty(c.request_body)}</pre>` : ''}
${c.response_body ? html`<div class="lbl" style="margin-top: 6px">Answered</div><pre class="mono" style="font-size: 11px; white-space: pre-wrap; overflow-wrap: anywhere; margin: 2px 0">${pretty(c.response_body)}</pre>` : ''}</details>` : ''}</div>`)}</div>`;
}

function detail(t, sess, s) {
  const f = stepFacts(sess, s);
  const line = f.line;
  const now = replay(sess.state, s.seq);
  const changed = line && line.fields ? Object.entries(line.fields) : [];
  const everything = Object.entries(now.fields);
  const storage = line && line.storage ? Object.entries(line.storage) : [];
  return html`<div style="display: flex; flex-direction: column; gap: 14px; min-width: 0">
<div style="display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap"><b class="mono" style="font-size: 13px">Step ${s.seq}</b><span class="mono" style="font-size: 11.5px; color: var(--tx3)">row ${s.row} · ${s.action}</span>
<span style="font-weight: 650; overflow-wrap: anywhere">${s.name || s.action}</span></div>
${f.warns.map((w) => html`<div class="bn bn-warn" role="status"><div style="display: flex; gap: 11px"><span style="color: var(--warn); display: inline-flex">${icon('warn', 16)}</span><span>${w.text}. A switched-off field is filled in by the site, so this means that did not happen.</span></div></div>`)}
${section('Console', f.group.console.length, consoleBlock(f.group.console))}
${section('Server calls', f.group.calls.length, callsBlock(f.group.calls))}
${line ? section(line.full ? `Fields on this page (first look at ${line.url ? line.url.replace(/^https?:\/\/[^/]+/, '').split('?')[0] || '/' : 'the page'})` : 'Fields that changed in this step', changed.length,
    changed.length ? fieldsTable(changed, true) : html`<span style="font-size: 12.5px; color: var(--tx3)">No field changed in this step.</span>`) : ''}
${storage.length ? section(line.full ? 'Storage' : 'Storage that changed', storage.length, html`<div style="display: flex; flex-direction: column; gap: 4px">${storage.map(([k, v]) => html`<div><span class="mono" style="font-size: 11.5px; color: var(--tx2)">${k}</span>
<div class="mono" style="font-size: 11.5px; overflow-wrap: anywhere; white-space: pre-wrap">${String(v).slice(0, 400)}</div></div>`)}</div>`) : ''}
${now.messages.length ? section('Messages showing on the page', now.messages.length, html`<div style="display: flex; flex-direction: column; gap: 3px">${now.messages.map((m) => html`<div class="mono" style="font-size: 12px; color: var(--fail); overflow-wrap: anywhere">${m}</div>`)}</div>`) : ''}
${line ? html`<div><button class="lnk" style="font-size: 12.5px" data-act="results-session-all">${t.sessionAll ? 'Hide every field' : `Show every field as it stood after this step (${everything.length})`}</button>
${t.sessionAll ? html`<div style="margin-top: 8px">${fieldsTable(everything, true)}</div>` : ''}</div>` : html`<span style="font-size: 12.5px; color: var(--tx3)">The page could not be read after this step (it was closing, or a dialog was open).</span>`}
</div>`;
}

export function sessionCard(t, test) {
  const sess = t.session;
  if (!sess) return '';
  const head = html`<div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap"><span class="ttl" style="font-size: 16px">Session, step by step</span>
<span style="font-size: 12px; color: var(--tx3)">what the page, its console and its server calls held at each step</span></div>`;
  if (!sess.has.console && !sess.has.network && !sess.has.state) {
    return html`<section class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 8px">${head}
<span style="font-size: 12.5px; color: var(--tx2)">This test did not record its session: it ran before that was added, or <span class="mono">capture:</span> is switched off in config.yaml.</span></section>`;
  }
  const steps = test.steps || [];
  const shown = t.sessionQuiet ? steps.filter((s) => stepFacts(sess, s).notable) : steps;
  const pick = steps.find((s) => s.seq === t.sessionStep)
    || steps.find((s) => s.status === 'FAILED') || steps.find((s) => stepFacts(sess, s).warns.length) || steps[0];
  const withWarnings = steps.filter((s) => stepFacts(sess, s).warns.length).length;
  return html`<section class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 12px">${head}
${withWarnings ? html`<div class="bn bn-warn" role="status"><div style="display: flex; gap: 11px"><span style="color: var(--warn); display: inline-flex">${icon('warn', 16)}</span>
<span>${withWarnings} step${withWarnings === 1 ? '' : 's'} saw a switched-off field with nothing in it. Those steps are marked ⚠.</span></div></div>` : ''}
${!sess.has.bodies ? html`<span style="font-size: 12px; color: var(--tx3)">What the calls sent and answered was not recorded for this test (<span class="mono">capture.bodies</span>).</span>` : ''}
${sess.traces.length ? html`<div style="font-size: 12.5px; color: var(--tx2)">Browser trace: ${sess.traces.map((p) => html`<a class="lnk" href="${runFileUrl(t.runId, p, true)}">${p.split('/').pop()}</a> `)}· open it with <span class="mono">python -m playwright show-trace trace.zip</span></div>` : ''}
<div class="rsplit" style="display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 16px; align-items: start">
<div style="display: flex; flex-direction: column; gap: 2px; max-height: 70vh; overflow: auto">
<label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--tx2); padding: 0 6px 6px"><input type="checkbox" class="cb" ${t.sessionQuiet ? html`checked` : ''} data-change="results-session-quiet"> Only steps with something to look at</label>
${shown.map((s) => stepRow(sess, s, pick && s.seq === pick.seq))}
${shown.length ? '' : html`<span style="font-size: 12.5px; color: var(--tx3); padding: 6px">Nothing stands out in this test.</span>`}</div>
${pick ? detail(t, sess, pick) : ''}</div></section>`;
}
