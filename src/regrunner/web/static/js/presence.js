// Tells the server this window is open (every few seconds) and when it closes, so the double-click launcher can stop
// QA Regression, and close its terminal window, once the last UI window is closed (`serve --exit-when-closed`).
// Without that flag the server just ignores these calls.
const HEADER = { 'X-Requested-With': 'regrunner', 'Content-Type': 'application/json' };
const HELLO_EVERY_MS = 10000;
const page = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Math.random()).slice(2);

function tell(path) {
  // keepalive lets the goodbye leave even though the window is closing
  fetch(path, { method: 'POST', headers: HEADER, body: JSON.stringify({ page }), keepalive: true }).catch(() => {});
}

export function startPresence() {
  tell('/api/ui/hello');
  setInterval(() => tell('/api/ui/hello'), HELLO_EVERY_MS);
  window.addEventListener('pagehide', () => tell('/api/ui/goodbye'));
  window.addEventListener('pageshow', (ev) => { if (ev.persisted) tell('/api/ui/hello'); });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') tell('/api/ui/hello'); });
}
