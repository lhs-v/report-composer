/* Tree: the outline column. Rows are keyed by node id and kept between renders, so a toggle only touches classes/text. */
window.Tree = (() => {
  // boot.js (which defines Composer) loads after this file, so look the helpers up at call time
  const api = (...a) => window.Composer.api(...a), esc = s => window.Composer.esc(s), toast = (...a) => window.Composer.toast(...a);
  const S = { draft: null, sel: null, rows: new Map(), filter: "all", saveTimer: null, rev: 0, range: null };
  const $ = s => document.querySelector(s);
  const list = () => document.getElementById("treeList");
  const nodes = () => S.draft.nodes;
  const marksOf = n => n.marks || [];
  const MARK = { new: "새", sent: "보냄", changed: "바뀜", noref: "근거 없음", home: "집", used: "지난주", "other-week": "다른 주", picked: "집은 그림" };

  // depth-first, in tree order; folded nodes keep their children out of the walk unless all=true
  function* walk(ids = S.draft.root, depth = 0, parent = null, all = true) {
    for (const id of ids) {
      const n = nodes()[id]; if (!n) continue;
      yield [n, depth, parent];
      if (all || !n.folded) yield* walk(n.children || [], depth + 1, id, all);
    }
  }
  const isStale = n => n.stale || marksOf(n).includes("noref");
  function visible(n) {
    return S.filter === "all" || (S.filter === "on" && n.on) || (S.filter === "new" && marksOf(n).includes("new")) || (S.filter === "stale" && isStale(n));
  }

  function row(n, depth) {
    let li = S.rows.get(n.id);
    if (!li) {
      li = document.createElement("li"); li.className = `t-row kind-${n.kind}`; li.dataset.id = n.id; li.setAttribute("role", "treeitem"); li.tabIndex = -1;
      li.innerHTML = `<button type="button" class="t-check" aria-label="켜기/끄기" tabindex="-1"></button><span class="t-rail"></span><span class="t-title"></span><span class="t-marks"></span><span class="t-count"></span>`;
      li.querySelector(".t-check").addEventListener("click", e => { e.stopPropagation(); select(n.id); toggle(n.id); Keys.hint("toggle"); });
      li.querySelector(".t-title").draggable = true; // the handle for moving the row; drawer.js owns the drag events
      li.addEventListener("click", () => select(n.id));
      li.addEventListener("dblclick", () => { if (n.children?.length) { fold(n.id); Keys.hint("fold"); } });
      S.rows.set(n.id, li);
    }
    li.style.setProperty("--depth", depth); li.setAttribute("aria-level", depth + 1);
    // classList.toggle (not className=) so a running .flash/.land/.open survives a render
    li.classList.toggle("off", !n.on); li.classList.toggle("folded", !!n.folded); li.classList.toggle("stale", isStale(n));
    li.classList.toggle("page", !!n.page); li.classList.toggle("sel", S.sel === n.id); li.classList.toggle("hidden", !visible(n));
    li.classList.toggle("range", !!S.range?.includes(n.id));
    li.tabIndex = S.sel === n.id ? 0 : -1; // roving tabindex: Tab from the page lands on the selected row
    li.setAttribute("aria-selected", String(S.sel === n.id));
    if (n.children?.length) li.setAttribute("aria-expanded", String(!n.folded)); else li.removeAttribute("aria-expanded");
    li.querySelector(".t-check").setAttribute("aria-pressed", String(!!n.on));
    li.querySelector(".t-title").textContent = n.title || (n.text || "").split("\n")[0] || "(빈 글)";
    const marks = marksOf(n).map(m => `<i class="chip m-${esc(m)}">${esc(MARK[m] || m)}</i>`).join("") + (n.page ? '<i class="chip m-page">별도 페이지</i>' : "");
    const mk = li.querySelector(".t-marks"); if (mk.dataset.sig !== marks) { mk.innerHTML = marks; mk.dataset.sig = marks; }
    li.querySelector(".t-count").textContent = n.children?.length || "";
    return li;
  }

  // put the rows in order inside ul, moving only what is out of place (keeps focus and avoids a rebuild)
  function sync(ul, rows) {
    rows.forEach((li, i) => { if (ul.children[i] !== li) ul.insertBefore(li, ul.children[i] || null); });
    while (ul.children.length > rows.length) ul.lastChild.remove();
  }
  function render() {
    const ul = list(), rows = [], seen = new Set();
    for (const [n, depth] of walk(S.draft.root, 0, null, false)) rows.push(row(n, depth));
    for (const [n] of walk()) seen.add(n.id);
    for (const id of [...S.rows.keys()]) if (!seen.has(id)) S.rows.delete(id);
    Motion.flip(ul, () => sync(ul, rows));
    meter();
  }

  function meter() {
    const all = Object.values(nodes()), total = all.length;
    const on = all.filter(n => n.on).length, stale = all.filter(isStale).length;
    const m = $(".t-meter");
    const bar = (cls, n, label) => `<i class="${cls}" style="flex:${n}"${n ? "" : " hidden"} title="${label} ${n}"></i>`;
    m.innerHTML = `<span class="t-bars">${bar("on", on, "켬") + bar("off", total - on, "끔") + bar("stale", stale, "다듬을 것")}</span>`
      + `<span class="t-nums" aria-hidden="true">켬 ${on} · 끔 ${total - on} · 다듬을 것 ${stale}</span>`;
    m.setAttribute("aria-label", `진행 상황: 켬 ${on}, 끔 ${total - on}, 다듬을 것 ${stale}`);
    const chip = $("#treeStale");
    chip.textContent = stale ? `다듬을 것 ${stale}` : "다듬을 것 없음"; chip.classList.toggle("clear", !stale);
  }

  // ---- saving: the whole draft, 600 ms after the last change ----
  const saveState = text => { const el = document.getElementById("saveState"); if (el) el.textContent = text; };
  async function save(draft, rev, leaving = false) {
    S.saveTimer = null;
    try {
      // leaving the page: keepalive lets the request outlive it, but browsers cap such bodies near 64 KB
      const body = JSON.stringify(draft);
      const saved = await api(`/api/drafts/${draft.id}`, { method: "PUT", body, keepalive: leaving && body.length < 60000 });
      if (saved?.updated && draft === S.draft && rev === S.rev) draft.updated = saved.updated;
      if (draft === S.draft && rev === S.rev && !S.saveTimer) saveState("저장됨");
    } catch (e) {
      saveState("저장 실패");
      toast("저장하지 못했습니다 (화면의 변경은 그대로입니다): " + esc(e.message), 8000);
    }
  }
  function flush(leaving = false) { // leaving a draft (or the page) with an unsaved change: send it now
    if (S.saveTimer && S.draft) { clearTimeout(S.saveTimer); save(S.draft, S.rev, leaving); }
  }
  window.addEventListener("pagehide", () => flush(true));
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") flush(true); }); // a tab switch or a closing window may never fire pagehide
  function change(mutate) {
    // a re-render moves rows and the browser drops focus from a moved row: put it back if the keyboard was in the list
    const ae = document.activeElement, keep = !ae || ae === document.body || list().contains(ae);
    mutate(); S.draft.updated = new Date().toISOString(); S.rev++; render();
    if (keep) S.rows.get(S.sel)?.focus();
    window.NodePane?.show?.(S.sel);
    clearTimeout(S.saveTimer); saveState("저장 중…");
    const draft = S.draft, rev = S.rev;
    S.saveTimer = setTimeout(() => save(draft, rev), 600);
  }

  function toggle(id) {
    const n = nodes()[id]; if (!n) return;
    Motion.tap(S.rows.get(id)?.querySelector(".t-check"));
    Keys.op({ type: "toggle", id, from: n.on, to: !n.on });
  }
  function fold(id) {
    const n = nodes()[id]; if (!n || !n.children?.length) return;
    Keys.op({ type: "fold", id, from: n.folded, to: !n.folded });
  }
  // range: [upper, lower] when two sibling rows are picked with Shift+↑↓ (to merge them); otherwise none
  function select(id, range = null) {
    if (!id || !nodes()[id]) return;
    if (id === S.sel && !range && !S.range) return;
    S.sel = id; S.range = range;
    for (const [k, li] of S.rows) {
      li.classList.toggle("sel", k === id); li.setAttribute("aria-selected", String(k === id));
      li.classList.toggle("range", !!range?.includes(k)); li.tabIndex = k === id ? 0 : -1;
    }
    S.rows.get(id)?.focus({ preventScroll: false });
    window.NodePane?.show?.(id); window.Drawer?.show?.(id);
  }
  function setFilter(f) {
    S.filter = f;
    document.querySelectorAll(".t-filters [data-filter]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.filter === f)));
    if (S.draft) render();
  }
  document.querySelectorAll(".t-filters [data-filter]").forEach(b => b.addEventListener("click", () => setFilter(b.dataset.filter)));

  function open(draft) {
    flush();
    S.draft = draft; S.rows.clear(); S.rev = 0; S.filter = "all"; S.sel = null; S.range = null;
    Keys.reset();
    document.querySelectorAll(".t-filters [data-filter]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.filter === "all")));
    $(".t-head h2").textContent = draft.title || "초안 트리";
    list().replaceChildren();
    const first = draft.root?.[1] || draft.root?.[0] || null; // the first row after the summary: where the writing starts
    render(); select(first); Keys.bind();
  }

  return { open, render, change, setDraft: change, toggle, fold, select, setFilter, flush, state: S, nodes, walk, markLabel: m => MARK[m] || m };
})();
