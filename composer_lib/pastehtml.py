"""Browser-pasteable HTML for the manual path (no Confluence API).

Images are embedded as data: URIs so that Ctrl+A / Ctrl+C in a browser, then Ctrl+V in the Confluence editor,
carries them along as attachments. Files that cannot be embedded (video, audio, zip) are listed by name so the
user can drag them in from the same export folder.
"""
from __future__ import annotations

import base64
import mimetypes
from html import escape
from pathlib import Path

from .storage import attachment_name

MAX_INLINE = 2 * 1024 * 1024
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

_INLINE_MD = (
    (r"`([^`]+)`", r"<code>\1</code>"),
    (r"\*\*(.+?)\*\*", r"<strong>\1</strong>"),
    (r"(?<![\w*])_(.+?)_(?![\w*])", r"<em>\1</em>"),
    (r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>'),
)


def inline_html(text: str) -> str:
    import re
    s = escape(text or "")
    for pat, rep in _INLINE_MD:
        s = re.sub(pat, rep, s)
    return s


def data_uri(path: Path) -> str | None:
    if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES or path.stat().st_size > MAX_INLINE:
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def paste_html(title: str, blocks: list[dict], weeks_dir: Path) -> tuple[str, list[str]]:
    """(html document, [file names that must be attached by hand])."""
    weeks_dir = Path(weeks_dir)
    body: list[str] = []
    manual: list[str] = []
    for b in blocks:
        t = b.get("type")
        if t == "heading":
            lvl = 3 if int(b.get("level") or 2) >= 3 else 2
            body.append(f"<h{lvl}>{inline_html(b.get('text', ''))}</h{lvl}>")
        elif t == "paragraph":
            body.append(f"<p>{inline_html(b.get('text', ''))}</p>")
        elif t == "bullets":
            items = b.get("items") or []
            body.append("<ul>" + "".join(f"<li>{inline_html(i)}</li>" for i in items) + "</ul>")
        elif t == "image":
            uri = data_uri(weeks_dir / b.get("src", ""))
            name = attachment_name(b.get("src", ""))
            if uri:
                body.append(f'<p><img src="{uri}" alt="{escape(b.get("caption") or name)}" style="max-width:100%"></p>')
            else:
                manual.append(name)
                body.append(f'<p>[그림 첨부: {escape(name)}]</p>')
            if b.get("caption"):
                body.append(f"<p><em>{escape(b['caption'])}</em></p>")
        elif t == "file":
            name = attachment_name(b.get("src", ""))
            manual.append(name)
            body.append(f'<p>[첨부 파일: {escape(name)}] {escape(b.get("caption") or "")}</p>')
        elif t == "divider":
            body.append("<hr>")
        elif t == "callout":
            body.append(f'<blockquote style="border-left:4px solid #0d6b61;padding:6px 10px;background:#eef6f4">{inline_html(b.get("text", ""))}</blockquote>')
    doc = ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
           f"<title>{escape(title)}</title>"
           "<style>body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;max-width:800px;margin:24px auto;padding:0 16px;line-height:1.6}"
           ".how{background:#fff7e6;border:1px solid #f0c36d;padding:10px 14px;border-radius:6px;font-size:13px}</style></head><body>"
           "<div class=\"how\" contenteditable=\"false\"><b>붙여넣는 법</b>: 아래 구분선 밑을 드래그하거나 Ctrl+A로 모두 선택 → Ctrl+C → Confluence 편집기에 Ctrl+V. "
           "그림은 함께 들어갑니다. [첨부 파일: …] 표시가 있는 영상·파일은 같은 폴더에서 편집기로 끌어 넣으세요. 이 안내 상자는 복사되어도 지우면 됩니다.</div><hr>"
           f"<h1>{escape(title)}</h1>" + "\n".join(body) + "</body></html>")
    return doc, sorted(set(manual))


def readme_text(title: str, manual: list[str]) -> str:
    lines = [f"[{title}] Confluence에 올리는 법 (API 없이)", "",
             "1. 이 폴더의 paste.html 을 브라우저로 엽니다 (더블클릭).",
             "2. Ctrl+A 로 모두 선택하고 Ctrl+C 로 복사합니다.",
             "3. Confluence에서 새 페이지를 만들고 편집기에 Ctrl+V 로 붙여넣습니다. 글 서식과 그림이 함께 들어갑니다.",
             "4. 맨 위의 노란 안내 상자가 같이 붙었으면 지웁니다.", ""]
    if manual:
        lines += ["5. 아래 파일은 붙여넣기로 들어가지 않으니, 이 폴더에서 편집기로 끌어 넣거나 '첨부'로 올리세요:"] + [f"   - {m}" for m in manual] + [""]
    lines += ["body.html 은 Confluence 저장 형식(ac:image 등) 원문으로, API가 열리면 그대로 쓸 수 있습니다."]
    return "\n".join(lines) + "\n"
