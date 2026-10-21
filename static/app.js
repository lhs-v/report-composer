/* Report Composer UI: library (left/middle) → draft (right). Vanilla JS, no build step. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const api = async (path, opts = {}) => {
    const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      body: opts.body !== undefined && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body });
    const data = r.headers.get("Content-Type")?.includes("json") ? await r.json() : await r.text();
    if (!r.ok) throw Object.assign(new Error(data?.error || `HTTP ${r.status}`), { status: r.status, data });
    return data;
  };
  const uid = () => "b-" + Math.random().toString(36).slice(2, 10);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const toast = (html, ms = 4000) => { const t = $("#toast"); t.innerHTML = html; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => t.hidden = true, ms); };
  const fmtSize = n => n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : n > 1024 ? Math.round(n / 1024) + " KB" : n + " B";

  const state = { library: [], week: null, query: "", types: new Set(["text", "image", "file", "page", "markdown"]),
    drafts: [], draft: null, history: [], future: [], saveTimer: null, tab: "edit", weeksInfo: null };

  // ---------- data ----------
  async function loadAll() {
    const [st, lib, drafts] = await Promise.all([api("/api/state"), api("/api/library"), api("/api/drafts")]);
    state.weeksInfo = st; state.library = lib; state.drafts = drafts;
    renderInbox(st);
    if (!state.week && lib.length) state.week = lib[0].week;
    renderWeeks(); renderLibrary();
    if (!state.draft) {
      if (drafts.length) await openDraft(drafts[0].id);
      else await newDraft(defaultTitle());
    }
    renderDraftSelect();
  }
  const defaultTitle = () => { const w = state.library[0]; return w ? `주간 성과 ${w.week} (${w.since ?? ""}~${w.until ?? ""})` : "새 페이지"; };

  function renderInbox(st) {
    const pending = (st.inbox || []).filter(i => !i.complete);
    const pill = $("#inboxStatus");
    pill.title = `받은편지함: ${st.config.inbox_dir}`;
    if (pending.length) {
      pill.className = "pill warn";
      pill.textContent = pending.map(i => `${i.week} 자료 ${i.parts.length}/${i.n_parts ?? "?"} 대기 중`).join(" · ");
    } else { pill.className = "pill"; pill.textContent = `주차 ${st.weeks.length}개 · 받은편지함 비어 있음`; }
    $("#inboxHint").textContent = st.inbox_status?.error ? `받은편지함 오류: ${st.inbox_status.error}` :
      `메일에서 받은 zip을 ${st.config.inbox_dir} 에 넣으면 3초 안에 자동으로 풀립니다. 마지막 확인 ${st.inbox_status?.checked ?? "-"}.`;
  }

  // ---------- library ----------
  const kindOf = b => (["heading", "paragraph", "bullet"].includes(b.type) ? "text" : b.type);
  const usedRefs = () => new Set((state.draft?.blocks || []).map(b => b.source_ref).filter(Boolean));
  const matches = b => {
    if (!state.types.has(kindOf(b))) return false;
    if (!state.query) return true;
    const q = state.query.toLowerCase();
    return (b.text || "").toLowerCase().includes(q) || (b.caption || "").toLowerCase().includes(q) || (b.label || "").toLowerCase().includes(q);
  };
  function renderWeeks() {
    $("#weekList").innerHTML = state.library.map(w => `<div class="week ${w.week === state.week ? "active" : ""}" data-week="${w.week}">
      <span>${w.week}</span><span class="n">${w.since ? w.since.slice(5) + "~" + (w.until || "").slice(5) : ""}</span></div>`).join("") ||
      `<p class="muted small">아직 풀린 주차가 없습니다.</p>`;
    $$("#weekList .week").forEach(el => el.onclick = () => { state.week = el.dataset.week; renderWeeks(); renderLibrary(); });
  }
  const icon = b => ({ heading: "H", paragraph: "¶", bullet: "•", image: "🖼", file: "📎", page: "🌐", markdown: "md" }[b.type] || "?");
  function libBlockHtml(b, used) {
    const body = b.type === "image" ? `<div class="lbl">${esc(b.caption)}</div><img src="/files/${b.src}" alt="">`
      : b.type === "file" ? `<div class="txt">${esc(b.caption)}</div><div class="meta">${esc(b.src.split("/").pop())} · ${fmtSize(b.size)}</div>`
      : b.type === "page" ? `<div class="txt">${esc(b.caption)}</div><div class="meta">결과 페이지 (로컬)</div>`
      : b.type === "markdown" ? `<div class="lbl">${esc(b.caption)}</div><div class="txt">${esc((b.text || "").slice(0, 200))}</div>`
      : `${b.label ? `<div class="lbl">${esc(b.label)}</div>` : ""}<div class="txt">${esc(b.text)}</div>`;
    const action = b.type === "page" ? `<button class="open" data-open="${b.src}">열기</button>` : used ? `<span class="badge">사용됨</span>` : `<button class="open" data-add="${b.id}">＋</button>`;
    return `<div class="lib-block ${used ? "used" : ""}" draggable="${b.type !== "page"}" data-id="${b.id}"><span class="icon">${icon(b)}</span><div class="body">${body}</div>${action}</div>`;
  }
  const openStreams = new Set();   // which <details> the user has expanded; survives re-renders
  function renderLibrary() {
    const w = state.library.find(x => x.week === state.week);
    const used = usedRefs();
    const libEl = $("#library");
    const scrollTop = libEl.scrollTop, midScroll = libEl.parentElement.scrollTop;
    if (!w) { libEl.innerHTML = `<p class="muted">주차를 고르세요.</p>`; return; }
    if (!openStreams.size && w.projects[0]?.streams[0]) openStreams.add(w.projects[0].streams[0].id);
    const parts = [];
    for (const p of w.projects) {
      const streams = p.streams.map(s => {
        const blocks = s.blocks.filter(matches);
        if (!blocks.length) return "";
        return `<details data-stream-id="${esc(s.id)}" ${openStreams.has(s.id) ? "open" : ""}><summary><span>${esc(s.title)}</span><span class="st">${esc(s.status)}</span>
          <button class="addAll" data-stream="${s.id}">전체 추가</button></summary>${blocks.map(b => libBlockHtml(b, used.has(b.id))).join("")}</details>`;
      }).join("");
      if (streams) parts.push(`<div class="proj"><h3>${esc(p.short)}</h3>${streams}</div>`);
    }
    const assets = (w.assets || []).filter(matches);
    const assetsId = `${w.week}:assets`;
    if (assets.length) parts.push(`<div class="proj"><h3>주차 자료</h3><details data-stream-id="${assetsId}" ${openStreams.has(assetsId) ? "open" : ""}><summary><span>README · 주간 보고 · 기타</span></summary>${assets.map(b => libBlockHtml(b, used.has(b.id))).join("")}</details></div>`);
    libEl.innerHTML = parts.join("") || `<p class="muted">조건에 맞는 재료가 없습니다.</p>`;
    $$("#library details").forEach(d => d.ontoggle = () => { d.open ? openStreams.add(d.dataset.streamId) : openStreams.delete(d.dataset.streamId); });
    libEl.scrollTop = scrollTop; libEl.parentElement.scrollTop = midScroll;
    $$("#library [data-add]").forEach(el => el.onclick = e => { e.stopPropagation(); addFromLibrary(el.dataset.add); });
    $$("#library [data-open]").forEach(el => el.onclick = e => { e.stopPropagation(); window.open(`/files/${el.dataset.open}`, "_blank"); });
    $$("#library [data-stream]").forEach(el => el.onclick = e => { e.preventDefault(); e.stopPropagation(); addStream(el.dataset.stream); });
    $$("#library .lib-block[draggable=true]").forEach(el => {
      el.ondragstart = e => { e.dataTransfer.setData("text/x-lib", el.dataset.id); e.dataTransfer.effectAllowed = "copy"; };
      el.onclick = () => addFromLibrary(el.dataset.id);
    });
    const rd = $("#reader"); const keep = rd.scrollTop; renderReader(); rd.scrollTop = keep;
  }
  // ---------- reader (the report, readable, with pick buttons) ----------
  const mdInline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  function mdToHtml(md) {
    const out = []; let list = null;
    const flush = () => { if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; } };
    for (const raw of (md || "").split(/\r?\n/)) {
      const line = raw.trimEnd();
      if (!line.trim()) { flush(); continue; }
      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) { flush(); const l = Math.min(h[1].length + 2, 5); out.push(`<h${l}>${mdInline(h[2])}</h${l}>`); continue; }
      const li = line.match(/^\s*[-*]\s+(.*)$/);
      if (li) { (list ??= []).push(`<li>${mdInline(li[1])}</li>`); continue; }
      if (/^!\[/.test(line)) continue;
      flush(); out.push(`<p>${mdInline(line)}</p>`);
    }
    flush(); return out.join("");
  }
  function renderReader() {
    const w = state.library.find(x => x.week === state.week);
    const used = usedRefs();
    const el = $("#reader");
    if (!w) { el.innerHTML = `<p class="muted">주차를 고르세요.</p>`; return; }
    const plus = b => `<button class="plus" data-add="${b.id}" title="초안에 추가">${used.has(b.id) ? "사용됨" : "＋"}</button>`;
    const elm = (b, inner, cls = "") => `<div class="el ${used.has(b.id) ? "used" : ""} ${cls}" data-id="${b.id}">${inner}${plus(b)}</div>`;
    const parts = [`<div class="wk">${esc(w.week)} · ${esc(w.since || "")} ~ ${esc(w.until || "")}</div>`];
    for (const p of w.projects) {
      parts.push(`<h3 class="proj">${esc(p.short)}</h3>`);
      for (const s of p.streams) {
        const by = { heading: null, paras: [], bullets: [], tail: [], images: [], files: [], pages: [], mds: [] };
        for (const b of s.blocks) {
          if (b.type === "heading") by.heading = b;
          else if (b.type === "paragraph") (["지금 어디까지", "다음"].includes(b.label) ? by.tail : by.paras).push(b);
          else if (b.type === "bullet") by.bullets.push(b);
          else if (b.type === "image") by.images.push(b);
          else if (b.type === "file") by.files.push(b);
          else if (b.type === "page") by.pages.push(b);
          else if (b.type === "markdown") by.mds.push(b);
        }
        const shown = new Set();
        const figs = ns => by.images.filter(i => ns.includes(i.evidence_n) && !shown.has(i.id)).map(i => { shown.add(i.id);
          return elm(i, `<figure><img src="/files/${i.src}" alt=""><figcaption>${esc(i.caption)}</figcaption></figure>`, "fig"); }).join("");
        const html = [`<article data-stream="${esc(s.id)}"><h4>${by.heading ? `<span class="el inl" data-id="${by.heading.id}">${esc(s.title)}</span>` : esc(s.title)}
            <button class="addAll" data-stream="${esc(s.id)}">흐름 전체 추가</button></h4>`];
        if (by.heading) html.push(elm(by.heading, `<p class="muted small">제목 블록: ${esc(s.title)}</p>`));
        for (const b of by.paras) html.push(elm(b, `<p><span class="lbl">${esc(b.label)}</span>${esc(b.text)}</p>`));
        if (by.bullets.length) {
          html.push(`<p class="muted small" style="margin:8px 0 0">대표 결과</p>`);
          for (const b of by.bullets) { html.push(elm(b, `<ul class="res"><li>${esc(b.text)}</li></ul>`)); html.push(figs(b.evidence || [])); }
        }
        const rest = by.images.filter(i => !shown.has(i.id));
        if (rest.length) html.push(rest.map(i => elm(i, `<figure><img src="/files/${i.src}" alt=""><figcaption>${esc(i.caption)}</figcaption></figure>`, "fig")).join(""));
        for (const b of by.tail) html.push(elm(b, `<p class="status"><span class="lbl">${esc(b.label)}</span>${esc(b.text)}</p>`));
        if (by.files.length || by.pages.length) html.push(`<div class="files">${by.pages.map(pg => `<button class="chip" data-open="${pg.src}">🌐 ${esc(pg.caption)} 열기</button>`).join("")}${by.files.map(f => `<button class="chip" data-add="${f.id}" title="첨부로 추가">📎 ${esc(f.src.split("/").pop())} · ${fmtSize(f.size)}${used.has(f.id) ? " ✓" : " ＋"}</button>`).join("")}</div>`);
        for (const m of by.mds) html.push(`<details class="md"><summary>md 전문 (${esc(m.caption)}) <button class="chip" data-add="${m.id}">전체 ＋</button></summary><pre>${esc(m.text)}</pre></details>`);
        html.push("</article>");
        parts.push(html.join(""));
      }
    }
    const weekly = (w.assets || []).find(a => a.src.endsWith("weekly.md"));
    if (weekly) parts.push(`<div class="weekly"><article data-stream="${esc(weekly.id)}"><h4>주간 방향 보고 <button class="addAll" data-add="${weekly.id}">전체 추가</button></h4><div class="el" data-id="${weekly.id}">${mdToHtml(weekly.text)}</div></article></div>`);
    const readme = (w.assets || []).find(a => a.src.endsWith("README.md"));
    if (readme) parts.push(`<details class="md"><summary>패키지 README</summary><pre>${esc(readme.text)}</pre></details>`);
    el.innerHTML = parts.join("");
    $$("#reader [data-add]", el).forEach(b => b.onclick = e => { e.stopPropagation(); e.preventDefault(); addFromLibrary(b.dataset.add); });
    $$("#reader [data-open]", el).forEach(b => b.onclick = e => { e.stopPropagation(); window.open(`/files/${b.dataset.open}`, "_blank"); });
    $$("#reader [data-stream].addAll", el).forEach(b => b.onclick = e => { e.stopPropagation(); addStream(b.dataset.stream); });
  }
  // text selection inside the reader → "선택한 글 추가"
  document.addEventListener("selectionchange", () => {
    const sel = getSelection(); const btn = $("#selAdd");
    if (!sel || sel.isCollapsed || !sel.toString().trim() || !$("#reader").contains(sel.anchorNode)) { btn.hidden = true; return; }
    const r = sel.getRangeAt(0).getBoundingClientRect();
    btn.style.left = Math.max(8, r.left) + "px"; btn.style.top = Math.max(8, r.top - 34) + "px"; btn.hidden = false;
  });
  $("#selAdd").onmousedown = e => e.preventDefault();
  $("#selAdd").onclick = () => {
    const sel = getSelection(); const text = sel.toString().trim(); if (!text) return;
    const art = sel.anchorNode.parentElement?.closest("[data-stream]");
    state.draft.blocks.push({ id: uid(), type: "paragraph", text: text.replace(/\s+/g, " "), source_ref: art ? art.dataset.stream + ":sel" : null });
    commit(); renderEditor(); sel.removeAllRanges(); $("#selAdd").hidden = true; toast("선택한 글을 문단으로 추가했습니다.");
  };
  $$(".midTabs button[data-mid]").forEach(btn => btn.onclick = () => { $$(".midTabs button").forEach(b => b.classList.toggle("active", b === btn));
    const r = btn.dataset.mid === "reader"; $("#reader").hidden = !r; $("#library").hidden = r; });

  function findLib(id) {
    for (const w of state.library) {
      for (const a of w.assets || []) if (a.id === id) return a;
      for (const p of w.projects) for (const s of p.streams) for (const b of s.blocks) if (b.id === id) return b;
    }
    return null;
  }
  // library block -> draft blocks
  function toDraftBlocks(b) {
    const base = { id: uid(), source_ref: b.id };
    switch (b.type) {
      case "heading": return [{ ...base, type: "heading", level: 2, text: b.text }];
      case "paragraph": return [{ ...base, type: "paragraph", text: b.label ? `**${b.label}:** ${b.text}` : b.text }];
      case "bullet": return [{ ...base, type: "bullets", items: [b.text] }];
      case "image": return [{ ...base, type: "image", src: b.src, caption: b.caption || "" }];
      case "file": return [{ ...base, type: "file", src: b.src, caption: b.caption || b.src.split("/").pop() }];
      case "markdown": return mdToBlocks(b.text || "", b.id);
      default: return [];
    }
  }
  function mdToBlocks(md, ref) {
    const out = []; let bullets = null;
    const flush = () => { if (bullets) { out.push(bullets); bullets = null; } };
    for (const raw of md.split(/\r?\n/)) {
      const line = raw.trimEnd();
      if (!line.trim()) { flush(); continue; }
      const h = line.match(/^(#{1,3})\s+(.*)$/);
      if (h) { flush(); out.push({ id: uid(), source_ref: ref, type: "heading", level: h[1].length >= 3 ? 3 : 2, text: h[2] }); continue; }
      const li = line.match(/^\s*[-*]\s+(.*)$/);
      if (li) { (bullets ??= { id: uid(), source_ref: ref, type: "bullets", items: [] }).items.push(li[1]); continue; }
      if (/^!\[/.test(line) || /^_.*_$/.test(line) && line.length < 40) { flush(); continue; }
      flush(); out.push({ id: uid(), source_ref: ref, type: "paragraph", text: line.replace(/^>\s?/, "") });
    }
    flush(); return out;
  }
  function addFromLibrary(id, index = null) {
    const b = findLib(id); if (!b) return;
    const blocks = toDraftBlocks(b);
    if (!blocks.length) return;
    // consecutive bullets from the same stream merge into one list
    const at = index ?? state.draft.blocks.length;
    const prev = state.draft.blocks[at - 1];
    if (blocks.length === 1 && blocks[0].type === "bullets" && prev?.type === "bullets" && (prev.source_ref || "").split(":").slice(0, 3).join(":") === id.split(":").slice(0, 3).join(":")) {
      prev.items.push(...blocks[0].items); prev.merged = [...(prev.merged || []), id];
    } else state.draft.blocks.splice(at, 0, ...blocks);
    commit(); renderEditor(); renderLibrary();
  }
  function addStream(streamId) {
    const w = state.library.find(x => x.week === state.week);
    const s = w?.projects.flatMap(p => p.streams).find(x => x.id === streamId); if (!s) return;
    for (const b of s.blocks.filter(x => x.type !== "page" && x.type !== "markdown" && x.type !== "file" && matches(x))) addFromLibrary(b.id);
    toast("흐름의 글과 캡처를 모두 추가했습니다 (파일·페이지는 제외).");
  }

  // ---------- drafts ----------
  function renderDraftSelect() {
    $("#draftSelect").innerHTML = state.drafts.map(d => `<option value="${d.id}" ${d.id === state.draft?.id ? "selected" : ""}>${esc(d.title)}${d.confluence?.page_id ? " ↑" : ""}</option>`).join("");
  }
  async function refreshDrafts() { state.drafts = await api("/api/drafts"); renderDraftSelect(); }
  async function openDraft(id) {
    state.draft = await api(`/api/drafts/${id}`); state.history = []; state.future = [];
    $("#draftTitle").value = state.draft.title; renderEditor(); renderLibrary(); renderDraftSelect();
  }
  async function newDraft(title) { const d = await api("/api/drafts", { method: "POST", body: { title } }); await refreshDrafts(); await openDraft(d.id); }
  function commit() {
    state.history.push(JSON.stringify(state.draft.blocks)); if (state.history.length > 50) state.history.shift(); state.future = [];
    scheduleSave();
  }
  function scheduleSave() {
    $("#saveState").textContent = "저장 중…"; clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(async () => {
      try { state.draft.title = $("#draftTitle").value || "제목 없음"; const saved = await api(`/api/drafts/${state.draft.id}`, { method: "PUT", body: state.draft });
        state.draft.updated = saved.updated; $("#saveState").textContent = "저장됨"; await refreshDrafts(); }
      catch (e) { $("#saveState").textContent = "저장 실패: " + e.message; }
    }, 500);
  }
  function undo() { if (!state.history.length) return; state.future.push(JSON.stringify(state.draft.blocks)); state.draft.blocks = JSON.parse(state.history.pop()); scheduleSave(); renderEditor(); renderLibrary(); }
  function redo() { if (!state.future.length) return; state.history.push(JSON.stringify(state.draft.blocks)); state.draft.blocks = JSON.parse(state.future.pop()); scheduleSave(); renderEditor(); renderLibrary(); }

  // ---------- editor ----------
  function blockInner(b) {
    switch (b.type) {
      case "heading": return `<div contenteditable="true" data-field="text" data-ph="제목">${esc(b.text)}</div>`;
      case "paragraph": return `<div contenteditable="true" data-field="text" data-ph="문단을 입력하세요 (**굵게**, _기울임_, [링크](주소))">${esc(b.text)}</div>`;
      case "bullets": return `<ul class="items">${(b.items || [""]).map((it, i) => `<li contenteditable="true" data-item="${i}" data-ph="항목">${esc(it)}</li>`).join("")}</ul>`;
      case "image": return `<div class="figure"><img src="/files/${b.src}" alt=""><input class="caption" data-field="caption" placeholder="캡션" value="${esc(b.caption)}"></div>`;
      case "file": return `<div class="filebox"><span>📎</span><div style="flex:1"><input class="caption" data-field="caption" placeholder="설명" value="${esc(b.caption)}"><div class="name">${esc(b.src.split("/").pop())}</div></div></div>`;
      case "divider": return `<hr>`;
      case "callout": return `<div class="callout" contenteditable="true" data-field="text" data-ph="강조할 내용">${esc(b.text)}</div>`;
      default: return `<em class="muted">알 수 없는 블록 ${esc(b.type)}</em>`;
    }
  }
  function renderEditor() {
    const ed = $("#editor");
    const blocks = state.draft?.blocks || [];
    ed.innerHTML = blocks.map((b, i) => `<div class="block" data-i="${i}" data-type="${b.type}" data-level="${b.level || ""}" draggable="false">
      <span class="handle" title="끌어서 이동" draggable="true">⋮⋮</span>
      <div class="content">${blockInner(b)}</div>
      <div class="menu">
        <button data-act="up" title="위로">↑</button><button data-act="down" title="아래로">↓</button>
        ${b.type === "heading" ? `<button data-act="level" title="제목 크기">H${b.level === 3 ? 3 : 2}</button>` : ""}
        ${b.type === "paragraph" ? `<button data-act="toCallout" title="강조 상자로">▣</button>` : ""}
        ${b.type === "callout" ? `<button data-act="toPara" title="문단으로">¶</button>` : ""}
        <button data-act="dup" title="복제">⧉</button><button data-act="del" title="삭제">✕</button>
      </div></div>`).join("");
    $("#dropHint").hidden = blocks.length > 0;
    wireEditor();
    if (state.tab === "preview") renderPreview();
  }
  function wireEditor() {
    const ed = $("#editor");
    $$(".block", ed).forEach(el => {
      const i = +el.dataset.i, b = state.draft.blocks[i];
      $$("[contenteditable]", el).forEach(ce => {
        ce.oninput = () => { if (ce.dataset.item !== undefined) b.items[+ce.dataset.item] = ce.innerText; else b[ce.dataset.field] = ce.innerText; scheduleSaveSoft(); };
        ce.onkeydown = e => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (ce.dataset.item !== undefined) { b.items.splice(+ce.dataset.item + 1, 0, ""); commit(); renderEditor(); focusBlock(i, +ce.dataset.item + 1); }
            else { state.draft.blocks.splice(i + 1, 0, { id: uid(), type: "paragraph", text: "", source_ref: null }); commit(); renderEditor(); focusBlock(i + 1); }
          } else if (e.key === "Backspace" && ce.innerText === "") {
            e.preventDefault();
            if (ce.dataset.item !== undefined && b.items.length > 1) { b.items.splice(+ce.dataset.item, 1); commit(); renderEditor(); focusBlock(i, Math.max(0, +ce.dataset.item - 1)); }
            else if (ce.dataset.item === undefined || b.items.length <= 1) { state.draft.blocks.splice(i, 1); commit(); renderEditor(); focusBlock(i - 1); }
          }
        };
        ce.onblur = () => { if (state.history.at(-1) !== JSON.stringify(state.draft.blocks)) commit(); };
      });
      $$("input.caption", el).forEach(inp => inp.oninput = () => { b.caption = inp.value; scheduleSaveSoft(); });
      $$(".menu button", el).forEach(btn => btn.onclick = () => blockAction(btn.dataset.act, i));
      const h = $(".handle", el);
      h.ondragstart = e => { e.dataTransfer.setData("text/x-move", String(i)); e.dataTransfer.effectAllowed = "move"; el.classList.add("dragging"); };
      h.ondragend = () => el.classList.remove("dragging");
    });
    ed.ondragover = e => { e.preventDefault(); showDropline(e.clientY); };
    ed.ondragleave = e => { if (e.target === ed) clearDropline(); };
    ed.ondrop = e => {
      e.preventDefault(); const at = dropIndex(e.clientY); clearDropline();
      const lib = e.dataTransfer.getData("text/x-lib"), mv = e.dataTransfer.getData("text/x-move");
      if (lib) addFromLibrary(lib, at);
      else if (mv !== "") { const from = +mv; const [blk] = state.draft.blocks.splice(from, 1); state.draft.blocks.splice(at > from ? at - 1 : at, 0, blk); commit(); renderEditor(); }
    };
  }
  let softTimer = null;
  function scheduleSaveSoft() { clearTimeout(softTimer); softTimer = setTimeout(() => { scheduleSave(); }, 400); }
  function focusBlock(i, item) {
    const el = $(`#editor .block[data-i="${i}"]`); if (!el) return;
    const ce = item !== undefined ? $(`[data-item="${item}"]`, el) : $("[contenteditable], input", el);
    if (ce) { ce.focus(); if (ce.isContentEditable) { const r = document.createRange(); r.selectNodeContents(ce); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r); } }
  }
  function blockAction(act, i) {
    const bl = state.draft.blocks, b = bl[i];
    if (act === "up" && i > 0) [bl[i - 1], bl[i]] = [bl[i], bl[i - 1]];
    if (act === "down" && i < bl.length - 1) [bl[i + 1], bl[i]] = [bl[i], bl[i + 1]];
    if (act === "dup") bl.splice(i + 1, 0, { ...JSON.parse(JSON.stringify(b)), id: uid() });
    if (act === "del") bl.splice(i, 1);
    if (act === "level") b.level = b.level === 3 ? 2 : 3;
    if (act === "toCallout") b.type = "callout";
    if (act === "toPara") b.type = "paragraph";
    commit(); renderEditor(); renderLibrary();
  }
  function dropIndex(y) {
    const els = $$("#editor .block"); let idx = els.length;
    for (const el of els) { const r = el.getBoundingClientRect(); if (y < r.top + r.height / 2) { idx = +el.dataset.i; break; } }
    return idx;
  }
  function showDropline(y) {
    clearDropline(); const idx = dropIndex(y); const els = $$("#editor .block"); const line = document.createElement("div"); line.className = "dropline";
    if (idx >= els.length) $("#editor").appendChild(line); else els[idx].before(line);
  }
  function clearDropline() { $$("#editor .dropline").forEach(l => l.remove()); }

  // ---------- preview ----------
  const inlineHtml = s => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^\w*])_(.+?)_(?![\w*])/g, "$1<em>$2</em>").replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2">$1</a>');
  function previewHtml(blocks) {
    return blocks.map(b => {
      switch (b.type) {
        case "heading": return `<h${b.level === 3 ? 3 : 2}>${inlineHtml(b.text)}</h${b.level === 3 ? 3 : 2}>`;
        case "paragraph": return `<p>${inlineHtml(b.text)}</p>`;
        case "bullets": return `<ul>${(b.items || []).map(i => `<li>${inlineHtml(i)}</li>`).join("")}</ul>`;
        case "image": return `<p><img src="/files/${b.src}" alt=""></p>${b.caption ? `<p><em>${esc(b.caption)}</em></p>` : ""}`;
        case "file": return `<p><span class="att">📎 ${esc(b.caption || b.src)}</span></p>`;
        case "divider": return `<hr>`;
        case "callout": return `<div class="info">${inlineHtml(b.text)}</div>`;
        default: return "";
      }
    }).join("\n");
  }
  async function renderPreview() {
    const blocks = state.draft.blocks;
    let xhtml = "", err = null;
    try { ({ xhtml, error: err } = await api("/api/preview", { method: "POST", body: { blocks } })); } catch (e) { err = e.message; }
    $("#preview").innerHTML = `<div class="doc"><h1 style="font-size:24px">${esc($("#draftTitle").value)}</h1>${previewHtml(blocks)}</div>
      <details><summary class="muted small">Confluence 저장 형식 원문 ${err ? `· <span class="error">변환 오류: ${esc(err)}</span>` : "· 검증 통과"}</summary><pre>${esc(xhtml)}</pre></details>`;
  }

  // ---------- publish / export / copy ----------
  async function openPublish() {
    const dlg = $("#publishDlg"); $("#pubError").textContent = ""; $("#pubTitle").value = $("#draftTitle").value;
    const cfg = state.weeksInfo.config.confluence;
    const b = state.draft.confluence;
    $("#pubBinding").textContent = b?.page_id ? `이미 올린 페이지(${b.page_id}, v${b.version})를 갱신합니다.` : "새 페이지를 만듭니다.";
    dlg.showModal();
    try {
      const spaces = await api("/api/confluence/spaces");
      $("#pubSpace").innerHTML = spaces.map(s => `<option value="${esc(s.key)}" ${s.key === (b?.space || cfg.default_space) ? "selected" : ""}>${esc(s.key)} · ${esc(s.name)}</option>`).join("");
      $("#pubParent").innerHTML = cfg.default_parent_id ? `<option value="${esc(cfg.default_parent_id)}" selected>기본 상위 페이지 (${esc(cfg.default_parent_id)})</option>` : "";
    } catch (e) { $("#pubError").textContent = e.message; }
  }
  $("#pubTest").onclick = async () => {
    $("#pubError").textContent = "연결 확인 중…";
    try { const w = await api("/api/confluence/whoami");
      $("#pubError").textContent = ""; $("#pubBinding").textContent = `연결 성공: ${w.displayName || w.username} (${w.username}) · 인증 ${w.auth === "basic" ? "Basic(email+토큰)" : "Bearer(PAT)"} · ${w.base_url}`; }
    catch (e) { $("#pubError").textContent = e.message; }
  };
  let parentTimer = null;
  $("#pubParentQuery").oninput = () => { clearTimeout(parentTimer); parentTimer = setTimeout(async () => {
    try { const pages = await api(`/api/confluence/search?space=${encodeURIComponent($("#pubSpace").value)}&q=${encodeURIComponent($("#pubParentQuery").value)}`);
      $("#pubParent").innerHTML = pages.map(p => `<option value="${esc(p.id)}">${esc(p.title)} (${esc(p.id)})</option>`).join("") || `<option disabled>결과 없음</option>`; }
    catch (e) { $("#pubError").textContent = e.message; } }, 350); };
  $("#publishDlg").onclose = async () => {
    if ($("#publishDlg").returnValue !== "go") return;
    const body = { space: $("#pubSpace").value, parent_id: $("#pubParent").value || null, title: $("#pubTitle").value };
    toast("Confluence에 올리는 중…", 60000);
    try { const res = await api(`/api/confluence/publish/${state.draft.id}`, { method: "POST", body });
      state.draft.confluence = res; await refreshDrafts();
      toast(`올렸습니다 (v${res.version}). <a href="${esc(res.url)}" target="_blank">페이지 열기</a>`, 12000); }
    catch (e) { toast(`실패: ${esc(e.message)}`, 12000); }
  };
  $("#publishBtn").onclick = openPublish;
  $("#copyHtml").onclick = async () => {
    try {
      const r = await api(`/api/paste/${state.draft.id}`);
      const html = r.html.replace(/<div class="how"[\s\S]*?<\/div><hr>/, "");   // drop the instruction box from the copy
      const text = state.draft.blocks.map(b => b.text || (b.items || []).join("\n") || b.caption || "").join("\n\n");
      await navigator.clipboard.write([new ClipboardItem({ "text/html": new Blob([html], { type: "text/html" }), "text/plain": new Blob([text], { type: "text/plain" }) })]);
      const extra = r.manual_files.length ? ` 영상·파일 ${r.manual_files.length}개는 '첨부 폴더'에서 끌어 넣으세요.` : "";
      toast("본문을 그림까지 포함해 복사했습니다. Confluence 편집기에 Ctrl+V." + extra, 7000);
    } catch (e) {
      toast("이 브라우저가 서식 복사를 막았습니다. '첨부 폴더'의 paste.html을 열어 Ctrl+A, Ctrl+C 하세요. (" + esc(e.message) + ")", 9000);
    }
  };
  $("#exportBtn").onclick = async () => {
    try { const r = await api(`/api/export/${state.draft.id}`, { method: "POST", body: {} });
      await api("/api/open", { method: "POST", body: { path: r.folder } });
      toast(`폴더를 열었습니다. paste.html을 브라우저로 열어 전체 복사 → Confluence에 붙여넣기. 수동 첨부 ${r.manual_files.length}개.`, 8000); } catch (e) { toast("실패: " + esc(e.message)); }
  };

  // ---------- top bar ----------
  $("#draftSelect").onchange = e => openDraft(e.target.value);
  $("#newDraft").onclick = () => newDraft(prompt("새 초안 제목", defaultTitle()) || defaultTitle());
  $("#dupDraft").onclick = async () => { const d = await api(`/api/drafts/${state.draft.id}/duplicate`, { method: "POST", body: {} }); await refreshDrafts(); await openDraft(d.id); };
  $("#delDraft").onclick = async () => { if (!confirm(`'${state.draft.title}' 초안을 삭제할까요?`)) return; await api(`/api/drafts/${state.draft.id}`, { method: "DELETE" }); state.draft = null; await refreshDrafts(); await loadAll(); };
  $("#draftTitle").oninput = scheduleSaveSoft;
  $("#undoBtn").onclick = undo; $("#redoBtn").onclick = redo;
  $("#addPara").onclick = () => { state.draft.blocks.push({ id: uid(), type: "paragraph", text: "", source_ref: null }); commit(); renderEditor(); focusBlock(state.draft.blocks.length - 1); };
  $("#addHead").onclick = () => { state.draft.blocks.push({ id: uid(), type: "heading", level: 2, text: "", source_ref: null }); commit(); renderEditor(); focusBlock(state.draft.blocks.length - 1); };
  $("#addDivider").onclick = () => { state.draft.blocks.push({ id: uid(), type: "divider", source_ref: null }); commit(); renderEditor(); };
  $$(".tabs button").forEach(btn => btn.onclick = () => { state.tab = btn.dataset.tab; $$(".tabs button").forEach(b => b.classList.toggle("active", b === btn));
    $("#editor").hidden = state.tab !== "edit"; $("#preview").hidden = state.tab !== "preview"; $("#dropHint").hidden = state.tab !== "edit" || state.draft.blocks.length > 0; if (state.tab === "preview") renderPreview(); });
  $("#search").oninput = e => { state.query = e.target.value.trim(); renderLibrary(); };
  $$("#typeChips input").forEach(cb => cb.onchange = () => { cb.checked ? state.types.add(cb.value) : state.types.delete(cb.value); renderLibrary(); });
  document.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); scheduleSave(); }
  });

  // inbox polling: pick up weeks that arrive while the page is open
  setInterval(async () => { try { const st = await api("/api/state"); renderInbox(st);
    if (st.weeks.length !== state.weeksInfo?.weeks.length) { state.library = await api("/api/library"); state.weeksInfo = st; if (!state.week && state.library.length) state.week = state.library[0].week; renderWeeks(); renderLibrary(); } } catch {} }, 5000);

  loadAll().catch(e => toast("초기화 실패: " + esc(e.message), 10000));
})();
