"""Draft blocks → Confluence storage format (XHTML with ac:/ri: elements).

Only a small inline markdown subset is supported on purpose: bold, italic, code, links. Everything is
XML-escaped first, so page text can never break the markup.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

NS_WRAP = ('<root xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/resource/identifier">', "</root>")

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])_(.+?)_(?![\w*])")
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def inline_md(text: str) -> str:
    s = escape(text or "")
    s = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", s)
    s = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", s)
    s = _ITALIC.sub(lambda m: f"<em>{m.group(1)}</em>", s)
    s = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', s)
    return s


def attachment_name(src: str) -> str:
    """Flat, unique, ASCII-safe attachment file name derived from the package-relative path."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", (src or "").replace("\\", "/").replace("/", "_"))
    return name.strip("_") or "file"


def render_block(b: dict) -> str:
    t = b.get("type")
    if t == "heading":
        lvl = 3 if int(b.get("level") or 2) >= 3 else 2
        return f"<h{lvl}>{inline_md(b.get('text', ''))}</h{lvl}>"
    if t == "paragraph":
        return f"<p>{inline_md(b.get('text', ''))}</p>"
    if t == "bullets":
        items = b.get("items") or ([b["text"]] if b.get("text") else [])
        return "<ul>" + "".join(f"<li>{inline_md(i)}</li>" for i in items) + "</ul>"
    if t == "image":
        out = f'<ac:image ac:width="800"><ri:attachment ri:filename={quoteattr(attachment_name(b.get("src", "")))}/></ac:image>'
        if b.get("caption"):
            out += f"<p><em>{escape(b['caption'])}</em></p>"
        return out
    if t == "file":
        label = (b.get("caption") or attachment_name(b.get("src", ""))).replace("]]>", "]]&gt;")
        return (f'<p><ac:link><ri:attachment ri:filename={quoteattr(attachment_name(b.get("src", "")))}/>'
                f"<ac:plain-text-link-body><![CDATA[{label}]]></ac:plain-text-link-body></ac:link></p>")
    if t == "divider":
        return "<hr/>"
    if t == "table":
        rows = [r for r in (b.get("rows") or []) if isinstance(r, list)]
        if not rows:
            return ""
        out = ["<table><tbody>"]
        for i, row in enumerate(rows):
            cell = "th" if (i == 0 and b.get("header", True)) else "td"
            out.append("<tr>" + "".join(f"<{cell}>{inline_md(str(c))}</{cell}>" for c in row) + "</tr>")
        out.append("</tbody></table>")
        return "".join(out)
    if t == "callout":
        return f'<ac:structured-macro ac:name="info"><ac:rich-text-body><p>{inline_md(b.get("text", ""))}</p></ac:rich-text-body></ac:structured-macro>'
    return ""


def render(blocks: list[dict]) -> str:
    return "\n".join(x for x in (render_block(b) for b in blocks) if x)


def validate(xhtml: str) -> str | None:
    """None when the markup parses as XML (with the Confluence namespaces declared), else the parser's message."""
    try:
        ET.fromstring(NS_WRAP[0] + xhtml + NS_WRAP[1])
        return None
    except ET.ParseError as e:
        return str(e)


def attachments_for(blocks: list[dict]) -> dict[str, str]:
    """{attachment filename: package-relative src} for every image/file block, in order, de-duplicated."""
    out: dict[str, str] = {}
    for b in blocks:
        if b.get("type") in ("image", "file") and b.get("src"):
            out.setdefault(attachment_name(b["src"]), b["src"])
    return out
