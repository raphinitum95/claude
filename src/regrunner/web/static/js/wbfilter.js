// Searching, ordering and paging the "In workbooks/" list.  Pure functions: no DOM, no state, so a folder of 100
// workbooks costs nothing (the list API only returns name / size / date; a workbook is read when it is picked).
import { esc, raw } from './util.js';

export const PAGE = 6;           // rows shown before "Show more"
export const MORE = 10;          // rows each "Show more" adds

export const searchTerms = (q) => String(q || '').toLowerCase().split(/\s+/).filter(Boolean);
const spaced = (s) => s.toLowerCase().replace(/[_\-.()[\]]+/g, ' ');

/** Every typed word must appear in the name, as typed or with _ - . read as spaces ("uat aem" finds UAT_AEM_...).
 *  Best matches first (name starts with the first word, then a word starts with it, then anywhere), then the chosen
 *  order: the list arrives newest first, or 'name' for A-Z with numbers ordered naturally (v2 before v10). */
export function filterWorkbooks(list, query, sort) {
  const terms = searchTerms(query);
  const scored = [];
  list.forEach((w, i) => {
    const lower = w.name.toLowerCase();
    const words = spaced(w.name);
    let rank = 0;
    if (terms.length) {
      if (!terms.every((t) => lower.includes(t) || words.includes(t))) return;
      rank = lower.startsWith(terms[0]) ? 0 : (' ' + words).includes(' ' + terms[0]) ? 1 : 2;
    }
    scored.push({ w, rank, i });
  });
  const byName = (a, b) => a.w.name.localeCompare(b.w.name, undefined, { numeric: true, sensitivity: 'base' });
  scored.sort((a, b) => a.rank - b.rank || (sort === 'name' ? byName(a, b) : a.i - b.i));
  return scored.map((s) => s.w);
}

/** The name with the searched words wrapped in <mark>.  Returns markup that is already escaped. */
export function highlight(name, query) {
  const terms = searchTerms(query);
  if (!terms.length) return name;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
  return raw(name.split(re).map((seg, i) => (i % 2 ? `<mark class="hl">${esc(seg)}</mark>` : esc(seg))).join(''));
}

/** Workbooks that were actually run lately, newest first: the usual ones stay one click away in a long folder. */
export function recentlyRun(runs, workbooks, limit = 4) {
  const have = new Set(workbooks.map((w) => w.name));
  const out = [];
  for (const r of runs || []) {
    const name = String(r.workbook || '').split(/[\\/]/).pop();
    if (have.has(name) && !out.includes(name)) out.push(name);
    if (out.length >= limit) break;
  }
  return out;
}
