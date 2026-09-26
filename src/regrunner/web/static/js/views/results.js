// Screen 3: a finished run, built from results.json.
import { html, raw, cx } from '../util.js';
import { icon, pill, STATUS } from '../icons.js';
import { num, dur, timeOf, plural } from '../fmt.js';
import { runFileUrl } from '../api.js';
import { strip, groupReview, reviewTotal, finalVars } from '../runstate.js';
import { banner, btn } from './shell.js';
import { baseName, envChip, runBanners, SHOTS, variablesCard, sharesStrip } from './live.js';
import { browserOf, browserChip } from '../browsers.js';

const BAD = new Set(['FAILED', 'ERROR']);

/** Make invisible characters visible: the usual cause of an Exact_Match mismatch. */
export function visible(text) {
  return String(text ?? '').replace(/\u00a0/g, '⍽').replace(/\t/g, '→').replace(/\r/g, '').replace(/\n/g, '↵');
}

/** Split `actual` around the part that differs from `expected` (common prefix / suffix are kept as is). */
export function diffParts(expected, actual) {
  expected = String(expected ?? ''); actual = String(actual ?? '');
  let a = 0;
  while (a < expected.length && a < actual.length && expected[a] === actual[a]) a++;
  let b = 0;
  while (b < expected.length - a && b < actual.length - a && expected[expected.length - 1 - b] === actual[actual.length - 1 - b]) b++;
  return { head: actual.slice(0, a), mid: actual.slice(a, actual.length - b), tail: actual.slice(actual.length - b) };
}

export function paramsOf(meta, results) {
  const p = (meta && meta.params) || {};
  const cfg = (results && results.config) || {};
  return {
    environment: p.environment || (results && results.environment) || '',
    workers: p.workers || (results && results.workers) || 1,
    screenshots: p.screenshots || (cfg.screenshots && cfg.screenshots.mode) || '',
    retries: p.retries ?? (cfg.behaviour && cfg.behaviour.retries) ?? 0,
    seed: p.seed ?? (results && results.seed),
    headless: p.headless ?? (cfg.runner ? cfg.runner.headless : true),
    browser: browserOf(results, meta),
    waits: p.waits || (cfg.waits && cfg.waits.mode) || 'smart',
    pdf: p.pdf ?? false, harvest: p.harvest ?? (cfg.selectors && cfg.selectors.harvest) ?? false, report: p.report !== false,
  };
}

function failedStepCard(S, runId, s) {
  const cmp = s.comparison && (s.expected !== '' || s.actual !== '');
  const d = diffParts(s.expected, s.actual);
  const origin = s.fallback_used ? html`<span class="tag tag-warn">legacy XPath fallback</span>`
    : s.locator_origin === 'map' || s.locator_origin === 'auto' ? html`<span class="tag tag-acc">selectors.yaml</span>`
    : s.locator_origin === 'sheet' ? html`<span class="tag tag-acc">sheet Locator column</span>`
    : s.locator ? html`<span class="tag">workbook locator</span>` : '';
  const shot = s.screenshot
    ? html`<div class="shot zoom" data-act="zoom" data-src="${runFileUrl(runId, s.screenshot)}" role="button" tabindex="0" aria-label="Enlarge the screenshot after step ${s.seq}">
<img src="${runFileUrl(runId, s.screenshot)}" alt="Screenshot after step ${s.seq}" loading="lazy" decoding="async">
${s.box ? html`<div class="hl bad" style="left: ${s.box.x}%; top: ${s.box.y}%; width: ${s.box.w}%; height: ${s.box.h}%"></div>` : ''}
<div class="cap">after step ${s.seq}</div></div>${s.screenshot_full ? html`<a class="lnk" style="font-size: 12.5px; margin-top: 6px; display: inline-block" href="${runFileUrl(runId, s.screenshot_full)}" target="_blank" rel="noopener">Whole page (scroll)</a>` : ''}`
    : html`<div class="shot"><div class="wait">No screenshot for this step</div></div>`;
  return html`<div style="display: grid; grid-template-columns: minmax(0, 1fr) 232px; gap: 20px; padding: 18px; border-radius: 14px; background: var(--surface); border: 1px solid var(--line2); margin-top: 14px" data-key="step-${s.seq}">
<div style="display: flex; flex-direction: column; gap: 13px; min-width: 0">
<div style="display: flex; align-items: center; gap: 9px; flex-wrap: wrap">${pill('FAILED')}<b class="mono" style="font-size: 13px">Step ${s.seq}</b><span class="mono" style="font-size: 11.5px; color: var(--tx3)">row ${s.row} · ${s.action}</span></div>
<div style="font-weight: 650; font-size: 16px; overflow-wrap: anywhere">${s.name || s.action}</div>
<div class="kv" style="grid-template-columns: 78px 1fr">
${cmp ? html`<span>Expected</span><span class="mono" style="justify-self: start; padding: 2px 9px; border-radius: 7px; background: var(--pass-soft); color: var(--pass); overflow-wrap: anywhere; white-space: pre-wrap">${visible(s.expected) || '(empty)'}</span>
<span>Actual</span><span class="mono" style="justify-self: start; padding: 2px 9px; border-radius: 7px; background: var(--fail-soft); color: var(--fail); overflow-wrap: anywhere; white-space: pre-wrap">${s.actual === '' ? '(empty)' : html`${visible(d.head)}<b style="text-decoration: underline">${visible(d.mid)}</b>${visible(d.tail)}`}</span>
<span>Compare</span><span>${s.comparison === 'exact' ? 'Exact match: text must equal the expected value' : 'Contains: the actual text must include the expected value'}</span>` : ''}
${s.error ? html`<span>Error</span><span style="overflow-wrap: anywhere">${s.error}</span>` : ''}
${s.locator ? html`<span>Locator</span><span style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap"><span class="mono" style="font-size: 12px; overflow-wrap: anywhere">${s.locator}</span>${origin}</span>` : ''}</div>
${why(s)}
${(s.notes || []).slice(0, 3).map((n) => html`<div style="font-size: 12.5px; color: var(--tx2)">${n}</div>`)}</div>${shot}</div>`;
}

// Why a step failed: what the engine read from the page when it did (results.json `diagnosis`), and the browser's whole error behind the one line above.
function why(s) {
  const lines = (s.diagnosis && s.diagnosis.summary) || [];
  const dom = Object.entries((s.diagnosis && s.diagnosis.dom) || {}).map(([kind, rel]) => `${kind}: ${rel}`);
  if (!lines.length && !s.detail && !dom.length) return '';
  return html`<div style="display: flex; flex-direction: column; gap: 6px">
<div style="font-size: 11px; letter-spacing: .05em; text-transform: uppercase; color: var(--tx3)">Why it failed</div>
${lines.map((l) => html`<div style="font-size: 13px; overflow-wrap: anywhere">${l}</div>`)}
${s.detail || dom.length ? html`<details class="more"><summary>The browser's whole error and saved HTML</summary>
${s.detail ? html`<div class="code" style="font-size: 11px; line-height: 1.55; white-space: pre-wrap; max-height: 220px; overflow: auto; margin-top: 8px">${s.detail}</div>` : ''}
${dom.map((d) => html`<div class="mono" style="font-size: 11.5px; color: var(--tx2); margin-top: 6px; overflow-wrap: anywhere">saved HTML · ${d}</div>`)}</details>` : ''}</div>`;
}

function testRows(S, runId, r) {
  const v = S.view;
  const ordered = r.tests.slice().sort((a, b) => (BAD.has(b.status) - BAD.has(a.status)) || (b.duration_s - a.duration_s));
  const retries = paramsOf(v.meta, r).retries;
  return ordered.map((t) => {
    const bad = BAD.has(t.status) || t.failed > 0;
    const failedSteps = (t.steps || []).filter((s) => s.status === 'FAILED');
    const open = v.expanded[t.id] ?? bad;
    const executed = (t.steps || []).length;
    const stateGlyph = t.status === 'PASSED' ? ['passc', 'var(--pass)'] : t.status === 'FAILED' ? ['failc', 'var(--fail)'] : ['warn', STATUS[t.status] ? STATUS[t.status].color : 'var(--warn)'];
    const shownFails = v.showAllFails[t.id] ? failedSteps : failedSteps.slice(0, 5);
    return html`<div style="border-top: 1px solid var(--line)" data-key="${t.id}">
<${raw(bad ? 'button' : 'div')} class="trow" ${bad ? html`data-act="expand-test" data-id="${t.id}" aria-expanded="${String(open)}"` : ''} style="width: 100%; display: grid; grid-template-columns: 22px 168px minmax(0, 1fr) 84px 60px; gap: 16px; align-items: center; padding: 15px 22px; background: ${bad ? 'var(--fail-soft)' : 'transparent'}; text-align: left">
<span style="color: ${stateGlyph[1]}; display: inline-flex">${icon(stateGlyph[0], 22)}</span>
<div style="min-width: 0"><div style="display: flex; gap: 8px; align-items: baseline"><b class="mono" style="font-size: 13.5px">${t.id}</b><span class="mono" style="font-size: 10.5px; color: var(--tx3)">${t.scenario}</span></div>
<div style="font-size: 12.5px; color: var(--tx2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis">${t.description}</div></div>
<div class="ticks tall" style="background: ${strip(executed, t.total_steps || executed, failedSteps.map((s) => s.seq), false)}"></div>
<div class="mono" style="font-size: 12.5px; text-align: right; color: ${bad ? 'var(--fail)' : 'var(--tx2)'}">${executed - failedSteps.length} / ${t.total_steps || executed}</div>
<div class="mono" style="font-size: 12.5px; text-align: right; color: var(--tx2)">${dur(t.duration_s)}</div></${raw(bad ? 'button' : 'div')}>
${bad && open ? html`<div style="padding: 4px 22px 22px; background: var(--surface2); border-top: 1px solid var(--line)">
<div style="display: flex; align-items: center; gap: 12px; padding: 14px 0">
<span class="lbl" style="color: var(--fail)">${failedSteps.length ? `Failed steps · ${failedSteps.length}` : t.status}</span>
<span class="mono" style="font-size: 11.5px; color: var(--tx3)">attempt ${t.attempt || 1} of ${retries + 1}</span>
${v.files && v.files.report_html ? html`<a class="lnk" style="margin-left: auto; display: inline-flex; align-items: center; gap: 6px" href="${runFileUrl(runId, 'report.html')}#t-${encodeURIComponent(t.id)}" target="_blank" rel="noopener">Open in the report ${icon('external', 13)}</a>` : ''}</div>
${t.error ? banner(t.status === 'ERROR' ? 'fail' : 'warn', 'warn', t.error) : ''}
${shownFails.map((s) => failedStepCard(S, runId, s))}
${failedSteps.length > 5 ? html`<div style="margin-top: 14px"><button class="lnk" data-act="toggle-fails" data-id="${t.id}">${v.showAllFails[t.id] ? 'Show fewer' : `Show all ${failedSteps.length} failed steps`}</button></div>` : ''}</div>` : ''}</div>`;
  });
}

function evidenceRow(iconName, name, text, right) {
  return html`<div style="display: flex; align-items: center; gap: 12px; padding: 12px 0; border-top: 1px solid var(--line)">
<span style="color: var(--acc); display: inline-flex">${icon(iconName, 18)}</span>
<div style="flex: 1; min-width: 0"><div class="mono" style="font-size: 12.5px; font-weight: 600">${name}</div><div style="font-size: 12px; color: var(--tx2)">${text}</div></div>${right}</div>`;
}

export function resultsView(S) {
  const v = S.view;
  const r = v.results;
  const meta = v.meta || {};
  const files = v.files || {};
  const id = v.id;
  const tests = r.tests;
  const n = tests.length;
  const by = (s) => tests.filter((t) => t.status === s).length;
  const passedT = by('PASSED'), failedT = by('FAILED'), errT = by('ERROR');
  const otherT = n - passedT - failedT - errT;
  const steps = tests.reduce((a, t) => a + (t.steps || []).length, 0);
  const failedSteps = tests.reduce((a, t) => a + (t.failed || 0), 0);
  const skipped = tests.reduce((a, t) => a + (t.skipped || 0), 0);
  const p = paramsOf(meta, r);
  const seq = tests.reduce((a, t) => a + (t.duration_s || 0), 0);
  const speedup = r.duration_s > 0 ? seq / r.duration_s : 1;
  const finishedT = tests.filter((t) => ['PASSED', 'FAILED', 'ERROR'].includes(t.status)).length;
  const headline = { PASSED: n === 1 ? 'The test passed' : `All ${n} tests passed`, FAILED: `${failedT + errT} of ${n} test${n === 1 ? '' : 's'} failed`,
                     CANCELLED: `Run cancelled · ${finishedT} of ${n} tests finished`, INTERRUPTED: `Run interrupted · ${finishedT} of ${n} tests finished`,
                     ERROR: 'The runner stopped before finishing' }[r.status] || `Run ${String(r.status).toLowerCase()}`;
  const groups = groupReview(tests.flatMap((t) => t.review || []));
  const shownGroups = v.showAllReview ? groups : groups.slice(0, 5);
  const failedIds = tests.filter((t) => BAD.has(t.status) || t.failed).map((t) => t.id);
  const pctA = n ? (100 * passedT) / n : 0, pctB = n ? (100 * (passedT + failedT + errT)) / n : 0;
  const shots = files.screenshots || 0;
  const pseudo = { id, status: r.status === 'ERROR' ? 'ERROR' : 'DONE', error: meta.error || '', exitCode: meta.exit_code ?? null };
  return html`<div class="page">
<div style="display: flex; align-items: flex-start; gap: 24px; flex-wrap: wrap">
<div style="display: flex; flex-direction: column; gap: 12px; min-width: 0">
<div class="eyebrow" style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap"><span>Run</span><span class="mono" style="color: var(--tx2); letter-spacing: .04em">${id}</span>${pill(r.status, r.status === 'FAILED' ? 'Failed' : undefined)}</div>
<h1 class="disp" style="font-size: 46px; line-height: 1.04; font-weight: 700; margin: 0">${headline}</h1>
<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--tx2); font-size: 13.5px">
<span>${baseName(r.workbook)}.xlsx</span><span style="color: var(--tx3)">·</span>${envChip(r.environment)}${browserChip(browserOf(r, meta))}
${r.ended_at ? html`<span style="color: var(--tx3)">·</span><span class="mono">finished ${timeOf(r.ended_at)}</span>` : ''}<span style="color: var(--tx3)">·</span><span class="mono">${dur(r.duration_s)}</span></div>
${sharesStrip(meta.shares)}</div>
<div style="margin-left: auto; display: flex; gap: 10px; padding-top: 6px; flex-wrap: wrap">
${files.report_html ? html`<a class="btn btn-pri" href="${runFileUrl(id, 'report.html')}" target="_blank" rel="noopener">${icon('external', 16)} Open HTML report</a>` : html`<button class="btn btn-pri" data-act="build-report" data-id="${id}">${icon('filetext', 16)} Build HTML report</button>`}
${files.report_pdf ? html`<a class="btn" href="${runFileUrl(id, 'report.pdf', true)}">${icon('file', 16)} PDF</a>` : html`<button class="btn ${v.buildingPdf ? 'busy' : ''}" data-act="build-pdf" data-id="${id}">${icon('file', 16)} ${v.buildingPdf ? 'Building PDF…' : 'Build PDF'}</button>`}
${failedIds.length ? html`<button class="btn" data-act="rerun-failed">${icon('undo', 16)} Re-run ${failedIds.length} failed test${failedIds.length === 1 ? '' : 's'}</button>` : ''}
${meta.command ? html`<button class="btn" data-act="copy-run-cmd">${icon('term', 16)} Copy command</button>` : ''}</div></div>
${runBanners(S, pseudo, meta)}
${r.partial ? banner('warn', 'warn', html`<b>Rebuilt from the event log.</b> This run stopped early; tests that were mid-flight are marked INTERRUPTED and repeat counts of review items restart at 1.`) : ''}
<div style="display: grid; grid-template-columns: 1.05fr 1.15fr 1fr; gap: 20px" class="stats3">
<section class="card" style="padding: 22px; display: flex; align-items: center; gap: 24px">
<div style="position: relative; width: 132px; height: 132px; flex: none">
<div class="ring" style="position: absolute; inset: 0; background: conic-gradient(var(--pass) 0 ${pctA.toFixed(3)}%, var(--fail) 0 ${pctB.toFixed(3)}%, var(--warn) 0)"></div>
<div style="position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center"><div class="disp" style="font-size: 34px; font-weight: 700; line-height: 1">${passedT}/${n}</div>
<div class="mono" style="font-size: 9.5px; letter-spacing: .14em; color: var(--tx3); text-transform: uppercase; margin-top: 5px">tests</div></div></div>
<div style="display: flex; flex-direction: column; gap: 9px; flex: 1; font-size: 13px">
${[['Passed', passedT, 'var(--pass)'], ['Failed', failedT, 'var(--fail)'], ['Error', errT, 'var(--fail)'], ['Cancelled', otherT, 'var(--warn)']].map(([l, c, col]) => html`<div style="display: flex; align-items: center; gap: 9px"><span class="dot" style="color: ${c ? col : 'var(--tx3)'}"></span><span style="flex: 1; color: ${c ? 'var(--tx2)' : 'var(--tx3)'}">${l}</span><b class="mono" style="color: ${c ? 'var(--tx)' : 'var(--tx3)'}">${c}</b></div>`)}</div></section>
<section class="card" style="padding: 22px; display: flex; flex-direction: column; gap: 14px; justify-content: center"><div class="lbl">Steps</div>
<div class="disp" style="font-size: 40px; font-weight: 650; line-height: 1">${num(steps - failedSteps)} <span style="font-size: 18px; color: var(--tx3); font-weight: 500">of ${num(steps)} passed</span></div>
<div style="display: flex; gap: 3px; height: 12px; border-radius: 5px; overflow: hidden"><div style="flex: ${Math.max(steps - failedSteps, 0)} 1 0; background: var(--pass)"></div>${failedSteps ? html`<div style="flex: 0 0 5px; background: var(--fail)"></div>` : ''}</div>
<div style="display: flex; gap: 20px; font-size: 12.5px; color: var(--tx2); flex-wrap: wrap"><span>Pass rate <b class="mono" style="color: var(--tx)">${steps ? (100 * (steps - failedSteps) / steps).toFixed(1) : '–'}%</b></span>
<span>Failed <b class="mono" style="color: ${failedSteps ? 'var(--fail)' : 'var(--tx)'}">${failedSteps}</b></span><span>Skipped <b class="mono" style="color: var(--tx)">${skipped}</b></span></div></section>
<section class="card" style="padding: 22px; display: flex; flex-direction: column; gap: 14px; justify-content: center"><div class="lbl">Wall time</div>
<div class="disp" style="font-size: 40px; font-weight: 650; line-height: 1">${dur(r.duration_s)}</div>
<div style="font-size: 12.5px; color: var(--tx2); line-height: 1.55">${n > 1 && r.workers > 1
    ? html`Running the ${n} tests one by one would have taken <b class="mono" style="color: var(--tx)">${dur(seq)}</b>. ${r.workers} workers made it <b class="mono" style="color: var(--acc)">${speedup.toFixed(1)}×</b> faster.`
    : n > 1 ? 'The tests ran one after another on a single worker.' : 'A single test, so there was nothing to run in parallel.'}</div></section></div>
<div class="split" style="--side-w: 372px">
<section class="card" style="padding: 20px 0 0; overflow: hidden; min-width: 0">
<div style="display: flex; align-items: center; gap: 12px; padding: 0 22px 16px; flex-wrap: wrap"><h2 class="ttl">Tests</h2><span style="font-size: 12.5px; color: var(--tx3)">Failed first, then longest</span>
<span class="chip" style="margin-left: auto">${p.screenshots === 'off' ? 'Screenshots were off' : p.screenshots === 'on_failure' ? 'Screenshots on failures' : 'Every step has a screenshot'}</span></div>
<div style="display: grid; grid-template-columns: 22px 168px minmax(0, 1fr) 84px 60px; gap: 16px; padding: 9px 22px; border-top: 1px solid var(--line); background: var(--surface2)">
<span></span><span class="lbl">Test</span><span class="lbl">Steps (each tick is a step)</span><span class="lbl" style="text-align: right">Passed</span><span class="lbl" style="text-align: right">Time</span></div>
${testRows(S, id, r)}</section>
<div class="col">
<section class="card" style="padding: 20px 22px"><h2 class="ttl" style="font-size: 17px; margin-bottom: 14px">Run parameters</h2>
<div class="kv" style="grid-template-columns: 104px 1fr; font-size: 12.5px">
<span>Environment</span><span class="mono">${p.environment}</span><span>Workers</span><span class="mono">${p.workers}</span>
<span>Screenshots</span><span class="mono">${p.screenshots}</span><span>Retries</span><span class="mono">${p.retries}</span>
<span>Seed</span><span class="mono">${p.seed == null ? 'random, frozen per test' : p.seed}</span>
<span>Browser</span><span class="mono" id="run-browser">${p.browser.id === 'unknown' ? p.browser.text : `${p.browser.text}, ${p.headless ? 'headless' : 'headed'}`}</span><span>Waits</span><span class="mono">${p.waits}</span>
<span>Options</span><span style="display: flex; gap: 6px; flex-wrap: wrap">${p.pdf ? html`<span class="tag">--pdf</span>` : ''}${p.harvest ? html`<span class="tag">--harvest</span>` : ''}${!p.report ? html`<span class="tag">--no-report</span>` : ''}${!p.pdf && !p.harvest && p.report ? html`<span class="mono" style="color: var(--tx3)">none</span>` : ''}</span></div>
${p.browser.approximate ? html`<div style="font-size: 12px; color: var(--tx3); margin-top: 12px; line-height: 1.5">${p.browser.what}</div>` : p.browser.recorded === false ? html`<div style="font-size: 12px; color: var(--tx3); margin-top: 12px; line-height: 1.5">${p.browser.id === 'unknown' ? 'This run did not record which browser it used.' : 'This run did not record its browser, so this is what its saved settings select; the exact version is unknown.'}</div>` : ''}</section>
<section class="card" style="padding: 20px 22px 8px"><h2 class="ttl" style="font-size: 17px; margin-bottom: 8px">Evidence</h2>
${files.report_html ? evidenceRow('filetext', 'report.html', 'Self-contained evidence report', html`<a class="icon-btn" href="${runFileUrl(id, 'report.html')}" target="_blank" rel="noopener" aria-label="Open report.html">${icon('external', 16)}</a>`) : ''}
${files.report_pdf ? evidenceRow('file', 'report.pdf', 'The same report, printable', html`<a class="icon-btn" href="${runFileUrl(id, 'report.pdf', true)}" aria-label="Download report.pdf">${icon('download', 16)}</a>`) : ''}
${files.results ? evidenceRow('list', 'results.json', 'Every step, machine readable', html`<a class="icon-btn" href="${runFileUrl(id, 'results.json', true)}" aria-label="Download results.json">${icon('download', 16)}</a>`) : ''}
${files.workbook ? evidenceRow('grid', files.workbook, 'Copy of the workbook that ran', html`<a class="icon-btn" href="${runFileUrl(id, files.workbook, true)}" aria-label="Download the workbook copy">${icon('download', 16)}</a>`) : ''}
${shots ? evidenceRow('image', 'tests/', `${num(shots)} screenshots plus named captures`, html`<button class="icon-btn" data-act="reveal" aria-label="Show the screenshots folder">${icon('folder', 16)}</button>`) : ''}</section>
${variablesCard(tests.flatMap((t) => finalVars(t.variables).map((x) => ({ test: t.id, ...x }))))}
<section class="card" style="padding: 20px 22px 6px"><div style="display: flex; align-items: center; gap: 10px; margin-bottom: 6px"><h2 class="ttl" style="font-size: 17px">Things to review</h2><span class="pill ${groups.length ? 'p-warn' : 'p-pend'}" style="margin-left: auto">${num(reviewTotal(groups))}</span></div>
<p style="font-size: 12px; color: var(--tx3); margin-bottom: 6px">Never changes pass or fail.</p>
${groups.length ? '' : html`<div style="padding: 12px 0 14px; border-top: 1px solid var(--line); color: var(--tx2); font-size: 12.5px">Nothing to review.</div>`}
${shownGroups.map((g) => html`<div style="display: flex; gap: 11px; padding: 12px 0; border-top: 1px solid var(--line)" data-key="${g.key}"><div style="flex: 1; min-width: 0"><span class="tag ${g.tone === 'warn' ? 'tag-warn' : g.tone === 'fail' ? 'tag-fail' : ''}">${g.cat}</span>
<div style="font-size: 12.5px; color: var(--tx2); margin-top: 6px; overflow-wrap: anywhere">${g.msg}</div></div>
<span class="mono" style="font-size: 12px; color: var(--tx2); height: 22px; padding: 0 8px; border-radius: 7px; background: var(--surface2); border: 1px solid var(--line2); display: inline-flex; align-items: center">×${g.count}</span></div>`)}
${groups.length > 5 ? html`<div style="padding: 10px 0 14px; border-top: 1px solid var(--line)"><button class="lnk" data-act="toggle-review">${v.showAllReview ? 'Show fewer' : `Show all ${groups.length}`}</button></div>` : ''}</section>
${files.suggestions ? html`<section class="card" style="padding: 20px 22px; border-color: var(--acc-line)"><h2 class="ttl" style="font-size: 17px; margin-bottom: 6px">Next</h2>
<p style="font-size: 12.5px; color: var(--tx2)">Harvest was on, so stable locators were learned from the live pages.</p>
<button class="btn btn-pri" style="width: 100%; margin-top: 14px" data-act="selectors">${icon('target', 16)} Review and merge locators</button>
<div class="code" style="margin-top: 12px; font-size: 11.5px"><span style="color: var(--tx3)">$ </span>regrunner selectors apply ${id}</div>
<div style="font-size: 12px; color: var(--tx3); margin-top: 10px">Adds unique, agreed-on id / name / data-* locators to selectors.yaml. The workbook is never modified.</div></section>` : ''}</div></div></div>`;
}
