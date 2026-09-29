// The Results tab's top-level pieces: the shared header and the screen dispatcher (history / batch / test / compare).
import { html } from '../../util.js';
import { icon } from '../../icons.js';
import { headerShell } from '../shell.js';
import { resultsRail, historyView } from './history.js';
import { batchView } from './batch.js';
import { testView } from './test.js';
import { compareView } from './compare.js';

export function resultsHeader() {
  const dark = document.documentElement.getAttribute('data-theme') !== 'light';
  return headerShell('Results', '',
    html`<button class="icon-btn" data-act="theme" aria-label="Switch between light and dark">${icon(dark ? 'sun' : 'moon', 16)}</button>`);
}

/** ``runPage``: main.js's run screen (the one Run shows), for a single run opened from here: it stays in this tab. */
export function resultsTabView(S, runPage) {
  const screen = S.results.screen;
  const main = screen === 'run' && runPage ? runPage() : screen === 'batch' ? batchView(S) : screen === 'test' ? testView(S)
    : screen === 'compare' ? compareView(S) : historyView(S);
  return html`<div class="app-body">${resultsRail(S)}<main class="main scroll" style="overflow: auto">${main}</main></div>`;
}
