/* Injected into result pages shown inside the composer. Hover highlights pickable elements; a click sends the
   element to the parent window (postMessage) so it can become a draft block. Does nothing when not framed. */
(() => {
  if (window.parent === window) return;
  const PICK = "img, video, audio, table, figure, pre, blockquote, p, h1, h2, h3, h4, li";
  const style = document.createElement("style");
  style.textContent = `
    .cp-hover { outline: 2px solid #0d6b61 !important; outline-offset: 2px; cursor: copy !important; background: rgba(13,107,97,.06) !important; }
    .cp-tip { position: fixed; z-index: 2147483647; background:#0d6b61; color:#fff; font: 12px system-ui, sans-serif; padding: 2px 8px; border-radius: 4px; pointer-events:none; }
    .cp-done { outline: 2px dashed #5f6a65 !important; }`;
  document.head.appendChild(style);
  const tip = document.createElement("div"); tip.className = "cp-tip"; tip.hidden = true; document.body.appendChild(tip);
  const label = el => ({ IMG: "그림", VIDEO: "영상", AUDIO: "음성", TABLE: "표", FIGURE: "그림", PRE: "코드", BLOCKQUOTE: "인용", LI: "항목" }[el.tagName] || (/^H\d$/.test(el.tagName) ? "제목" : "문단"));
  let cur = null;
  const target = e => e.target.closest ? e.target.closest(PICK) : null;
  document.addEventListener("mousemove", e => {
    const t = target(e);
    if (t !== cur) { cur?.classList.remove("cp-hover"); cur = t; cur?.classList.add("cp-hover"); }
    if (cur) { tip.hidden = false; tip.textContent = `${label(cur)} 추가 (클릭)`; tip.style.left = (e.clientX + 12) + "px"; tip.style.top = (e.clientY + 14) + "px"; } else tip.hidden = true;
  }, true);
  document.addEventListener("mouseleave", () => { cur?.classList.remove("cp-hover"); cur = null; tip.hidden = true; });

  const abs = u => { try { return new URL(u, document.baseURI).href; } catch { return u; } };
  async function toDataUri(img) {
    if (img.src.startsWith("data:")) return img.src;
    try { const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight;
      c.getContext("2d").drawImage(img, 0, 0); return c.toDataURL("image/png"); } catch { return null; }
  }
  const text = el => (el.innerText || el.textContent || "").replace(/\s+\n/g, "\n").trim();
  document.addEventListener("click", async e => {
    const t = target(e); if (!t) return;
    e.preventDefault(); e.stopPropagation();
    let msg = { kind: "cp-pick", tag: t.tagName.toLowerCase(), title: document.title };
    if (t.tagName === "IMG" || (t.tagName === "FIGURE" && t.querySelector("img"))) {
      const img = t.tagName === "IMG" ? t : t.querySelector("img");
      msg = { ...msg, tag: "img", src: abs(img.getAttribute("src") || ""), data: await toDataUri(img), alt: img.alt || "", caption: t.querySelector?.("figcaption")?.innerText || img.alt || "" };
    } else if (t.tagName === "VIDEO" || t.tagName === "AUDIO") {
      const srcEl = t.querySelector("source"); msg = { ...msg, src: abs(t.getAttribute("src") || srcEl?.getAttribute("src") || ""), caption: t.title || "" };
    } else if (t.tagName === "TABLE") {
      msg = { ...msg, rows: [...t.querySelectorAll("tr")].map(tr => [...tr.children].map(td => td.innerText.trim())), header: !!t.querySelector("th") };
    } else if (t.tagName === "LI") {
      msg = { ...msg, text: text(t) };
    } else {
      msg = { ...msg, text: text(t), level: /^H\d$/.test(t.tagName) ? +t.tagName[1] : null };
    }
    window.parent.postMessage(msg, "*");
    t.classList.add("cp-done");
  }, true);
  window.parent.postMessage({ kind: "cp-ready", title: document.title }, "*");
})();
