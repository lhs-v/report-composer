/* Aids: the three writing aids (rewrite a node, rewrite the week summary, rewrite a record's captions) and the dialog that picks the
   provider behind them. A request becomes a server job; this file polls it once a second, shows a thin progress line with a cancel
   under the node in the document, and when the answer is in, a proposal panel (now | proposed). Nothing changes until [적용]; applying is one
   history entry (Keys.applyProposal), so one Ctrl+Z gives the text and the stale flag back together.
   Jobs are kept per node id (Aids.state.jobs): leaving a node does not stop its job, and coming back shows the same state. */
window.Aids = (() => {
  // boot.js (which defines Composer) loads after this file: look the helpers up at call time
  const api = (...a) => window.Composer.api(...a), esc = s => window.Composer.esc(s), toast = (...a) => window.Composer.toast(...a);
  const $ = id => document.getElementById(id);
  const TIP = "LLM 공급자가 설정되지 않았습니다 · ⚙ 설정";
  const FIELD = { node: "text", summary: "text", caption: "caption" };     // which field of the node a kind rewrites
  const POLL_MS = 1000, MAX_MS = 5 * 60 * 1000, MAX_MISSES = 5;
  const S = { ready: false, providers: {}, llm: null, available: {}, jobs: {}, draftId: null };
  const timers = new Map();                                                // node id -> polling interval
  const node = id => window.Tree?.nodes?.()[id];
  const busy = id => { const j = S.jobs[id]; return !!j && (j.status === "queued" || j.status === "running"); };
  const style = () => { try { const v = localStorage.getItem("cp.polish.style"); return ["brief", "polite", "plain"].includes(v) ? v : "brief"; } catch { return "brief"; } };
  const secs = ms => (ms / 1000).toFixed(1) + "초";

  // ---- what the server has configured ----
  async function refresh() {
    try {
      const r = await api("/api/llm/providers");
      S.providers = r.providers || {}; S.llm = r.llm || null; S.available = r.available || {}; S.ready = !!r.ready;
    } catch { S.ready = false; }
    const b = $("llmBtn");
    if (b) b.title = S.ready ? `글쓰기 보조: ${S.llm?.provider || ""}${S.llm?.model ? ":" + S.llm.model : ""} (눌러서 바꿉니다)` : TIP;
    const sel = window.Tree?.state?.sel;
    if (window.Tree?.state?.draft) { window.Doc?.update?.(); if (sel) window.Inspector?.show?.(sel); }     // enable / disable the buttons on screen
    return S.ready;
  }
  // a tree draft opened: another draft's jobs are forgotten, the same draft's keep running
  function open(draft) {
    if ((draft?.id || null) !== S.draftId) {
      for (const [id, j] of Object.entries(S.jobs)) {
        stop(id);
        if (j.id && (j.status === "queued" || j.status === "running")) api(`/api/llm/jobs/${j.id}/cancel`, { method: "POST", body: {} }).catch(() => {});
      }
      S.jobs = {}; S.draftId = draft?.id || null;       // a job still on its way to the server cancels itself when it finds its entry gone
    }
    refresh();
  }

  // ---- jobs ----
  function stop(nodeId) { clearInterval(timers.get(nodeId)); timers.delete(nodeId); }
  function boxFor(nodeId) { return document.querySelector(`#docPane .n-aidbox[data-for="${CSS.escape(nodeId)}"]`); }
  // full: the buttons around the box change too (a job started or ended); otherwise only the seconds tick.
  // Not gated on the selection: a job can finish on a node that is not selected, and its article is on screen.
  function paint(nodeId, full) {
    if (full) { window.Doc?.refresh?.(nodeId); if (window.Tree?.state?.sel === nodeId) window.Inspector?.show?.(nodeId); }   // the inspector shows the selected node only
    else { const box = boxFor(nodeId); if (box) render(nodeId, box); }
  }
  function fail(job, why) {
    if (S.jobs[job.nodeId] !== job) return;
    stop(job.nodeId); job.status = "failed"; job.error = why; paint(job.nodeId, true);
  }
  function settle(job, rec) {
    Object.assign(job, { id: rec.id, status: rec.status, cached: !!rec.cached, result: rec.result || null, error: rec.error || null });
    if (job.status === "queued" || job.status === "running") return false;
    stop(job.nodeId);
    if (job.status === "cancelled") delete S.jobs[job.nodeId];               // cancelled somewhere else: nothing to show
    else if (job.status === "failed" && !job.error) job.error = "다시 쓰지 못했습니다";
    else if (job.status === "done" && !job.result) { job.status = "failed"; job.error = "답이 비어 있습니다"; }
    paint(job.nodeId, true);
    return true;
  }
  function poll(job) {
    stop(job.nodeId);
    timers.set(job.nodeId, setInterval(async () => {
      if (S.jobs[job.nodeId] !== job) { stop(job.nodeId); return; }
      if (Date.now() - job.t0 > MAX_MS) {
        api(`/api/llm/jobs/${job.id}/cancel`, { method: "POST", body: {} }).catch(() => {});
        fail(job, "시간이 너무 걸려 멈췄습니다"); return;
      }
      if (job.polling) return;                                               // the last answer has not come back yet
      job.polling = true;
      try {
        const rec = await api(`/api/llm/jobs/${job.id}`);
        if (S.jobs[job.nodeId] !== job) return;
        job.misses = 0;
        const was = job.status;
        if (!settle(job, rec)) paint(job.nodeId, was !== job.status);
      } catch (e) {
        if (S.jobs[job.nodeId] === job && ++job.misses >= MAX_MISSES) fail(job, "작업 상태를 읽지 못했습니다: " + e.message);
      } finally { job.polling = false; }
    }, POLL_MS));
  }

  async function request(kind, nodeId) {
    const draft = window.Tree?.state?.draft;
    if (!draft || !FIELD[kind] || !nodeId || !node(nodeId)) return;
    if (!S.ready) { toast(esc(TIP)); return; }
    if (busy(nodeId)) return;
    stop(nodeId);
    const job = S.jobs[nodeId] = { id: null, kind, nodeId, status: "queued", t0: Date.now(), cached: false, result: null, error: null, misses: 0 };
    paint(nodeId, true);
    try {
      await window.Tree.settle();                                            // the server builds the prompt from the stored draft: send what is pending first
      if (S.jobs[nodeId] !== job) return;                                    // cancelled before it left
      const r = await api("/api/llm/jobs", { method: "POST", body: { kind, draft_id: draft.id, node_id: nodeId, style: style() } });
      if (S.jobs[nodeId] !== job) { api(`/api/llm/jobs/${r.job.id}/cancel`, { method: "POST", body: {} }).catch(() => {}); return; }
      if (!settle(job, r.job)) poll(job);
    } catch (e) {
      if (S.jobs[nodeId] !== job) return;
      if (e.status === 409 && e.data?.code === "NO_PROVIDER") refresh();      // the setting was removed behind our back
      fail(job, e.message);
    }
  }

  function cancel(nodeId) {
    const j = S.jobs[nodeId]; if (!j) return;
    delete S.jobs[nodeId]; stop(nodeId);
    if (j.id) api(`/api/llm/jobs/${j.id}/cancel`, { method: "POST", body: {} }).catch(() => {});
    paint(nodeId, true);
  }
  function discard(nodeId) { delete S.jobs[nodeId]; stop(nodeId); paint(nodeId, true); }

  function apply(nodeId) {
    const j = S.jobs[nodeId], n = node(nodeId);
    if (!j || j.status !== "done" || !n) return;
    const v = j.result.value, caption = j.kind === "caption";
    const to = caption ? (Array.isArray(v) ? v : [String(v)]).slice(0, 2) : Array.isArray(v) ? v.join("\n") : String(v);
    delete S.jobs[nodeId]; stop(nodeId);
    if (!window.Keys.applyProposal(nodeId, FIELD[j.kind], to)) return;
    window.Motion.sweep(document.querySelector(`#docPane .doc-node[data-id="${CSS.escape(nodeId)}"] ${caption ? ".doc-caps" : ".n-body"}`));   // 착지
    if (caption) window.Doc?.remember?.(nodeId);                              // the memory keeps the caption the writer settled on
  }

  // ---- the box under the node in the document: progress line, proposal panel, or the reason it failed ----
  const cur = (j, n) => j.kind === "caption" ? (n.caption || []) : (n.text || "");
  const lines = v => (Array.isArray(v) ? v : String(v ?? "").split("\n")).filter(l => String(l).trim());
  function column(j, v) {
    if (j.kind === "node") return String(v).trim() ? `<div class="n-ptxt">${esc(v)}</div>` : '<div class="n-ptxt n-none">(비어 있음)</div>';
    const ls = lines(v);
    return ls.length ? `<div class="n-ptxt">${ls.map(l => `<p>${esc(l)}</p>`).join("")}</div>` : '<div class="n-ptxt n-none">(비어 있음)</div>';
  }
  function render(nodeId, host) {
    const j = S.jobs[nodeId], n = node(nodeId);
    if (!j || !n) { if (host.dataset.sig) { host.replaceChildren(); host.dataset.sig = ""; } return; }
    const now = cur(j, n);
    const sig = j.status === "done" ? `d|${j.id}|${JSON.stringify(now)}` : j.status === "failed" ? `f|${j.error}` : `p|${j.kind}`;
    if (host.dataset.sig !== sig) {
      host.dataset.sig = sig;
      if (j.status === "done") {
        const r = j.result, meta = [r.provider, secs(r.ms || 0), r.via === "fallback" ? "폴백" : "", j.cached ? "캐시" : ""].filter(Boolean).join(" · ");
        host.innerHTML = `<section class="n-proposal" aria-label="제안">`
          + `<header class="n-phead"><b>제안</b><span class="n-pmeta">${esc(meta)}</span></header>`
          + `<div class="n-pcols"><div class="n-pcol"><h4>지금</h4>${column(j, now)}</div><div class="n-pcol n-new"><h4>제안</h4>${column(j, r.value)}</div></div>`
          + `<div class="n-pbtns"><button type="button" class="n-papply accent">적용</button><button type="button" class="n-pdiscard">버리기</button></div></section>`;
        host.querySelector(".n-papply").addEventListener("click", () => apply(nodeId));
        host.querySelector(".n-pdiscard").addEventListener("click", () => discard(nodeId));
        if (!j.shown) { j.shown = true; window.Motion.once(host.firstElementChild, "enter", 200); }   // slides in once, not on every re-render
      } else if (j.status === "failed") {
        host.innerHTML = `<div class="n-aidfail" role="alert"><span class="n-ftext">${esc(j.error)}</span><button type="button" class="n-fclose">닫기</button></div>`;
        host.querySelector(".n-fclose").addEventListener("click", () => discard(nodeId));
      } else {
        host.innerHTML = `<div class="n-progress" role="status"><span class="n-pbar" aria-hidden="true"></span><span class="n-ptext">다시 쓰는 중<span class="n-psec" aria-hidden="true"></span></span>`
          + `<button type="button" class="n-pcancel" aria-label="취소" title="취소">×</button></div>`;
        host.querySelector(".n-pcancel").addEventListener("click", () => cancel(nodeId));
      }
    }
    const t = host.querySelector(".n-psec");                                  // the seconds tick silently: a screen reader hears the static text once
    if (t && (j.status === "queued" || j.status === "running")) {
      const text = ` · ${Math.floor((Date.now() - j.t0) / 1000)}초`;
      if (t.textContent !== text) t.textContent = text;
    }
  }

  // ---- the provider dialog ----
  const dlg = () => $("llmDlg");
  const opt = (value, text) => Object.assign(document.createElement("option"), { value, textContent: text });
  function hints(prefix) {                                                    // placeholders and the model list follow the chosen provider
    const spec = S.providers[$(prefix === "llm" ? "llmProvider" : "llmFbProvider").value] || {};
    const model = $(prefix === "llm" ? "llmModel" : "llmFbModel"), list = $(prefix === "llm" ? "llmModels" : "llmFbModels");
    model.placeholder = spec.default || "";
    list.replaceChildren(...(spec.models || []).map(m => opt(m, "")));
    if (prefix === "llm") $("llmCommand").placeholder = spec.command || "";
  }
  function fillDialog() {
    const llm = S.llm || {}, fb = llm.fallback || null;
    const names = Object.keys(S.providers);
    $("llmProvider").replaceChildren(opt("", "사용 안 함"), ...names.map(n => opt(n, "")));
    $("llmFbProvider").replaceChildren(opt("", "없음"), ...names.map(n => opt(n, "")));
    $("llmProvider").value = llm.provider || ""; $("llmCommand").value = llm.command || ""; $("llmModel").value = llm.model || "";
    $("llmFbProvider").value = fb?.provider || ""; $("llmFbModel").value = fb?.model || "";
    hints("llm"); hints("fb"); relabel();
    setResult("", "");
  }
  // a CLI is marked "설치 안 됨" only when it was not found under its own default name: a command typed or saved for it
  // (a full path, a wrapper) is not judged here, the test call is the check
  function relabel() {
    const typed = $("llmProvider").value, llm = S.llm || {};
    const override = n => (n === typed ? $("llmCommand").value.trim() : n === llm.provider ? llm.command : "") || (llm.fallback?.provider === n ? llm.fallback.command : "") || "";
    for (const sel of [$("llmProvider"), $("llmFbProvider")]) {
      for (const o of sel.options) if (o.value) o.textContent = S.providers[o.value].label + (S.available[o.value] || override(o.value) ? "" : " — 설치 안 됨");
    }
  }
  function setResult(text, cls) { const r = $("llmResult"); r.textContent = text; r.className = "small " + cls; }
  const form = () => {
    const fbp = $("llmFbProvider").value, keep = S.llm?.fallback?.provider === fbp ? S.llm.fallback.command || "" : "";   // the fallback's command is not in the form
    return { provider: $("llmProvider").value, command: $("llmCommand").value.trim(), model: $("llmModel").value.trim(),
             fallback: fbp ? { provider: fbp, command: keep, model: $("llmFbModel").value.trim() } : null };
  };
  async function testCall() {
    const f = form();
    if (!f.provider) { setResult("주 공급자를 먼저 고르세요", "error"); return; }
    const btn = $("llmTest"); btn.disabled = true; setResult("시험 호출 중… (보통 몇 초)", "muted");
    try {
      const r = await api("/api/llm/test", { method: "POST", body: { provider: f.provider, command: f.command, model: f.model } });
      if (r.ok) setResult(`OK · ${secs(r.ms || 0)} · ${f.provider}:${f.model || S.providers[f.provider]?.default || ""}`, "ok");   // which tool and model answered, not what it said
      else setResult(r.error || "실패했습니다", "error");
    } catch (e) { setResult(e.message, "error"); }
    finally { btn.disabled = false; }
  }
  async function save() {
    const btn = $("llmSave"); btn.disabled = true;
    try {
      await api("/api/llm/config", { method: "PUT", body: form() });
      toast("LLM 설정을 저장했습니다");
      dlg().close();
      await refresh();
    } catch (e) { setResult("저장하지 못했습니다: " + e.message, "error"); }
    finally { btn.disabled = false; }
  }
  async function openDialog() {
    await refresh();
    fillDialog();
    dlg().showModal();
  }

  function bind() {
    $("llmBtn")?.addEventListener("click", openDialog);
    $("llmClose")?.addEventListener("click", () => dlg().close());
    $("llmTest")?.addEventListener("click", testCall);
    $("llmSave")?.addEventListener("click", save);
    $("llmProvider")?.addEventListener("change", () => { $("llmCommand").value = ""; $("llmModel").value = ""; hints("llm"); relabel(); setResult("", ""); });
    $("llmCommand")?.addEventListener("input", relabel);
    $("llmFbProvider")?.addEventListener("change", () => { $("llmFbModel").value = ""; hints("fb"); });
    dlg()?.querySelector("form")?.addEventListener("submit", e => { e.preventDefault(); save(); });   // Enter in a field saves; it does not just close
  }
  bind();
  document.addEventListener("DOMContentLoaded", refresh);                      // boot.js is loaded by then

  return { refresh, open, request, cancel, render, busy, state: S, TIP };
})();
