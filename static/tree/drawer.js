/* Drawer: the right column. Three tabs: 근거 (the files and sentences behind the selected row), 다른 주 (rows of another week to copy
   in), 집은 그림 (images picked at home). It is read-only context: the only ways a drawer item reaches the draft are dragging it onto a
   tree row (Keys.insert) and, for tree rows themselves, Keys.moveTo. Drag and drop for the whole tree lives here: the drawer's items,
   the rows' own handle (.t-title), the landing band and the ghost. The body is rebuilt on show(); everything that listens is bound once
   to a node that stays (the body, the tab strip, #treeList), so rebuilding never piles up listeners. */
window.Drawer = (() => {
  // boot.js (which defines Composer) loads after this file: look the helpers up at call time
  const api = (...a) => window.Composer.api(...a), esc = s => window.Composer.esc(s), toast = (...a) => window.Composer.toast(...a);
  const MIME = "application/x-tree-item";
  const IMG = /\.(png|jpe?g|gif|webp|svg|avif)$/i, VID = /\.(mp4|webm)$/i;
  const TABS = ["evidence", "weeks", "picked"];
  const KIND = { claim: "주장", record: "기록" };
  const ROLE = { core: "핵심", support: "부속", derived: "파생" };
  const FILES_SHOWN = 6;
  const S = { tab: "evidence", id: null, seq: 0, built: null, builtDraft: null, lib: null, libAt: 0, libDraft: null, week: null,
              outlines: new Map(), items: [], origin: null, drag: null };

  const root = () => document.getElementById("drawer");
  const body = () => root().querySelector(".d-body");
  const list = () => document.getElementById("treeList");
  const draft = () => window.Tree?.state?.draft || null;
  const node = id => { const d = draft(); return id && d ? d.nodes[id] : null; };
  const enc = p => String(p).split("/").map(encodeURIComponent).join("/");
  const newId = () => "n-" + Math.random().toString(36).slice(2, 10);
  const none = text => `<p class="d-none">${esc(text)}</p>`;

  // ---- data: the library (every week's blocks) is fetched once per draft and again after a minute; page host from /api/state ----
  function library(fresh = false) {
    if (!fresh && S.lib && S.libDraft === draft() && Date.now() - S.libAt < 60000) return S.lib;
    const p = api("/api/library"); S.lib = p; S.libDraft = draft(); S.libAt = Date.now();
    p.catch(() => { if (S.lib === p) S.lib = null; });
    return p;
  }
  function pageOrigin() {
    S.origin = S.origin || api("/api/state").then(s => s.page_origin || null).catch(() => null);
    return S.origin.then(o => o || `${location.protocol}//${location.hostname}:${location.port}`);
  }

  // ---- tabs ----
  function paintTabs() {
    root().querySelectorAll(".d-tabs [data-drawer]").forEach(b => {
      const on = b.dataset.drawer === S.tab;
      b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1;
    });
  }
  // show(id, tab): the selected row's context; `tab` switches tabs when given. The other tabs are not rebuilt by a mere selection.
  function show(id, tab) {
    if (id !== undefined) S.id = id;
    if (tab && TABS.includes(tab)) S.tab = tab;
    render(false);
  }
  function render(force) {
    if (!draft()) return;
    paintTabs();
    body().dataset.tab = S.tab;
    if (S.tab === "evidence") return evidence();
    if (force || S.built !== S.tab || S.builtDraft !== draft()) return S.tab === "weeks" ? weeks() : picked();
  }
  const built = () => { S.built = S.tab; S.builtDraft = draft(); };

  // ---- 근거: the selected record's files (or all records of a claim) and the sentences of its chapter ----
  const relOf = src => String(src).split("/").slice(4).join("/");   // <week>/records/<short>/<R-id>/<rel>
  function find(lib, rec) {
    const s = rec.src || {}, wk = lib.find(w => w.week === (s.week || draft().week));
    const proj = wk?.projects?.find(p => p.project === s.project || p.short === s.project);
    const row = proj?.records?.find(r => r.id === s.record) || null;
    const blocks = [], seen = new Set();
    for (const st of proj?.streams || []) for (const b of st.blocks || []) {
      if (s.record && b.record === s.record && b.src && !seen.has(b.src)) { seen.add(b.src); blocks.push(b); }
    }
    const chapter = row?.chapter || s.chapter;
    const stream = chapter ? proj?.streams?.find(st => st.chapter === chapter) : null;
    return { week: s.week || draft().week, proj, row, blocks, stream, sentences: (stream?.blocks || []).filter(b => b.type === "bullet") };
  }
  function filesOf(rec, hit) {
    const own = new Map((rec.files || []).map(f => [f.rel, f]));
    const out = [], home = [];
    for (const b of hit.blocks) {
      if (!["image", "file", "page", "markdown"].includes(b.type)) continue;
      const rel = relOf(b.src), name = rel || b.src.split("/").pop();
      const type = b.type === "page" ? "page" : VID.test(b.src) ? "video" : (b.type === "image" || IMG.test(b.src)) ? "image" : "doc";
      const role = own.get(rel)?.role || (hit.row?.href && b.src.endsWith(hit.row.href) ? "core" : b.optional ? "support" : null);
      out.push({ name, src: b.src, type, role });
    }
    if (hit.row) for (const name of hit.row.home || []) home.push({ name });
    if (!hit.blocks.length && !hit.row) {      // this week is not in the library (an old package): the node's own file list is all there is
      const wk = rec.src?.week || draft().week, add = (href, role) => href && !out.some(f => f.src === `${wk}/${href}`) && out.push({ name: href.split("/").pop(), src: `${wk}/${href}`, role,
        type: VID.test(href) ? "video" : IMG.test(href) ? "image" : /\.html?$/i.test(href) ? "page" : "doc" });
      add(rec.representative, "derived"); add(rec.href, "core");
      for (const f of rec.files || []) { if (f.home) home.push({ name: f.rel }); else add(f.href, f.role); }
    }
    return { out, home };
  }
  function fileHTML(f, origin, poster) {
    const role = f.role ? `<i class="chip d-role">${esc(ROLE[f.role] || f.role)}</i>` : "";
    const url = `/files/${enc(f.src)}`, name = `<span class="d-name">${esc(f.name)}</span>`;
    if (f.type === "image") return `<li class="d-file"><a class="d-thumbwrap" href="${esc(url)}" target="_blank" rel="noopener" title="새 창에서 보기"><img class="d-thumb" loading="lazy" draggable="false" src="${esc(url)}" alt="${esc(f.name)}"></a>${name}${role}</li>`;
    if (f.type === "video") return `<li class="d-file"><video class="d-thumb" controls preload="none"${poster ? ` poster="${esc(poster)}"` : ""} src="${esc(url)}" aria-label="${esc(f.name)}"></video>${name}${role}</li>`;
    if (f.type === "page") return `<li class="d-file">${name}${role}<a class="d-open" href="${esc(origin)}/page/${esc(enc(f.src))}" target="_blank" rel="noopener">열기</a></li>`;
    return `<li class="d-file">${name}${role}<a class="d-open" href="${esc(url)}" target="_blank" rel="noopener">열기</a></li>`;
  }
  function recordHTML(rec, hit, origin) {
    const title = rec.title || hit.row?.title || "(제목 없음)";
    const chips = [hit.row?.kind && `<i class="chip">${esc(hit.row.kind)}</i>`, hit.row && hit.row.arrived === false && '<i class="chip m-noref">도착 안 함</i>'].filter(Boolean).join("");
    let head = `<header class="d-rechead"><h3>${esc(title)}</h3>${chips}</header>`;
    if (!rec.src?.record) {      // an image picked at home: no record behind it, only the file
      const href = rec.representative || rec.href, wk = rec.src?.week || draft().week;
      return `<section class="d-rec">${head}${none("집에서 집어 온 그림이에요. 근거 기록은 없어요.")}`
        + (href ? `<ul class="d-files">${fileHTML({ name: href.split("/").pop(), src: `${wk}/${href}`, type: IMG.test(href) ? "image" : "doc" }, origin)}</ul>` : "") + "</section>";
    }
    const { out, home } = filesOf(rec, hit);
    const poster = out.find(f => f.type === "image" && /preview/.test(f.name))?.src || out.find(f => f.type === "image")?.src;
    const posterUrl = poster ? `/files/${enc(poster)}` : "";
    const items = out.map(f => fileHTML(f, origin, posterUrl));
    let files = items.length ? `<ul class="d-files">${items.slice(0, FILES_SHOWN).join("")}</ul>` : none("패키지에 담겨 온 파일이 없어요.");
    if (items.length > FILES_SHOWN) files += `<details class="d-more"><summary>나머지 ${items.length - FILES_SHOWN}개</summary><ul class="d-files">${items.slice(FILES_SHOWN).join("")}</ul></details>`;
    if (home.length) {
      files += `<details class="d-home"${home.length <= FILES_SHOWN ? " open" : ""}><summary>집에 있는 파일 ${home.length}개</summary><ul class="d-files">`
        + home.map(f => `<li class="d-file home"><span class="d-name">집에 있음 · ${esc(f.name)}</span></li>`).join("") + "</ul></details>";
    }
    return `<section class="d-rec">${head}${files}</section>`;
  }
  function sentencesHTML(hit) {
    if (!hit.sentences.length) return "";
    return `<section class="d-sec"><h4>이 기록이 속한 정리 단위의 문장${hit.stream?.title ? ` · ${esc(hit.stream.title)}` : ""}</h4>`
      + `<ol class="d-sent">${hit.sentences.map(b => `<li>${esc(b.text)}</li>`).join("")}</ol></section>`;
  }

  async function evidence() {
    const seq = ++S.seq, b = body(), n = node(S.id);
    if (!n) { b.innerHTML = none("줄을 고르면 그 줄의 근거가 여기에 보여요."); built(); return; }
    const recs = n.kind === "record" ? [n] : n.kind === "claim" ? (n.children || []).map(node).filter(c => c?.kind === "record") : [];
    if (!recs.length) {
      b.innerHTML = none(n.kind === "claim" ? "이 주장 아래에는 기록이 아직 없어요." : "이 줄에는 열어 볼 근거 파일이 없어요. 기록이나 주장 줄을 골라 보세요.");
      built(); return;
    }
    if (!S.lib) b.innerHTML = none("근거를 불러오는 중…");
    let lib, origin;
    try { [lib, origin] = await Promise.all([library(), pageOrigin()]); }
    catch (e) { if (seq === S.seq) { b.innerHTML = none("근거를 불러오지 못했어요: " + e.message); built(); } return; }
    if (seq !== S.seq || S.tab !== "evidence") return;
    const hits = recs.map(r => find(lib, r));
    // the sentences are the chapter's, so records of one claim share them: show each chapter once
    const shown = new Set(), sentences = hits.map(h => { const k = h.week + "|" + h.proj?.project + "|" + h.stream?.chapter; if (shown.has(k)) return ""; shown.add(k); return sentencesHTML(h); }).join("");
    const records = recs.map((r, i) => recordHTML(r, hits[i], origin)).join("");
    b.innerHTML = n.kind === "claim" ? sentences + records : records + sentences;
    b.scrollTop = 0; root().scrollTop = 0;
    built();
  }

  // ---- 다른 주 ----
  function* outlineRows(o) {
    const nodes = o.nodes || {};
    function* go(ids, depth) { for (const id of ids || []) { const n = nodes[id]; if (!n) continue; yield [n, depth]; yield* go(n.children, depth + 1); } }
    yield* go(o.root, 0);
  }
  const markChips = n => (n.marks || []).map(m => `<i class="chip m-${esc(m)}">${esc(Tree.markLabel(m))}</i>`).join("");
  async function weeks() {
    const seq = ++S.seq, b = body(), d = draft();
    if (!S.lib) b.innerHTML = none("주차를 불러오는 중…");
    let lib;
    try { lib = await library(); } catch (e) { if (seq === S.seq) b.innerHTML = none("주차를 불러오지 못했어요: " + e.message); return; }
    if (seq !== S.seq || S.tab !== "weeks") return;
    const others = lib.filter(w => w.week !== d.week);
    if (!others.length) { b.innerHTML = none("다른 주의 자료가 아직 없어요."); built(); return; }
    if (!others.some(w => w.week === S.week)) S.week = others[0].week;
    b.innerHTML = `<label class="d-weekpick">주차 <select class="d-week" aria-label="다른 주 고르기">${others.map(w =>
      `<option value="${esc(w.week)}"${w.week === S.week ? " selected" : ""}>${esc(w.week)}${w.since ? ` · ${esc(w.since.slice(5))} ~ ${esc((w.until || "").slice(5))}` : ""}</option>`).join("")}</select></label>`
      + `<p class="d-hint">끌어서 이 주의 트리에 넣으면 복사돼요.</p><ul class="d-list" aria-label="그 주의 주장과 기록"></ul>`;
    built();
    loadWeek(S.week);
  }
  async function loadWeek(week) {
    const seq = ++S.seq, host = body().querySelector(".d-list"); if (!host) return;
    let o = S.outlines.get(week);
    if (!o) {
      host.innerHTML = `<li class="d-none">불러오는 중…</li>`;
      try { o = await api(`/api/outline/${week}`); S.outlines.set(week, o); }
      catch (e) { if (seq === S.seq) host.innerHTML = `<li class="d-none">${esc(week)}는 트리로 열 수 없어요: ${esc(e.message)}</li>`; return; }
    }
    if (seq !== S.seq || S.week !== week) return;
    S.items = []; const html = [];
    for (const [n, depth] of outlineRows(o)) {
      if (n.kind === "project") { html.push(`<li class="d-projhead">${esc(n.title)}</li>`); continue; }
      if (!KIND[n.kind]) continue;
      const i = S.items.push({ kind: "node", week, node: n }) - 1;
      const img = n.kind === "record" && n.representative && IMG.test(n.representative) ? `<img class="d-mini" loading="lazy" draggable="false" src="/files/${esc(enc(`${n.src?.week || week}/${n.representative}`))}" alt="">` : "";
      const sub = n.kind === "claim" && n.text ? `<small class="d-isub">${esc(n.text.replace(/\s+/g, " ").slice(0, 70))}</small>` : "";
      html.push(`<li class="d-item kind-${esc(n.kind)}" draggable="true" data-i="${i}" style="--d:${Math.max(0, depth - 1)}">${img}<span class="d-itext"><span class="d-ititle">${esc(n.title || "(제목 없음)")}</span>${sub}</span>`
        + `<span class="d-imarks"><i class="chip">${esc(KIND[n.kind])}</i>${markChips(n)}</span></li>`);
    }
    host.innerHTML = S.items.length ? html.join("") : `<li class="d-none">${esc(week)}에는 끌어 올 주장이나 기록이 없어요.</li>`;
  }

  // ---- 집은 그림 ----
  async function picked() {
    const seq = ++S.seq, b = body(), d = draft();
    if (!S.lib) b.innerHTML = none("불러오는 중…");
    let lib;
    try { lib = await library(true); } catch (e) { if (seq === S.seq) b.innerHTML = none("그림을 불러오지 못했어요: " + e.message); return; }
    if (seq !== S.seq || S.tab !== "picked") return;
    const imgs = (lib.find(w => w.week === d.week)?.assets || []).filter(a => a.picked && (a.type === "image" || IMG.test(a.src || "")));
    S.items = imgs.map(a => ({ kind: "picked", week: d.week, src: a.src, name: (a.caption || a.src.split("/").pop()) }));
    b.innerHTML = imgs.length
      ? `<p class="d-hint">끌어서 트리에 넣으면 기록 줄이 돼요.</p><ul class="d-grid" aria-label="집은 그림">${S.items.map((it, i) =>
        `<li class="d-pick" draggable="true" data-i="${i}" title="${esc(it.name)}"><img class="d-thumb" loading="lazy" draggable="false" src="/files/${esc(enc(it.src))}" alt="${esc(it.name)}"><span class="d-name">${esc(it.name)}</span></li>`).join("")}</ul>`
      : none("이 주에 집은 그림이 아직 없어요.");
    built();
  }

  // ---- what a drop makes ----
  function copyOf(payload) {
    const c = JSON.parse(JSON.stringify(payload.node));
    return { ...c, id: newId(), marks: c.kind === "text" ? ["other-week", "noref"] : ["other-week"], src: { ...(c.src || {}), week: c.src?.week || payload.week },
             on: true, folded: false, page: false, stale: false, children: [] };
  }
  function pickedNode(payload) {
    const name = payload.src.split("/").pop(), prefix = payload.week + "/";
    return { id: newId(), kind: "record", title: name, text: "", on: true, folded: false, page: false, stale: false,
             src: { week: payload.week, project: null, chapter: null, record: null }, marks: ["picked"], tier: "main", children: [],
             caption: [name], show: "representative", representative: payload.src.startsWith(prefix) ? payload.src.slice(prefix.length) : payload.src,
             href: null, files: [], kind_label: "그림" };
  }

  // ---- dragging: one state (S.drag) set at dragstart, because dragover cannot read the data ----
  let band = null;
  function bandEl() { // one band for the whole tree, outside the <ul> so row order and FLIP never see it
    if (!band) {
      band = Object.assign(document.createElement("div"), { className: "t-drop", hidden: true });
      band.setAttribute("aria-hidden", "true");
      document.querySelector(".t-outline").appendChild(band);
    }
    return band;
  }
  function hideBand() { if (band) band.hidden = true; }
  function showBand(land) {
    const row = Tree.state.rows.get(land.anchor), host = bandEl().parentElement; if (!row) { hideBand(); return; }
    const r = row.getBoundingClientRect(), h = host.getBoundingClientRect(), indent = 12 + land.depth * 18;
    const el = bandEl();
    el.style.top = `${(land.side === "top" ? r.top : r.bottom) - h.top + host.scrollTop - 2}px`;
    el.style.left = `${r.left - h.left + indent}px`;
    el.style.width = `${Math.max(24, r.width - indent - 8)}px`;
    el.hidden = false;
  }
  function endDrag() {
    hideBand();
    list().querySelectorAll(".t-ghost").forEach(li => li.classList.remove("t-ghost"));
    root().querySelectorAll(".dragging").forEach(el => el.classList.remove("dragging"));
    S.drag = null;
  }
  const landingAt = (e, d) => {
    const li = e.target.closest?.(".t-row"); if (!li) return null;
    const r = li.getBoundingClientRect();
    return Keys.landing(d.kind, li.dataset.id, e.clientY < r.top + r.height / 2 ? "above" : "below", d.movingId);
  };
  function landed(id) {
    Tree.select(id);
    Motion.once(Tree.state.rows.get(id)?.querySelector(".t-title"), "land", 200);
  }
  function drop(e, d, land) {
    let payload = d.payload;
    try { payload = JSON.parse(e.dataTransfer.getData(MIME)) || payload; } catch { /* keep the one from dragstart */ }
    if (payload.kind === "row") { if (Keys.moveTo(payload.id, land)) { landed(payload.id); Keys.hint("drag"); } return; }
    let n;
    if (payload.kind === "node" && payload.node) n = copyOf(payload);
    else if (payload.kind === "picked" && payload.src) n = pickedNode(payload);
    if (!n) return;
    const id = Keys.insert(n, land.parent, land.index);
    if (!id) return;
    landed(id);
    if (payload.node?.kind === "claim" && payload.node.children?.length) toast("자식은 함께 오지 않아요"); else Keys.hint("drag");
  }

  function bindDrag() {
    const ul = list();
    // drawer items
    root().addEventListener("dragstart", e => {
      const el = e.target.closest?.("[data-i]"), it = el && S.items[+el.dataset.i]; if (!it) return;
      const payload = it.kind === "picked" ? { kind: "picked", week: it.week, src: it.src } : { kind: "node", week: it.week, node: it.node };
      e.dataTransfer.setData(MIME, JSON.stringify(payload)); e.dataTransfer.effectAllowed = "copy";
      S.drag = { kind: it.kind === "picked" ? "record" : it.node.kind, payload, movingId: null };
      el.classList.add("dragging");
    });
    // tree rows, by their title
    ul.addEventListener("dragstart", e => {
      const li = e.target.closest?.(".t-title")?.closest(".t-row"), n = li && node(li.dataset.id); if (!n) return;
      if (n.kind === "summary" || n.kind === "project") { e.preventDefault(); toast("요약과 프로젝트 줄은 제자리에 둬요"); return; }
      const payload = { kind: "row", week: draft().week, id: n.id };
      e.dataTransfer.setData(MIME, JSON.stringify(payload)); e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setDragImage(li, 24, 16);
      S.drag = { kind: n.kind, payload, movingId: n.id };
      setTimeout(() => { if (S.drag?.movingId === n.id) li.classList.add("t-ghost"); }, 0); // after the browser has taken the drag image
    });
    ul.addEventListener("dragover", e => {
      const d = S.drag; if (!d) return;
      const land = landingAt(e, d);
      if (!land) { hideBand(); return; }                 // no preventDefault: the cursor says "not here" and no band shows
      e.preventDefault(); e.dataTransfer.dropEffect = d.movingId ? "move" : "copy";
      showBand(land);
    });
    ul.addEventListener("dragleave", e => { if (!ul.contains(e.relatedTarget)) hideBand(); });
    ul.addEventListener("drop", e => {
      const d = S.drag; if (!d) return;
      const land = landingAt(e, d);
      e.preventDefault(); endDrag();
      if (land) drop(e, d, land);
    });
    document.addEventListener("dragend", endDrag);        // cancelled, or dropped somewhere that is not the tree
  }

  // ---- bound once ----
  function bind() {
    const r = root(); if (!r) return;
    r.querySelector(".d-tabs").addEventListener("click", e => {
      const b = e.target.closest?.("[data-drawer]"); if (!b) return;
      S.tab = b.dataset.drawer; render(true);
    });
    r.querySelector(".d-tabs").addEventListener("keydown", e => {   // arrow keys move along the tab strip
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const i = TABS.indexOf(S.tab), next = TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
      S.tab = next; render(true); r.querySelector(`[data-drawer="${next}"]`)?.focus();
    });
    r.querySelector(".d-body").addEventListener("change", e => {
      if (e.target.matches?.(".d-week")) { S.week = e.target.value; loadWeek(S.week); }
    });
    r.querySelector(".d-body").addEventListener("error", e => {       // a file that did not load: say so instead of an empty box
      const el = e.target; if (!el?.matches?.("img.d-thumb, img.d-mini")) return;
      if (el.classList.contains("d-mini")) { el.remove(); return; }
      el.replaceWith(Object.assign(document.createElement("span"), { className: "d-none", textContent: "그림을 불러오지 못했어요" }));
    }, true);
    if (list()) bindDrag();
  }
  bind();

  return { show, state: S };
})();
