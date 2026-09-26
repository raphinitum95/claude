// Thin wrappers over /api/build/* (dev/plan/CONTRACT.md section 3).
import { api } from '../../api.js';

const enc = encodeURIComponent;

export const keywords = () => api('/api/build/keywords');
export const newWorkbook = (body) => api('/api/build/workbooks', { method: 'POST', body });
export const model = (name, env) => api(`/api/build/workbooks/${enc(name)}${env ? `?env=${enc(env)}` : ''}`);
export const status = (name) => api(`/api/build/workbooks/${enc(name)}/status`);
export const edit = (name, ops, version, env) => api(`/api/build/workbooks/${enc(name)}/edit${env ? `?env=${enc(env)}` : ''}`, { method: 'POST', body: { ops, version } });
export const undo = (name, env) => api(`/api/build/workbooks/${enc(name)}/undo${env ? `?env=${enc(env)}` : ''}`, { method: 'POST' });
export const redo = (name, env) => api(`/api/build/workbooks/${enc(name)}/redo${env ? `?env=${enc(env)}` : ''}`, { method: 'POST' });
export const save = (name, force = false) => api(`/api/build/workbooks/${enc(name)}/save`, { method: 'POST', body: { force } });
export const reload = (name, env) => api(`/api/build/workbooks/${enc(name)}/reload${env ? `?env=${enc(env)}` : ''}`, { method: 'POST' });
export const history = (name) => api(`/api/build/workbooks/${enc(name)}/history`);
export const diff = (name, against = 'disk') => api(`/api/build/workbooks/${enc(name)}/diff?against=${enc(against)}`);
export const restore = (name, id, env) => api(`/api/build/workbooks/${enc(name)}/restore${env ? `?env=${enc(env)}` : ''}`, { method: 'POST', body: { id } });
export const sheet = (name, sheetName) => api(`/api/build/workbooks/${enc(name)}/sheets/${enc(sheetName)}`);
