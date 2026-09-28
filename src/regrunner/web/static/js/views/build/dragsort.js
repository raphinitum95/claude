// Dragging in the test editor: step cards to a new place (between two cards, or onto a page in the test map strip), and the "selected" bar
// by its grip. Native drag and drop for the cards (a card is draggable="true"; the ticked ones move together when the dragged card is one of
// them); pointer events for the bar. Neither re-renders while dragging (the DOM patcher would replace what is being dragged): the drop
// marker and the bar's position are set on the elements directly, and one edit (move_steps) or one saved position happens on release.
import { S, rerender } from '../../state.js';
import { currentTest, moveSteps, rememberBulkPos, forgetBulkPos } from './actions.js';

let drag = null;                 // { rows: [...] } while a card is dragged
let marked = null;               // the element showing the drop marker

const inEditor = () => S.route.name === 'build' && S.build.screen === 'test' && S.build.ed.mode === 'cards';

function unmark() {
  if (marked) marked.classList.remove('drop-before', 'drop-after', 'drop-into');
  marked = null;
}

function mark(el, cls) {
  if (marked !== el || !el.classList.contains(cls)) { unmark(); el.classList.add(cls); marked = el; }
}

/** Where a drop on this card lands: before it (top half) or after it (bottom half). */
function sideOf(card, ev) {
  const r = card.getBoundingClientRect();
  return ev.clientY < r.top + r.height / 2 ? 'before' : 'after';
}

document.addEventListener('dragstart', (ev) => {
  const card = ev.target instanceof Element ? ev.target.closest('.scard[data-row]') : null;
  if (!card || !inEditor()) return;
  const row = Number(card.dataset.row);
  const multi = S.build.ed.multi;
  const rows = multi.includes(row) ? multi.slice() : [row];
  drag = { rows };
  ev.dataTransfer.effectAllowed = 'move';
  ev.dataTransfer.setData('text/plain', `rows:${rows.join(',')}`);
  card.classList.add('dragging');
});

document.addEventListener('dragover', (ev) => {
  if (!drag || !(ev.target instanceof Element)) return;
  const card = ev.target.closest('.scard[data-row]');
  const block = ev.target.closest('[data-block-title]');
  if (card && !drag.rows.includes(Number(card.dataset.row))) {
    ev.preventDefault();
    mark(card, sideOf(card, ev) === 'before' ? 'drop-before' : 'drop-after');
  } else if (block) {
    ev.preventDefault();
    mark(block, 'drop-into');
  } else unmark();
});

document.addEventListener('drop', (ev) => {
  if (!drag || !(ev.target instanceof Element)) return;
  const t = currentTest();
  const card = ev.target.closest('.scard[data-row]');
  const blockEl = ev.target.closest('[data-block-title]');
  const rows = drag.rows;
  unmark();
  if (!t) return;
  if (card && !rows.includes(Number(card.dataset.row))) {
    ev.preventDefault();
    const target = t.steps.find((s) => s.row === Number(card.dataset.row));
    if (!target) return;
    let before = target.row;
    if (sideOf(card, ev) === 'after') {
      const next = t.steps.find((s) => s.n > target.n && !rows.includes(s.row));
      before = next ? next.row : null;                     // (after the test's last step)
    }
    moveSteps(rows, before, target.block);
  } else if (blockEl) {
    ev.preventDefault();
    const title = blockEl.dataset.blockTitle;
    const b = t.blocks.find((x) => x.title === title);
    const next = b ? t.steps.find((s) => s.n === b.end + 1 && !rows.includes(s.row)) : null;
    moveSteps(rows, next ? next.row : null, title);        // onto a page: at its end
  }
});

document.addEventListener('dragend', () => {
  unmark();
  document.querySelectorAll('.scard.dragging').forEach((el) => el.classList.remove('dragging'));
  drag = null;
});

// ---- the "selected" bar's grip -------------------------------------------------------------------------------------------------------
let bar = null;                  // { el, dx, dy } while the bar is dragged

document.addEventListener('pointerdown', (ev) => {
  const grip = ev.target instanceof Element ? ev.target.closest('[data-bulk-grip]') : null;
  if (!grip || !inEditor()) return;
  const el = grip.closest('.bulk-bar');
  const r = el.getBoundingClientRect();
  bar = { el, dx: ev.clientX - r.left, dy: ev.clientY - r.top, moved: false };
  ev.preventDefault();
});

document.addEventListener('pointermove', (ev) => {
  if (!bar) return;
  const { el } = bar;
  const x = Math.min(Math.max(4, ev.clientX - bar.dx), window.innerWidth - el.offsetWidth - 4);
  const y = Math.min(Math.max(4, ev.clientY - bar.dy), window.innerHeight - el.offsetHeight - 4);
  Object.assign(el.style, { position: 'fixed', left: `${x}px`, top: `${y}px`, bottom: 'auto', transform: 'none' });
  bar.moved = true;
  bar.pos = { x: Math.round(x), y: Math.round(y) };
});

document.addEventListener('pointerup', () => {
  if (!bar) return;
  if (bar.moved) rememberBulkPos(bar.pos);
  bar = null;
  rerender();
});

document.addEventListener('dblclick', (ev) => {
  const grip = ev.target instanceof Element ? ev.target.closest('[data-bulk-grip]') : null;
  if (!grip) return;
  forgetBulkPos();
  rerender();
});
