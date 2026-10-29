/* Inspector: the right column. Top: what the selected row is and the few things you set on it (state, file to show, 글로 바꾸기,
   다시 쓰기). Below: the drawer (근거 · 다른 주 · 집은 그림), unchanged. Every edit goes through Keys/Tree.
   Also owns the two pane toggles (the outline and this column): the choice is remembered once the writer touches a toggle. */
window.Inspector = (() => {
  // boot.js (which defines Composer) and tree.js load after this file: look everything up at call time
  const esc = s => window.Composer.esc(s);
  const tree = () => document.getElementById("tree");
  const root = () => document.getElementById("inspector");
  const props = () => root().querySelector(".i-props");
  const I = () => window.NodeInfo;
  const node = id => window.Tree?.nodes?.()[id];
  const S = { id: null, kind: null, els: {} };
  const WIDE = "(min-width: 1400px)", NARROW = "(max-width: 1007px)";

  // ---- pane state: stored once the writer touched a toggle; otherwise the width decides ----
  const stored = k => { try { return localStorage.getItem("cp.pane." + k); } catch { return null; } };
  const store = (k, v) => { try { localStorage.setItem("cp.pane." + k, v); } catch { /* storage unavailable: the choice lasts until reload */ } };
  function applyPanes() {
    const t = tree();
    t.dataset.outline = stored("outline") || "on";
    t.dataset.insp = stored("insp") || (matchMedia(WIDE).matches ? "on" : "off");
    for (const b of document.querySelectorAll("[data-toggle-pane]")) b.setAttribute("aria-pressed", String(t.dataset[b.dataset.togglePane] === "on"));
  }
  const isOpen = () => tree().dataset.insp === "on";
  function toggle(open = !isOpen()) {
    store("insp", open ? "on" : "off"); applyPanes();
    if (open && matchMedia(NARROW).matches) tree().dataset.pane = "drawer";
  }
  function setOutline(open = tree().dataset.outline !== "on") { store("outline", open ? "on" : "off"); applyPanes(); }
  matchMedia(WIDE).addEventListener("change", () => { if (!stored("insp")) applyPanes(); });

  // ---- the files a record can show (a radio per file; files that stayed at home are listed but cannot be picked) ----
  function optionsHTML(n, name) {
    const opts = I().options(n), radio = o => `<label class="n-opt${o.home ? " home" : ""}"><input type="radio" name="${esc(name)}" value="${esc(o.v)}"${o.home ? " disabled" : ""}`
      + `${(n.show || "representative") === o.v ? " checked" : ""}><span class="n-optl">${esc(o.label)}</span>${o.sub ? `<small class="n-optsub">${esc(o.sub)}</small>` : ""}${o.home ? "<small class=\"n-optsub\">집에 있음</small>" : ""}</label>`;
    const here = opts.filter(o => !o.home), home = opts.filter(o => o.home);
    return (here.map(radio).join("") || '<p class="n-none">패키지에 담겨 온 파일이 없어요.</p>')
      + (home.length ? `<details class="n-homefiles"><summary>집에 있는 파일 ${home.length}개 (여기서는 고를 수 없어요)</summary>${home.map(radio).join("")}</details>` : "");
  }

  // ---- props ----
  function build(n) {
    const record = n.kind === "record", listed = n.kind === "flow" || n.kind === "ledger", aid = I().AID[n.kind];
    props().innerHTML = `<div class="i-kind"><span class="chip">${esc(I().KIND_LABEL[n.kind] || n.kind)}</span><span class="i-flags"></span></div>`
      + `<button type="button" class="i-src" title="이 줄의 근거를 아래 참고에서 봅니다"></button>`
      + `<div class="i-states"><button type="button" class="i-on"></button><button type="button" class="i-fold"></button><button type="button" class="i-page"></button></div>`
      + (record ? `<fieldset class="n-show"><legend>보여 줄 것</legend><div class="n-opts"></div></fieldset>` : "")
      + (listed ? `<button type="button" class="i-totext">글로 바꾸기</button>` : "")
      + (aid ? `<div class="i-aid"><button type="button" class="n-aid">${aid[1]}</button><span class="i-aidnote small muted"></span></div>` : "");
    const q = s => props().querySelector(s);
    S.els = { flags: q(".i-flags"), src: q(".i-src"), on: q(".i-on"), fold: q(".i-fold"), page: q(".i-page"), opts: q(".n-opts"), totext: q(".i-totext"), aid: q(".n-aid"), aidnote: q(".i-aidnote") };
    S.kind = n.kind;
    const id = n.id, e = S.els;
    e.src.addEventListener("click", () => {
      window.Drawer?.show?.(id, "evidence");
      if (matchMedia(NARROW).matches) tree().dataset.pane = "drawer";
      else root().querySelector(".t-drawer")?.scrollIntoView?.({ block: "start" });
    });
    e.on.addEventListener("click", () => window.Tree.toggle(id));
    e.fold.addEventListener("click", () => window.Tree.fold(id));
    e.page.addEventListener("click", () => window.Keys.togglePage(id));
    e.opts?.addEventListener("change", ev => {
      const r = ev.target.closest?.("input[type=radio]"), m = node(id);
      if (r && m && r.value !== (m.show || "representative")) window.Keys.op({ type: "text", id, field: "show", from: m.show || "representative", to: r.value });
    });
    e.totext?.addEventListener("click", () => {
      const m = node(id); if (!m?.items?.length) return;
      const lines = m.items.map(i => m.kind === "flow" ? `- ${String(i.when || "").slice(0, 10)} · ${i.text || ""}` : `- ${I().LEDGER_LABEL[i.kind] || i.kind}: ${i.text || ""}`);
      const nid = window.Keys.newText(id);                            // a text node right after this one (and selected)
      if (nid) window.Keys.typing(nid, "text", lines.join("\n"));
    });
    e.aid?.addEventListener("click", () => window.Aids?.request(I().AID[n.kind][0], id));
  }
  function sync(n) {
    const e = S.els, info = I();
    e.flags.textContent = info.flags(n); e.src.textContent = info.sourceLine(n);
    e.on.textContent = n.on ? "끄기" : "켜기"; e.on.setAttribute("aria-pressed", String(!!n.on));
    e.fold.hidden = !n.children?.length; e.fold.textContent = n.folded ? "펴기" : "접기"; e.fold.setAttribute("aria-pressed", String(!!n.folded));
    e.page.hidden = !["project", "claim"].includes(n.kind); e.page.textContent = "별도 페이지"; e.page.setAttribute("aria-pressed", String(!!n.page));
    if (e.opts) {
      const sig = JSON.stringify([info.options(n).map(o => [o.v, !!o.home])]);
      if (e.opts.dataset.sig !== sig && !e.opts.contains(document.activeElement)) { e.opts.innerHTML = optionsHTML(n, "show-" + n.id); e.opts.dataset.sig = sig; }
      const want = n.show || "representative";
      e.opts.querySelectorAll("input[type=radio]").forEach(r => { r.checked = r.value === want; });
    }
    if (e.totext) e.totext.disabled = !(n.items || []).length;
    const aids = window.Aids, ready = !!aids?.state.ready, busy = !!aids?.busy(n.id);
    if (e.aid) {
      e.aid.disabled = !ready || busy;
      e.aid.title = !ready ? aids?.TIP || "" : busy ? "다시 쓰는 중입니다" : "";
      e.aidnote.textContent = !ready ? (aids?.TIP || "") : busy ? "다시 쓰는 중…" : "";
    }
  }
  function show(id) {
    const n = id && node(id);
    if (!n) { S.id = null; S.kind = null; props().replaceChildren(); return; }
    if (S.id !== id || S.kind !== n.kind) { S.id = id; build(n); }
    sync(n);
  }
  function open() { applyPanes(); S.id = null; S.kind = null; props().replaceChildren(); }

  return { open, show, toggle, isOpen, setOutline, applyPanes };
})();
