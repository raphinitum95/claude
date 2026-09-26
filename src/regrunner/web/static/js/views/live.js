// Screen 2: a run in progress (also the frozen view of a run that was interrupted or crashed).
import { html, raw, cx } from '../util.js';
import { icon, pill, STATUS } from '../icons.js';
import { num, pct, dur, clock, timeOf, plural } from '../fmt.js';
import { runFileUrl } from '../api.js';
import { counts, timing, lanes as laneList, pending as pendingList, finished as finishedList, strip, groupReview, reviewOfRun, reviewTotal, varsOfRun } from '../runstate.js';
import { banner, btn } from './shell.js';
import { browserOf, browserChip } from '../browsers.js';

export const baseName = (p) => String(p || '').split(/[\\/]/).pop().replace(/\.(xlsx|xlsm)$/i, '');
export const SHOTS = { every_step: 'Every step', on_failure: 'Failures only', off: 'No screenshots' };

export function envChip(env) {
  const prod = env === 'PROD';
  return html`<span class="chip mono ${prod ? '' : 'chip-acc'}" ${prod ? raw('style="color: var(--fail); border-color: var(--fail-line); background: var(--fail-soft)"') : ''}>${env || '–'}</span>`;
}

export function paramChips(run, meta) {
  const p = run.params || (meta && meta.params) || {};
  const started = run.startedMs ? timeOf(new Date(run.startedMs).toISOString()) : '';
  return html`${envChip(run.environment)}
${browserChip(browserOf(run, meta))}
<span class="chip">${icon('cpu', 14)} ${run.workers} worker${run.workers === 1 ? '' : 's'}</span>
<span class="chip">${icon(run.headless ? 'eyeoff' : 'eye', 14)} ${run.headless ? 'Headless' : 'Headed'}</span>
${p.screenshots ? html`<span class="chip">${icon('camera', 14)} ${SHOTS[p.screenshots] || p.screenshots}</span>` : ''}
${p.pdf ? html`<span class="chip">${icon('file', 14)} PDF</span>` : ''}
${p.harvest ? html`<span class="chip">${icon('target', 14)} Harvesting selectors</span>` : ''}
${started ? html`<span class="chip mono">${icon('clock', 14)} started ${started}</span>` : ''}`;
}

/** The other runs on the same workers (a run started with several workbooks, or one that joined a run in progress): each opens that run. */
export function sharesStrip(shares) {
  if (!shares || !shares.length) return '';
  return html`<div id="shares" style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; color: var(--tx2)"><span class="lbl">Sharing workers with</span>
${shares.map((x) => html`<button class="chip" data-key="share-${x.run_id}" data-act="open-run" data-id="${x.run_id}" title="${x.run_id}" style="cursor: pointer; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">${x.workbook}</button>`)}
<span>the workers split between the runs</span></div>`;
}

/** Banners that belong to a run (crash, interruption, cancelling, lost connection). */
export function runBanners(S, run, meta) {
  const v = S.view;
  const out = [];
  if (v.conn === 'reconnecting') {
    out.push(banner('acc', 'wifi', html`<b>Reconnecting…</b> The page replays the event stream from the start, so nothing is missed.`));
  }
  const cancelAt = meta && meta.cancel_requested_at ? Date.parse(meta.cancel_requested_at) : v.cancelAtMs;
  if (cancelAt && run.status === 'RUNNING') {
    const grace = (meta && meta.cancel_grace_s) || 45;
    const left = Math.max(0, grace - (S.now - cancelAt) / 1000);
    out.push(banner('warn', 'stop', html`<b>Cancelling…</b> Each running test finishes its current step, and pending tests will not start.`, '',
      html`<div class="bar" style="height: 5px; background: var(--warn-soft)"><div style="width: ${Math.round(100 * (1 - left / grace))}%; background: var(--warn)"></div></div>
<div class="mono" style="font-size: 11px; color: var(--tx2); margin-top: 6px">${left > 0 ? html`forced stop in ${Math.ceil(left)} s` : 'stopping now: closing the browsers'}</div>`));
  }
  for (const ask of Object.values(run.asks || {})) {
    if (run.status !== 'RUNNING') break;
    const left = Math.max(0, Math.ceil((ask.untilMs - S.now) / 1000));
    const busy = S.view.askBusy && S.view.askBusy[ask.id];
    const typed = (S.view.askText && S.view.askText[ask.id]) || '';
    if (ask.kind === 'captcha') {                                  // no typing: solve it in the browser window, the test carries on by itself
      out.push(banner('warn', 'shield', html`<b>Captcha detected</b> in ${ask.test}. ${ask.question}`, '',
        html`<div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap">${ask.mode === 'ui'
          ? html`<button class="btn btn-sm ${busy ? 'busy' : ''}" data-act="ask-skip" data-ask="${ask.id}" ${busy ? raw('disabled') : ''}>Skip: fail this test</button>` : ''}
<span class="mono" style="font-size: 11.5px; color: var(--tx2)">${left} s left · other tests keep running${ask.mode === 'ui' ? '' : ' · this run was started from a terminal'}</span></div>`));
      continue;
    }
    out.push(banner('acc', 'key', html`<b>Waiting for you.</b> ${ask.test}: ${ask.question}`, '',
      ask.mode === 'ui'
        ? html`<div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap"><input id="ask-${ask.id}" class="fld" style="max-width: 320px" type="${ask.secret ? 'password' : 'text'}" autocomplete="off" spellcheck="false"
placeholder="${ask.secret ? 'Type it here (hidden)' : 'Type your answer'}" aria-label="${ask.question}" value="${typed}" data-input="ask-text" data-ask="${ask.id}" data-enter="ask-send">
<button class="btn btn-pri btn-sm ${busy ? 'busy' : ''}" data-act="ask-send" data-ask="${ask.id}" ${busy ? raw('disabled') : ''}>${busy ? 'Sending…' : 'Send answer'}</button>
<span class="mono" style="font-size: 11.5px; color: var(--tx2)">${left} s left · other tests keep running</span></div>`
        : html`<div class="mono" style="font-size: 11.5px; color: var(--tx2)">This run was started from a terminal: answer there. ${left} s left.</div>`));
  }
  const pause = run.paused;
  if (pause && run.status === 'RUNNING' && S.now < pause.until) {
    const left = Math.max(0, Math.ceil((pause.until - S.now) / 1000));
    out.push(banner('warn', 'clock', html`<b>Paused: the site blocked this machine.</b> Waiting ${left} s, then ${pause.test} starts again (retry ${pause.attempt} of ${pause.of}). Nothing is stuck.`,
      '', html`<div class="mono" style="font-size: 11.5px; color: var(--tx2); overflow-wrap: anywhere">${pause.reason}</div>`));
  }
  if (run.status === 'ERROR') {
    const lines = String(run.error || '').split('\n').filter(Boolean).slice(-2);
    out.push(banner('fail', 'warn', html`<b>The runner stopped before finishing</b>${run.exitCode != null ? html` (exit code ${run.exitCode})` : ''}. Steps so far are kept.`,
      html`${btn('Show full log', 'show-log', { id: run.id })}${btn('Run doctor', 'doctor', { cls: 'btn-ghost' })}`,
      lines.length ? html`<div class="code" style="font-size: 11px; line-height: 1.55; padding: 9px 11px; white-space: pre-wrap">${lines.join('\n')}</div>` : ''));
  }
  if (meta && meta.status === 'INTERRUPTED') {
    out.push(banner('warn', 'warn', html`<b>This run stopped responding.</b> No events for 90 s and the process is gone, so it was likely killed or the computer slept.`,
      html`${S.view.mode === 'live' ? '' : btn('Replay events', 'replay-events', { id: run.id })}${btn('Build report from what ran', 'build-report', { id: run.id })}`));
  }
  return out;
}

export function runHeaderActions(S, run, meta, active) {
  return html`<div style="margin-left: auto; display: flex; gap: 10px; padding-top: 4px; flex-wrap: wrap">
${meta && meta.command ? html`<button class="btn" data-act="copy-run-cmd">${icon('term', 16)} Copy command</button>` : ''}
${active ? html`<button class="btn btn-dng" data-act="cancel-run" data-id="${run.id}" ${S.view.cancelAtMs || (meta && meta.cancel_requested_at) ? raw('disabled') : ''}>${icon('stop', 16)} Cancel run</button>` : ''}</div>`;
}

function shotBox(run, t, big) {
  if (!t.shot) return html`<div class="shot"><div class="wait">Waiting for the first screenshot…</div></div>`;
  const bad = t.fails.some((f) => f.seq === t.shotStep);
  const b = t.box;
  return html`<div class="shot zoom" data-act="zoom" data-src="${runFileUrl(run.id, t.shot)}" role="button" tabindex="0" aria-label="Enlarge the latest screenshot of ${t.id}">
<img src="${runFileUrl(run.id, t.shot)}" alt="Latest screenshot of ${t.id}">
${b ? html`<div class="hl ${bad ? 'bad' : ''}" style="left: ${b.x}%; top: ${b.y}%; width: ${b.w}%; height: ${b.h}%"></div>` : ''}
<div class="cap">live · after step ${t.shotStep}</div></div>`;
}

function laneCard(S, run, t) {
  const c = t.fails.length;
  const last = c ? t.fails[c - 1] : null;
  const elapsed = t.startedMs ? (S.now - t.startedMs) / 1000 : 0;
  return html`<article class="card" data-key="${t.id}" style="padding: 16px; display: flex; flex-direction: column; gap: 14px; border-color: ${c ? 'var(--fail-line)' : 'var(--line)'}">
<div style="display: flex; align-items: center; gap: 10px">
<span class="mono" style="height: 24px; padding: 0 8px; border-radius: 7px; background: var(--acc-soft); color: var(--acc); border: 1px solid var(--acc-line); font-size: 11px; font-weight: 600; display: inline-flex; align-items: center">W${t.worker ?? '?'}</span>
<div style="min-width: 0; flex: 1"><div style="font-weight: 650; font-size: 15.5px">${t.id}</div>
<div class="mono" style="font-size: 11px; color: var(--tx3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis">${t.scenario} · ${t.description}</div></div>${pill('RUNNING')}</div>
${shotBox(run, t)}
<div style="display: flex; align-items: baseline; gap: 9px; min-width: 0">
<span class="mono" style="font-size: 11px; color: var(--acc); font-weight: 600; letter-spacing: .06em">${t.step ? t.step.action : ''}</span>
<span style="font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">${t.step ? t.step.name : 'Starting…'}</span></div>
<div><div class="ticks" style="background: ${strip(t.done, t.total, t.fails.map((f) => f.seq), true)}"></div>
<div class="mono" style="display: flex; justify-content: space-between; margin-top: 9px; font-size: 12px; color: var(--tx2)"><span>step ${t.done} / ${t.total}</span><b style="color: var(--tx)">${pct(t.done, t.total)}%</b></div></div>
${last ? html`<div style="display: flex; gap: 9px; align-items: flex-start; padding: 10px 12px; border-radius: 10px; background: var(--fail-soft); border: 1px solid var(--fail-line); font-size: 12.5px">
<span style="color: var(--fail); display: inline-flex; margin-top: 1px">${icon('failc', 16)}</span>
<span style="color: var(--tx); overflow-wrap: anywhere">Step ${last.seq} failed: ${last.name || last.action}${last.error ? ' · ' + last.error.split('\n')[0] : ''}</span></div>` : ''}
<div class="mono" style="display: flex; gap: 14px; font-size: 11.5px; color: var(--tx3); padding-top: 12px; border-top: 1px solid var(--line)">
<span>${dur(elapsed)} elapsed</span><span style="color: ${c ? 'var(--fail)' : 'var(--tx3)'}">${plural(c, 'failed step')}</span></div></article>`;
}

function statCard(iconHtml, tint, label, big, sub, subColor, border) {
  return html`<div class="card" style="padding: 18px 20px; display: flex; align-items: center; gap: 16px; ${border ? 'border-color: var(--acc-line)' : ''}">
<div style="width: 46px; height: 46px; border-radius: 13px; background: ${tint[0]}; color: ${tint[1]}; display: grid; place-items: center; flex: none">${iconHtml}</div>
<div style="min-width: 0"><div class="lbl">${label}</div><div class="disp" style="font-size: 34px; font-weight: 700; line-height: 1.1">${big}</div>
<div style="font-size: 12px; color: ${subColor || 'var(--tx2)'}">${sub}</div></div></div>`;
}

function reviewCard(S, run) {
  const groups = groupReview(reviewOfRun(run));
  const shown = S.view.showAllReview ? groups : groups.slice(0, 5);
  return html`<section class="card" style="padding: 20px 22px 6px">
<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 4px"><h2 class="ttl" style="font-size: 17px">Things to review</h2>
<span class="pill ${groups.length ? 'p-warn' : 'p-pend'}" style="margin-left: auto">${num(reviewTotal(groups))}</span></div>
<p style="font-size: 12px; color: var(--tx3); margin-bottom: 8px">Console errors, page exceptions and HTTP 4xx/5xx are tagged to a step and never change pass or fail.</p>
${groups.length ? '' : html`<div style="padding: 12px 0 14px; border-top: 1px solid var(--line); color: var(--tx2); font-size: 12.5px">Nothing so far.</div>`}
${shown.map((r) => html`<div style="display: flex; gap: 11px; padding: 13px 0; border-top: 1px solid var(--line)" data-key="${r.key}"><div style="flex: 1; min-width: 0">
<div style="display: flex; align-items: center; gap: 8px"><span class="tag ${r.tone === 'warn' ? 'tag-warn' : r.tone === 'fail' ? 'tag-fail' : ''}">${r.cat}</span><span class="mono" style="font-size: 11px; color: var(--tx3)">${r.where}</span></div>
<div style="font-size: 12.5px; color: var(--tx2); margin-top: 6px; overflow-wrap: anywhere">${r.msg}</div></div>
<span class="mono" style="font-size: 12px; color: var(--tx2); height: 22px; padding: 0 8px; border-radius: 7px; background: var(--surface2); border: 1px solid var(--line2); display: inline-flex; align-items: center">×${r.count}</span></div>`)}
${groups.length > 5 ? html`<div style="padding: 10px 0 14px; border-top: 1px solid var(--line)"><button class="lnk" data-act="toggle-review">${S.view.showAllReview ? 'Show fewer' : `Show all ${groups.length}`}</button></div>` : ''}
</section>`;
}

/** "Values set": the parameters steps filled in (a quote number, a policy number...), so what a test produced is visible without opening the sheet. */
export function variablesCard(rows) {
  if (!rows.length) return '';
  return html`<section class="card" style="padding: 20px 22px 8px" data-key="variables">
<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 4px"><h2 class="ttl" style="font-size: 17px">Values set</h2>
<span class="pill p-pend" style="margin-left: auto">${rows.length}</span></div>
<p style="font-size: 12px; color: var(--tx3); margin-bottom: 8px">Parameters a step filled in. Later tests of the run read them.</p>
${rows.map((v) => html`<div style="padding: 11px 0; border-top: 1px solid var(--line)" data-key="var-${v.test}-${v.name}">
<div style="display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap"><b class="mono" style="font-size: 12.5px">${v.name}</b>
<span class="mono" style="font-size: 12.5px; padding: 1px 8px; border-radius: 7px; background: var(--acc-soft); color: var(--acc); overflow-wrap: anywhere; user-select: all">${v.stored ?? v.value}</span></div>
<div class="mono" style="font-size: 11px; color: var(--tx3); margin-top: 4px; overflow-wrap: anywhere">${v.test} · ${v.by_hand ? 'entered by hand' : `step ${v.seq} · row ${v.row}${v.step ? ' · ' + v.step : ''}`}${v.cell ? ' · ' + v.cell : ''}</div></div>`)}
</section>`;
}

function logCard(run, live) {
  const rows = run.log.slice(-8).reverse();
  return html`<section class="card" style="padding: 20px 22px 18px">
<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px"><h2 class="ttl" style="font-size: 17px">Event log</h2>
${live ? html`<span class="chip mono" style="margin-left: auto"><span class="dot pulse" style="color: var(--acc)"></span>live</span>` : ''}</div>
<div class="code" style="padding: 8px 12px; font-size: 11.5px; line-height: 1.5">
${rows.map((e, i) => html`<div style="display: grid; grid-template-columns: 58px 46px minmax(0, 1fr); gap: 8px; padding: 6px 0; ${i ? 'border-top: 1px solid var(--line)' : ''}">
<span style="color: var(--tx3)">${timeOf(e.t)}</span><b style="color: ${e.c}">${e.k}</b><span style="color: var(--tx); overflow-wrap: anywhere">${e.m}</span></div>`)}</div></section>`;
}

export function liveView(S) {
  const v = S.view;
  const run = v.run;
  const meta = v.meta;
  // A run with no run_finished event is only "running" while its process is: the server says when it is gone.
  const active = run.status === 'RUNNING' && !(meta && meta.active === false);
  const c = counts(run);
  const tm = timing(run, S.now, active);
  const lanes = laneList(run);
  const queue = pendingList(run);
  const done = finishedList(run);
  const passedTests = done.filter((t) => t.status === 'PASSED');
  const failedIds = [...new Set(run.order.map((id) => run.tests[id]).filter((t) => t.failed).map((t) => t.id))];
  const ringPct = c.total ? (100 * c.done) / c.total : 0;
  const stateLabel = active ? pill('RUNNING') : pill(run.status === 'RUNNING' ? (meta && meta.status) || 'INTERRUPTED' : run.status);
  const leftEmpty = !queue.length && !done.length && lanes.length > 0;   // nothing to list on the left: give review and log a column each
  const seg = (n, style) => (n > 0 ? html`<div style="flex: ${n} 1 0; ${style}"></div>` : '');
  return html`<div class="page">
<div style="display: flex; align-items: flex-start; gap: 24px; flex-wrap: wrap">
<div style="display: flex; flex-direction: column; gap: 12px; min-width: 0">
<div class="eyebrow" style="display: flex; align-items: center; gap: 10px"><span>Run</span><span class="mono" style="color: var(--tx2); letter-spacing: .04em">${run.id}</span></div>
<h1 class="disp" style="font-size: 38px; line-height: 1.05; font-weight: 700; margin: 0; overflow-wrap: anywhere">${baseName(run.workbook) || run.id}</h1>
<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">${paramChips(run, meta)}</div>
${sharesStrip(run.shares.length ? run.shares : (meta && meta.shares))}</div>
${runHeaderActions(S, run, meta, active)}</div>
${runBanners(S, run, meta)}
<section class="card" style="padding: 28px; display: grid; grid-template-columns: 200px minmax(0, 1fr) 250px; gap: 34px; align-items: center; box-shadow: var(--glow); border-color: var(--acc-line)">
<div style="position: relative; width: 200px; height: 200px">
<div class="ring" style="position: absolute; inset: 0; background: conic-gradient(${c.failedSteps && !active ? 'var(--warn)' : 'var(--acc)'} 0 ${ringPct.toFixed(2)}%, var(--track) 0)"></div>
<div style="position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center">
<div class="disp" style="font-size: 58px; font-weight: 700; line-height: 1">${Math.round(ringPct)}<span style="font-size: 26px; color: var(--tx2)">%</span></div>
<div class="mono" style="font-size: 10.5px; letter-spacing: .16em; color: var(--tx3); text-transform: uppercase; margin-top: 8px">of all steps</div></div></div>
<div style="display: flex; flex-direction: column; gap: 18px; min-width: 0">
<div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">${stateLabel}
<span style="color: var(--tx2); font-size: 13.5px">${c.failedSteps ? `${plural(c.failedSteps, 'step')} ${c.failedSteps === 1 ? 'has' : 'have'} failed. The test carries on; only Global!QuitBreakOnFailure=Y would stop it.` : active ? 'Tests run in parallel across workers.' : 'The run is no longer active.'}</span></div>
<div class="disp" style="font-size: 38px; font-weight: 650; line-height: 1.05">${num(c.done)} <span style="color: var(--tx3); font-weight: 500">of ${num(c.total)} steps</span></div>
<div><div style="display: flex; gap: 3px; height: 14px; border-radius: 5px; overflow: hidden">
${seg(c.passedSteps, 'background: var(--pass)')}${c.failedSteps ? html`<div style="flex: 0 0 5px; background: var(--fail)"></div>` : ''}${seg(c.inFlight, 'background: var(--acc); opacity: .55')}${seg(c.queuedSteps, 'background: var(--tick)')}</div>
<div style="display: flex; gap: 22px; margin-top: 12px; font-size: 12.5px; color: var(--tx2); flex-wrap: wrap">
<span style="display: inline-flex; align-items: center; gap: 7px"><span class="dot" style="color: var(--pass)"></span>Passed <b class="mono" style="color: var(--tx)">${num(c.passedSteps)}</b></span>
<span style="display: inline-flex; align-items: center; gap: 7px"><span class="dot" style="color: var(--fail)"></span>Failed <b class="mono" style="color: var(--tx)">${num(c.failedSteps)}</b></span>
<span style="display: inline-flex; align-items: center; gap: 7px"><span class="dot" style="color: var(--acc)"></span>In flight <b class="mono" style="color: var(--tx)">${num(c.inFlight)}</b></span>
<span style="display: inline-flex; align-items: center; gap: 7px"><span class="dot" style="color: var(--pend)"></span>Queued <b class="mono" style="color: var(--tx)">${num(c.queuedSteps)}</b></span></div></div></div>
<div style="display: flex; flex-direction: column; border-left: 1px solid var(--line); padding-left: 28px">
<div style="padding-bottom: 14px"><div class="lbl">Elapsed</div><div class="mono" style="font-size: 30px; font-weight: 500; line-height: 1.2">${clock(tm.elapsed)}</div></div>
<div style="padding: 14px 0; border-top: 1px solid var(--line)"><div class="lbl">Estimated remaining</div><div class="mono" style="font-size: 20px; font-weight: 500; line-height: 1.3">${active && tm.remaining != null ? '≈ ' + dur(Math.round(tm.remaining / 5) * 5 || tm.remaining) : '–'}</div></div>
<div style="padding-top: 14px; border-top: 1px solid var(--line); display: flex; gap: 22px"><div><div class="lbl">Speed</div><div class="mono" style="font-size: 14px">${tm.speed ? tm.speed.toFixed(1) : '–'} steps/s</div></div>
<div><div class="lbl">Workers</div><div class="mono" style="font-size: 14px">${lanes.length} of ${run.workers} busy</div>${(run.shares || []).length ? html`<div class="mono" style="font-size: 11px; color: var(--tx3)">shared with ${plural(run.shares.length, 'run')}</div>` : ''}</div></div></div></section>
<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px">
${statCard(html`<span class="dot ${active ? 'pulse' : ''}" style="width: 12px; height: 12px"></span>`, ['var(--acc-soft)', 'var(--acc)'], 'Running', c.running, lanes.length ? 'on ' + lanes.map((t) => 'W' + t.worker).join(', ') : 'nothing running', '', true)}
${statCard(icon('dashed', 24), ['var(--pend-soft)', 'var(--tx2)'], 'Pending', c.pending, `${num(c.queuedSteps)} steps waiting`)}
${statCard(icon('passc', 24), ['var(--pass-soft)', 'var(--pass)'], 'Passed', c.passedTests, passedTests.length ? `${num(passedTests.reduce((a, t) => a + t.total, 0))} steps · ${dur(passedTests.reduce((a, t) => a + (t.duration || 0), 0))}` : 'no test finished yet')}
${statCard(icon('failc', 24), ['var(--fail-soft)', 'var(--fail)'], 'Failed', c.failedTests + c.otherTests, c.failedSteps ? `${plural(c.failedSteps, 'failing step')} in ${failedIds.join(', ')}` : 'no failing steps', c.failedSteps ? 'var(--fail)' : '')}</div>
${lanes.length ? html`<div><div style="display: flex; align-items: center; gap: 12px; margin-bottom: 14px"><h2 class="ttl">Now running</h2>
<span class="chip mono">${lanes.length} of ${run.workers} workers</span><span style="font-size: 12.5px; color: var(--tx3); margin-left: auto">Screenshots update after every step</span></div>
<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr)); gap: 20px">${lanes.map((t) => laneCard(S, run, t))}</div></div>` : ''}
<div class="split" style="--side-w: ${leftEmpty ? 'minmax(0, 1fr)' : '400px'}">
${leftEmpty ? '' : html`<div class="col">
${queue.length ? html`<section class="card" style="padding: 20px 0 4px"><div style="display: flex; align-items: center; gap: 12px; padding: 0 22px 14px"><h2 class="ttl">Up next</h2><span class="pill p-pend">${queue.length} pending</span>
<span style="font-size: 12.5px; color: var(--tx3); margin-left: auto">Longest first · starts when a worker frees up</span></div>
${queue.map((q, i) => html`<div data-key="${q.id}" style="display: flex; align-items: center; gap: 16px; padding: 14px 22px; border-top: 1px solid var(--line)">
<div class="mono" style="width: 28px; height: 28px; flex: none; border-radius: 50%; border: 1.5px dashed var(--pend); color: var(--tx2); display: grid; place-items: center; font-size: 11.5px">${i + 1}</div>
<div style="flex: 1; min-width: 0"><div style="display: flex; gap: 9px; align-items: baseline"><b class="mono" style="font-size: 13.5px">${q.id}</b><span class="mono" style="font-size: 11px; color: var(--tx3)">${q.scenario}</span></div>
<div style="font-size: 12.5px; color: var(--tx2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis">${q.description}</div>
${(q.waitsFor || []).some((d) => !run.tests[d] || ['QUEUED', 'RUNNING'].includes(run.tests[d].status)) ? html`<div class="mono" style="font-size: 11px; color: var(--warn)">waits for ${q.waitsFor.filter((d) => !run.tests[d] || ['QUEUED', 'RUNNING'].includes(run.tests[d].status)).join(', ')}</div>` : ''}</div>
<div class="mono" style="font-size: 12.5px; color: var(--tx2)">${q.total} steps</div>${pill('QUEUED')}</div>`)}</section>` : ''}
${done.length ? html`<section class="card" style="padding: 20px 0 4px"><div style="display: flex; align-items: center; gap: 12px; padding: 0 22px 14px"><h2 class="ttl">Finished</h2>
${c.passedTests ? html`<span class="pill p-pass">${c.passedTests} passed</span>` : ''}${c.failedTests + c.otherTests ? html`<span class="pill p-fail">${c.failedTests + c.otherTests} failed</span>` : ''}</div>
${done.map((f) => html`<div data-key="${f.id}" style="display: flex; align-items: center; gap: 16px; padding: 14px 22px; border-top: 1px solid var(--line)">
<span style="color: ${STATUS[f.status] ? STATUS[f.status].color : 'var(--tx2)'}; display: inline-flex">${icon(f.status === 'PASSED' ? 'passc' : f.status === 'FAILED' ? 'failc' : 'warn', 22)}</span>
<div style="width: 210px; min-width: 0"><div style="display: flex; gap: 9px; align-items: baseline"><b class="mono" style="font-size: 13.5px">${f.id}</b><span class="mono" style="font-size: 11px; color: var(--tx3)">${f.scenario}</span></div>
<div style="font-size: 12.5px; color: var(--tx2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis">${f.description}</div></div>
<div class="ticks" style="flex: 1; background: ${strip(f.done, f.total, f.fails.map((x) => x.seq), false)}"></div>
<div class="mono" style="font-size: 12px; color: var(--tx2); width: 62px; text-align: right">${f.done - f.failed}/${f.total}</div>
<div class="mono" style="font-size: 12px; color: var(--tx2); width: 58px; text-align: right">${dur(f.duration)}</div>${pill(f.status)}</div>`)}</section>` : ''}
${!queue.length && !done.length && !lanes.length ? html`<section class="card" style="padding: 26px; color: var(--tx2)">${v.loading ? 'Loading the run…' : 'Waiting for the first event…'}</section>` : ''}</div>`}
${leftEmpty ? html`${variablesCard(varsOfRun(run))}${reviewCard(S, run)}${logCard(run, active)}` : html`<div class="col">${variablesCard(varsOfRun(run))}${reviewCard(S, run)}${logCard(run, active)}</div>`}</div></div>`;
}
