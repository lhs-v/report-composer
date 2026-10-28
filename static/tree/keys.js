/* Keys: every change to the tree is an op. An op is applied by apply(), its inverse is pushed on the undo stack, and the
   tree re-renders through Tree.change (which animates and schedules the save). Nothing else touches nodes or order. */
window.Keys = (() => {
  const T = () => Tree.state, N = () => Tree.nodes();
  const toast = (...a) => window.Composer.toast(...a);
  const LIMIT = 200;
  const KIND = { summary: "요약", project: "프로젝트", claim: "주장", record: "기록", flow: "흐름", ledger: "장부", text: "내 글" };
  // what may live under what ("" = the top level); fixed kinds never change place or depth
  const CHILD_KINDS = { "": ["summary", "project", "text"], project: ["claim", "ledger", "text"], claim: ["record", "flow", "text"] };
  const FIXED = ["summary", "project"];
  const BODIED = ["claim", "text"]; // kinds whose body is one text: the only ones that split and merge
  const PAGEABLE = ["project", "claim"];

  const parentOf = id => { for (const [n, , p] of Tree.walk()) if (n.id === id) return p; return null; };
  const siblings = parent => parent ? N()[parent].children : T().draft.root;
  const canLive = (kind, parentId) => (CHILD_KINDS[parentId ? N()[parentId].kind : ""] || []).includes(kind);
  const order = () => [...Tree.walk(T().draft.root, 0, null, false)].map(([n]) => n.id).filter(id => !T().rows.get(id)?.classList.contains("hidden"));
  const clone = v => JSON.parse(JSON.stringify(v));
  const newId = () => "n-" + Math.random().toString(36).slice(2, 10);

  let undo = [], redo = [], tp = null, busy = false, bound = false;

  // ---- apply: the only code that mutates nodes ----
  function apply(o) {
    const n = N()[o.id];
    switch (o.type) {
      case "toggle": if (n) n.on = o.to; break;
      case "fold": if (n) n.folded = o.to; break;
      case "page": if (n) n.page = o.to; break;
      case "stale": if (n) n.stale = o.to; break;
      case "text": if (n) n[o.field] = o.to; break;
      case "move": {
        const from = siblings(o.from.parent), i = from.indexOf(o.id); if (i >= 0) from.splice(i, 1);
        siblings(o.to.parent).splice(o.to.index, 0, o.id); break;
      }
      case "split": {
        if (!n) break;
        const sib = siblings(o.parent);
        n.text = n.text.slice(0, o.at).trimEnd(); n.stale = true;
        N()[o.newId] = { ...clone(n), id: o.newId, title: o.title2, text: o.text2, children: [], stale: true, page: false, folded: false,
          marks: n.kind === "text" ? [...(n.marks || [])] : (n.marks || []).filter(m => m !== "noref") }; // a typed text still has no source
        sib.splice(sib.indexOf(o.id) + 1, 0, o.newId); break;
      }
      case "merge": {
        const keep = N()[o.keepId], gone = N()[o.goneId]; if (!keep || !gone) break;
        keep.text = [keep.text, gone.text].filter(Boolean).join("\n\n");
        keep.children.push(...gone.children); keep.stale = true;
        const sib = siblings(parentOf(o.goneId)); sib.splice(sib.indexOf(o.goneId), 1); delete N()[o.goneId]; break;
      }
      case "newText":
        N()[o.id] = { id: o.id, kind: "text", title: "", text: "", on: true, folded: false, page: false, stale: false,
          src: { week: T().draft.week, project: null, chapter: null, record: null }, marks: ["noref"], tier: "main", children: [] };
        siblings(o.parent).splice(o.index, 0, o.id); break;
      case "insertNode": N()[o.id] = clone(o.node); siblings(o.parent).splice(o.index, 0, o.id); break;
      case "removeNode": { const sib = siblings(o.parent), i = sib.indexOf(o.id); if (i >= 0) sib.splice(i, 1); delete N()[o.id]; break; }
      case "restoreNode": N()[o.id] = clone(o.node); siblings(o.parent).splice(o.index, 0, o.id); break;
      case "restoreBody": if (n) { n.text = o.text; n.children = [...o.children]; n.stale = o.stale; } break;
    }
  }

  // inverse of one forward op, as a list of ops to apply in order
  function invert(o) {
    switch (o.type) {
      case "toggle": case "fold": case "page": case "stale": case "text": case "move": return [{ ...o, from: o.to, to: o.from }];
      case "split": return [{ type: "removeNode", id: o.newId, parent: o.parent },
                            { type: "restoreBody", id: o.id, text: o.snapshot.text, children: o.snapshot.children, stale: o.snapshot.stale }];
      case "merge": return [{ type: "restoreNode", id: o.goneId, node: o.snapshot.node, parent: o.snapshot.parent, index: o.snapshot.index },
                            { type: "restoreBody", id: o.keepId, text: o.snapshot.keepText, children: o.snapshot.keepChildren, stale: o.snapshot.keepStale }];
      case "newText": case "insertNode": return [{ type: "removeNode", id: o.id, parent: o.parent }];
      default: return [];
    }
  }

  // the forward ops one user action stands for: snapshots, "stale" on the parent claim, and unfolding a folded host
  function plan(o) {
    const pre = [], seen = new Set();
    const stale = id => { const p = id && N()[id]; if (p && p.kind === "claim" && !p.stale && !seen.has("s" + id)) { seen.add("s" + id); pre.push({ type: "stale", id, from: false, to: true }); } };
    const reveal = id => { const h = id && N()[id]; if (h && h.folded && !seen.has("f" + id)) { seen.add("f" + id); pre.push({ type: "fold", id, from: true, to: false }); } };
    switch (o.type) {
      case "toggle": stale(parentOf(o.id)); break;
      case "split": { const n = N()[o.id]; o.parent = parentOf(o.id); o.snapshot = { text: n.text, children: [...n.children], stale: n.stale }; stale(o.parent); break; }
      case "merge": {
        const gone = N()[o.goneId], keep = N()[o.keepId], p = parentOf(o.goneId);
        o.snapshot = { node: clone(gone), parent: p, index: siblings(p).indexOf(o.goneId), keepText: keep.text, keepChildren: [...keep.children], keepStale: keep.stale };
        stale(p); break;
      }
      case "move": if (o.from.parent !== o.to.parent) { stale(o.from.parent); stale(o.to.parent); } reveal(o.to.parent); break;
      case "newText": reveal(o.parent); break;
      case "insertNode": stale(o.parent); reveal(o.parent); break;
    }
    const fwd = [...pre, o];
    return { fwd, inv: fwd.slice().reverse().flatMap(invert), sel: o.keepId || o.id };
  }

  // keep the selection on a row that still exists
  function fixSel(before, prefer) {
    const S = T(); if (S.sel && N()[S.sel]) return;
    if (prefer && N()[prefer]) { S.sel = prefer; return; }
    const i = before.indexOf(S.sel);
    for (let k = i - 1; k >= 0; k--) if (N()[before[k]]) { S.sel = before[k]; return; }
    for (let k = i + 1; k < before.length; k++) if (N()[before[k]]) { S.sel = before[k]; return; }
    S.sel = S.draft.root[0] || null;
  }

  function commit(p) {
    tp = null; T().range = null;
    const before = order();
    Tree.change(() => { p.fwd.forEach(apply); fixSel(before, p.sel); });
    undo.push(p); if (undo.length > LIMIT) undo.shift();
    redo.length = 0;
  }
  const op = o => commit(plan(o));

  function step(back) {
    const e = (back ? undo : redo).pop();
    if (!e) { toast(back ? "되돌릴 것이 없어요" : "다시 할 것이 없어요"); return; }
    tp = null; T().range = null;
    const before = order();
    Tree.change(() => { (back ? e.inv : e.fwd).forEach(apply); if (N()[e.sel]) T().sel = e.sel; fixSel(before, null); });
    (back ? redo : undo).push(e);
  }

  // typing: edits within one second of each other are a single undo step
  function typing(id, field, value) {
    const n = N()[id]; if (!n || n[field] === value) return;
    const e = tp && tp.id === id && tp.field === field && Date.now() - tp.at < 1000 && undo[undo.length - 1] === tp.entry ? tp.entry : null;
    if (e) { tp.at = Date.now(); e.fwd[0].to = value; e.inv[0].from = value; Tree.change(() => { n[field] = value; }); return; }
    commit(plan({ type: "text", id, field, from: n[field], to: value }));
    tp = { id, field, at: Date.now(), entry: undo[undo.length - 1] };
  }

  // ---- gestures ----
  function move(id, dir) {
    const n = N()[id]; if (!n) return;
    if (FIXED.includes(n.kind)) { toast("요약과 프로젝트 줄은 제자리에 둬요"); return; }
    const p = parentOf(id), sib = siblings(p), i = sib.indexOf(id), j = i + dir;
    if (sib[j]) {
      if (N()[sib[j]].kind === "summary") return; // nothing goes above the summary
      op({ type: "move", id, from: { parent: p, index: i }, to: { parent: p, index: j } }); return;
    }
    // at the edge of its parent: hop into the neighbouring parent when the node may live there (a record into the next claim)
    if (!p) return;
    const gsib = siblings(parentOf(p)), hostId = gsib[gsib.indexOf(p) + dir];
    if (!hostId || !canLive(n.kind, hostId)) return;
    op({ type: "move", id, from: { parent: p, index: i }, to: { parent: hostId, index: dir > 0 ? 0 : N()[hostId].children.length } });
  }

  function indent(id, deeper) {
    const n = N()[id]; if (!n) return;
    if (FIXED.includes(n.kind)) { toast("요약과 프로젝트 줄은 깊이를 바꾸지 않아요"); return; }
    const p = parentOf(id), sib = siblings(p), i = sib.indexOf(id);
    let host;
    if (deeper) { if (i === 0) return; host = sib[i - 1]; }
    else { if (!p) return; host = parentOf(p); }
    if (!canLive(n.kind, host)) { toast(n.kind === "record" ? "기록은 주장 아래에만 놓을 수 있어요" : `${KIND[n.kind] || "이"} 줄은 그 자리에 놓을 수 없어요`); return; }
    const to = deeper ? { parent: host, index: N()[host].children.length } : { parent: host, index: siblings(host).indexOf(p) + 1 };
    op({ type: "move", id, from: { parent: p, index: i }, to });
  }

  function togglePage(id) {
    const n = N()[id]; if (!n) return;
    if (!PAGEABLE.includes(n.kind)) { toast("별도 페이지는 프로젝트나 주장 줄에서만 정해요"); return; }
    op({ type: "page", id, from: !!n.page, to: !n.page });
  }

  function newText(after) {
    const a = N()[after]; if (!a) return null;
    // under a project the new text is its first child; otherwise it is the next sibling of the selected row
    const parent = a.kind === "project" ? after : parentOf(after);
    const index = a.kind === "project" ? 0 : siblings(parent).indexOf(after) + 1;
    const id = newId();
    op({ type: "newText", id, parent, index });
    Tree.select(id);
    return id;
  }

  // ---- dragging: where a dropped row would land, and the two ways to land it ----
  const depthOf = id => { let d = 0; for (let p = parentOf(id); p; p = parentOf(p)) d++; return d; };
  // the last row of this subtree that is on screen (a folded row hides its children)
  function lastVisible(id) {
    for (;;) {
      const n = N()[id], rows = T().rows;
      if (!n || n.folded) return id;
      const kid = [...n.children].reverse().find(c => rows.get(c) && !rows.get(c).classList.contains("hidden"));
      if (!kid) return id;
      id = kid;
    }
  }
  const inside = (id, rootId) => { for (const [n] of Tree.walk([rootId])) if (n.id === id) return true; return false; };
  // Where would a dragged `kind` land when dropped on the upper ("above") or lower ("below") half of row `overId`?
  // -> { parent, index (before the row leaves its old place), anchor (the row the landing band hugs), side, depth } or null when it may not go there.
  // A record goes only under a claim: the lower half of a claim row makes it that claim's last child, a record row (or anything else
  // inside a claim) makes it a neighbour. A claim goes among a project's children. A text goes wherever a text may.
  function landing(kind, overId, half, movingId = null) {
    const o = N()[overId]; if (!o || !kind) return null;
    if (movingId && inside(overId, movingId)) return null;                    // not onto itself or into its own subtree
    const below = half === "below", p = parentOf(overId);
    let res = null;
    const into = (kind === "record" && o.kind === "claim") || (o.kind === "project" && (kind === "claim" || kind === "text"));
    if (into) {
      if (!below) { if (kind === "text") res = null; else return null; }     // the upper half of a container row is not "inside" it
      else res = { parent: overId, index: kind === "record" ? o.children.length : 0, anchor: kind === "record" ? lastVisible(overId) : overId, side: "bottom", depth: depthOf(overId) + 1 };
    }
    if (!res) {
      if (!canLive(kind, p)) return null;
      const sib = siblings(p), index = sib.indexOf(overId) + (below ? 1 : 0);
      if (!p && N()[sib[0]]?.kind === "summary" && index < 1) return null;   // nothing goes above the summary
      res = { parent: p, index, anchor: below ? lastVisible(overId) : overId, side: below ? "bottom" : "top", depth: depthOf(overId) };
    }
    if (movingId && res.parent === parentOf(movingId)) {                       // dropping a row where it already is
      const i = siblings(res.parent).indexOf(movingId);
      if ((res.index > i ? res.index - 1 : res.index) === i) return null;
    }
    return res;
  }
  // a row moves to a landing from landing(); the index it was computed with counts the row itself, the move op's does not
  function moveTo(id, land) {
    const n = N()[id]; if (!n || !land || FIXED.includes(n.kind) || inside(land.parent, id)) return false;
    const p = parentOf(id), i = siblings(p).indexOf(id);
    const to = land.parent === p && land.index > i ? land.index - 1 : land.index;
    if (land.parent === p && to === i) return false;
    op({ type: "move", id, from: { parent: p, index: i }, to: { parent: land.parent, index: to } });
    return true;
  }
  // a node that was made elsewhere (the drawer's copies) lands at parent[index]; undo removes it again
  function insert(node, parent, index) {
    if (!node || !node.kind || !canLive(node.kind, parent)) { toast("그 자리에는 놓을 수 없어요"); return null; }
    const n = clone(node); if (!n.id || N()[n.id]) n.id = newId();
    n.children = []; // a copy never brings nodes that are not in this tree
    op({ type: "insertNode", id: n.id, node: n, parent, index: Math.max(0, Math.min(index, siblings(parent).length)) });
    return n.id;
  }

  function flashMs() { return parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--t-flash")) || 0; }
  // "줄 지우기": both rows flash together, then the lower one folds up into the upper one, then the op lands
  function merge(keep, gone) {
    if (busy) return;
    const a = N()[keep], b = N()[gone];
    const p = parentOf(keep), sib = siblings(p);
    if (!a || !b || a.kind !== b.kind || !BODIED.includes(a.kind) || parentOf(gone) !== p || sib.indexOf(gone) !== sib.indexOf(keep) + 1) {
      toast("글이 있는 같은 종류의 아래위 두 줄(주장끼리, 내 글끼리)만 합칠 수 있어요"); return;
    }
    const ra = T().rows.get(keep), rb = T().rows.get(gone), draft = T().draft;
    if (!ra || !rb) return;
    busy = true;
    Motion.flash([ra, rb]);
    setTimeout(() => Motion.collapseInto(rb, ra, () => {
      busy = false;
      if (T().draft === draft && N()[keep] && N()[gone]) op({ type: "merge", keepId: keep, goneId: gone });
    }), flashMs());
  }
  function mergeRange() {
    const r = T().range;
    if (!r || r.length !== 2) { toast("합칠 두 줄을 Shift+↑↓로 고르세요"); return; }
    merge(r[0], r[1]);
  }

  // "열림": the new second row opens with a thin line
  function split(id, at) {
    const n = N()[id]; if (!n) return null;
    if (!BODIED.includes(n.kind)) { toast("글이 있는 주장이나 내 글만 나눌 수 있어요"); return null; }
    const text = n.text || "", head = text.slice(0, at).trimEnd(), tail = text.slice(at).trimStart();
    if (!head) { toast("나눌 자리가 글의 맨 앞이에요"); return null; }
    // nothing after the caret: the second Enter at the end of a body opens an empty sibling to write in
    const title2 = tail ? (tail.split(/[.!?。\n]/)[0].trim().slice(0, 40) || (n.title ? n.title + " (2)" : "")) : (n.kind === "claim" && n.title ? n.title + " (2)" : "");
    const nid = newId();
    op({ type: "split", id, newId: nid, at, title2, text2: tail });
    const li = T().rows.get(nid); if (li) Motion.once(li, "open", 200);
    Tree.select(nid);
    return nid;
  }

  // two rows picked with Shift+↑↓: this row and its neighbouring sibling
  function pair(dir) {
    const id = T().sel, sib = siblings(parentOf(id)), other = sib[sib.indexOf(id) + dir];
    if (other) Tree.select(other, dir > 0 ? [id, other] : [other, id]);
  }

  // ---- hints after a mouse gesture: three times per gesture, then never again ----
  const HINTS = { toggle: "Space로도 켜고 끌 수 있어요", fold: "F로도 접고 펼 수 있어요", drag: "Alt+↑↓로도 옮길 수 있어요" };
  let memHints = {};
  function hint(kind) {
    if (!HINTS[kind]) return;
    let h = memHints;
    try { h = JSON.parse(localStorage.getItem("hints") || "{}") || {}; } catch { /* storage unavailable: count in memory */ }
    if ((h[kind] || 0) >= 3) return;
    h[kind] = (h[kind] || 0) + 1; memHints = h;
    try { localStorage.setItem("hints", JSON.stringify(h)); } catch { /* ignore */ }
    toast(HINTS[kind]);
  }

  // ---- keyboard ----
  const helpDlg = () => document.getElementById("keysDlg");
  function onKey(e) {
    const S = T(); if (!S.draft || document.getElementById("tree").hidden || busy) return;
    if (document.querySelector("dialog[open]")) return;
    const k = e.key, code = e.code, ctrl = e.ctrlKey || e.metaKey, alt = e.altKey, shift = e.shiftKey;
    const editable = !!e.target.closest?.("input, textarea, select, [contenteditable]:not([contenteditable='false'])");
    if (ctrl && code === "KeyS") { e.preventDefault(); Tree.flush(); return; }
    if (ctrl && k === "Enter") { e.preventDefault(); if (S.sel) newText(S.sel); return; }
    if (editable) return; // inside a text field the field's own keys win
    if (ctrl && !alt && code === "KeyZ") { e.preventDefault(); step(!shift); return; }
    if (ctrl && !alt && code === "KeyY") { e.preventDefault(); step(false); return; }
    if (ctrl && !alt && code === "KeyM") { e.preventDefault(); mergeRange(); return; }
    if (k === "?") { e.preventDefault(); helpDlg()?.showModal(); return; }
    if (ctrl || !e.target.closest?.("#treeList")) return;
    const id = S.sel, n = id && N()[id]; if (!n) return;
    // letters go by e.code so the Korean layout (ㄹ, ㅔ) works too
    if (k === " ") { e.preventDefault(); if (!e.repeat) Tree.toggle(id); }
    else if (k === "Delete") { e.preventDefault(); if (n.on) Tree.toggle(id); }
    else if (code === "KeyF" && !alt) Tree.fold(id);
    else if (code === "KeyP" && !alt) togglePage(id);
    else if ((k === "ArrowDown" || k === "ArrowUp") && alt) { e.preventDefault(); move(id, k === "ArrowDown" ? 1 : -1); }
    else if ((k === "ArrowDown" || k === "ArrowUp") && shift) { e.preventDefault(); pair(k === "ArrowDown" ? 1 : -1); }
    else if (k === "ArrowDown" || k === "ArrowUp") {
      e.preventDefault(); const o = order(), j = o.indexOf(id) + (k === "ArrowDown" ? 1 : -1); if (o[j]) Tree.select(o[j]);
    }
    else if (k === "ArrowRight") { e.preventDefault(); if (n.folded) Tree.fold(id); else if (n.children.length) Tree.select(n.children[0]); }
    else if (k === "ArrowLeft") { e.preventDefault(); if (!n.folded && n.children.length) Tree.fold(id); else { const p = parentOf(id); if (p) Tree.select(p); } }
    else if (k === "Tab" && !alt) { e.preventDefault(); indent(id, !shift); }
    else if (k === "Enter" && !alt) { e.preventDefault(); newText(id); }
    else if (k === "Escape") {
      if (S.range) Tree.select(id, null); // drop the pair
      else document.querySelector('.t-filters [data-filter][aria-pressed="true"]')?.focus(); // Tab is depth here, so Esc is the way out
    }
  }

  function bind() { // once, however often a draft is opened
    if (bound) return; bound = true;
    document.addEventListener("keydown", onKey);
    document.getElementById("keysBtn")?.addEventListener("click", () => helpDlg()?.showModal());
  }
  function reset() { undo = []; redo = []; tp = null; busy = false; } // a different draft: its history starts empty

  return { op, type: typing, typing, move, indent, merge, split, newText, togglePage, hint, bind, reset, insert, landing, moveTo, parentOf,
           undo: () => step(true), redo: () => step(false) };
})();
