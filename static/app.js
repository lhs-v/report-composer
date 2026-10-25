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
    state.pageOrigin = st.page_origin;
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
    $("#weekList").innerHTML = state.library.map(w => `<div class="week ${w.week === state.week ? "active" : ""}" data-week="${esc(w.week)}">
      <span>${esc(w.week)}</span><span class="n">${w.since ? esc(String(w.since).slice(5) + "~" + String(w.until || "").slice(5)) : ""}</span></div>`).join("") ||
      `<p class="muted small">아직 풀린 주차가 없습니다.</p>`;
    $$("#weekList .week").forEach(el => el.onclick = () => { state.week = el.dataset.week; renderWeeks(); renderLibrary(); });
  }
  const icon = b => ({ heading: "H", paragraph: "¶", bullet: "•", image: "🖼", file: "📎", page: "🌐", markdown: "md" }[b.type] || "?");
  // package format v2: chapters (정리 단위) arrive as streams carrying kind/value/section/tier
  const chapterBadges = s => `<span class="chbs">${[["kind", s.kind], ["value", s.value], ["section", s.section !== s.kind ? s.section : ""]].filter(([, v]) => v)
    .map(([k, v]) => `<span class="chb ${k}">${esc(v)}</span>`).join("")}</span>`;
  const byTier = streams => [streams.filter(s => s.tier !== "appendix"), streams.filter(s => s.tier === "appendix")];
  const projCount = p => p.schema < 2 ? `흐름 ${p.streams.length}개` : p.mode === "one_line" ? "한 줄" : p.mode === "daily_list" ? "작업 단위 목록" : `정리 단위 ${p.streams.length}개`;
  function libBlockHtml(b, used) {
    const body = b.type === "image" ? `<div class="lbl">${esc(b.caption)}</div><img src="/files/${esc(b.src)}" alt="">`
      : b.type === "file" ? `<div class="txt">${esc(b.caption)}</div><div class="meta">${esc(b.src.split("/").pop())} · ${fmtSize(b.size)}</div>`
      : b.type === "page" ? `<div class="txt">${esc(b.caption)}</div><div class="meta">결과 페이지 (로컬)</div>`
      : b.type === "markdown" ? `<div class="lbl">${esc(b.caption)}</div><div class="txt">${esc((b.text || "").slice(0, 200))}</div>`
      : `${b.label ? `<div class="lbl">${esc(b.label)}</div>` : ""}<div class="txt">${esc(b.text)}</div>`;
    const action = b.type === "page" ? `<button class="open" data-view="${esc(b.src)}" data-title="${esc(b.caption)}">열기</button>` : used ? `<span class="badge">사용됨</span>` : `<button class="open" data-add="${esc(b.id)}">＋</button>`;
    const opt = b.optional ? ` title="초안에 기본으로 넣지 않는 조각입니다 (흐름 전체 추가에서 빠짐)"` : "";
    return `<div class="lib-block ${used ? "used" : ""} ${b.optional ? "optional" : ""}"${opt} draggable="${b.type !== "page"}" data-id="${esc(b.id)}"><span class="icon">${icon(b)}</span><div class="body">${body}</div>${action}</div>`;
  }
  const openStreams = new Set();   // which stream <details> the user has expanded; survives re-renders
  const folds = new Set(JSON.parse(localStorage.getItem("cp.folds") || "[]"));   // collapsed projects/streams, remembered
  const saveFolds = () => { try { localStorage.setItem("cp.folds", JSON.stringify([...folds])); } catch {} };
  const foldable = (key, cls, summary, body) => `<details class="${cls}" data-fold="${esc(key)}" ${folds.has(key) ? "" : "open"}><summary>${summary}</summary>${body}</details>`;
  function wireFolds(root) {
    $$("details[data-fold]", root).forEach(d => d.ontoggle = () => {
      const shown = d.dataset.inverse ? !d.open : d.open;   // inverse folds start closed and remember being opened
      shown ? folds.delete(d.dataset.fold) : folds.add(d.dataset.fold); saveFolds();
    });
    $$("details[data-stream-id]", root).forEach(d => d.ontoggle = () => { d.open ? openStreams.add(d.dataset.streamId) : openStreams.delete(d.dataset.streamId); });
  }
  function renderLibrary() {
    const w = state.library.find(x => x.week === state.week);
    const used = usedRefs();
    const libEl = $("#library");
    const scrollTop = libEl.scrollTop, midScroll = libEl.parentElement.scrollTop;
    if (!w) { libEl.innerHTML = `<p class="muted">주차를 고르세요.</p>`; return; }
    const first = (w.schema >= 2 ? w.projects.find(p => p.streams.length) : w.projects[0])?.streams[0];
    if (!openStreams.size && first) openStreams.add(first.id);
    const parts = [];
    const streamHtml = s => {
      const blocks = s.blocks.filter(matches);
      if (!blocks.length) return "";
      return `<details class="${s.value === "생략" ? "skip" : ""}" data-stream-id="${esc(s.id)}" ${openStreams.has(s.id) ? "open" : ""}><summary><span>${esc(s.title)}</span><span class="st">${s.chapter ? chapterBadges(s) : esc(s.status)}</span>
          <button class="addAll" data-stream="${esc(s.id)}">전체 추가</button></summary>${blocks.filter(b => !b.in_page).map(b => libBlockHtml(b, used.has(b.id))).join("")}${
          blocks.some(b => b.in_page) ? `<details class="pfiles"><summary>페이지 안 파일 ${blocks.filter(b => b.in_page).length}개</summary>${blocks.filter(b => b.in_page).map(b => libBlockHtml(b, used.has(b.id))).join("")}</details>` : ""}</details>`;
    };
    for (const p of w.projects) {
      if (p.schema >= 2) {
        const [main, appendix] = byTier(p.streams);
        const apx = appendix.map(streamHtml).join("");
        let body = main.map(streamHtml).join("") + (apx ? `<div class="tierHead">부록</div>${apx}` : "");
        const q = state.query.toLowerCase();
        const own = (p.blocks || []).filter(matches).map(b => libBlockHtml(b, used.has(b.id))).join("");
        if (p.mode === "one_line") body = own;
        else body = own + body;
        if (p.error) body = `<p class="err">이 프로젝트를 읽지 못했습니다: ${esc(p.error)}</p>` + body;
        if (body) parts.push(foldable(`lib:${w.week}:${p.short}`, "proj", `<h3>${esc(p.short)} <span class="n">${projCount(p)}</span></h3>`, body));
        continue;
      }
      const streams = p.streams.map(streamHtml).join("");
      if (streams) parts.push(foldable(`lib:${w.week}:${p.short}`, "proj", `<h3>${esc(p.short)} <span class="n">흐름 ${p.streams.length}개</span></h3>`, streams));
    }
    const assets = (w.assets || []).filter(matches);
    const assetsId = `${w.week}:assets`;
    if (assets.length) parts.push(foldable(`lib:${w.week}:assets`, "proj", `<h3>주차 자료</h3>`, `<details data-stream-id="${assetsId}" ${openStreams.has(assetsId) ? "open" : ""}><summary><span>README · 주간 보고 · 기타</span></summary>${assets.map(b => libBlockHtml(b, used.has(b.id))).join("")}</details>`));
    libEl.innerHTML = parts.join("") || `<p class="muted">조건에 맞는 재료가 없습니다.</p>`;
    wireFolds(libEl);
    libEl.scrollTop = scrollTop; libEl.parentElement.scrollTop = midScroll;
    $$("#library [data-add]").forEach(el => el.onclick = e => { e.stopPropagation(); e.preventDefault(); addFromLibrary(el.dataset.add); });
    $$("#library [data-view]").forEach(el => el.onclick = e => { e.stopPropagation(); e.preventDefault(); openPageViewer(el.dataset.view, el.dataset.title); });
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
    const plus = b => `<button class="plus" data-add="${esc(b.id)}" title="초안에 추가">${used.has(b.id) ? "사용됨" : "＋"}</button>`;
    const elm = (b, inner, cls = "") => `<div class="el ${used.has(b.id) ? "used" : ""} ${cls}" data-id="${esc(b.id)}">${inner}${plus(b)}</div>`;
    const chipsHtml = (pages, files) => (files.length || pages.length) ? `<div class="files">${pages.map(pg => `<button class="chip" data-view="${esc(pg.src)}" data-title="${esc(pg.caption)}">🌐 ${esc(pg.caption)} 열어서 집어오기</button>`).join("")}${files.map(f => `<button class="chip" data-add="${esc(f.id)}" title="첨부로 추가">📎 ${esc(f.src.split("/").pop())} · ${fmtSize(f.size)}${used.has(f.id) ? " ✓" : " ＋"}</button>`).join("")}</div>` : "";
    const mediaHtml = files => files.map(f => {
      const ext = f.src.split(".").pop().toLowerCase();
      const tag = ["mp4", "webm", "mov"].includes(ext) ? "video" : ["mp3", "wav", "ogg", "m4a"].includes(ext) ? "audio" : null;
      return tag ? `<div class="media"><${tag} controls preload="metadata" src="/files/${esc(f.src)}"></${tag}><div class="cap">${esc(f.caption)} <button class="chip" data-add="${esc(f.id)}">${used.has(f.id) ? "첨부됨 ✓" : "첨부로 추가 ＋"}</button></div></div>` : "";
    }).join("");
    const mdFullHtml = m => `<details class="md"><summary>md 전문 (${esc(m.caption)}) <button class="chip" data-add="${esc(m.id)}">전체 ＋</button></summary><pre>${esc(m.text)}</pre></details>`;
    const fig = i => elm(i, `<figure><img src="/files/${esc(i.src)}" alt=""><figcaption>${esc(i.caption)}</figcaption></figure>`, "fig");
    // v2: one chapter (정리 단위) — lead, sentences, results, then the change line and the units folded as 근거
    const chapterHtml = s => {
      const by = { heading: null, lead: null, change: null, units: null, bullets: [], images: [], pages: [], files: [], texts: [], mds: [], inPage: [] };
      for (const b of s.blocks) {
        if (b.in_page) by.inPage.push(b);
        else if (b.type === "heading") by.heading = b;
        else if (b.type === "paragraph") { if (b.role === "units") by.units = b; else if (b.optional) by.change = b; else by.lead = b; }
        else if (b.type === "bullet") by.bullets.push(b);
        else if (b.type === "image") by.images.push(b);
        else if (b.type === "page") by.pages.push(b);
        else if (b.type === "file") by.files.push(b);
        else if (b.type === "markdown") (b.eid ? by.texts : by.mds).push(b);
      }
      const html = [];
      if (by.lead) html.push(elm(by.lead, `<p class="lead">${esc(by.lead.text)}</p>`));
      if (by.bullets.length) html.push(by.bullets.map(b => elm(b, `<ul class="res"><li>${esc(b.text)}</li></ul>`)).join(""));
      html.push(by.images.map(fig).join(""));
      for (const t of by.texts) {           // reply excerpts: folded, they can be long and wander off the topic
        const text = t.text || "", cut = text.length > 600;
        html.push(`<details class="excerptFold"><summary>${esc(t.caption)}</summary>${elm(t, `<div class="excerpt">${mdToHtml(cut ? text.slice(0, 600) + " …" : text)}</div>`)}</details>`);
      }
      html.push(chipsHtml(by.pages, by.files), mediaHtml(by.files));
      if (by.inPage.length) {               // what a page carries stays folded under it
        const imgs = by.inPage.filter(b => b.type === "image"), other = by.inPage.filter(b => b.type !== "image");
        html.push(`<details class="pfiles"><summary>페이지 안 파일 ${by.inPage.length}개</summary>${imgs.map(fig).join("")}${chipsHtml([], other)}${mediaHtml(other)}</details>`);
      }
      if (by.change) html.push(elm(by.change, `<p class="change">${esc(by.change.label)} · ${esc(by.change.text)}</p>`, "opt"));
      if (by.units) html.push(`<details class="units"><summary>근거</summary>${elm(by.units, `<p class="ulines">${esc(by.units.text)}</p>`, "opt")}</details>`);
      if (s.home && s.home.length)            // v3: files the sender kept home are named, not shown
        html.push(`<p class="home">집에 있음 · ${s.home.map(h => `${esc(h.title)}: ${h.files.slice(0, 3).map(esc).join(", ")}${h.files.length > 3 ? ` 외 ${h.files.length - 3}개` : ""}`).join(" · ")}</p>`);
      for (const m of by.mds) html.push(mdFullHtml(m));
      const title = by.heading ? `<span class="el inl" data-id="${esc(by.heading.id)}">${esc(s.title)}</span>` : esc(s.title);
      const head = `<h4>${title}${chapterBadges(s)}</h4><button class="addAll" data-stream="${esc(s.id)}">흐름 전체 추가</button>`;
      const skip = s.value === "생략";
      const fold = skip ? `skip:${s.id}` : s.id;
      const open = skip ? folds.has(fold) : !folds.has(fold);   // a 생략 chapter's key means "opened"
      return `<details class="stream ${skip ? "skip" : ""}" data-stream="${esc(s.id)}" data-fold="${esc(fold)}" ${skip ? 'data-inverse="1"' : ""} ${open ? "open" : ""}><summary>${head}</summary><div class="body">${html.join("")}</div></details>`;
    };
    const v2ProjectHtml = p => {
      const [main, appendix] = byTier(p.streams);
      const own = role => (p.blocks || []).filter(b => b.role === role).map(b => elm(b, `<p class="${role === "one_line" ? "oneLine" : "overview"}">${esc(b.text)}</p>`)).join("");
      const err = p.error ? `<p class="err">이 프로젝트를 읽지 못했습니다: ${esc(p.error)}</p>` : "";
      const copies = (p.blocks || []).filter(b => !b.role);      // packaged results no chapter cites
      const copiesHtml = copies.filter(b => b.type === "image").map(fig).join("") +
        chipsHtml(copies.filter(b => b.type === "page"), copies.filter(b => b.type === "file")) + mediaHtml(copies.filter(b => b.type === "file"));
      const loose = p.mode !== "one_line" && copies.length ? `<div class="tierHead">정리 단위 밖 결과물</div>${copiesHtml}` : "";
      const late = (p.records || []).filter(r => r.sent === "core" && !r.arrived);   // v3: parts still on the way
      const lateHtml = late.length ? `<p class="late">아직 안 온 결과물 ${late.length}개: ${late.map(r => esc(r.title)).join(", ")} — 자료 메일이 더 오면 풀립니다.</p>` : "";
      const homeN = (p.records || []).filter(r => r.sent === "core").reduce((a, r) => a + (r.home || []).length, 0);
      const homeHtml = p.mode !== "chapters" && homeN ? `<p class="home">집에 있음 · 보낸 쪽에 남은 파일 ${homeN}개 (큰 부속·원본 영상)</p>` : "";
      const body = err + (p.mode === "one_line" ? own("one_line") + copiesHtml
        : own("overview") + main.map(chapterHtml).join("") +
          (appendix.length ? `<div class="tierHead">부록</div>${appendix.map(chapterHtml).join("")}` : "") + loose) + homeHtml + lateHtml;
      return foldable(`rd:${w.week}:${p.short}`, "proj", `<h3>${esc(p.short)}</h3><span class="n">${projCount(p)}</span>`, body);
    };
    const parts = [`<div class="wk">${esc(w.week)} · ${esc(w.since || "")} ~ ${esc(w.until || "")}</div>`];
    if (w.warning) parts.push(`<p class="err">${esc(w.warning)}</p>`);
    for (const p of w.projects) {
      if (p.schema >= 2) { parts.push(v2ProjectHtml(p)); continue; }
      const streamsHtml = [];
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
          return elm(i, `<figure><img src="/files/${esc(i.src)}" alt=""><figcaption>${esc(i.caption)}</figcaption></figure>`, "fig"); }).join("");
        const html = [];
        if (by.heading) html.push(elm(by.heading, `<p class="muted small">제목 블록: ${esc(s.title)}</p>`));
        for (const b of by.paras) html.push(elm(b, `<p><span class="lbl">${esc(b.label)}</span>${esc(b.text)}</p>`));
        if (by.bullets.length) {
          html.push(`<p class="muted small" style="margin:8px 0 0">대표 결과</p>`);
          for (const b of by.bullets) { html.push(elm(b, `<ul class="res"><li>${esc(b.text)}</li></ul>`)); html.push(figs(b.evidence || [])); }
        }
        const rest = by.images.filter(i => !shown.has(i.id));
        if (rest.length) html.push(rest.map(i => elm(i, `<figure><img src="/files/${esc(i.src)}" alt=""><figcaption>${esc(i.caption)}</figcaption></figure>`, "fig")).join(""));
        for (const b of by.tail) html.push(elm(b, `<p class="status"><span class="lbl">${esc(b.label)}</span>${esc(b.text)}</p>`));
        html.push(chipsHtml(by.pages, by.files), mediaHtml(by.files));
        for (const m of by.mds) html.push(mdFullHtml(m));
        const head = `<h4>${by.heading ? `<span class="el inl" data-id="${esc(by.heading.id)}">${esc(s.title)}</span>` : esc(s.title)}</h4><button class="addAll" data-stream="${esc(s.id)}">흐름 전체 추가</button>`;
        streamsHtml.push(`<details class="stream" data-stream="${esc(s.id)}" data-fold="${esc(s.id)}" ${folds.has(s.id) ? "" : "open"}><summary>${head}</summary><div class="body">${html.join("")}</div></details>`);
      }
      parts.push(foldable(`rd:${w.week}:${p.short}`, "proj", `<h3>${esc(p.short)}</h3><span class="n">흐름 ${p.streams.length}개</span>`, streamsHtml.join("")));
    }
    const weekly = (w.assets || []).find(a => a.src.endsWith("weekly.md"));
    const weeklyLabel = w.schema >= 2 ? "주간 개요" : "주간 방향 보고";
    if (weekly) parts.push(foldable(`rd:${w.week}:weekly`, "proj", `<h3>${weeklyLabel}</h3>`, `<article class="weekly" data-stream="${esc(weekly.id)}"><h4><span>${weeklyLabel}</span> <button class="addAll" data-add="${esc(weekly.id)}">전체 추가</button></h4><div class="el" data-id="${esc(weekly.id)}">${mdToHtml(weekly.text)}</div></article>`));
    const readme = (w.assets || []).find(a => a.src.endsWith("README.md"));
    if (readme) parts.push(`<details class="md"><summary>패키지 README</summary><pre>${esc(readme.text)}</pre></details>`);
    el.innerHTML = parts.join("");
    wireFolds(el);
    $$("#reader [data-add]", el).forEach(b => b.onclick = e => { e.stopPropagation(); e.preventDefault(); addFromLibrary(b.dataset.add); });
    $$("#reader [data-view]", el).forEach(b => b.onclick = e => { e.stopPropagation(); e.preventDefault(); openPageViewer(b.dataset.view, b.dataset.title); });
    $$("#reader [data-stream].addAll", el).forEach(b => b.onclick = e => { e.stopPropagation(); e.preventDefault(); addStream(b.dataset.stream); });
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
  $$(".midTabs button[data-mid]").forEach(btn => btn.onclick = () => { $$(".midTabs button[data-mid]").forEach(b => b.classList.toggle("active", b === btn));
    const r = btn.dataset.mid === "reader"; $("#reader").hidden = !r; $("#library").hidden = r; });
  const visibleMid = () => $("#reader").hidden ? $("#library") : $("#reader");
  $("#foldAll").onclick = () => $$("details", visibleMid()).forEach(d => d.open = false);
  $("#unfoldAll").onclick = () => $$("details:not(.md):not(.units)", visibleMid()).forEach(d => d.open = true);

  // ---------- page view: a result page opens in this column; the draft stays visible on the right ----------
  let pvSrc = null, pvReturn = null, lastPick = [];
  function openPageViewer(src, title) {
    pvSrc = src; lastPick = [];
    pvReturn = { tab: $(".midTabs button[data-mid].active")?.dataset.mid || "reader", scroll: $(".col.mid").scrollTop };
    $("#pvTitle").textContent = title || src.split("/").slice(-2, -1)[0]; $("#pvTitle").title = title || "";
    $("#pvFrame").src = `${state.pageOrigin}/page/${src}`;   // pages run on their own origin, away from the API
    $(".col.mid").classList.add("viewing"); $(".cols").classList.add("viewing"); $("#pageView").hidden = false;
    $(".midTabs").hidden = true; $(".midHint").hidden = true; $("#reader").hidden = true; $("#library").hidden = true;
    renderPickCount();
  }
  function closePageViewer() {
    if (!pvSrc) return;
    $("#pvFrame").src = "about:blank"; pvSrc = null;
    $(".col.mid").classList.remove("viewing"); $(".cols").classList.remove("viewing"); $("#pageView").hidden = true; $(".midTabs").hidden = false; $(".midHint").hidden = false;
    const lib = pvReturn?.tab === "library"; $("#reader").hidden = lib; $("#library").hidden = !lib;
    requestAnimationFrame(() => { $(".col.mid").scrollTop = pvReturn?.scroll || 0; });
  }
  $("#pvBack").onclick = closePageViewer;
  $("#pvNewWin").onclick = () => { if (!pvSrc) return; const w = window.open(`${state.pageOrigin}/page/${pvSrc}`, `cp-${pvSrc}`, "popup,width=1100,height=900"); if (w) pvWins.set(w, pvSrc); toast("새 창에서 클릭해도 이 초안에 담깁니다.", 3000); };
  $("#pvUndo").onclick = () => {
    if (!lastPick.length) return;
    const ids = new Set(lastPick); state.draft.blocks = state.draft.blocks.filter(b => !ids.has(b.id)); lastPick = [];
    commit(); renderEditor(); renderPickCount(); toast("방금 담은 것을 뺐습니다.", 1500);
  };
  function renderPickCount() {
    const n = state.draft && pvSrc ? state.draft.blocks.filter(b => b.source_ref === `page:${pvSrc}`).length : 0;
    $("#pvCount").textContent = n ? `이 페이지에서 ${n}개 담음` : ""; $("#pvUndo").hidden = !lastPick.length;
  }
  document.addEventListener("keydown", e => { if (e.key === "Escape" && pvSrc && !$("#publishDlg").open) closePageViewer(); });

  // a pick names files by URL; only a plain path inside the week of the page being shown is accepted
  let localWeek = null;
  const pvWins = new Map();   // popups the viewer opened -> the page each one shows; no other window's picks count
  const localSrc = u => {
    if (!u || !u.includes("/files/")) return null;
    let p; try { p = decodeURIComponent(u.split("/files/")[1].split(/[?#]/)[0]); } catch { return null; }
    if (!localWeek || !p.startsWith(`${localWeek}/`) || p.includes("\\") || p.split("/").includes("..")) return null;
    return p;
  };
  async function blockFor(m, week) {
    switch (m.t) {
      case "image": {
        let src = localSrc(m.src);
        if (!src && m.data) src = (await api("/api/pick-image", { method: "POST", body: { week, data: m.data, name: m.caption || "figure" } })).src;
        if (!src) { toast(m.src && /^https?:/.test(m.src) ? "이 그림은 패키지 밖(외부 주소)에 있어 저장할 수 없습니다." : "이 그림을 화면에서 읽어 오지 못했습니다."); return null; }
        return { type: "image", src, caption: m.caption || "" };
      }
      case "media": { const src = localSrc(m.src); if (!src) { toast("이 미디어는 패키지 안에 없어 첨부할 수 없습니다."); return null; } return { type: "file", src, caption: m.caption || src.split("/").pop() }; }
      case "table": return m.rows?.length ? { type: "table", rows: m.rows, header: !!m.header } : null;
      case "list": return m.items?.length ? { type: "bullets", items: m.items } : null;
      case "heading": return m.text ? { type: "heading", level: m.level <= 2 ? 2 : 3, text: m.text } : null;
      case "callout": return (m.title || m.text) ? { type: "callout", text: (m.title ? `**${m.title}**\n` : "") + (m.text || "").replace(/[ \t]*\n[ \t]*/g, "\n").trim() } : null;
      case "columns": {
        const cols = [];
        for (const cell of m.cells || []) { const bs = []; for (const it of cell) { const nb = await blockFor(it, week); if (nb) bs.push({ ...nb, id: uid() }); } cols.push(bs); }
        return cols.some(c => c.length) ? { type: "columns", cols } : null;
      }
      case "code": return m.text ? { type: "paragraph", text: "`" + m.text.replace(/`/g, "'") + "`" } : null;
      default: return m.text ? { type: "paragraph", text: m.text.replace(/\s*\n\s*/g, " ") } : null;
    }
  }
  window.addEventListener("message", async e => {
    if (e.origin !== state.pageOrigin) return;            // picks come only from result pages
    // ...and only from the viewer frame (the page it shows now) or a popup it opened (the page that popup got)
    const src = e.source === $("#pvFrame").contentWindow ? pvSrc : pvWins.get(e.source);
    const m = e.data; if (!m || m.kind !== "cp-pick" || !src || !state.draft) return;
    const week = src.split("/")[0], ref = `page:${src}`;
    localWeek = week;
    try {
      const made = [];
      for (const it of m.items || []) { const b = await blockFor(it, week); if (b) made.push({ ...b, id: uid(), source_ref: ref }); }
      if (!made.length) return;
      if (made.length > 1) { const gid = "g-" + Math.random().toString(36).slice(2, 8); made.forEach(b => b.group = gid); made[0].group_label = m.label || m.unit; }
      state.draft.blocks.push(...made); lastPick = made.map(b => b.id);
      commit(); renderEditor(); renderPickCount(); toast(`${esc(m.label || "")} 담았습니다.`, 1200);
      $("#editor").lastElementChild?.scrollIntoView({ block: "nearest" });
    } catch (err) { toast("가져오기 실패: " + esc(err.message)); }
  });

  function findLib(id) {
    for (const w of state.library) {
      for (const a of w.assets || []) if (a.id === id) return a;
      for (const p of w.projects) {
        for (const b of p.blocks || []) if (b.id === id) return b;
        for (const s of p.streams) for (const b of s.blocks) if (b.id === id) return b;
      }
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
    for (const b of s.blocks.filter(x => x.type !== "page" && x.type !== "markdown" && x.type !== "file" && !x.optional && matches(x))) addFromLibrary(b.id);
    toast(s.chapter ? "글과 캡처를 모두 추가했습니다 (파일·페이지·지난주 대비·근거는 제외)." : "흐름의 글과 캡처를 모두 추가했습니다 (파일·페이지는 제외).");
  }

  // ---------- drafts ----------
  function renderDraftSelect() {
    $("#draftSelect").innerHTML = state.drafts.map(d => `<option value="${esc(d.id)}" ${d.id === state.draft?.id ? "selected" : ""}>${esc(d.title)}${d.confluence?.page_id ? " ↑" : ""}</option>`).join("");
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
      case "image": return `<div class="figure"><img src="/files/${esc(b.src)}" alt=""><input class="caption" data-field="caption" placeholder="캡션" value="${esc(b.caption)}"></div>`;
      case "file": return `<div class="filebox"><span>📎</span><div style="flex:1"><input class="caption" data-field="caption" placeholder="설명" value="${esc(b.caption)}"><div class="name">${esc(b.src.split("/").pop())}</div></div></div>`;
      case "divider": return `<hr>`;
      case "callout": return `<div class="callout" contenteditable="true" data-field="text" data-ph="강조할 내용">${esc(b.text)}</div>`;
      case "table": return `<table class="tbl">${(b.rows || []).map((r, ri) => `<tr>${r.map((c, ci) => { const tag = ri === 0 && b.header !== false ? "th" : "td"; return `<${tag} contenteditable="true" data-cell="${ri},${ci}">${esc(c)}</${tag}>`; }).join("")}</tr>`).join("")}</table>`;
      case "columns": return `<div class="colgrid" style="grid-template-columns:repeat(${(b.cols || []).length || 1},minmax(0,1fr))">${(b.cols || []).map((col, c) => `<div class="colcell">${col.map((nb, k) => nestedInner(nb, c, k)).join("") || `<span class="muted small">빈 칸</span>`}</div>`).join("")}</div>`;
      default: return `<em class="muted">알 수 없는 블록 ${esc(b.type)}</em>`;
    }
  }
  // blocks inside a columns cell: text stays editable (data-path), structure is fixed until "세로로" unpacks it
  function nestedInner(nb, c, k) {
    const path = `${c},${k}`;
    switch (nb.type) {
      case "heading": return `<div class="nh" contenteditable="true" data-path="${path},text">${esc(nb.text)}</div>`;
      case "paragraph": return `<div contenteditable="true" data-path="${path},text">${esc(nb.text)}</div>`;
      case "callout": return `<div class="callout" contenteditable="true" data-path="${path},text">${esc(nb.text)}</div>`;
      case "bullets": return `<ul class="items">${(nb.items || []).map((it, i) => `<li contenteditable="true" data-path="${path},items,${i}">${esc(it)}</li>`).join("")}</ul>`;
      case "image": return `<div class="figure"><img src="/files/${esc(nb.src)}" alt=""><input class="caption" data-path="${path},caption" placeholder="캡션" value="${esc(nb.caption)}"></div>`;
      case "file": return `<div class="filebox"><span>📎</span><div class="name">${esc(nb.caption || (nb.src || "").split("/").pop())}</div></div>`;
      case "table": return `<table class="tbl">${(nb.rows || []).map(r => `<tr>${r.map(x => `<td>${esc(x)}</td>`).join("")}</tr>`).join("")}</table>`;
      case "divider": return `<hr>`;
      default: return "";
    }
  }
  function setPath(b, path, value) {
    const p = path.split(","); const nb = b.cols?.[+p[0]]?.[+p[1]]; if (!nb) return;
    if (p[2] === "items") nb.items[+p[3]] = value; else nb[p[2]] = value;
  }
  function blockHtml(b, i) {
    return `<div class="block" data-i="${i}" data-type="${b.type}" data-level="${b.level || ""}" draggable="false">
      <span class="handle" title="끌어서 이동" draggable="true">⋮⋮</span>
      <div class="content">${blockInner(b)}</div>
      <div class="menu">
        <button data-act="up" title="위로">↑</button><button data-act="down" title="아래로">↓</button>
        ${b.type === "heading" ? `<button data-act="level" title="제목 크기">H${b.level === 3 ? 3 : 2}</button>` : ""}
        ${b.type === "paragraph" ? `<button data-act="toCallout" title="강조 상자로">▣</button>` : ""}
        ${b.type === "callout" ? `<button data-act="toPara" title="문단으로">¶</button>` : ""}
        ${b.type === "columns" ? `<button data-act="flatten" title="가로 칸을 풀어 세로로 늘어놓기">세로로</button>` : ""}
        <button data-act="dup" title="복제">⧉</button><button data-act="del" title="삭제">✕</button>
      </div></div>`;
  }
  function renderEditor() {
    const ed = $("#editor");
    const blocks = state.draft?.blocks || [];
    const html = []; let i = 0;
    while (i < blocks.length) {
      const b = blocks[i];
      let j = i + 1; if (b.group) while (j < blocks.length && blocks[j].group === b.group) j++;
      if (j - i > 1) html.push(`<div class="grp" data-i="${i}" data-n="${j - i}"><div class="grpHead"><span class="handle" draggable="true" title="묶음 끌어서 이동">⋮⋮</span><span class="lbl">${esc(b.group_label || "묶음")}</span><span>${j - i}개 · 함께 움직입니다</span><span class="sp"></span><button data-gact="up" title="묶음 위로">↑</button><button data-gact="down" title="묶음 아래로">↓</button><button data-gact="ungroup" title="묶음을 풀어 낱개로">풀기</button><button data-gact="del" title="묶음 삭제">✕</button></div>${blocks.slice(i, j).map((x, k) => blockHtml(x, i + k)).join("")}</div>`);
      else html.push(blockHtml(b, i));
      i = j;
    }
    ed.innerHTML = html.join("");
    $("#dropHint").hidden = blocks.length > 0;
    wireEditor();
    if (state.tab === "preview") renderPreview();
  }
  function wireEditor() {
    const ed = $("#editor");
    $$(".block", ed).forEach(el => {
      const i = +el.dataset.i, b = state.draft.blocks[i];
      $$("[contenteditable]", el).forEach(ce => {
        ce.oninput = () => {
          if (ce.dataset.path) { setPath(b, ce.dataset.path, ce.innerText); scheduleSaveSoft(); return; }
          if (ce.dataset.cell !== undefined) { const [ri, ci] = ce.dataset.cell.split(",").map(Number); b.rows[ri][ci] = ce.innerText; }
          else if (ce.dataset.item !== undefined) b.items[+ce.dataset.item] = ce.innerText; else b[ce.dataset.field] = ce.innerText;
          scheduleSaveSoft();
        };
        ce.onkeydown = e => {
          if (ce.dataset.cell !== undefined || ce.dataset.path) return;   // tables and column cells: plain editing
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (ce.dataset.item !== undefined) { b.items.splice(+ce.dataset.item + 1, 0, ""); commit(); renderEditor(); focusBlock(i, +ce.dataset.item + 1); }
            else { state.draft.blocks.splice(i + 1, 0, { id: uid(), type: "paragraph", text: "", source_ref: null, ...(b.group ? { group: b.group } : {}) }); commit(); renderEditor(); focusBlock(i + 1); }
          } else if (e.key === "Backspace" && ce.innerText === "") {
            e.preventDefault();
            if (ce.dataset.item !== undefined && b.items.length > 1) { b.items.splice(+ce.dataset.item, 1); commit(); renderEditor(); focusBlock(i, Math.max(0, +ce.dataset.item - 1)); }
            else if (ce.dataset.item === undefined || b.items.length <= 1) { state.draft.blocks.splice(i, 1); commit(); renderEditor(); focusBlock(i - 1); }
          }
        };
        ce.onblur = () => { if (state.history.at(-1) !== JSON.stringify(state.draft.blocks)) commit(); };
      });
      $$("input.caption", el).forEach(inp => inp.oninput = () => { if (inp.dataset.path) setPath(b, inp.dataset.path, inp.value); else b.caption = inp.value; scheduleSaveSoft(); });
      $$(".menu button", el).forEach(btn => btn.onclick = () => blockAction(btn.dataset.act, i));
      const h = $(".handle", el);
      h.ondragstart = e => { e.dataTransfer.setData("text/x-move", `${i}:1`); e.dataTransfer.effectAllowed = "move"; el.classList.add("dragging"); e.stopPropagation(); };
      h.ondragend = () => el.classList.remove("dragging");
    });
    $$(".grp", ed).forEach(g => {
      const i = +g.dataset.i, n = +g.dataset.n;
      $$(".grpHead button", g).forEach(btn => btn.onclick = () => groupAction(btn.dataset.gact, i, n));
      const h = $(".grpHead .handle", g);
      h.ondragstart = e => { e.dataTransfer.setData("text/x-move", `${i}:${n}`); e.dataTransfer.effectAllowed = "move"; g.classList.add("dragging"); };
      h.ondragend = () => g.classList.remove("dragging");
    });
    ed.ondragover = e => { e.preventDefault(); showDropline(e.clientY); };
    ed.ondragleave = e => { if (e.target === ed) clearDropline(); };
    ed.ondrop = e => {
      e.preventDefault(); const at = snapOut(dropIndex(e.clientY)); clearDropline();
      const lib = e.dataTransfer.getData("text/x-lib"), mv = e.dataTransfer.getData("text/x-move");
      if (lib) addFromLibrary(lib, at);
      else if (mv !== "") { const [from, len] = mv.split(":").map(Number); if (len === 1) ungroupOne(from); moveRun(from, len, at); commit(); renderEditor(); }
    };
  }
  // groups: blocks that came from one pick share a group id and move/delete together
  const runAt = i => { const bl = state.draft.blocks, g = bl[i]?.group; if (!g) return [i, 1]; let s = i, e = i; while (s > 0 && bl[s - 1].group === g) s--; while (e + 1 < bl.length && bl[e + 1].group === g) e++; return [s, e - s + 1]; };
  const snapOut = at => { const bl = state.draft.blocks; if (at > 0 && at < bl.length && bl[at - 1].group && bl[at - 1].group === bl[at].group) { const [s, n] = runAt(at); return s + n; } return at; };
  function moveRun(from, len, to) { if (to >= from && to <= from + len) return; const bl = state.draft.blocks; const run = bl.splice(from, len); bl.splice(to > from ? to - len : to, 0, ...run); }
  function ungroupOne(i) { const b = state.draft.blocks[i]; if (b) { delete b.group; delete b.group_label; } }
  function groupAction(act, i, n) {
    const bl = state.draft.blocks;
    if (act === "up" && i > 0) { const [ps] = runAt(i - 1); moveRun(i, n, ps); }
    if (act === "down" && i + n < bl.length) { const [ns, nl] = runAt(i + n); moveRun(i, n, ns + nl); }
    if (act === "ungroup") for (let k = i; k < i + n; k++) ungroupOne(k);
    if (act === "del") bl.splice(i, n);
    commit(); renderEditor(); renderLibrary();
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
    if (act === "up" && i > 0) { ungroupOne(i); [bl[i - 1], bl[i]] = [bl[i], bl[i - 1]]; }
    if (act === "down" && i < bl.length - 1) { ungroupOne(i); [bl[i + 1], bl[i]] = [bl[i], bl[i + 1]]; }
    if (act === "dup") bl.splice(i + 1, 0, { ...JSON.parse(JSON.stringify(b)), id: uid(), group_label: undefined });
    if (act === "del") bl.splice(i, 1);
    if (act === "level") b.level = b.level === 3 ? 2 : 3;
    if (act === "toCallout") b.type = "callout";
    if (act === "toPara") b.type = "paragraph";
    if (act === "flatten" && b.type === "columns") {
      const gid = "g-" + Math.random().toString(36).slice(2, 8);
      const flat = (b.cols || []).flat().map(x => ({ ...x, id: uid(), group: gid, source_ref: b.source_ref }));
      if (flat.length) { flat[0].group_label = "가로 칸을 풀어놓음"; bl.splice(i, 1, ...flat); }
    }
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
  const inlineHtml = s => esc(s).replace(/\n/g, "<br>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^\w*])_(.+?)_(?![\w*])/g, "$1<em>$2</em>").replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2">$1</a>');
  function previewHtml(blocks) {
    return blocks.map(b => {
      switch (b.type) {
        case "heading": return `<h${b.level === 3 ? 3 : 2}>${inlineHtml(b.text)}</h${b.level === 3 ? 3 : 2}>`;
        case "paragraph": return `<p>${inlineHtml(b.text)}</p>`;
        case "bullets": return `<ul>${(b.items || []).map(i => `<li>${inlineHtml(i)}</li>`).join("")}</ul>`;
        case "image": return `<p><img src="/files/${esc(b.src)}" alt=""></p>${b.caption ? `<p><em>${esc(b.caption)}</em></p>` : ""}`;
        case "file": return `<p><span class="att">📎 ${esc(b.caption || b.src)}</span></p>`;
        case "divider": return `<hr>`;
        case "callout": return `<div class="info">${inlineHtml(b.text)}</div>`;
        case "table": return `<table>${(b.rows || []).map((r, ri) => `<tr>${r.map(c => { const tag = ri === 0 && b.header !== false ? "th" : "td"; return `<${tag}>${inlineHtml(c)}</${tag}>`; }).join("")}</tr>`).join("")}</table>`;
        case "columns": return `<table class="cols"><tr>${(b.cols || []).map(col => `<td style="width:${Math.floor(100 / ((b.cols || []).length || 1))}%">${previewHtml(col)}</td>`).join("")}</tr></table>`;
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
      const r = await api(`/api/paste/${state.draft.id}`, { method: "POST", body: {} });
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
