"""単体で読める調査 HTML の形式を検査する。未信頼 HTML の無害化は行わない。"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import date
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

MAX_BYTES = 5 * 1024 * 1024
TEMPLATE = Path(__file__).resolve().parents[1] / "references/research-report.html.tpl"
SECTIONS = {"question", "summary", "conditions", "results", "reproduce", "limitations"}
TAGS = {
    "html", "head", "meta", "title", "style", "body", "main", "header", "section",
    "article", "footer", "nav", "div", "span", "h1", "h2", "h3", "h4", "p", "time",
    "a", "ul", "ol", "li", "dl", "dt", "dd", "figure", "img", "figcaption", "pre",
    "code", "blockquote", "table", "caption", "thead", "tbody", "tr", "th", "td",
    "strong", "em", "b", "i", "details", "summary", "br", "hr",
}
VOID = {"meta", "img", "br", "hr"}
ATTRS = {
    "html": {"lang"},
    "meta": {"charset"},
    "time": {"datetime"},
    "a": {"href"},
    "img": {"src", "alt"},
}
ID = re.compile(r"[A-Za-z][A-Za-z0-9._:-]*\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z", re.ASCII)
TITLE_START = re.compile(r"<title(?=[ \t\r\n\f/>])", re.IGNORECASE | re.ASCII)
TITLE_OPEN = re.compile(r"<title[ \t\r\n\f]*>", re.IGNORECASE | re.ASCII)
TITLE_CLOSE = re.compile(r"</title[ \t\r\n\f]*>", re.IGNORECASE | re.ASCII)


def is_report(root: Path, path: Path) -> bool:
    return path.suffix == ".html" and path.is_relative_to(root / "docs/research")


@cache
def template_css() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    return text.split("<style>", 1)[1].split("</style>", 1)[0].strip()


def allowed_image(src: str) -> bool:
    header, _, payload = src.partition(",")
    formats = {"data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64"}
    if header not in formats or not payload:
        return False
    try:
        image = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return False
    if header.startswith("data:image/png"):
        return image.startswith(b"\x89PNG\r\n\x1a\n")
    if header.startswith("data:image/jpeg"):
        return image.startswith(b"\xff\xd8\xff")
    return image.startswith(b"RIFF") and image[8:12] == b"WEBP"


class Report(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.sections: set[str] = set()
        self.links: list[str] = []
        self.problems: list[str] = []
        self.observed_date = False
        self.tags: set[str] = set()
        self.css: list[str] | None = None
        self.styles = 0

    def issue(self, message: str) -> None:
        self.problems.append(f"{self.getpos()[0]} 行: {message}")

    def handle_decl(self, decl: str) -> None:
        if decl.lower() != "doctype html":
            self.issue("DOCTYPE は html のみ使用可")

    def handle_pi(self, data: str) -> None:
        self.issue("処理命令は使用不可")

    def unknown_decl(self, data: str) -> None:
        self.issue("特殊な宣言は使用不可")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in TAGS:
            self.issue(f"要素 <{tag}> は使用不可")
            return
        self.tags.add(tag)
        fields = dict(attrs)
        if len(attrs) != len(fields):
            self.issue(f"要素 <{tag}> の属性が重複")
        for name in sorted(fields.keys() - ATTRS.get(tag, set()) - {"id"}):
            self.issue(f"要素 <{tag}> の属性 {name} は使用不可")
        if "id" in fields:
            identifier = fields["id"] or ""
            if not ID.fullmatch(identifier) or identifier in self.ids:
                self.issue("空・不正・重複した id")
            self.ids.add(identifier)
            if tag == "section":
                self.sections.add(identifier)
        if tag == "meta" and (fields.get("charset") or "").lower() != "utf-8":
            self.issue("meta は charset=utf-8 のみ使用可")
        elif tag == "style":
            self.styles += 1
            self.css = []
        elif tag == "time":
            value = fields.get("datetime") or ""
            try:
                if not DATE.fullmatch(value):
                    raise ValueError
                date.fromisoformat(value)
            except ValueError:
                self.issue("time の datetime は実在する YYYY-MM-DD を指定する")
            else:
                self.observed_date = True
        elif tag == "img":
            if not allowed_image(fields.get("src") or ""):
                self.issue("画像は PNG・JPEG・WebP の base64 data URI で埋め込む")
            if not (fields.get("alt") or "").strip():
                self.issue("画像には代替テキストを付ける")
        elif tag == "a":
            self.add_link(fields.get("href") or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in VOID:
            self.issue(f"要素 <{tag}/> は自己終了不可")
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.css is not None:
            self.css.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag not in TAGS or tag in VOID:
            self.issue(f"終了タグ </{tag}> は使用不可")
        if tag == "style" and self.css is not None:
            if "".join(self.css).strip() != template_css():
                self.issue("style には同梱テンプレートの CSS のみ使用可")
            self.css = None

    def add_link(self, href: str) -> None:
        # 引用先への移動だけを許可する。ファイルや URL はここでは開かない。
        if not href or any(ch.isspace() or ord(ch) < 32 or ch == "\\" for ch in href):
            self.issue("href は空白・制御文字を含まないリンクを指定する")
            return
        try:
            target = urlsplit(href)
        except ValueError:
            self.issue("href の URL が不正")
            return
        if target.scheme in {"http", "https"} and target.netloc:
            return
        if target.scheme or target.netloc or href.startswith("/") or not (target.path or target.fragment):
            self.issue("href は http(s) URL・相対パス・文書内アンカーのみ使用可")
            return
        self.links.append(href)

    def finish(self) -> None:
        self.close()
        if self.css is not None or self.styles > 1:
            self.issue("style は閉じた要素を最大1つだけ使用可")
        for tag in sorted({"html", "meta", "title", "h1"} - self.tags):
            self.issue(f"<{tag}> が無い")
        if not self.observed_date:
            self.issue("観測日を指定する time が無い")
        for section in sorted(SECTIONS - self.sections):
            self.issue(f"必須の section #{section} が無い")


def check_title_markup(text: str) -> None:
    # title 内のタグを HTMLParser が報告するかどうかは Python の版で異なる。
    starts = TITLE_START.finditer(text)
    start = next(starts, None)
    if start is None:
        return  # 欠落は通常の要素検査で報告する。
    if next(starts, None) is not None:
        raise ValueError("<title> は1つだけ使用可")
    opening = TITLE_OPEN.match(text, start.start())
    if opening is None:
        raise ValueError("<title> の開始タグに属性は使用不可")
    closing = TITLE_CLOSE.search(text, opening.end())
    if closing is None:
        raise ValueError("<title> の終了タグが無い")
    if text.find("<", opening.end(), closing.start()) != -1:
        raise ValueError("<title> には文字列だけを入れる")


def read_report(path: Path) -> Report:
    """過大なファイルを全文読まずに拒否する。"""
    with path.open("rb") as handle:
        buf = handle.read(MAX_BYTES + 1)
    if len(buf) > MAX_BYTES:
        raise ValueError("上限の 5 MiB を超えている")
    text = buf.decode("utf-8")
    # ブラウザと HTMLParser で壊れたコメントの終端が異なる。解析前に禁止する。
    if "<!--" in text:
        raise ValueError("HTML コメントは使用不可")
    check_title_markup(text)
    report = Report()
    report.feed(text)
    report.finish()
    return report
