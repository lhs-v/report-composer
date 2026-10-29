/* NodePane: the middle column. One node at a time: where it came from, title, state buttons, body (rendered while resting, raw while
   editing), and for a record its captions and the file to show. Under it, the server's own render of this subtree.
   Named NodePane because window.Node is the DOM constructor.
   Every edit goes through Keys (typing / op); this file never touches nodes. show() is called after every Tree.change, so it is cheap
   and never rebuilds a field that has focus. */
window.NodePane = (() => {
  // boot.js (which defines Composer) loads after this file: look the helpers up at call time
  const api = (...a) => window.Composer.api(...a), esc = s => window.Composer.esc(s);
  const pane = () => document.getElementById("nodePane");
  const { IMG, VID, BODIED, SPLITTABLE, AID, KIND_LABEL, LEDGER_LABEL, enc, mediaFor, options, sourceLine, flags } = window.NodeInfo;   // nodeinfo.js loads before this file

  let cur = null, curDraft = null, curKind = null, main = null;     // what is on screen
  let els = {};                                                    // the fields of the current node
  const videos = new Map();                                        // node id -> <video>, kept so a redraw does not restart playback
  let pageOrigin = null;                                           // where result pages open (from /api/state)

  const node = id => window.Tree?.nodes?.()[id];
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>").replace(/\n/g, "<br>");
  const focused = el => el && document.activeElement === el;

  // ---- the resting body shows markdown; the focused body shows the raw text ----
  const rawOf = body => body.textContent;
  // text before the selection's start, as the user sees it (a <br> counts as a line break)
  function textBefore(body) {
    const sel = getSelection();
    if (!sel.rangeCount || !body.contains(sel.anchorNode)) return null;
    const r = document.createRange(); r.selectNodeContents(body); r.setEnd(sel.anchorNode, sel.anchorOffset);
    let out = "";
    const walk = n => { if (n.nodeType === 3) out += n.data; else if (n.nodeName === "BR") out += "\n"; else n.childNodes.forEach(walk); };
    walk(r.cloneContents());
    return out;
  }
  // which raw index the n-th visible character of the rendered text sits at (the ** and ` marks are not visible)
  function rawIndexOf(raw, visible) {
    const hide = new Array(raw.length).fill(false);
    for (const [re, w] of [[/\*\*(.+?)\*\*/g, 2], [/`(.+?)`/g, 1]]) {
      for (const m of raw.matchAll(re)) for (let k = 0; k < w; k++) { hide[m.index + k] = true; hide[m.index + m[0].length - 1 - k] = true; }
    }
    let seen = 0;
    for (let i = 0; i < raw.length; i++) { if (hide[i]) continue; if (seen === visible) return i; seen++; }
    return raw.length;
  }
  function setCaret(body, at) {
    const t = body.firstChild; if (!t) return;
    const r = document.createRange(); r.setStart(t, Math.min(at, t.data.length)); r.collapse(true);
    const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
  }
  function caretOffset(body) {
    const sel = getSelection();
    if (!sel.rangeCount || !body.contains(sel.anchorNode)) return null;
    const r = document.createRange(); r.selectNodeContents(body); r.setEnd(sel.anchorNode, sel.anchorOffset);
    return r.toString().length;
  }

  // ---- pieces ----
  function optionsHTML(n, name) {
    const opts = options(n), radio = o => `<label class="n-opt${o.home ? " home" : ""}"><input type="radio" name="${esc(name)}" value="${esc(o.v)}"${o.home ? " disabled" : ""}`
      + `${(n.show || "representative") === o.v ? " checked" : ""}><span class="n-optl">${esc(o.label)}</span>${o.sub ? `<small class="n-optsub">${esc(o.sub)}</small>` : ""}${o.home ? "<small class=\"n-optsub\">집에 있음</small>" : ""}</label>`;
    const here = opts.filter(o => !o.home), home = opts.filter(o => o.home);
    return (here.map(radio).join("") || '<p class="n-none">패키지에 담겨 온 파일이 없어요.</p>')
      + (home.length ? `<details class="n-homefiles"><summary>집에 있는 파일 ${home.length}개 (여기서는 고를 수 없어요)</summary>${home.map(radio).join("")}</details>` : "");
  }

  // ---- the caption the writer last settled on is what the memory keeps (next week's tree starts from it) ----
  // Called after typing and after undo/redo (Keys): the memory must follow the visible text, not the last thing typed.
  const memTimers = new Map();
  function remember(id) {
    clearTimeout(memTimers.get(id));
    const m = node(id), rec = m?.src?.record, week = Tree.state.draft?.week;
    if (!rec || !week) return;                                       // a text with no record has nothing to remember
    const text = (m.caption || []).filter(Boolean);                  // both lines empty: [] tells the server to forget the fix
    memTimers.set(id, setTimeout(() => {
      memTimers.delete(id);
      api("/api/memory/caption", { method: "PUT", body: { record: rec, text, week } })
        .catch(e => window.Composer.toast("설명을 기억하지 못했습니다: " + esc(e.message), 6000));
    }, 800));
  }

  // ---- building one node's pane ----
  function shell() {
    const p = pane();
    if (main && p.contains(main)) return;
    p.innerHTML = `<div class="n-main"></div><section id="nodePreview" class="n-previewbox" aria-label="내보내기 미리보기">`
      + `<h3>내보내면 이렇게 보여요</h3><p class="n-pstate" role="status" aria-live="polite"></p><div class="n-preview"></div></section>`;
    main = p.querySelector(".n-main"); previewKey = null;
  }

  function build(n) {
    const id = n.id, draft = Tree.state.draft;
    const record = n.kind === "record", listed = n.kind === "flow" || n.kind === "ledger", aid = AID[n.kind];
    // the aid button and the place its progress / proposal appears
    const aidHTML = aid ? `<div class="n-aidrow"><button type="button" class="n-aid">${aid[1]}</button></div><div class="n-aidbox" data-for="${esc(id)}" aria-live="polite"></div>` : "";
    main.innerHTML = `<div class="n-stale" role="status" hidden><span>구조가 바뀌었습니다. 본문을 다시 읽어 보세요</span>`
      + `<span class="n-stalebtns"><button type="button" class="n-polish" hidden>✨ 다시 다듬기</button><button type="button" class="n-ack">확인했어요</button></span></div>`
      + `<button type="button" class="n-src" title="이 줄의 근거를 서랍에서 봅니다"></button>`
      + `<input class="n-title" aria-label="제목" placeholder="제목" autocomplete="off">`
      + `<div class="n-states"><span class="n-flags"></span>`
      + `<button type="button" class="n-on"></button><button type="button" class="n-fold"></button><button type="button" class="n-page"></button></div>`
      + (record ? `<div class="n-media" hidden></div>`
        + `<div class="n-caps"><input class="n-cap" aria-label="설명 첫 줄: 무엇이 보이는가" placeholder="무엇이 보이는가" autocomplete="off">`
        + `<input class="n-cap" aria-label="설명 둘째 줄: 왜 중요한가" placeholder="왜 중요한가" autocomplete="off"></div>` + aidHTML
        + `<fieldset class="n-show"><legend>보여 줄 것</legend><div class="n-opts"></div></fieldset>` : "")
      + (listed ? `<ul class="n-items"></ul><button type="button" class="n-totext">글로 바꾸기</button>` : "")
      + (BODIED.includes(n.kind) ? aidHTML + `<div class="n-body" role="textbox" aria-multiline="true" aria-label="본문" data-placeholder="본문을 쓰세요"></div>` : "");
    const q = s => main.querySelector(s);
    els = { stale: q(".n-stale"), src: q(".n-src"), title: q(".n-title"), flags: q(".n-flags"), on: q(".n-on"), fold: q(".n-fold"), page: q(".n-page"),
            ack: q(".n-ack"), polish: q(".n-polish"), aid: q(".n-aid"), box: q(".n-aidbox"),
            media: q(".n-media"), caps: [...main.querySelectorAll(".n-cap")], opts: q(".n-opts"), items: q(".n-items"), body: q(".n-body") };
    curKind = n.kind;

    q(".n-ack").addEventListener("click", () => {
      const m = node(id); if (!m?.stale) return;
      if (els.body) Motion.sweep(els.body);                          // 착지: the one motion here
      Keys.op({ type: "stale", id, from: true, to: false });
    });
    els.polish.addEventListener("click", () => { if (AID[n.kind]) window.Aids?.request(AID[n.kind][0], id); });
    els.aid?.addEventListener("click", () => window.Aids?.request(AID[n.kind][0], id));
    els.src.addEventListener("click", () => {
      window.Drawer?.show?.(id, "evidence");
      if (matchMedia("(max-width: 1007px)").matches) document.getElementById("tree").dataset.pane = "drawer";
    });
    els.title.addEventListener("input", () => Keys.typing(id, "title", els.title.value));
    els.on.addEventListener("click", () => Tree.toggle(id));
    els.fold.addEventListener("click", () => Tree.fold(id));
    els.page.addEventListener("click", () => Keys.togglePage(id));

    if (record) {
      const onCap = () => {
        const text = els.caps.map(c => c.value.trim() ? c.value : "").filter(Boolean);
        Keys.typing(id, "caption", text);
        remember(id);
      };
      els.caps.forEach(c => c.addEventListener("input", onCap));
      els.opts.addEventListener("change", e => {
        const r = e.target.closest?.("input[type=radio]"), m = node(id);
        if (r && m && r.value !== (m.show || "representative")) Keys.op({ type: "text", id, field: "show", from: m.show || "representative", to: r.value });
      });
    }
    if (listed) {
      main.querySelector(".n-totext").addEventListener("click", () => {
        const m = node(id); if (!m?.items?.length) return;
        const lines = m.items.map(i => m.kind === "flow" ? `- ${String(i.when || "").slice(0, 10)} · ${i.text || ""}` : `- ${LEDGER_LABEL[i.kind] || i.kind}: ${i.text || ""}`);
        const nid = Keys.newText(id);                                 // a text node right after this one (and selected)
        if (nid) Keys.typing(nid, "text", lines.join("\n"));
      });
    }
    if (els.body) wireBody(id);
  }

  function wireBody(id) {
    const body = els.body;
    try { body.contentEditable = "plaintext-only"; } catch { body.contentEditable = "true"; } // browsers without plaintext-only
    body.addEventListener("focus", () => {
      const m = node(id); if (!m) return;
      const raw = m.text || "", vis = textBefore(body);
      body.textContent = raw;
      setCaret(body, vis === null ? raw.length : rawIndexOf(raw, vis.length));
    });
    body.addEventListener("blur", () => { const m = node(id); if (m) renderBody(m, true, body); }); // this body, not whatever els.body is by then
    body.addEventListener("input", () => Keys.typing(id, "text", rawOf(body)));
    body.addEventListener("keydown", e => {
      if (e.key !== "Enter" || e.isComposing || e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return;
      const m = node(id); if (!m || !SPLITTABLE.includes(m.kind)) return;
      const at = caretOffset(body), raw = rawOf(body);
      if (at === null || at < 1 || raw[at - 1] !== "\n") return;       // an Enter at the start of a line splits (the second Enter in a row); inside a line it breaks the line
      e.preventDefault();
      Keys.typing(id, "text", raw);                                    // the model must hold exactly what is on screen
      if (Keys.split(id, at)) els.body?.focus();                       // the new node is shown now: keep writing in it
    });
  }

  function renderBody(n, force, b = els.body) {
    if (!b || (focused(b) && !force)) return;
    if (!force && b.dataset.raw === (n.text || "") && b.dataset.rendered) return;
    b.innerHTML = inline(n.text || ""); b.dataset.raw = n.text || ""; b.dataset.rendered = "1";
  }

  function renderItems(n) {
    if (!els.items) return;
    const html = (n.items || []).map(i => n.kind === "flow"
      ? `<li><time>${esc(String(i.when || "").slice(0, 10))}</time> ${esc(i.text || "")}</li>`
      : `<li><i class="chip">${esc(LEDGER_LABEL[i.kind] || i.kind)}</i> ${esc(i.text || "")}</li>`).join("");
    if (els.items.dataset.sig !== html) { els.items.innerHTML = html || '<li class="n-none">항목이 없어요.</li>'; els.items.dataset.sig = html; }
    const btn = main.querySelector(".n-totext"); if (btn) btn.disabled = !(n.items || []).length;
  }

  const failed = (what, href) => Object.assign(document.createElement("p"), { className: "n-none", textContent: `${what}을 불러오지 못했습니다 (${href.split("/").pop()})` });

  function renderMedia(n) {
    const host = els.media; if (!host) return;
    const m = mediaFor(n), week = n.src?.week || Tree.state.draft.week;
    const key = m ? m.kind + "|" + m.href : "";
    if (host.dataset.key === key) return;
    host.dataset.key = key;
    if (!m) { host.hidden = true; host.replaceChildren(); return; }
    host.hidden = false;
    const url = `/files/${week}/${enc(m.href)}`;
    if (m.kind === "video") {
      let v = videos.get(n.id);
      if (v && v.dataset.url !== url) { v.pause(); videos.delete(n.id); v = null; }
      if (!v) {
        v = document.createElement("video"); v.controls = true; v.preload = "metadata"; v.playsInline = true; v.dataset.url = url; v.src = url;
        v.setAttribute("aria-label", n.title || "영상"); videos.set(n.id, v);
        v.addEventListener("error", () => {  // a failed source: say so instead of a dead player, and let the next visit try again
          videos.delete(n.id); v.parentNode?.replaceChildren(failed("영상", m.href));
        });
      }
      if (host.firstChild !== v) host.replaceChildren(v);
    } else if (m.kind === "image") {
      const img = new Image(); img.alt = n.title || ""; img.className = "n-img"; host.classList.add("loading");
      img.onload = () => host.classList.remove("loading");
      img.onerror = () => { host.classList.remove("loading"); host.replaceChildren(failed("그림", m.href)); };
      img.src = url; host.replaceChildren(img);
    } else {
      const a = document.createElement("a"); a.className = "n-open"; a.target = "_blank"; a.rel = "noopener"; a.textContent = "열기 · " + m.href.split("/").pop();
      a.href = `${pageOrigin || location.protocol + "//localhost:" + location.port}/page/${week}/${enc(m.href)}`;
      host.replaceChildren(a);
    }
  }

  // bring every field to the node's current values; fields with focus are left alone
  function sync(n) {
    const e = els;
    e.src.textContent = sourceLine(n);
    if (!focused(e.title) && e.title.value !== (n.title || "")) e.title.value = n.title || "";
    e.stale.hidden = !n.stale;
    // writing aids: usable when a provider is set (aids.js knows), otherwise the old "확인했어요" stays and the button says why it is off
    const aids = window.Aids, ready = !!aids?.state.ready, busy = !!aids?.busy(n.id);
    e.polish.hidden = !ready || !AID[n.kind]; e.polish.disabled = busy; e.ack.hidden = !e.polish.hidden;
    if (e.aid) { e.aid.disabled = !ready || busy; e.aid.title = !ready ? aids?.TIP || "" : busy ? "다시 쓰는 중입니다" : ""; }
    if (e.box) aids?.render(n.id, e.box);
    e.flags.textContent = flags(n);
    e.on.textContent = n.on ? "끄기" : "켜기"; e.on.setAttribute("aria-pressed", String(!!n.on));
    e.fold.hidden = !n.children?.length; e.fold.textContent = n.folded ? "펴기" : "접기"; e.fold.setAttribute("aria-pressed", String(!!n.folded));
    e.page.hidden = !["project", "claim"].includes(n.kind); e.page.textContent = "별도 페이지"; e.page.setAttribute("aria-pressed", String(!!n.page));
    if (n.kind === "record") {
      if (!e.caps.some(focused)) { const cap = n.caption || []; e.caps.forEach((c, i) => { if (c.value !== (cap[i] || "")) c.value = cap[i] || ""; }); }
      const sig = JSON.stringify([options(n).map(o => [o.v, !!o.home])]);
      if (e.opts.dataset.sig !== sig) {
        if (!e.opts.contains(document.activeElement)) { e.opts.innerHTML = optionsHTML(n, "show-" + n.id); e.opts.dataset.sig = sig; }
      }
      const want = n.show || "representative";
      e.opts.querySelectorAll("input[type=radio]").forEach(r => { r.checked = r.value === want; });
      renderMedia(n);
    }
    renderItems(n);
    renderBody(n);
  }

  // ---- the preview: this subtree through the server's own renderer ----
  let ptimer = null, pseq = 0, previewKey = null;
  const cache = new Map();
  const previewEls = () => ({ box: pane().querySelector(".n-preview"), state: pane().querySelector(".n-pstate") });
  function schedulePreview(id) {
    clearTimeout(ptimer);
    ptimer = setTimeout(() => runPreview(id), 300);
  }
  async function runPreview(id) {
    const d = Tree.state.draft, n = node(id);
    if (!d || !n || cur !== id) return;
    const sub = {}; for (const [m] of Tree.walk([id])) sub[m.id] = m;
    const key = id + "|" + d.week + "|" + JSON.stringify(sub);
    if (key === previewKey) return;
    const { box, state } = previewEls(); if (!box) return;
    const hit = cache.get(key);
    if (hit !== undefined) { previewKey = key; paint(box, state, hit, n); return; }
    const seq = ++pseq;
    const slow = setTimeout(() => { if (seq === pseq) { state.textContent = "미리보기 만드는 중…"; box.classList.add("busy"); } }, 300);
    try {
      const r = await api("/api/preview", { method: "POST", body: { draft: { ...d, nodes: sub, root: [id] } } });
      if (seq !== pseq || cur !== id) return;
      const html = r?.error ? null : (r?.xhtml || "");
      if (r?.error) { state.textContent = "미리보기를 만들지 못했어요: " + r.error; }
      else { cache.set(key, html); if (cache.size > 40) cache.delete(cache.keys().next().value); paint(box, state, html, n); }
      previewKey = r?.error ? null : key;
    } catch (e) {
      if (seq === pseq) state.textContent = "미리보기를 만들지 못했어요: " + e.message;
    } finally { clearTimeout(slow); if (seq === pseq) box.classList.remove("busy"); }
  }
  // The export is Confluence storage XHTML, which a browser does not draw (ac:image, CDATA links): give the attachments their real
  // files here, and keep the rest as the browser's plain reading of it.
  function display(xhtml, id) {
    const urls = new Map();
    for (const [m] of Tree.walk([id])) {
      const week = m.src?.week || Tree.state.draft.week;
      for (const href of [m.href, m.representative, ...(m.files || []).map(f => f.href)]) {
        if (href) urls.set(`${week}_${href.replace(/\//g, "_")}`, `/files/${week}/${enc(href)}`);
      }
    }
    return xhtml
      .replace(/<ac:image\b[^>]*>\s*<ri:attachment ri:filename="([^"]*)"\s*\/>\s*<\/ac:image>/g, (_, name) => {
        const url = urls.get(name.replace(/&amp;/g, "&"));
        return url ? `<img src="${esc(url)}" alt="${name}">` : `<span class="n-pimg">[그림] ${name}</span>`;
      })
      .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, (_, t) => esc(t));
  }
  function paint(box, state, html, n) {
    box.classList.remove("busy");
    box.innerHTML = html ? display(html, n.id) : ""; // the server renders our own blocks to XHTML (text escaped there)
    state.textContent = html ? "" : (n.on ? "내보낼 내용이 아직 없어요." : "이 줄은 꺼져 있어서 내보내지 않아요.");
  }

  // ---- entry point ----
  function show(id) {
    const n = id && node(id);
    if (!n) { cur = null; main = null; clearTimeout(ptimer); pseq++; pane().replaceChildren(); return; }
    const draft = Tree.state.draft;
    if (draft !== curDraft) { // another draft: forget the old draft's videos and previews
      videos.forEach(v => v.pause()); videos.clear(); cache.clear(); previewKey = null; curDraft = draft; cur = null;
    }
    shell();
    if (cur !== id || curKind !== n.kind || !main.querySelector(".n-title")) {
      cur = id; build(n); previewKey = null;
      const { box } = previewEls(); box.classList.add("busy"); // the old subtree's preview stays, dimmed, until the new one arrives
    }
    sync(n);
    schedulePreview(id);
  }

  fetch("/api/state").then(r => r.json()).then(s => { pageOrigin = s.page_origin || null; }).catch(() => {});

  return { show, remember };
})();
