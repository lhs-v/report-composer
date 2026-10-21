/* Injected into result pages shown by the composer (in its middle column or in a window it opened).
   Hovering shows the *reading unit* under the mouse — a figure with its caption, a callout card, a whole list,
   a table, a section under a heading, or a paragraph — and a click sends that unit to the composer, which turns
   it into draft blocks. Alt widens the unit to the enclosing region. Does nothing when the page stands alone. */
(() => {
  const host = window.parent !== window ? window.parent : window.opener;
  if (!host) return;
  const post = msg => host.postMessage({ ...msg, page: location.pathname, title: document.title }, "*");

  const style = document.createElement("style");
  style.textContent = `
    .cp-hover { outline: 2px solid #0d6b61 !important; outline-offset: 3px; cursor: copy !important; background: rgba(13,107,97,.05) !important; }
    .cp-wide { outline: 2px dashed #b4541f !important; outline-offset: 4px; cursor: copy !important; background: rgba(180,84,31,.05) !important; }
    .cp-tip { position: fixed; z-index: 2147483647; background:#0d6b61; color:#fff; font: 12px system-ui, sans-serif; padding: 3px 9px; border-radius: 4px; pointer-events:none; white-space:nowrap; box-shadow:0 2px 8px rgba(0,0,0,.25); }
    .cp-tip.wide { background:#b4541f; }
    .cp-done { outline: 2px dashed #5f6a65 !important; outline-offset: 3px; }`;
  document.head.appendChild(style);
  const tip = document.createElement("div"); tip.className = "cp-tip"; tip.hidden = true; document.body.appendChild(tip);

  // ---------- classifying elements ----------
  const MEDIA = "img, svg, canvas, video, audio";
  const SKIP = "script, style, template, noscript, button, input, select, textarea, label, nav, [role=button], [hidden], .cp-tip";
  const cs = el => getComputedStyle(el);
  const tagOf = el => (el.tagName || "").toUpperCase();
  const BLOCK_TAGS = /^(P|DIV|SECTION|ARTICLE|LI|DD|DT|H[1-6]|BLOCKQUOTE|PRE|FIGURE|FIGCAPTION|TD|TH|ASIDE|HEADER|FOOTER|MAIN|DETAILS|SUMMARY|UL|OL|TABLE|OUTPUT)$/;
  const isBlock = el => el instanceof Element && el !== document.documentElement && el !== document.body &&
    (BLOCK_TAGS.test(tagOf(el)) || /^(block|flex|grid|list-item|table|flow-root|inline-block)/.test(cs(el).display));
  const visible = el => el.getClientRects().length > 0 && cs(el).visibility !== "hidden";
  const txt = el => (el.innerText ?? el.textContent ?? "").replace(/[ \t]+\n/g, "\n").trim();
  const level = el => /^H[1-6]$/.test(tagOf(el)) ? +tagOf(el)[1] : null;
  const blockKids = el => [...el.children].filter(c => isBlock(c) && !c.matches(SKIP) && visible(c));
  // a leaf text block: has text of its own, holds no media/table, and none of its block children carry text
  const isLeafText = el => isBlock(el) && !el.matches(SKIP) && txt(el).length > 0 && !el.querySelector(MEDIA + ", table") && !blockKids(el).some(c => txt(c).length > 0);
  const isHeadingLike = el => level(el) != null || (isLeafText(el) && parseInt(cs(el).fontWeight) >= 600 && txt(el).length <= 80 && !el.closest("li, td, th, figcaption"));
  const boxed = el => { const s = cs(el), bg = cs(document.body).backgroundColor, pbg = el.parentElement ? cs(el.parentElement).backgroundColor : bg;
    return (s.backgroundColor !== "rgba(0, 0, 0, 0)" && s.backgroundColor !== bg && s.backgroundColor !== pbg) || parseFloat(s.borderLeftWidth) > 1 || parseFloat(s.borderTopWidth) > 0 ||
      /card|callout|box|note|panel|alert|tip|warn|claim|info|finding|highlight|summary/i.test(el.className || ""); };

  // children laid out side by side (a grid or flex row): [[a, b, c], [d, e, f]], or null when stacked
  function rowsOf(el) {
    if (!el || el === document.body || !isBlock(el)) return null;
    const kids = blockKids(el).filter(k => txt(k) || k.querySelector(MEDIA));
    if (kids.length < 2 || kids.length > 24) return null;
    const rects = kids.map(k => k.getBoundingClientRect());
    if (rects.some(r => r.width < 90 || r.height < 16)) return null;
    const rows = [];
    kids.forEach((k, i) => { const r = rects[i]; const row = rows.find(rw => Math.abs(rw.top - r.top) < 12); row ? row.items.push([k, r]) : rows.push({ top: r.top, items: [[k, r]] }); });
    rows.sort((a, b) => a.top - b.top);
    const n = rows[0].items.length;
    if (n < 2 || n > 4 || !rows.slice(0, -1).every(rw => rw.items.length === n) || rows.at(-1).items.length > n) return null;
    return rows.map(rw => rw.items.sort((a, b) => a[1].left - b[1].left).map(x => x[0]));
  }
  const richRow = rows => rows.flat().some(k => boxed(k) || k.querySelector(MEDIA) || txt(k).length > 80);

  // a figure box: holds exactly one piece of media and at most a short caption
  function figureMedia(box) {
    if (!box || box === document.body || box.querySelector("table, ul, ol")) return null;
    const medias = [...box.querySelectorAll(MEDIA)].filter(m => !m.closest("svg") || m.closest("svg") === m);
    if (medias.length !== 1) return null;
    return captionOf(box, medias[0]).length <= 320 ? medias[0] : null;
  }
  // a callout card: a boxed container with a short title-like first line and a little body text
  function cardOf(box) {
    if (!box || box === document.body || !isBlock(box) || !boxed(box)) return null;
    if (box.querySelector(MEDIA + ", table, ul, ol") || txt(box).length > 700) return null;
    const kids = blockKids(box).filter(k => txt(k));
    if (kids.some(k => boxed(k) && blockKids(k).length)) return null;      // a region holding cards, not a card
    const rows = rowsOf(box); if (rows && richRow(rows)) return null;
    if (kids.length >= 2 && kids.length <= 8) {
      const first = kids[0];
      const titled = isHeadingLike(first) || (first.querySelector(":scope > b, :scope > strong") && txt(first).length <= 120);
      return { el: box, title: titled ? txt(first) : "", body: kids.slice(titled ? 1 : 0).map(txt).join("\n") };
    }
    if (isLeafText(box)) {                                           // <div class="claim"><b>title.</b> body</div>
      const b = box.querySelector(":scope > b, :scope > strong");
      if (b) { const title = txt(b); return { el: box, title, body: txt(box).slice(title.length).replace(/^[\s:.·-]+/, "") }; }
      return { el: box, title: "", body: txt(box) };
    }
    return null;
  }

  // ---------- units ----------
  // unit = { kind, label, els: [elements to outline], nodes: [content descriptors in reading order] }
  const unitOf = (kind, label, els, nodes) => ({ kind, label, els, nodes });
  function mediaUnit(m) {
    let box = m.parentElement;
    for (let i = 0; i < 3 && box && box !== document.body; i++, box = box.parentElement) {
      if (figureMedia(box) === m) { const cap = captionOf(box, m); return unitOf("figure", mediaLabel(m) + (cap ? "+설명" : ""), [box], [mediaNode(m, cap)]); }
      if (txt(box).length > 320) break;
    }
    return unitOf("figure", mediaLabel(m), [m], [mediaNode(m, "")]);
  }
  const mediaLabel = m => ({ IMG: "그림", SVG: "SVG 그림", CANVAS: "그림", VIDEO: "영상", AUDIO: "음성" })[tagOf(m)] || "그림";
  const mediaNode = (m, caption) => ({ kind: ["VIDEO", "AUDIO"].includes(tagOf(m)) ? "media" : "image", el: m, caption });
  function captionOf(box, m) {
    const fc = box.querySelector("figcaption"); if (fc) return txt(fc);
    const clone = box.cloneNode(true);                               // caption = the box's text without the media and controls
    clone.querySelectorAll(MEDIA + ", " + SKIP).forEach(x => x.remove());
    const holder = document.createElement("div"); holder.style.cssText = "position:fixed;left:-9999px;top:0;width:800px"; holder.appendChild(clone); document.body.appendChild(holder);
    const t = txt(clone); holder.remove();
    return t.replace(/\s*\n\s*/g, " ").trim();
  }
  function sectionUnit(h) {
    const lv = level(h) ?? 3, parent = h.parentElement, sibs = blockKids(parent);
    const i = sibs.indexOf(h), span = [h];
    for (const s of sibs.slice(i + 1)) { if (isHeadingLike(s) && (level(s) ?? 3) <= lv) break; span.push(s); }
    const whole = i === 0 && span.length === sibs.length && parent !== document.body;
    const nodes = collect(span);
    return unitOf("section", span.length > 1 ? `섹션 ${nodes.length}개` : "제목", whole ? [parent] : span, nodes);
  }
  function closestCard(leaf) {
    for (let cur = leaf, i = 0; cur && cur !== document.body && i < 4; cur = cur.parentElement, i++) { const c = cardOf(cur); if (c) return c; }
    return null;
  }
  function leafOf(el) {
    if (!(el instanceof Element) || el.closest(SKIP)) return null;
    const svg = el.closest("svg"); if (svg) return svg;
    const m = el.closest(MEDIA); if (m) return m;
    const tbl = el.closest("table"); if (tbl) return tbl;
    for (let cur = el; cur && cur !== document.body; cur = cur.parentElement) if (isLeafText(cur)) return cur;
    return null;
  }
  function unitFor(target) {
    const leaf = leafOf(target); if (!leaf) return null;
    const T = tagOf(leaf);
    if (leaf.matches(MEDIA)) return mediaUnit(leaf);
    if (T === "TABLE") return unitOf("table", `표 ${leaf.querySelectorAll("tr").length}행`, [leaf], [{ kind: "table", el: leaf }]);
    const li = leaf.closest("li");
    if (li) {                                                        // a boxed <li> is a card of its own; a plain one belongs to its list
      const card = cardOf(li); if (card) return unitOf("callout", "강조 상자", [li], [{ kind: "callout", ...card }]);
      return listUnit(li.closest("ul, ol"));
    }
    const pre = leaf.closest("pre"); if (pre) return unitOf("code", "코드", [pre], [{ kind: "code", el: pre }]);
    const card = closestCard(leaf);                                 // anywhere inside a card picks the card; Alt widens to its row
    if (card) return unitOf("callout", "강조 상자", [card.el], [{ kind: "callout", ...card }]);
    if (isHeadingLike(leaf)) return sectionUnit(leaf);
    const q = leaf.closest("blockquote"); if (q) return unitOf("quote", "인용", [q], [{ kind: "text", el: q }]);
    return unitOf("text", "문단", [leaf], [{ kind: "text", el: leaf }]);
  }
  const listUnit = list => unitOf("list", `목록 ${list.children.length}개`, [list], [{ kind: "list", el: list }]);
  function widen(u) {
    const base = u.els[0];
    if (tagOf(base) === "LI") return listUnit(base.closest("ul, ol"));
    let box = base.parentElement;
    while (box && box !== document.body && (blockKids(box).filter(k => txt(k) || k.querySelector(MEDIA)).length < 2 || txt(box).length === txt(base).length)) box = box.parentElement;
    if (!box || box === document.body) return u;
    const nodes = collect([box]);
    const label = nodes.length && nodes.every(n => n.kind === "columns") ? `가로 ${nodes[0].cells.length}칸${nodes.length > 1 ? ` × ${nodes.length}줄` : ""}` : `구역 ${nodes.length}개`;
    return unitOf(nodes.every(n => n.kind === "columns") ? "columns" : "region", label, [box], nodes);
  }
  // flatten elements into content nodes, in reading order
  function collect(els) {
    const out = [];
    const walk = el => {
      if (!(el instanceof Element) || el.matches(SKIP) || !visible(el)) return;
      const T = tagOf(el);
      if (el.matches(MEDIA)) { out.push(mediaNode(el, "")); return; }
      const fm = figureMedia(el); if (fm && txt(el).length) { out.push(mediaNode(fm, captionOf(el, fm))); return; }
      if (T === "TABLE") { out.push({ kind: "table", el }); return; }
      if (T === "UL" || T === "OL") { const lis = [...el.children]; if (lis.length && lis.every(li => cardOf(li))) { lis.forEach(li => out.push({ kind: "callout", ...cardOf(li) })); } else out.push({ kind: "list", el }); return; }
      if (T === "PRE") { out.push({ kind: "code", el }); return; }
      if (isHeadingLike(el)) { out.push({ kind: "heading", el, level: level(el) ?? 3 }); return; }
      const rows = isLeafText(el) ? null : rowsOf(el);
      if (rows && (richRow(rows) || !cardOf(el))) { rows.forEach(r => out.push({ kind: "columns", el, cells: r.map(cell => collect([cell])) })); return; }
      const card = isLeafText(el) ? null : cardOf(el);
      if (card) { out.push({ kind: "callout", ...card }); return; }
      if (isLeafText(el)) { out.push({ kind: "text", el }); return; }
      for (const c of el.children) walk(c);
    };
    for (const el of els) walk(el);
    return out;
  }

  // ---------- hover ----------
  let cur = null, curTarget = null, curWide = null;
  function setCur(u, wide) {
    if (cur) cur.els.forEach(e => e.classList.remove("cp-hover", "cp-wide"));
    cur = u; if (cur) cur.els.forEach(e => e.classList.add(wide ? "cp-wide" : "cp-hover"));
  }
  function unitAt(target, wide) {
    if (target === curTarget && wide === curWide && cur) return cur;
    curTarget = target; curWide = wide;
    const u = unitFor(target);
    return u && wide ? widen(u) : u;
  }
  document.addEventListener("mousemove", e => {
    const u = unitAt(e.target, e.altKey);
    if (u !== cur) setCur(u, e.altKey);
    if (u) { tip.hidden = false; tip.className = "cp-tip" + (e.altKey ? " wide" : ""); tip.textContent = e.altKey ? `${u.label} 통째로 담기 (Alt+클릭)` : `${u.label} 담기 (클릭 · Alt: 더 넓게)`;
      tip.style.left = Math.min(e.clientX + 12, innerWidth - tip.offsetWidth - 8) + "px"; tip.style.top = (e.clientY + 16) + "px"; }
    else tip.hidden = true;
  }, true);
  document.addEventListener("keydown", e => { if (e.key === "Alt") { curTarget = null; e.preventDefault(); } });
  document.addEventListener("keyup", e => { if (e.key === "Alt") { curTarget = null; setCur(null); tip.hidden = true; } });
  document.addEventListener("mouseleave", () => { setCur(null); tip.hidden = true; curTarget = null; });

  // ---------- describing nodes ----------
  const abs = u => { try { return new URL(u, document.baseURI).href; } catch { return u; } };
  async function imgData(img) {
    if (img.src.startsWith("data:")) return img.src;
    try { if (!img.naturalWidth) return null; const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight; c.getContext("2d").drawImage(img, 0, 0); return c.toDataURL("image/png"); } catch { return null; }
  }
  async function svgData(svg) {
    try {
      const clone = svg.cloneNode(true);
      const r = svg.getBoundingClientRect(); const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
      clone.setAttribute("width", w); clone.setAttribute("height", h); clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      const s = cs(svg); clone.style.color = s.color; clone.style.fontFamily = s.fontFamily;
      // inline computed presentation so CSS variables and stylesheet rules survive outside the page
      const src = svg.querySelectorAll("*"), dst = clone.querySelectorAll("*");
      src.forEach((el, i) => { const c = cs(el); const d = dst[i]; if (!d) return;
        for (const p of ["fill", "stroke", "stroke-width", "opacity", "font-size", "font-family", "font-weight", "text-anchor", "stroke-dasharray", "fill-opacity", "stroke-opacity"]) { const v = c.getPropertyValue(p); if (v) d.style.setProperty(p, v); } });
      const xml = new XMLSerializer().serializeToString(clone);
      const url = URL.createObjectURL(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }));
      const bg = s.backgroundColor && s.backgroundColor !== "rgba(0, 0, 0, 0)" ? s.backgroundColor : cs(document.body).backgroundColor || "#ffffff";
      const png = await new Promise(res => { const im = new Image(); im.onload = () => { try { const c = document.createElement("canvas"); c.width = w * 2; c.height = h * 2;
        const g = c.getContext("2d"); g.fillStyle = bg; g.fillRect(0, 0, c.width, c.height); g.drawImage(im, 0, 0, c.width, c.height); res(c.toDataURL("image/png")); } catch { res(null); } };
        im.onerror = () => res(null); im.src = url; });
      URL.revokeObjectURL(url);
      return png || ("data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml))));
    } catch { return null; }
  }
  const listItems = list => [...list.children].filter(c => tagOf(c) === "LI").map(li => txt(li).replace(/\s*\n\s*/g, " — ")).filter(Boolean);
  async function describe(n) {
    const el = n.el, T = el ? tagOf(el) : "";
    switch (n.kind) {
      case "columns": { const cells = []; for (const cell of n.cells) { const items = []; for (const x of cell) items.push(await describe(x)); cells.push(items); } return { t: "columns", cells }; }
      case "image": {
        if (T === "IMG") return { t: "image", src: abs(el.getAttribute("src") || ""), data: await imgData(el), caption: n.caption || el.alt || "" };
        if (T === "SVG") return { t: "image", data: await svgData(el), caption: n.caption || el.getAttribute("aria-label") || el.querySelector("title")?.textContent || "" };
        try { return { t: "image", data: el.toDataURL("image/png"), caption: n.caption || el.getAttribute("aria-label") || "" }; } catch { return { t: "image", data: null, caption: n.caption || "" }; }
      }
      case "media": { const s = el.querySelector("source"); return { t: "media", tag: T.toLowerCase(), src: abs(el.getAttribute("src") || s?.getAttribute("src") || ""), caption: n.caption || el.title || el.getAttribute("aria-label") || "" }; }
      case "table": return { t: "table", rows: [...el.querySelectorAll("tr")].map(tr => [...tr.children].map(td => txt(td))), header: !!el.querySelector("th") };
      case "list": return { t: "list", items: listItems(el), ordered: T === "OL" };
      case "heading": return { t: "heading", level: n.level ?? 3, text: txt(el) };
      case "code": return { t: "code", text: txt(el) };
      case "callout": return { t: "callout", title: n.title || "", text: n.body || "" };
      default: return { t: "text", text: txt(el) };
    }
  }

  // ---------- click ----------
  document.addEventListener("click", async e => {
    const u = unitAt(e.target, e.altKey); if (!u) return;
    e.preventDefault(); e.stopPropagation();
    const items = [];
    for (const n of u.nodes) items.push(await describe(n));
    post({ kind: "cp-pick", unit: u.kind, label: u.label, items });
    u.els.forEach(el => el.classList.add("cp-done"));
  }, true);
  post({ kind: "cp-ready" });
})();
