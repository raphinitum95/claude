// A small DOM patcher: render the whole view as a string, then update the live DOM in place.
// Elements keep their identity (focus, scroll position, playing animations, loaded images) while only
// what changed is touched.  Elements carrying data-key are matched by key, everything else by position.

const keyOf = (n) => (n.nodeType === 1 ? n.getAttribute('data-key') : null);
const sameKind = (a, b) => a.nodeType === b.nodeType && (a.nodeType !== 1 || a.tagName === b.tagName);

function syncAttrs(node, want) {
  for (const { name, value } of Array.from(want.attributes)) {
    if (node.getAttribute(name) !== value) node.setAttribute(name, value);
  }
  for (const { name } of Array.from(node.attributes)) {
    if (!want.hasAttribute(name)) node.removeAttribute(name);
  }
}

function patchNode(node, want) {
  if (node.nodeType !== 1) {
    if (node.nodeValue !== want.nodeValue) node.nodeValue = want.nodeValue;
    return;
  }
  syncAttrs(node, want);
  const tag = node.tagName;
  if (tag === 'INPUT') {
    const type = (want.getAttribute('type') || 'text').toLowerCase();
    if (type === 'file') return;
    if (type === 'checkbox' || type === 'radio') node.checked = want.hasAttribute('checked');
    else if (node !== document.activeElement && node.value !== (want.getAttribute('value') || '')) node.value = want.getAttribute('value') || '';
    return;
  }
  if (tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (node.hasAttribute('data-morph-skip')) return;
  patchChildren(node, want);
}

function patchChildren(parent, from) {
  const want = Array.from(from.childNodes);
  const have = Array.from(parent.childNodes);
  const byKey = new Map();
  const loose = [];
  for (const n of have) {
    const k = keyOf(n);
    if (k !== null) byKey.set(k, n); else loose.push(n);
  }
  let li = 0;
  want.forEach((w, idx) => {
    const k = keyOf(w);
    let node = null;
    if (k !== null) {
      node = byKey.get(k) || null;
      if (node && !sameKind(node, w)) node = null;
    } else if (li < loose.length && sameKind(loose[li], w)) {
      node = loose[li++];
    }
    if (node) patchNode(node, w); else node = document.importNode(w, true);
    const ref = parent.childNodes[idx] || null;
    if (node !== ref) parent.insertBefore(node, ref);
  });
  while (parent.childNodes.length > want.length) parent.removeChild(parent.lastChild);
}

/** Replace the contents of `root` with `markup`, reusing existing nodes wherever possible. */
export function morph(root, markup) {
  const tpl = document.createElement('template');
  tpl.innerHTML = String(markup);
  patchChildren(root, tpl.content);
}
