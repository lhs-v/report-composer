/* NodeInfo: pure, DOM-free facts about one node that both the document and the inspector need. Looked up at call time by the
   files that load after it. Nothing here mutates a node. */
window.NodeInfo = (() => {
  const IMG = /\.(png|jpe?g|gif|webp|svg|avif)$/i, VID = /\.(mp4|webm)$/i;
  const BODIED = ["claim", "text", "summary", "project"];      // kinds that show a body
  const SPLITTABLE = ["claim", "text"];
  // which writing aid a kind has (aids.js asks the server for it): the body kinds rewrite their text, the summary its lines, a record its captions
  const AID = { claim: ["node", "다시 쓰기"], project: ["node", "다시 쓰기"], text: ["node", "다시 쓰기"], summary: ["summary", "요약 다시 쓰기"], record: ["caption", "설명 다시 쓰기"] };
  const KIND_LABEL = { summary: "요약", project: "프로젝트", claim: "주장", record: "기록", flow: "흐름", ledger: "장부", text: "내 글" };
  const LEDGER_LABEL = { decision: "결정", resolved: "닫힘", open: "열림", next: "다음" };
  const enc = href => String(href).split("/").map(encodeURIComponent).join("/");
  const node = id => window.Tree?.nodes?.()[id];
  const firstSentence = text => String(text || "").trim().split(/(?<=[.!?。])\s/)[0] || "";

  function sourceLine(n) {
    const s = n.src || {};
    if ((n.marks || []).includes("picked")) return "집은 그림 · 근거 기록 없음";
    if (!s.project && !s.record && !s.chapter) return "내가 쓴 글 · 근거 없음";
    let chapter = "";
    if (n.kind === "record" || n.kind === "flow") {
      for (const [m, , p] of window.Tree.walk()) if (m.id === n.id && p) { chapter = node(p)?.title || ""; break; }
    } else if (n.kind === "claim" || n.kind === "ledger") chapter = KIND_LABEL[n.kind];
    return [s.project, chapter && (chapter.length > 28 ? chapter.slice(0, 27) + "…" : chapter), s.record].filter(Boolean).join(" · ");
  }
  function flags(n) {
    return [n.on ? "켜짐" : "꺼짐", n.children?.length ? (n.folded ? "접힘" : "펼침") : "", n.page ? "별도 페이지" : ""].filter(Boolean).join(" · ");
  }
  function mediaFor(n) {
    const show = n.show || "representative";
    let href = show === "representative" ? (n.representative || n.href) : show === "core" ? n.href : (n.files || []).find(f => f.rel === show)?.href;
    if (!href) return null;
    return { href, kind: VID.test(href) ? "video" : IMG.test(href) ? "image" : "link" };
  }
  function options(n) {
    const out = [];
    if (n.representative) out.push({ v: "representative", label: "대표 그림", sub: n.representative.split("/").pop() });
    if (n.href) out.push({ v: "core", label: "핵심 파일", sub: n.href.split("/").pop() });
    for (const f of n.files || []) {
      if (f.home || !f.href) { if (f.home) out.push({ v: f.rel, label: f.rel, home: true }); continue; }
      if (f.href === n.href || f.href === n.representative) continue;   // already offered above
      out.push({ v: f.rel, label: f.rel });
    }
    return out;
  }

  return { IMG, VID, BODIED, SPLITTABLE, AID, KIND_LABEL, LEDGER_LABEL, enc, mediaFor, options, sourceLine, flags, firstSentence };
})();
