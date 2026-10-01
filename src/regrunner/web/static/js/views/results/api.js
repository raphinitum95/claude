// Thin wrappers over /api/results/* (dev/plan/CONTRACT.md; the batch/run/compare list endpoints stay /api/batches,
// /api/runs - CONTRACT.md "Runs and batches stay under /api/runs, /api/batches").
import { api } from '../../api.js';

const enc = encodeURIComponent;

export const batches = () => api('/api/batches');
export const runs = () => api('/api/runs');
export const batchPage = (id) => api(`/api/results/batches/${enc(id)}`);
export const rerunFailed = (id) => api(`/api/results/batches/${enc(id)}/rerun-failed`, { method: 'POST' });
export const testPage = (runId, testId) => api(`/api/results/runs/${enc(runId)}/tests/${enc(testId)}`);
export const session = (runId, testId) => api(`/api/results/runs/${enc(runId)}/tests/${enc(testId)}/session`);
export const compare = (workbooks, n) => api(`/api/results/compare?workbooks=${enc(workbooks.join(','))}&n=${enc(n)}`);
