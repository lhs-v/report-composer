/* Doc: the middle column. The whole report as one editable document, in the order the export walks it (outline.py to_blocks):
   every on node is an <article class="doc-node">; an off node is a dim stub line; a folded node leaves a stub in place and its
   subtree moves to a "참고" section at the end; a page node leaves a stub paragraph and its subtree follows inline under a band.
   Articles are keyed and kept between updates (only what changed is re-synced, nothing is rebuilt under a field that has focus).
   Every edit goes through Keys (typing / op / split) or Tree (toggle / fold); this file never touches nodes. */
window.Doc = (() => {
  // boot.js (which defines Composer) loads after this file: look the helpers up at call time
  const api = (...a) => window.Composer.api(...a), esc = s => window.Composer.esc(s);
  const I = () => window.NodeInfo;                                  // nodeinfo.js loads before this file
  const host = () => document.getElementById("doc");
  const pane = () => document.getElementById("docPane");

  const els = new Map();                                            // key -> <article> (or the 참고 heading)
  const videos = new Map();                                         // node id -> <video>, kept so a redraw does not restart playback
  let curDraft = null, pageOrigin = null, mode = "edit";                           // where result pages open (from /api/state)

  const node = id => window.Tree?.nodes?.()[id];
  const key = e => `${e.id}|${e.stub || "node"}`;
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>").replace(/\n/g, "<br>");
  const focused = el => !!el && document.activeElement === el;
  const label = n => n.title || (n.text || "").split("\n")[0] || "(빈 글)";
  // a short fingerprint of a string (the items and files of a node go into the signature without making it long)
  const hash = s => { let h = 5381; for (let i = 0; i < s.length; i++) h = (h * 33 + s.charCodeAt(i)) | 0; return s.length + ":" + (h >>> 0).toString(36); };

  // ---- the walk: export order ----
  // [{id, stub: null|"off"|"folded"|"page"|"heading", pageOf: id|null}] in document order.
  // on=false -> one stub entry, no children. folded (not already in reference) -> a "folded" stub in place, and the subtree walked
  // again into the reference list of the document it belongs to. page (not in reference) -> a "page" stub in place, then the
  // subtree inline right after it, marked pageOf=id (the band). As in outline.py page_blocks, a page has its own reference list:
  // a folded node inside the page lands after the page's last inline entry, under a heading keyed "__ref:<pageId>". The main
  // reference list (folded nodes outside every page) is appended at the end under the "__ref" heading.
  function plan() {
    const main = [], ref = [], N = Tree.nodes();
    const walk = (ids, out, refOut, inRef, pageOf) => {
      for (const id of ids) {
        const n = N[id]; if (!n) continue;
        if (!n.on) { out.push({ id, stub: "off", pageOf }); continue; }
        if (n.page && !inRef) {
          out.push({ id, stub: "page", pageOf }, { id, stub: null, pageOf: id });
          const own = [];
          walk(n.children || [], out, own, false, id);
          if (own.length) out.push({ id: "__ref:" + id, stub: "heading", pageOf: id }, ...own);
          continue;
        }
        if (n.folded && !inRef) {
          out.push({ id, stub: "folded", pageOf }); refOut.push({ id, stub: null, pageOf });
          walk(n.children || [], refOut, refOut, true, pageOf); continue;
        }
        out.push({ id, stub: null, pageOf }); walk(n.children || [], out, refOut, inRef, pageOf);
      }
    };
    walk(Tree.state.draft.root, main, ref, false, null);
    return { main, ref };
  }

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
  // the caret at text offset `at` (counted over the body's text nodes, as caretOffset counts it)
  function setCaret(body, at) {
    const w = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    let t = null, last = null;
    while ((t = w.nextNode())) { last = t; if (at <= t.data.length) break; at -= t.data.length; }
    t = t || last; if (!t) return;
    const r = document.createRange(); r.setStart(t, Math.max(0, Math.min(at, t.data.length))); r.collapse(true);
    const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
  }
  function caretOffset(body) {
    const sel = getSelection();
    if (!sel.rangeCount || !body.contains(sel.anchorNode)) return null;
    const r = document.createRange(); r.selectNodeContents(body); r.setEnd(sel.anchorNode, sel.anchorOffset);
    return r.toString().length;
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

  // ---- one article ----
  function stubHTML(n, entry) {
    const main = entry.stub === "off" ? `<span class="doc-stubtext"></span><button type="button" class="doc-stubbtn">켜기</button>`
      : entry.stub === "folded" ? `<span class="doc-stubtext"></span><button type="button" class="doc-stubbtn">펴기</button>`
      : `<p class="doc-pagestub"><span class="doc-stubtext"></span> <span class="doc-link">[자세히]</span></p>`;
    return `<div class="doc-gutter"></div><div class="doc-main">${main}</div>`;
  }
  function stubText(n, entry) {
    if (entry.stub === "off") return `꺼짐 · ${label(n)}`;
    if (entry.stub === "folded") return `참고 절로 · ${label(n)}`;
    const first = I().firstSentence(n.text);
    return first ? `${n.title || label(n)} — ${first}` : (n.title || label(n));
  }

  function build(n, entry) {
    const id = n.id, art = document.createElement("article");
    art.className = `doc-node kind-${n.kind}`; art.dataset.id = id; art.dataset.key = key(entry); art.tabIndex = -1;
    // a click anywhere in the article (not on a control) selects its row; the keyboard stays where the writer put it
    art.addEventListener("click", e => {
      if (e.target.closest?.("button, a, video, summary")) return;
      Tree.select(id, null, { focus: false, scroll: false });
    });
    if (entry.stub) {
      art.classList.add("stub", "stub-" + entry.stub); art.innerHTML = stubHTML(n, entry);
      const btn = art.querySelector(".doc-stubbtn");
      btn?.addEventListener("click", () => {
        const off = entry.stub === "off";
        if (off) Tree.toggle(id); else Tree.fold(id);
        Tree.select(id, null, { focus: false });
        // this button has left the document: the keyboard goes to the expanded article (its dot after 켜기, so Space turns it off again)
        const art2 = els.get(`${id}|node`), dot = art2?.querySelector(".doc-dot");
        Motion.tap(dot);                                               // the 딸깍 lands where the eye is
        (off ? dot : art2)?.focus({ preventScroll: true });
      });
      return art;
    }
    const { BODIED, AID } = I();
    const record = n.kind === "record", listed = n.kind === "flow" || n.kind === "ledger", bodied = BODIED.includes(n.kind);
    art.innerHTML = `<div class="doc-gutter"><button type="button" class="doc-dot" aria-label="켜기/끄기"></button><span class="doc-stale" hidden role="img" aria-label="다듬을 것">●</span></div>`
      + `<div class="doc-main">`
      + `<div class="n-stale" role="status" hidden><span>구조가 바뀌었습니다. 본문을 다시 읽어 보세요</span><span class="n-stalebtns"><button type="button" class="n-polish" hidden>✨ 다시 다듬기</button><button type="button" class="n-ack">확인했어요</button></span></div>`
      + (n.kind === "project" || n.kind === "claim" ? `<input class="doc-title ${n.kind === "project" ? "h2" : "h3"}" aria-label="제목" placeholder="제목" autocomplete="off">` : "")
      + (record ? `<div class="n-media" hidden></div><div class="doc-caps"><textarea class="n-cap" rows="1" aria-label="설명 첫 줄: 무엇이 보이는가" placeholder="무엇이 보이는가" autocomplete="off"></textarea><textarea class="n-cap" rows="1" aria-label="설명 둘째 줄: 왜 중요한가" placeholder="왜 중요한가" autocomplete="off"></textarea></div>` : "")
      + (listed ? `<ul class="n-items"></ul>` : "")
      + (bodied ? `<div class="n-body" role="textbox" aria-multiline="true" aria-label="본문" data-placeholder="본문을 쓰세요"></div>` : "")
      + `<div class="n-aidbox" data-for="${esc(id)}" aria-live="polite"></div>`
      + `</div>`;
    const q = s => art.querySelector(s);
    const dot = q(".doc-dot"), title = q(".doc-title"), caps = [...art.querySelectorAll(".n-cap")], body = q(".n-body");
    dot.addEventListener("click", () => {
      Motion.tap(dot); Tree.toggle(id);
      // the article became a stub: the keyboard goes to its 켜기 (Space turns the node back on)
      const btn = els.get(`${id}|off`)?.querySelector(".doc-stubbtn");
      Motion.tap(btn); btn?.focus({ preventScroll: true });
    });
    q(".n-ack").addEventListener("click", () => {
      const m = node(id); if (!m?.stale) return;
      if (body) Motion.sweep(body);                                  // 착지: the one motion here
      Keys.op({ type: "stale", id, from: true, to: false });
    });
    q(".n-polish").addEventListener("click", () => { if (AID[n.kind]) window.Aids?.request(AID[n.kind][0], id); });
    title?.addEventListener("input", () => Keys.typing(id, "title", title.value));
    if (record) {
      const onCap = () => {
        grow(caps[0]); grow(caps[1]);
        const text = caps.map(c => c.value.trim() ? c.value : "").filter(Boolean);
        Keys.typing(id, "caption", text);
        remember(id);
      };
      caps.forEach(c => {
        c.addEventListener("input", () => {                         // a caption is one line that wraps: no line breaks, typed or pasted
          if (c.value.includes("\n")) { const at = c.selectionStart; c.value = c.value.replace(/\s*\n\s*/g, " "); c.setSelectionRange(at, at); }
          onCap();
        });
        c.addEventListener("keydown", e => { if (e.key === "Enter" && !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey && !e.isComposing) e.preventDefault(); });
      });
      requestAnimationFrame(() => caps.forEach(grow));
    }
    if (body) wireBody(id, body);
    return art;
  }

  // a caption field is as tall as its text (a long line wraps instead of being cut); a hidden field has no height to measure yet
  function grow(c) { c.style.height = "auto"; if (c.scrollHeight) c.style.height = c.scrollHeight + "px"; }
  new ResizeObserver(() => { if (mode === "edit") host()?.querySelectorAll(".n-cap").forEach(grow); }).observe(document.getElementById("docPane"));

  function wireBody(id, body) {
    try { body.contentEditable = "plaintext-only"; } catch { body.contentEditable = "true"; } // browsers without plaintext-only
    body.addEventListener("focus", () => {
      const m = node(id); if (!m) return;
      const raw = m.text || "", vis = textBefore(body);
      body.textContent = raw; delete body.dataset.rendered;
      setCaret(body, vis === null ? raw.length : rawIndexOf(raw, vis.length));
    });
    body.addEventListener("blur", () => { const m = node(id); if (m) renderBody(body, m, true); });
    body.addEventListener("input", () => Keys.typing(id, "text", rawOf(body)));
    body.addEventListener("keydown", e => {
      if (e.key !== "Enter" || e.isComposing || e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return;
      const m = node(id); if (!m || !I().SPLITTABLE.includes(m.kind)) return;
      const at = caretOffset(body), raw = rawOf(body);
      if (at === null || at < 1 || raw[at - 1] !== "\n") return;       // an Enter at the start of a line splits (the second Enter in a row); inside a line it breaks the line
      e.preventDefault();
      Keys.typing(id, "text", raw);                                    // the model must hold exactly what is on screen
      const nid = Keys.split(id, at);
      if (nid) requestAnimationFrame(() => focusNode(nid));            // the new article exists after Tree.change: keep writing in it
    });
  }

  function renderBody(b, n, force) {
    if (!b || (focused(b) && !force)) return;
    if (!force && b.dataset.raw === (n.text || "") && b.dataset.rendered) return;
    b.innerHTML = inline(n.text || ""); b.dataset.raw = n.text || ""; b.dataset.rendered = "1";
  }

  function renderItems(ul, n) {
    if (!ul) return;
    const html = (n.items || []).map(i => n.kind === "flow"
      ? `<li><time>${esc(String(i.when || "").slice(0, 10))}</time> ${esc(i.text || "")}</li>`
      : `<li><i class="chip">${esc(I().LEDGER_LABEL[i.kind] || i.kind)}</i> ${esc(i.text || "")}</li>`).join("");
    if (ul.dataset.sig !== html) { ul.innerHTML = html || '<li class="n-none">항목이 없어요.</li>'; ul.dataset.sig = html; }
  }

  const failed = (what, href) => Object.assign(document.createElement("p"), { className: "n-none", textContent: `${what}을 불러오지 못했습니다 (${href.split("/").pop()})` });

  function renderMedia(box, n) {
    if (!box) return;
    const m = I().mediaFor(n), week = n.src?.week || Tree.state.draft.week;
    const k = m ? m.kind + "|" + m.href : "";
    if (box.dataset.key === k) return;
    box.dataset.key = k;
    if (!m) { box.hidden = true; box.replaceChildren(); return; }
    box.hidden = false;
    const url = `/files/${week}/${I().enc(m.href)}`;
    if (m.kind === "video") {
      let v = videos.get(n.id);
      if (v && v.dataset.url !== url) { v.pause(); videos.delete(n.id); v = null; }
      if (!v) {
        v = document.createElement("video"); v.controls = true; v.preload = "none"; v.playsInline = true; v.dataset.url = url; v.src = url;
        v.setAttribute("aria-label", n.title || "영상"); videos.set(n.id, v);
        v.addEventListener("error", () => {  // a failed source: say so instead of a dead player, and let the next visit try again
          videos.delete(n.id); v.parentNode?.replaceChildren(failed("영상", m.href));
        });
      }
      if (box.firstChild !== v) box.replaceChildren(v);
    } else if (m.kind === "image") {
      const img = new Image(); img.loading = "lazy"; img.alt = n.title || ""; img.className = "n-img"; box.classList.add("loading");
      img.onload = () => box.classList.remove("loading");
      img.onerror = () => { box.classList.remove("loading"); box.replaceChildren(failed("그림", m.href)); };
      img.src = url; box.replaceChildren(img);
    } else {
      const a = document.createElement("a"); a.className = "n-open"; a.target = "_blank"; a.rel = "noopener"; a.textContent = "열기 · " + m.href.split("/").pop();
      a.href = `${pageOrigin || location.protocol + "//localhost:" + location.port}/page/${week}/${I().enc(m.href)}`;
      box.replaceChildren(a);
    }
  }

  // the parts that follow the writing aids (provider set, a job running) rather than the node: checked on every sync
  function syncAids(art, n) {
    const box = art.querySelector(".n-aidbox"); if (!box) return;
    const aids = window.Aids, ready = !!aids?.state.ready, busy = !!aids?.busy(n.id);
    const polish = art.querySelector(".n-polish"), ack = art.querySelector(".n-ack");
    polish.hidden = !ready || !I().AID[n.kind]; polish.disabled = busy; ack.hidden = !polish.hidden;
    aids?.render(n.id, box);
  }

  // bring one article to the node's current values; fields with focus are left alone
  function sync(art, n, entry) {
    art._entry = entry;
    art.classList.toggle("sel", Tree.state.sel === n.id);
    if (!entry.stub) syncAids(art, n);
    const sig = JSON.stringify([n.title, n.text, n.caption, n.show, n.on, n.folded, n.page, n.stale, n.representative, n.href,
      hash(JSON.stringify([n.items || [], n.files || [], n.src?.week || ""])), Tree.state.sel === n.id, entry.pageOf]);
    if (art.dataset.sig === sig) return;
    art.dataset.sig = sig;
    if (entry.pageOf) art.dataset.pageOf = entry.pageOf; else delete art.dataset.pageOf;
    if (entry.stub) { art.querySelector(".doc-stubtext").textContent = stubText(n, entry); return; }
    // the band of a page sits on the page's own article (the first inline one)
    let band = art.querySelector(":scope > .doc-band");
    if (entry.pageOf === n.id) {
      if (!band) { band = document.createElement("div"); band.className = "doc-band"; art.prepend(band); }
      band.textContent = `별도 페이지 · ${n.title || label(n)}`;
    } else band?.remove();
    const q = s => art.querySelector(s);
    const dot = q(".doc-dot"), title = q(".doc-title");
    dot.setAttribute("aria-pressed", String(!!n.on)); dot.setAttribute("aria-label", `${label(n)} 켜기/끄기`);
    q(".doc-stale").hidden = !n.stale;
    q(".n-stale").hidden = !n.stale;
    if (title && !focused(title) && title.value !== (n.title || "")) title.value = n.title || "";
    if (n.kind === "record") {
      const caps = [...art.querySelectorAll(".n-cap")];
      if (!caps.some(focused)) { const cap = n.caption || []; caps.forEach((c, i) => { if (c.value !== (cap[i] || "")) c.value = cap[i] || ""; grow(c); }); }
      renderMedia(q(".n-media"), n);
    }
    renderItems(q(".n-items"), n);
    renderBody(q(".n-body"), n);
  }

  // the "참고" heading of a reference list: "__ref" for the document's own (at the end), "__ref:<pageId>" for a page's (inside its band)
  function refHeading(entry) {
    const h = document.createElement("h2"); h.className = "doc-refhead"; h.dataset.key = entry.id; h.textContent = "참고";
    if (entry.pageOf) h.dataset.pageOf = entry.pageOf;
    return h;
  }

  // where the caret (or an input's selection) is, so it can be put back when its article had to move
  function caretOf(el) {
    if (el.matches("input, textarea")) return { start: el.selectionStart, end: el.selectionEnd };
    if (el.isContentEditable) { const at = caretOffset(el); return at === null ? null : { at }; }
    return null;
  }
  function restoreCaret(el, c) {
    if (!c) return;
    if ("start" in c) { try { el.setSelectionRange(c.start, c.end); } catch { /* not a text input */ } return; }
    const raw = el.classList.contains("n-body") ? node(el.closest(".doc-node")?.dataset.id)?.text : null;
    if (raw != null && el.textContent !== raw) el.textContent = raw;   // a blur on the way may have rendered it
    setCaret(el, c.at);
  }

  // ---- update: re-walk, move/create/remove articles, re-sync what changed ----
  function update() {
    const h = host(); if (!h || !Tree.state.draft) return;
    if (mode === "check") { scheduleCheck(); return; }               // the articles are re-synced on the way back to the edit view
    const { main, ref } = plan(), N = Tree.nodes();
    const wanted = [...main, ...(ref.length ? [{ id: "__ref", stub: "heading", pageOf: null }, ...ref] : [])];
    const keys = wanted.map(e => e.stub === "heading" ? e.id : key(e)), keep = new Set(keys);
    const ae = document.activeElement, inside = ae && h.contains(ae) ? ae : null, caret = inside && caretOf(inside);
    let moved = false;
    // remove first, so the rest only moves when its order really changed (a moved ancestor drops the focus)
    for (const [k, el] of els) if (!keep.has(k)) { el.remove(); els.delete(k); }
    wanted.forEach((e, i) => {
      const k = keys[i];
      let el = els.get(k);
      if (!el) { el = e.stub === "heading" ? refHeading(e) : build(N[e.id], e); els.set(k, el); }
      if (h.children[i] !== el) { if (inside && el.contains(inside)) moved = true; h.insertBefore(el, h.children[i] || null); }
      if (e.stub !== "heading") sync(el, N[e.id], e);
    });
    while (h.children.length > wanted.length) h.lastChild.remove();
    // the field being edited sat in an article that had to move: give it back its focus and its caret
    if (inside && inside.isConnected && (moved || document.activeElement !== inside)) {
      if (document.activeElement !== inside) inside.focus({ preventScroll: true });
      restoreCaret(inside, caret);
    }
    h.classList.toggle("empty", !wanted.length);
  }

  function open(draft) {
    if (draft !== curDraft) { videos.forEach(v => v.pause()); videos.clear(); curDraft = draft; checkKey = null; checkEl()?.querySelector(".doc-checkbody")?.replaceChildren(); setMode("edit"); }
    els.clear(); host()?.replaceChildren();
    const p = pane(); if (p) p.scrollTop = 0;
    update();
  }

  // re-sync the articles of one node (the writing aids call this when a job starts or ends)
  function refresh(id) {
    const n = node(id); if (!n) return;
    for (const el of host().querySelectorAll(`.doc-node[data-id="${CSS.escape(id)}"]`)) if (el._entry) { delete el.dataset.sig; sync(el, n, el._entry); }
  }

  // highlight the node's articles; scroll to its page stub when it is a page (the stub paragraph is where it sits in the report),
  // else to its body article, else to its stub
  function select(id, { scroll = true } = {}) {
    if (mode === "check") return;                                    // the check view has no per-node anchors: no selection sync there
    let target = null;
    const rank = el => el.classList.contains("stub-page") ? 3 : el.classList.contains("stub") ? 1 : 2;
    for (const el of host().querySelectorAll(".doc-node")) {
      const on = el.dataset.id === id; el.classList.toggle("sel", on);
      if (on && (!target || rank(el) > rank(target))) target = el;
    }
    if (scroll && target) target.scrollIntoView({ block: "start", behavior: Motion.reduced() ? "auto" : "smooth" });
  }

  // put the caret in that node's body (or its title when it has no body)
  function focusNode(id) {
    const art = els.get(`${id}|node`); if (!art) return;
    (art.querySelector(".n-body") || art.querySelector(".doc-title") || art.querySelector(".n-cap"))?.focus();
  }

  // The export is Confluence storage XHTML, which a browser does not draw (ac:image, CDATA links): give the attachments their real
  // files here, and keep the rest as the browser's plain reading of it. The 내보내기 점검 view paints with it.
  // the attachment name the server gives a file: storage.attachment_name of "<week>/<href>" (flat, ASCII-safe, `_` for everything else)
  const attName = src => src.replace(/\\/g, "/").replace(/\//g, "_").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "") || "file";
  function display(xhtml) {
    const urls = new Map();
    for (const [m] of Tree.walk()) {
      const week = m.src?.week || Tree.state.draft.week;
      for (const href of [m.href, m.representative, ...(m.files || []).map(f => f.href)]) {
        if (!href) continue;
        const k = attName(`${week}/${href}`);
        if (!urls.has(k)) urls.set(k, `/files/${week}/${I().enc(href)}`);   // first wins, like storage.attachments_for (setdefault)
      }
    }
    return xhtml
      .replace(/<ac:image\b[^>]*>\s*<ri:attachment ri:filename="([^"]*)"\s*\/>\s*<\/ac:image>/g, (_, name) => {
        const plain = name.replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
        const url = urls.get(plain);
        return url ? `<img src="${esc(url)}" alt="${esc(plain)}">` : `<span class="n-pimg">[그림] ${esc(plain)}</span>`;
      })
      .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, (_, t) => esc(t));
  }

  // ---- 내보내기 점검: the whole draft through the server's own renderer, read-only ----
  // No fields and no selection sync here (the export has no per-node anchors). Cached by what the export depends on.
  let checkKey = null, checkTimer = null, checkSeq = 0;
  const checkEl = () => document.getElementById("docCheck");
  function scheduleCheck() { clearTimeout(checkTimer); checkTimer = setTimeout(renderCheck, 400); }
  async function renderCheck() {
    const box = checkEl(); if (!box || mode !== "check") return;
    const seq = ++checkSeq, state = box.querySelector(".n-pstate"), view = box.querySelector(".doc-checkbody");
    const slow = setTimeout(() => { if (seq === checkSeq) { state.textContent = "미리보기 만드는 중…"; view.classList.add("busy"); } }, 300);
    try {
      await Tree.settle();                                           // a pending save first: what is shown is what is stored
      const d = Tree.state.draft; if (!d || seq !== checkSeq) return;
      const key = JSON.stringify(d.nodes) + "|" + JSON.stringify(d.root) + "|" + (d.week || "");
      if (key === checkKey && view.childNodes.length) { state.textContent = ""; return; }
      const r = await api("/api/preview", { method: "POST", body: { draft: d } });
      if (seq !== checkSeq || mode !== "check") return;
      if (r?.error) { state.textContent = "미리보기를 만들지 못했어요: " + r.error; return; }
      view.innerHTML = r?.xhtml ? display(r.xhtml) : "";            // the server renders our own blocks to XHTML (text escaped there)
      view.querySelectorAll("a").forEach(a => { a.target = "_blank"; a.rel = "noopener"; });
      state.textContent = r?.xhtml ? "" : "내보낼 내용이 아직 없어요. 개요에서 줄을 켜 보세요.";
      checkKey = key;
    } catch (e) {
      if (seq === checkSeq) state.textContent = "미리보기를 만들지 못했어요: " + e.message;
    } finally { clearTimeout(slow); if (seq === checkSeq) view.classList.remove("busy"); }
  }

  // "edit" | "check": the toggle in the document head, and Escape (keys.js) back from the check view
  function setMode(m) {
    if (m !== "edit" && m !== "check") return;
    document.getElementById("tree")?.setAttribute("data-mode", m);
    document.querySelectorAll(".doc-mode [data-mode]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.mode === m)));
    if (m === mode) return;
    mode = m;
    const h = host(), box = checkEl(); if (!h || !box) return;
    clearTimeout(checkTimer); checkSeq++;
    if (m === "check") { h.hidden = true; box.hidden = false; box.querySelector(".doc-checkbody").classList.remove("busy"); renderCheck(); return; }
    box.hidden = true; h.hidden = false;
    update(); h.querySelectorAll(".n-cap").forEach(grow);            // what changed while it was hidden; captions could not measure themselves
  }
  document.querySelectorAll(".doc-mode [data-mode]").forEach(b => b.addEventListener("click", () => setMode(b.dataset.mode)));

  fetch("/api/state").then(r => r.json()).then(s => { pageOrigin = s.page_origin || null; }).catch(() => {});

  return { open, update, select, refresh, remember, focusNode, setMode };
})();
