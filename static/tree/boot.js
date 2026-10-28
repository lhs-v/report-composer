/* Boot: decides which editor is open. app.js (the block editor) calls Composer.route(draft) after every openDraft. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  // copies of the helpers in app.js: that file is a closed IIFE, so the tree editor gets its own
  const api = async (path, opts = {}) => {
    const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      body: opts.body !== undefined && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body });
    const data = r.headers.get("Content-Type")?.includes("json") ? await r.json() : await r.text();
    if (!r.ok) throw Object.assign(new Error(data?.error || `HTTP ${r.status}`), { status: r.status, data });
    return data;
  };
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const toast = (html, ms = 4000) => { const t = $("#toast"); t.innerHTML = html; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => t.hidden = true, ms); };

  // tree drafts open the tree editor; block drafts keep the old three-column editor
  function route(draft) {
    const isTree = draft?.kind === "tree";
    $("main.cols").hidden = isTree;
    $("#tree").hidden = !isTree;
    for (const id of ["dupDraft", "undoBtn", "redoBtn", "polishBtn"]) { const b = $("#" + id); if (b) b.disabled = isTree; }
    if (!isTree) { window.Aids?.open?.(null); return; }   // no tree draft: its jobs are cancelled and their timers stop
    $("#treeTitle").textContent = draft.title || "초안 트리";
    $("#treeWeek").textContent = draft.week || "";
    $("#treeWeek").hidden = !draft.week;
    window.Aids?.open?.(draft);                      // before the tree: another draft's jobs go, then the provider state is re-read
    window.Tree?.open?.(draft);
  }

  // narrow windows: the three columns become tabs
  $$("#tree .t-tabs button").forEach(b => b.addEventListener("click", () => { $("#tree").dataset.pane = b.dataset.pane; }));

  // "＋ 이번 주 초안": a tree draft for the newest week, then reload; app.js opens the newest draft (the list is newest-first)
  $("#newTree").addEventListener("click", async () => {
    const btn = $("#newTree");
    btn.disabled = true;
    try {
      const st = await api("/api/state");
      const week = st.weeks?.[0]?.week;
      if (!week) { toast("아직 받은 주차가 없습니다. 패키지가 도착하면 다시 눌러 주세요."); return; }
      await api("/api/drafts/tree", { method: "POST", body: { title: `주간 보고 ${week}`, week } });
      location.reload();
    } catch (e) {
      toast("트리 초안을 만들지 못했습니다: " + esc(e.message), 8000);
    } finally { btn.disabled = false; }
  });

  window.Composer = { api, esc, toast, route };

  // app.js may have opened a draft before this file ran (its first route() call found no Composer): route it once now
  const openId = $("#draftSelect").value;
  if (openId && !window.Tree?.state?.draft) api(`/api/drafts/${openId}`).then(route).catch(() => {});
})();
