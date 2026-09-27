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

// ---- templates (P11) --------------------------------------------------------------------------------------------
export const templates = () => api('/api/build/templates');
export const saveTemplate = (body) => api('/api/build/templates', { method: 'POST', body });
export const deleteTemplate = (name) => api(`/api/build/templates/${enc(name)}`, { method: 'DELETE' });
export const templateMapping = (name, workbook) => api(`/api/build/templates/${enc(name)}/mapping?workbook=${enc(workbook)}`);
export const insertTemplate = (name, body, env) => api(`/api/build/workbooks/${enc(name)}/templates/insert${env ? `?env=${enc(env)}` : ''}`, { method: 'POST', body });

// ---- duplicate / find & replace / merge (P11) --------------------------------------------------------------------
export const findPreview = (name, pairs) => api(`/api/build/workbooks/${enc(name)}/find`, { method: 'POST', body: { pairs } });
export const findApply = (name, hits, version, env) => api(`/api/build/workbooks/${enc(name)}/find/apply${env ? `?env=${enc(env)}` : ''}`, { method: 'POST', body: { hits, version } });
export const duplicateCandidates = (name, newName) => api(`/api/build/workbooks/${enc(name)}/duplicate-candidates?newName=${enc(newName)}`);
export const merge = (name, picks, version, env) => api(`/api/build/workbooks/${enc(name)}/merge${env ? `?env=${enc(env)}` : ''}`, { method: 'POST', body: { picks, version } });
