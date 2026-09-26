// Thin fetch/XHR wrappers.  Every state-changing request carries the header the server requires, which is
// what stops a different website in the same browser from driving this interface.
const HEADER = { 'X-Requested-With': 'regrunner' };

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.kind = (data && data.kind) || '';
    this.data = data || {};
  }
}

export async function api(path, { method = 'GET', body, signal } = {}) {
  const headers = { ...HEADER };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal });
  } catch (err) {
    if (err && err.name === 'AbortError') throw err;
    throw new ApiError('Cannot reach the regrunner server. Is it still running?', 0, { kind: 'offline' });
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok) throw new ApiError((data && data.error) || `Request failed (${res.status})`, res.status, data);
  return data;
}

/** Multipart upload with progress and cancel (fetch cannot report upload progress). */
export function upload(path, file, { onProgress, signal } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', path);
    xhr.setRequestHeader('X-Requested-With', HEADER['X-Requested-With']);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError((data && data.error) || `Upload failed (${xhr.status})`, xhr.status, data));
    };
    xhr.onerror = () => reject(new ApiError('Cannot reach the regrunner server. Is it still running?', 0, { kind: 'offline' }));
    xhr.onabort = () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
    if (signal) signal.addEventListener('abort', () => xhr.abort());
    const form = new FormData();
    form.append('file', file, file.name);
    xhr.send(form);
  });
}

export const runFileUrl = (runId, path, download = false) =>
  `/runs/${encodeURIComponent(runId)}/files/${path.split('/').map(encodeURIComponent).join('/')}${download ? '?download=1' : ''}`;

export function openSocket(runId, { onEvents, onClose }) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/runs/${encodeURIComponent(runId)}`);
  let closedByServer = false;
  ws.onmessage = (m) => {
    let data;
    try { data = JSON.parse(m.data); } catch (e) { return; }
    if (data.events && data.events.length) onEvents(data.events);
    if (data.closed) closedByServer = true;
  };
  ws.onclose = () => onClose(closedByServer);
  ws.onerror = () => { /* onclose follows */ };
  return ws;
}
