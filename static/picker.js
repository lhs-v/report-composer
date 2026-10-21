/* Injected into result pages shown inside the composer. Hover highlights pickable elements; a click sends the
   element to the parent window (postMessage) so it can become a draft block. Alt+hover targets the enclosing
   section so a whole region can be lifted at once. Does nothing when not framed. */
(() => {
  if (window.parent === window) return;
  const PICK = "img, svg, canvas, video, audio, table, figure, pre, blockquote, p, h1, h2, h3, h4, li, dt, dd";
  const REGION = "section, article, main, aside, details, div";
  const style = document.createElement("style");
  style.textContent = `
    .cp-hover { outline: 2px solid #0d6b61 !important; outline-offset: 2px; cursor: copy !important; background: rgba(13,107,97,.06) !important; }
    .cp-region { outline: 2px dashed #b4541f !important; outline-offset: 3px; cursor: copy !important; background: rgba(180,84,31,.05) !important; }
    .cp-tip { position: fixed; z-index: 2147483647; background:#0d6b61; color:#fff; font: 12px system-ui, sans-serif; padding: 2px 8px; border-radius: 4px; pointer-events:none; white-space:nowrap; }
    .cp-tip.region { background:#b4541f; }
    .cp-done { outline: 2px dashed #5f6a65 !important; }`;
  document.head.appendChild(style);
  const tip = document.createElement("div"); tip.className = "cp-tip"; tip.hidden = true; document.body.appendChild(tip);
  const label = el => ({ IMG: "그림", SVG: "SVG 그림", CANVAS: "캔버스 그림", VIDEO: "영상", AUDIO: "음성", TABLE: "표", FIGURE: "그림", PRE: "코드",
    BLOCKQUOTE: "인용", LI: "항목", DT: "용어", DD: "설명" }[el.tagName] || (/^H\d$/.test(el.tagName) ? "제목" : "문단"));
  let cur = null, curRegion = false;
  const closestPick = el => el.closest ? el.closest(PICK) : null;
  const closestRegion = el => { let r = el.closest ? el.closest(REGION) : null; while (r && r.innerText.trim().length < 40 && r.parentElement) r = r.parentElement.closest(REGION); return r; };
  function setCur(t, region) {
    if (t === cur && region === curRegion) return;
    cur?.classList.remove("cp-hover", "cp-region"); cur = t; curRegion = region;
    cur?.classList.add(region ? "cp-region" : "cp-hover");
  }
  document.addEventListener("mousemove", e => {
    const region = e.altKey;
    const t = region ? closestRegion(e.target) : closestPick(e.target);
    setCur(t, region);
    if (cur) { tip.hidden = false; tip.className = "cp-tip" + (region ? " region" : ""); tip.textContent = region ? "구역 통째로 담기 (Alt+클릭)" : `${label(cur)} 담기 (클릭)`;
      tip.style.left = (e.clientX + 12) + "px"; tip.style.top = (e.clientY + 14) + "px"; } else tip.hidden = true;
  }, true);
  document.addEventListener("keyup", e => { if (e.key === "Alt") setCur(null, false); });
  document.addEventListener("mouseleave", () => { setCur(null, false); tip.hidden = true; });

  const abs = u => { try { return new URL(u, document.baseURI).href; } catch { return u; } };
  const text = el => (el.innerText || el.textContent || "").replace(/\s+\n/g, "\n").trim();
  async function imgData(img) {
    if (img.src.startsWith("data:")) return img.src;
    try { const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight; c.getContext("2d").drawImage(img, 0, 0); return c.toDataURL("image/png"); } catch { return null; }
  }
  async function svgData(svg) {
    try {
      const clone = svg.cloneNode(true);
      const r = svg.getBoundingClientRect(); const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
      if (!clone.getAttribute("width")) clone.setAttribute("width", w); if (!clone.getAttribute("height")) clone.setAttribute("height", h);
      clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      const cs = getComputedStyle(svg); clone.style.color = cs.color; clone.style.fontFamily = cs.fontFamily; clone.style.background = cs.backgroundColor;
      const xml = new XMLSerializer().serializeToString(clone);
      const url = URL.createObjectURL(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }));
      const png = await new Promise(res => { const im = new Image(); im.onload = () => { const c = document.createElement("canvas"); c.width = w * 2; c.height = h * 2;
        const g = c.getContext("2d"); g.fillStyle = cs.backgroundColor && cs.backgroundColor !== "rgba(0, 0, 0, 0)" ? cs.backgroundColor : "#ffffff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(im, 0, 0, c.width, c.height); res(c.toDataURL("image/png")); };
        im.onerror = () => res(null); im.src = url; });
      URL.revokeObjectURL(url);
      return png || ("data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml))));
    } catch { return null; }
  }
  async function describe(t) {
    const tag = t.tagName;
    if (tag === "IMG" || (tag === "FIGURE" && t.querySelector("img"))) {
      const img = tag === "IMG" ? t : t.querySelector("img");
      return { tag: "img", src: abs(img.getAttribute("src") || ""), data: await imgData(img), alt: img.alt || "", caption: t.querySelector?.("figcaption")?.innerText || img.alt || "" };
    }
    if (tag === "SVG" || (tag === "FIGURE" && t.querySelector("svg"))) {
      const svg = tag === "SVG" ? t : t.querySelector("svg");
      return { tag: "svg", data: await svgData(svg), caption: t.querySelector?.("figcaption")?.innerText || svg.getAttribute("aria-label") || svg.querySelector("title")?.textContent || "" };
    }
    if (tag === "CANVAS") { try { return { tag: "canvas", data: t.toDataURL("image/png"), caption: t.getAttribute("aria-label") || "" }; } catch { return { tag: "canvas", data: null }; } }
    if (tag === "VIDEO" || tag === "AUDIO") { const s = t.querySelector("source"); return { tag: tag.toLowerCase(), src: abs(t.getAttribute("src") || s?.getAttribute("src") || ""), caption: t.title || "" }; }
    if (tag === "TABLE") return { tag: "table", rows: [...t.querySelectorAll("tr")].map(tr => [...tr.children].map(td => td.innerText.trim())), header: !!t.querySelector("th") };
    if (tag === "LI" || tag === "DD" || tag === "DT") return { tag: "li", text: text(t) };
    if (tag === "FIGURE") return { tag: "p", text: text(t) };
    return { tag: tag.toLowerCase(), text: text(t), level: /^H\d$/.test(tag) ? +tag[1] : null };
  }
  async function bundle(region) {
    const items = [];
    const nodes = region.querySelectorAll("h1, h2, h3, h4, p, li, img, svg, canvas, table, video, audio, pre, blockquote");
    const used = new Set();
    for (const n of nodes) {
      if ([...used].some(u => u.contains(n))) continue;            // skip nested duplicates (li inside a picked table etc.)
      if (n.closest("table") && n.tagName !== "TABLE") continue;
      if ((n.tagName === "P" || n.tagName === "LI") && !text(n)) continue;
      used.add(n);
      items.push({ ...(await describe(n)), title: document.title });
    }
    return items;
  }
  document.addEventListener("click", async e => {
    const region = e.altKey ? closestRegion(e.target) : null;
    const t = region || closestPick(e.target); if (!t) return;
    e.preventDefault(); e.stopPropagation();
    const base = { kind: "cp-pick", title: document.title };
    const msg = region ? { ...base, tag: "bundle", items: await bundle(region) } : { ...base, ...(await describe(t)) };
    window.parent.postMessage(msg, "*");
    t.classList.add("cp-done");
  }, true);
  window.parent.postMessage({ kind: "cp-ready", title: document.title }, "*");
})();
