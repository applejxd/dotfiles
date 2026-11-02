"""PR ビューア 段 1・2 の画面（apps/pr-viewer/web/）の試験。

1. 静的検査: 描画の安全規則（XSS を防ぐ規則）と配信の規則（CSP）、書き込みの規則（POST に X-PRV を付ける）に違反する記述が無いこと。
   検査関数そのものが違反を検出できることを、違反の断片で先に確かめる。
2. 描画の smoke: 契約どおりの JSON を返す小さな HTTP サーバ（POST を受けて状態が変わる）と web/ を配信し、ヘッドレス Chromium で
   一覧・概要・差分・コメント入力・レビュー送信を開く。敵対的な文字列が文字として表示され、実行されないことも確かめる。
   ブラウザ部分は `uv run --with playwright python <このファイル> --browser` を子プロセスで呼ぶ（無ければ skip）。
"""

from __future__ import annotations

import glob
import http.server
import json
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "pr-viewer" / "web"
FIX = pathlib.Path(__file__).resolve().parent / "pr_viewer_fixtures"
MAX_LINES = 800
SKIP_CODE = 77  # ブラウザが使えないときの終了コード
BUMPED_OID = "9" * 40  # PR が更新された後の source (架空の値)

# ---------------------------------------------------------------- 静的検査 ---

JS_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("innerHTML", re.compile(r"\binnerHTML\b")),
    ("outerHTML", re.compile(r"\bouterHTML\b")),
    ("insertAdjacentHTML", re.compile(r"\binsertAdjacentHTML\b")),
    ("document.write", re.compile(r"\bdocument\s*\.\s*write(ln)?\b")),
    ("eval", re.compile(r"(?<![\w.])eval\s*\(")),
    ("new Function", re.compile(r"\bnew\s+Function\b|(?<![\w.])Function\s*\(")),
    ("文字列の timer", re.compile(r"\bset(Timeout|Interval)\s*\(\s*[\"'`]")),
    ("on* プロパティ", re.compile(r"\.on[a-z]+\s*=(?!=)")),
    ("on* 属性の設定", re.compile(r"setAttribute\(\s*[\"']\s*on", re.I)),
    ("style 属性の設定", re.compile(r"setAttribute\(\s*[\"']\s*style", re.I)),
    ("srcdoc", re.compile(r"\bsrcdoc\b")),
    ("javascript: URL", re.compile(r"javascript\s*:", re.I)),
    ("外部 URL", re.compile(r"https?://", re.I)),
    (
        "外部通信の API",
        re.compile(r"\b(XMLHttpRequest|WebSocket|EventSource|sendBeacon|importScripts)\b"),
    ),
    ("動的 import", re.compile(r"\bimport\s*\(")),
]

HTML_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("inline script", re.compile(r"<script\b(?![^>]*\bsrc\s*=)", re.I)),
    ("inline style 要素", re.compile(r"<style\b", re.I)),
    ("イベント属性", re.compile(r"\son[a-z]+\s*=", re.I)),
    ("style 属性", re.compile(r"\sstyle\s*=", re.I)),
    ("javascript: URL", re.compile(r"javascript\s*:", re.I)),
    ("外部 URL", re.compile(r"https?://", re.I)),
    ("埋め込み要素", re.compile(r"<(iframe|object|embed|form)\b", re.I)),
]

CSS_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("外部 URL", re.compile(r"https?://", re.I)),
    ("@import", re.compile(r"@import\b", re.I)),
    ("javascript: URL", re.compile(r"javascript\s*:", re.I)),
]

HOVER_MEDIA = re.compile(r"@media[^{]*\(\s*hover\s*:\s*hover\s*\)", re.I)
POST_RE = re.compile(r"method\s*:\s*[\"'](?!GET[\"'])[A-Za-z]+[\"']")
FETCH_RE = re.compile(r"(?<![\w.])fetch\s*\(")


def write_violations(name: str, text: str) -> list[str]:
    """書き込みの規則: fetch は api.js だけ。GET 以外のリクエストは X-PRV と JSON の Content-Type を付ける。"""
    bad = []
    if name != "api.js" and FETCH_RE.search(text):
        bad.append("api.js 以外で fetch を呼んでいる")
    for m in POST_RE.finditer(text):
        window = text[max(0, m.start() - 300) : m.end() + 300]
        if not re.search(r"[\"']X-PRV[\"']\s*:\s*[\"']1[\"']", window):
            bad.append(
                f"X-PRV ヘッダーが無い書き込み（{text.count(chr(10), 0, m.start()) + 1} 行目）"
            )
        if not re.search(r"[\"']Content-Type[\"']\s*:\s*[\"']application/json", window):
            bad.append(
                f"Content-Type が無い書き込み（{text.count(chr(10), 0, m.start()) + 1} 行目）"
            )
    return bad


def scan(text: str, rules: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    """規則に当たった名前の一覧を返す（行番号つき）。"""
    found = []
    for name, pat in rules:
        for m in pat.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            found.append(f"{name}（{line} 行目）")
    return found


def hover_violations(css: str) -> list[str]:
    """`@media (hover: hover)` の外にある `:hover` を返す。"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    stack: list[str] = []
    start = 0
    bad = []
    for i, ch in enumerate(css):
        if ch == "{":
            prelude = css[start:i].strip()
            if ":hover" in prelude and not any(HOVER_MEDIA.search(p) for p in stack):
                bad.append(f":hover が hover 判定の外にある: {prelude[:60]}")
            stack.append(prelude)
            start = i + 1
        elif ch == "}":
            if stack:
                stack.pop()
            start = i + 1
        elif ch == ";":
            start = i + 1
    return bad


def web_files() -> list[pathlib.Path]:
    return sorted(p for p in WEB.iterdir() if p.is_file())


# --- 検査関数が違反を検出できること（断片の試験。実ファイルの検査より先に確かめる） ---

BAD_JS = [
    "el.innerHTML = x;",
    "el.outerHTML = x;",
    "el.insertAdjacentHTML('beforeend', x);",
    "document.write(x);",
    "eval(code);",
    "const f = new Function('return 1');",
    "setTimeout('alert(1)', 10);",
    "setInterval(`x()`, 10);",
    "btn.onclick = function () {};",
    "el.setAttribute('onerror', 'x()');",
    "el.setAttribute('style', 'color:red');",
    "ifr.srcdoc = x;",
    "a.href = 'javascript:alert(1)';",
    "fetch('https://example.com/a');",
    "new WebSocket(u);",
    "navigator.sendBeacon(u);",
    "const m = import('./x.js');",
]
GOOD_JS = [
    "el.textContent = x;",
    "el.setAttribute('class', 'a');",
    "setTimeout(function () {}, 10);",
    "btn.addEventListener('click', f);",
    "if (a.onx == 1) {}",
    "const r = obj.reval(1);",
]
BAD_HTML = [
    "<script>alert(1)</script>",
    "<style>a{}</style>",
    '<img src="x" onerror="a()">',
    '<p style="color:red">x</p>',
    '<a href="javascript:a()">x</a>',
    '<script src="https://example.com/a.js"></script>',
    "<iframe src='/x'></iframe>",
]
GOOD_HTML = [
    '<script src="/web/a.js"></script>',
    '<link rel="stylesheet" href="/web/app.css">',
    "<p>on the way</p>",
]
BAD_CSS = [
    "a:hover { color: red; }",
    "@media (max-width: 700px) { a:hover { color: red; } }",
    "@media (hover: none) { a:hover { color: red; } }",
    "body { background: url(https://example.com/a.png); }",
    "@import url(x.css);",
]
GOOD_CSS = [
    "@media (hover: hover) { a:hover { color: red; } }",
    "@media (hover: hover) { a:hover { color: red; } b:hover { color: blue; } }",
    "@media (min-width: 1px) { @media (hover: hover) { a:hover { color: red; } } }",
    "a:focus-visible { color: red; }",
    "/* a:hover */ a { color: red; }",
]


def css_problems(css: str) -> list[str]:
    return scan(css, CSS_RULES) + hover_violations(css)


@pytest.mark.parametrize("frag", BAD_JS)
def test_js_checker_detects_violation(frag: str) -> None:
    assert scan(frag, JS_RULES), frag


@pytest.mark.parametrize("frag", GOOD_JS)
def test_js_checker_accepts_safe_code(frag: str) -> None:
    assert scan(frag, JS_RULES) == []


@pytest.mark.parametrize("frag", BAD_HTML)
def test_html_checker_detects_violation(frag: str) -> None:
    assert scan(frag, HTML_RULES), frag


@pytest.mark.parametrize("frag", GOOD_HTML)
def test_html_checker_accepts_safe_markup(frag: str) -> None:
    assert scan(frag, HTML_RULES) == []


@pytest.mark.parametrize("frag", BAD_CSS)
def test_css_checker_detects_violation(frag: str) -> None:
    assert css_problems(frag), frag


@pytest.mark.parametrize("frag", GOOD_CSS)
def test_css_checker_accepts_safe_css(frag: str) -> None:
    assert css_problems(frag) == []


GOOD_POST = 'fetch(p, { method: "POST", headers: { "Content-Type": "application/json", "X-PRV": "1" }, body: b });'
BAD_POST = [
    'fetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: b });',
    'fetch(p, { method: "POST", headers: { "X-PRV": "1" }, body: b });',
    'fetch(p, { method: "PUT", headers: { "Content-Type": "application/json" }, body: b });',
    'fetch(p, { method: "DELETE" });',
]


@pytest.mark.parametrize("frag", BAD_POST)
def test_write_checker_detects_missing_header(frag: str) -> None:
    assert write_violations("api.js", frag), frag


def test_write_checker_accepts_complete_post() -> None:
    assert write_violations("api.js", GOOD_POST) == []
    assert write_violations("api.js", 'fetch(p, { method: "GET" });') == []


def test_write_checker_rejects_fetch_outside_api() -> None:
    assert write_violations("view-pr.js", GOOD_POST)
    assert write_violations("view-pr.js", "PRV.api.pr(id);") == []


# --- 実ファイル ---


def test_web_dir_has_files() -> None:
    names = {p.name for p in web_files()}
    assert {"index.html", "app.css", "api.js", "core.js", "review.js", "send.js"} <= names


def test_only_allowed_file_kinds() -> None:
    """サーバの許可リスト（index.html・app.css・*.js）に載る種類だけ置く。"""
    for p in web_files():
        assert p.name in ("index.html", "app.css") or p.suffix == ".js", p.name


@pytest.mark.parametrize("path", [p for p in WEB.glob("*.js")], ids=lambda p: p.name)
def test_js_has_no_forbidden_api(path: pathlib.Path) -> None:
    assert scan(path.read_text(encoding="utf-8"), JS_RULES) == []


@pytest.mark.parametrize("path", [p for p in WEB.glob("*.js")], ids=lambda p: p.name)
def test_js_writes_follow_rules(path: pathlib.Path) -> None:
    assert write_violations(path.name, path.read_text(encoding="utf-8")) == []


def test_api_posts_with_x_prv() -> None:
    """api.js に POST が実在し、X-PRV を付けている（検査が空振りしていないこと）。"""
    text = (WEB / "api.js").read_text(encoding="utf-8")
    assert POST_RE.search(text)
    assert '"X-PRV": "1"' in text


def test_api_sends_expect_and_handles_stale_view() -> None:
    """書き込みは表示していた版 (expect) を付け、409 stale_view のあとは詳細のキャッシュを捨てる。"""
    api = (WEB / "api.js").read_text(encoding="utf-8")
    assert re.search(r"/comments\"[^;]*expect\s*:\s*c\.expect", api)
    assert re.search(r"/submit\"[^;]*expect\s*:\s*s\.expect", api)
    assert "stale_view" in api and re.search(r"PRV\.cache\s*=\s*\{\}", api)
    # 呼び出し側 (コメント・送信) がすべて expect を渡している
    for name in ("review.js", "view-pr.js", "view-diff.js", "send.js"):
        text = (WEB / name).read_text(encoding="utf-8")
        for m in re.finditer(r"PRV\.api\.(comment|submit)\(([^\n]*)", text):
            assert "expect" in m.group(2), f"{name}: {m.group(0)}"


def test_fake_server_checks_expect() -> None:
    """偽物サーバ自身の確認: 版が違えば 409 stale_view、省略は missing_expect に記録される。"""
    st = ReviewState()
    path = "/api/prs/r1a2b3c4d/paaaaaaaaaaaaaaa1/comments"
    pr = find_pr(["api", "prs", "r1a2b3c4d", "paaaaaaaaaaaaaaa1"])
    exp = {"source": pr["sourceOid"], "target": pr["targetOid"], "base": pr["baseOid"]}
    assert post_response(path, {"body": "x", "expect": exp}, st)[0] == 201
    assert st.missing_expect == []
    st.bumped.add("paaaaaaaaaaaaaaa1")
    code, res = post_response(path, {"body": "x", "expect": exp}, st)
    assert code == 409 and res["error"]["code"] == "stale_view"
    assert post_response(path, {"body": "x"}, st)[0] == 201 and st.missing_expect == ["comments"]


def test_html_has_no_inline_code() -> None:
    assert scan((WEB / "index.html").read_text(encoding="utf-8"), HTML_RULES) == []


def test_css_is_safe() -> None:
    assert css_problems((WEB / "app.css").read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", web_files(), ids=lambda p: p.name)
def test_file_is_under_line_limit(path: pathlib.Path) -> None:
    n = len(path.read_text(encoding="utf-8").splitlines())
    assert n < MAX_LINES, f"{path.name} は {n} 行"


def test_index_references_existing_files() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="(/web/[^"]+)"', html)
    assert refs
    for ref in refs:
        assert (WEB / ref.removeprefix("/web/")).is_file(), ref
    # 読み込む script は、すべて許可リストの内側にある
    for src in re.findall(r'<script[^>]*\ssrc="([^"]+)"', html):
        assert src.startswith("/web/"), src


def test_single_global() -> None:
    """グローバルの追加は window.PRV だけ（window.<名前> = の代入を検出する）。"""
    for p in WEB.glob("*.js"):
        for m in re.finditer(r"\bwindow\.([A-Za-z_]\w*)\s*=(?!=)", p.read_text(encoding="utf-8")):
            assert m.group(1) == "PRV", f"{p.name}: window.{m.group(1)}"


# ----------------------------------------------------------- fixture サーバ ---

CSP = "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


def load_fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def err_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


class ReviewState:
    """POST で変わる review の状態（サーバごと。fixture を初期値にする）。"""

    def __init__(self) -> None:
        self.rv: dict[str, dict] = {}
        self.pending: dict[str, list[str]] = {}
        self.seq = 0
        self.bumped: set[str] = set()  # PR が更新された (source が変わった) ことにする key
        self.missing_expect: list[str] = []  # expect を付けずに届いた書き込み
        self.last_expect: dict | None = None
        self.last_submit: dict | None = None

    def get(self, key: str) -> dict:
        if key not in self.rv:
            rv = load_fixture(f"review_{key}.json")
            self.rv[key] = rv
            self.pending[key] = [
                c["id"] for t in rv["threads"] if t["status"] == "unsent" for c in t["comments"]
            ]
        return self.rv[key]

    def view(self, key: str) -> dict:
        rv = self.get(key)
        return {**rv, "unsent": len(self.pending[key])}

    def add_comment(self, key: str, payload: dict) -> tuple[int, dict]:
        rv = self.get(key)
        body = payload.get("body")
        if not isinstance(body, str) or not body.strip():
            return 400, err_body("bad_body", "コメントが空です。")
        self.seq += 1
        cid = f"n{self.seq}"
        anchor = payload.get("anchor")
        thread = None
        if payload.get("thread"):
            thread = next((t for t in rv["threads"] if t["id"] == payload["thread"]), None)
            if thread is None:
                return 400, err_body("bad_thread", "スレッドが見つかりません。")
            anchor = None
        elif anchor is not None:
            blob = anchor.get("blob") if isinstance(anchor, dict) else None
            if not isinstance(blob, str) or not re.fullmatch(r"[0-9a-f]{40}", blob):
                return 400, err_body("bad_anchor", "コメントの位置が正しくありません。")
        comment = {
            "id": cid,
            "by": "app",
            "at": "2099-02-01T00:00:00+00:00",
            "body": body,
            "anchor": anchor,
        }
        if thread is None:
            rv["threads"].append(
                {"id": cid, "status": "unsent", "stale": False, "comments": [comment]}
            )
        else:
            thread["comments"].append(comment)
        self.pending[key].append(cid)
        return 201, {"comment": {**comment, "thread": thread["id"] if thread else cid}}

    def submit(self, key: str, payload: dict) -> tuple[int, dict]:
        rv = self.get(key)
        kind = payload.get("kind")
        if kind not in ("comment", "changes", "approve"):
            return 400, err_body("bad_kind", "種別が正しくありません。")
        self.last_submit = payload
        resend = payload.get("resendOf")
        if resend:
            old = next((b for b in rv["batches"] if b["batchId"] == resend), None)
            if old is None:
                return 400, err_body("bad_resend", "再送する送信が見つかりません。")
            self.seq += 1
            batch = {**old, "batchId": f"nb{self.seq}", "received": False, "resendOf": resend}
            rv["batches"].append(batch)
            return 201, {k: batch[k] for k in ("batchId", "kind", "items", "dest")}
        items = list(self.pending[key])
        if kind == "comment" and not items:
            return 400, err_body("nothing_to_send", "送るコメントがありません。")
        dest = payload.get("dest") or rv["defaultDest"]
        if dest["worktreeId"] not in {w["worktreeId"] for w in rv["worktrees"]}:
            return 400, err_body("bad_dest", "宛先が正しくありません。")
        for t in rv["threads"]:
            if any(c["id"] in items for c in t["comments"]) and t["status"] == "unsent":
                t["status"] = "sent"
        self.seq += 1
        batch = {
            "batchId": f"nb{self.seq}",
            "kind": kind,
            "items": items,
            "dest": dest,
            "received": False,
        }
        rv["batches"].append(batch)
        self.pending[key] = []
        if kind != "comment":
            rv["review"] = kind
            rv["reviewStale"] = False
        return 201, {k: batch[k] for k in ("batchId", "kind", "items", "dest")}


def find_pr(parts: list[str], state: ReviewState | None = None) -> dict | None:
    pr = next(
        (p for p in load_fixture("prs.json")["prs"] if p["id"] == f"{parts[2]}/{parts[3]}"), None
    )
    if pr is not None and state is not None and parts[3] in state.bumped:
        pr = {**pr, "sourceOid": BUMPED_OID}  # 更新後の版
    return pr


def api_response(path: str, state: ReviewState | None = None) -> tuple[int, dict]:
    """契約の GET エンドポイント（段 1 の 4 本 + review）を fixture から返す。"""
    state = state or ReviewState()
    u = urllib.parse.urlparse(path)
    parts = [p for p in u.path.split("/") if p]
    err = (404, {"error": {"code": "not_found", "message": "見つかりません。"}})
    if parts == ["api", "repos"]:
        return 200, load_fixture("repos.json")
    if parts == ["api", "prs"]:
        return 200, load_fixture("prs.json")
    if len(parts) in (4, 5) and parts[:2] == ["api", "prs"]:
        pr = find_pr(parts, state)
        if pr is None:
            return err
        if len(parts) == 4:
            return 200, {"pr": pr, **load_fixture(f"detail_{parts[3]}.json")}
        if parts[4] == "review":
            return 200, state.view(parts[3])
        if parts[4] == "diff":
            q = urllib.parse.parse_qs(u.query)
            if "path" not in q:
                return 400, {
                    "error": {"code": "bad_request", "message": "指定が正しくありません。"}
                }
            return 200, load_fixture(f"diff_{parts[3]}.json")
    return err


def post_response(path: str, payload: dict, state: ReviewState) -> tuple[int, dict]:
    parts = [p for p in urllib.parse.urlparse(path).path.split("/") if p]
    if len(parts) == 5 and parts[:2] == ["api", "prs"] and find_pr(parts, state) is not None:
        pr = find_pr(parts, state)
        exp = payload.get("expect")
        if exp is None:
            state.missing_expect.append(parts[4])
        else:
            cur = {"source": pr["sourceOid"], "target": pr["targetOid"], "base": pr["baseOid"]}
            if exp != cur:
                return 409, err_body(
                    "stale_view",
                    "表示中の版から PR が更新されています。再読み込みしてから送ってください。",
                )
            state.last_expect = exp
        if parts[4] == "comments":
            return state.add_comment(parts[3], payload)
        if parts[4] == "submit":
            return state.submit(parts[3], payload)
    return 404, err_body("not_found", "見つかりません。")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_a) -> None:  # 試験の出力を汚さない
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(
            code,
            json.dumps(data, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def do_POST(self) -> None:
        """契約どおり X-PRV と JSON の Content-Type が無い書き込みは 400。"""
        ctype = self.headers.get("Content-Type", "")
        if self.headers.get("X-PRV") != "1" or not ctype.startswith("application/json"):
            self._json(400, err_body("bad_request", "ヘッダーが正しくありません。"))
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            self._json(400, err_body("bad_json", "本文が正しくありません。"))
            return
        code, data = post_response(self.path, payload, self.server.state)  # type: ignore[attr-defined]
        self._json(code, data)

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            code, data = api_response(self.path, self.server.state)  # type: ignore[attr-defined]
            self._json(code, data)
            return
        name = (
            "index.html"
            if path == "/"
            else path.removeprefix("/web/")
            if path.startswith("/web/")
            else ""
        )
        f = WEB / name
        if (
            name
            and re.fullmatch(r"[\w.-]+", name)
            and f.is_file()
            and (name in ("index.html", "app.css") or f.suffix == ".js")
        ):
            self._send(200, f.read_bytes(), TYPES[f.suffix])
            return
        self._send(
            404,
            b'{"error":{"code":"not_found","message":"\xe8\xa6\x8b\xe3\x81\xa4\xe3\x81\x8b\xe3\x82\x8a\xe3\x81\xbe\xe3\x81\x9b\xe3\x82\x93\xe3\x80\x82"}}',
            "application/json",
        )


def serve() -> tuple[http.server.ThreadingHTTPServer, str]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.state = ReviewState()  # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_fixtures_follow_contract() -> None:
    prs = load_fixture("prs.json")["prs"]
    keys = {
        "repoId",
        "prKey",
        "id",
        "repoName",
        "branch",
        "target",
        "state",
        "commits",
        "files",
        "additions",
        "deletions",
        "lastCommit",
        "sourceOid",
        "targetOid",
        "baseOid",
    }
    assert len(prs) == 3
    for p in prs:
        assert keys <= set(p), p["id"]
        assert re.fullmatch(r"r[0-9a-f]{8}", p["repoId"]) and re.fullmatch(
            r"p[0-9a-f]{16}", p["prKey"]
        )
        assert p["id"] == f"{p['repoId']}/{p['prKey']}" and p["state"] in ("open", "merged")
        status, body = api_response(f"/api/prs/{p['id']}")
        assert status == 200 and {"pr", "commits", "files", "filesTruncated"} <= set(body)
        status, body = api_response(f"/api/prs/{p['id']}/diff?path=x")
        assert status == 200 and {"path", "binary", "truncated", "hunks"} <= set(body)
        assert {"oldBlob", "newBlob"} <= set(body)  # コメントの anchor.blob に使う
        for b in (body["oldBlob"], body["newBlob"]):
            assert b is None or re.fullmatch(r"[0-9a-f]{40}", b)
        status, rv = api_response(f"/api/prs/{p['id']}/review")
        assert status == 200 and set(rv) >= REVIEW_KEYS, p["id"]
        for t in rv["threads"]:
            assert t["status"] in ("unsent", "sent", "read", "replied")
            assert {"id", "stale", "comments"} <= set(t)


REVIEW_KEYS = {
    "schema",
    "readonly",
    "bad",
    "review",
    "reviewStale",
    "stale",
    "staleParts",
    "merged",
    "threads",
    "batches",
    "summary",
    "worktrees",
    "defaultDest",
    "unsent",
}


def test_fixture_review_covers_states() -> None:
    """fixture が 4 状態・stale・サマリー・宛先候補を含むこと。"""
    rv = load_fixture("review_paaaaaaaaaaaaaaa1.json")
    assert {t["status"] for t in rv["threads"]} == {"unsent", "sent", "read", "replied"}
    assert any(t["stale"] for t in rv["threads"])
    assert rv["summary"] and len(rv["worktrees"]) >= 2 and any(w["isMain"] for w in rv["worktrees"])


def test_fake_server_state_machine() -> None:
    """偵物の POST サーバ自身の確認: コメント → 未送信が増える → 送信 → 送信済み。"""
    st = ReviewState()
    key = "paaaaaaaaaaaaaaa1"
    assert st.view(key)["unsent"] == 1
    assert st.add_comment(key, {"body": "  "})[0] == 400
    code, res = st.add_comment(key, {"body": "x"})
    assert code == 201 and res["comment"]["thread"] == res["comment"]["id"]
    assert st.view(key)["unsent"] == 2
    code, res = st.submit(key, {"kind": "changes"})
    assert code == 201 and len(res["items"]) == 2
    rv = st.view(key)
    assert rv["unsent"] == 0 and rv["review"] == "changes"
    assert {t["status"] for t in rv["threads"]} == {"sent", "read", "replied"}
    assert st.submit(key, {"kind": "comment"})[0] == 400  # 空の送信


def test_fixture_server_serves_web_and_csp() -> None:
    import urllib.request

    srv, base = serve()
    try:
        with urllib.request.urlopen(base + "/") as r:
            assert r.headers["Content-Security-Policy"].startswith("default-src 'self'")
            assert b"/web/core.js" in r.read()
        with urllib.request.urlopen(base + "/api/prs") as r:
            assert "feature/add-search" in r.read().decode("utf-8")
    finally:
        srv.shutdown()


# ------------------------------------------------------------- ブラウザ smoke ---


def find_chrome() -> str | None:
    found = sorted(
        glob.glob(
            str(pathlib.Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux64/chrome")
        )
    )
    return found[-1] if found else None


EVIL = 'onerror="window.__pwned=1"'


def shot(page, shots: pathlib.Path | None, name: str) -> None:
    if shots:
        page.screenshot(path=str(shots / f"{name}.png"), full_page=True)


def flow_overview(page, kind: str, check, shots) -> None:
    """概要: サマリー・全体スレッド・送信バー。統合のボタンが無いこと。"""
    t = page.inner_text("#app")
    for s in (
        "pi のまとめ",
        "やったこと",
        "確認してほしい点",
        "db.find の例外処理",
        "全体として、テストを足して",
        "➤ 送信済み",
    ):
        check(s in t, f"{kind} 概要に {s!r} が無い")
    bar = page.inner_text(".revbar")
    check("未送信 1 件" in bar, f"{kind} 送信バーに未送信の件数が無い: {bar!r}")
    check("次に pi へ入力したときに届く" in bar, f"{kind} 送信バーに届くタイミングの説明が無い")
    check(page.locator("button", has_text="統合").count() == 0, f"{kind} 統合のボタンがある")
    ws = page.evaluate("getComputedStyle(document.querySelector('.summary .cbody')).whiteSpace")
    check(ws == "pre-wrap", f"{kind} 本文が pre-wrap でない: {ws}")
    shot(page, shots, f"{kind}-overview-review")


def flow_diff_comment(page, kind: str, check, shots) -> None:
    """差分: 4 状態・stale の表示、行クリック → 入力 → 未送信スレッド、返信。"""
    t = page.inner_text(".file")
    for s in (
        "◐ pi が読んだ",
        "● pi が返信済み",
        "⚠ 古い版",
        "確認します。",
        "ここは null を返さない?",
    ):
        check(s in t, f"{kind} 差分のスレッドに {s!r} が無い")
    ws = page.evaluate("getComputedStyle(document.querySelector('.thread .cbody')).whiteSpace")
    check(ws == "pre-wrap", f"{kind} コメント本文が pre-wrap でない: {ws}")
    # 同じ path・同じ行番号でも別の blob のスレッドは行の下に出さず、表の上の「対応しない」箱にまとめる
    other = "別の版の同じ行番号のコメント"
    check(
        page.locator("table.diff", has_text=other).count() == 0,
        f"{kind} 別の blob のコメントが行の下に出ている",
    )
    check(
        page.locator(".orphans", has_text=other).count() == 1,
        f"{kind} 別の blob のコメントが「対応しない」箱に無い",
    )
    row = page.locator("tr.a", has_text="return db.find(q);")
    row.locator("td.code").click()
    page.wait_for_selector("tr.editor textarea")
    page.locator("tr.editor button", has_text="保存").click()  # 空の保存は日本語で断る
    check(
        "コメントを入力してください" in page.inner_text("tr.editor"), f"{kind} 空の保存を断らない"
    )
    shot(page, shots, f"{kind}-comment-editor")
    page.locator("tr.editor textarea").fill("新しいコメント\n2 行目")
    page.locator("tr.editor button", has_text="保存").click()
    page.wait_for_selector(".thread:has-text('新しいコメント')")
    thread = page.locator(".thread", has_text="新しいコメント")
    check("○ 未送信" in thread.inner_text(), f"{kind} 保存したスレッドが「未送信」でない")
    check(page.locator("tr.editor").count() == 0, f"{kind} 保存後も入力欄が残っている")
    below = row.evaluate("e => e.nextElementSibling.className")
    check(below == "thr", f"{kind} スレッドが行の下に無い: {below}")
    # 返信
    old = page.locator(".thread", has_text="確認します。")
    old.locator("button", has_text="返信").click()
    old.locator("textarea").fill("返信です")
    old.locator("button", has_text="返信を保存").click()
    page.wait_for_selector(".thread:has-text('返信です')")
    shot(page, shots, f"{kind}-threads")
    if kind == "pc":  # 左右並びでも、右（新）のセルで入力欄が開き、キャンセルで閉じる
        page.locator("button", has_text="左右並び").click()
        page.locator("table.diff.split td.code.a").first.click()
        page.wait_for_selector("tr.editor textarea")
        page.locator("tr.editor button", has_text="キャンセル").click()
        check(page.locator("tr.editor").count() == 0, "pc 左右並びでキャンセルしても入力欄が残る")
        page.locator("button", has_text="1 列").first.click()


def flow_send(page, kind: str, base: str, check, shots) -> None:
    """概要に戻って、全体コメント → レビューを送るシート → 送信済み。一覧のチップ。"""
    page.locator(".tabs a", has_text="概要").click()
    page.wait_for_selector(".revbar")
    check(
        "未送信 3 件" in page.inner_text(".revbar"),
        f"{kind} 未送信が 3 件にならない: {page.inner_text('.revbar')!r}",
    )
    card = page.locator(".card", has_text="PR 全体のコメント")
    card.locator("textarea").fill("全体への追記")
    card.locator("button", has_text="コメントを保存").click()
    page.wait_for_selector(".thread:has-text('全体への追記')")
    check(
        "未送信 4 件" in page.inner_text(".revbar"),
        f"{kind} 全体コメント後に未送信が 4 件にならない",
    )
    page.locator(".revbar button", has_text="レビューを送る").click()
    page.wait_for_selector(".sheet")
    st = page.inner_text(".sheet")
    for s in (
        "次に pi へ入力したときに届く",
        "未送信のコメント: 4 件",
        "コメントのみ",
        "変更を依頼",
        "承認",
    ):
        check(s in st, f"{kind} 送信シートに {s!r} が無い")
    opts = page.locator("#dest-sel option").all_inner_texts()
    check("example-app（親）" in opts and len(opts) == 2, f"{kind} 宛先の候補がおかしい: {opts}")
    page.locator(".sheet button", has_text="変更を依頼").click()
    check(
        page.locator(".sheet button[aria-pressed='true']").inner_text().endswith("変更を依頼"),
        f"{kind} 種別が選ばれない",
    )
    shot(page, shots, f"{kind}-send-sheet")
    page.locator(".sheet button", has_text="送る").click()
    page.wait_for_selector(".sheet", state="detached")
    page.wait_for_selector(".revnotice")
    check("届きます" in page.inner_text(".revnotice"), f"{kind} 送信後の案内が無い")
    check("変更依頼" in page.inner_text(".prhead h1"), f"{kind} 変更依頼のチップが無い")
    check("未送信 0 件" in page.inner_text(".revbar"), f"{kind} 送信後も未送信が残る")
    check("送信したレビュー (2)" in page.inner_text("#app"), f"{kind} 送信履歴が無い")
    check(
        page.locator(".thread .chip", has_text="○ 未送信").count() == 0,
        f"{kind} 送信後も未送信のスレッドが残る",
    )
    check(
        page.locator(".thread .chip", has_text="➤ 送信済み").count() >= 2,
        f"{kind} 「送信済み」のスレッドが無い",
    )
    shot(page, shots, f"{kind}-after-send")
    page.goto(f"{base}/#/")
    page.wait_for_selector(".prrow:has-text('feature/add-search') .chip")
    check(
        "変更依頼" in page.locator(".prrow", has_text="feature/add-search").inner_text(),
        f"{kind} 一覧に変更依頼のチップが無い",
    )


def flow_stale_and_resend(page, kind: str, base: str, state, check) -> None:
    """表示中に PR が更新されたときは 409 を日本語で示し、取り直してから送れる。送信履歴の再送。"""
    key = "paaaaaaaaaaaaaaa1"
    page.goto(f"{base}/#/pr/r1a2b3c4d/{key}")
    page.wait_for_selector(".revbar button")
    state.bumped.add(key)  # 画面が古い版を表示している間に、PR を更新する
    card = page.locator(".card", has_text="PR 全体のコメント")
    card.locator("textarea").fill("版がずれた後のコメント")
    card.locator("button", has_text="コメントを保存").click()
    page.wait_for_selector(".formerr:has-text('更新されています')")
    check(
        page.locator(".thread", has_text="版がずれた後のコメント").count() == 0,
        f"{kind} 版がずれたコメントが保存された",
    )
    reload = page.locator(".cform button", has_text="最新の版を読み込む")
    check(reload.count() == 1, f"{kind} 409 のあとに取り直しのボタンが無い")
    reload.click()
    page.wait_for_selector(f"text={BUMPED_OID[:7]}")  # 取り直した詳細の先頭 (source) が出る
    card = page.locator(".card", has_text="PR 全体のコメント")
    card.locator("textarea").fill("取り直した後のコメント")
    card.locator("button", has_text="コメントを保存").click()
    page.wait_for_selector(".thread:has-text('取り直した後のコメント')")
    check(
        (state.last_expect or {}).get("source") == BUMPED_OID,
        f"{kind} 取り直した版を expect に付けていない: {state.last_expect}",
    )
    # 送信履歴の再送
    before = page.locator(".card", has_text="送信したレビュー").locator("li").count()
    page.locator(".card", has_text="送信したレビュー").locator(
        "button", has_text="再送"
    ).first.click()
    page.wait_for_selector(".revnotice")
    after = page.locator(".card", has_text="送信したレビュー").locator("li").count()
    check(after == before + 1, f"{kind} 再送しても履歴が増えない: {before} -> {after}")
    sent = state.last_submit or {}
    check(bool(sent.get("resendOf")), f"{kind} 再送の要求に resendOf が無い: {sent}")
    check(
        state.missing_expect == [],
        f"{kind} expect を付けない書き込みがある: {state.missing_expect}",
    )


def flow_hostile_review(page, kind: str, check) -> None:
    """敵対的な review（本文・サマリー・作業ツリー名）が文字として出る。古いレビューの印。"""
    check(
        "✓ 承認" in page.inner_text("h1") and "古いレビュー" in page.inner_text("h1"),
        f"{kind} 承認・古いレビューの印が無い",
    )
    check(
        EVIL in page.inner_text(".summary"),
        f"{kind} サマリーの敵対的な文字列が文字として出ていない",
    )
    check(
        EVIL in page.inner_text(".thread"), f"{kind} スレッドの敵対的な本文が文字として出ていない"
    )
    page.locator(".revbar button", has_text="レビューを送る").click()
    page.wait_for_selector(".sheet")
    check(
        any(EVIL in o for o in page.locator("#dest-sel option").all_inner_texts()),
        f"{kind} 作業ツリー名が文字として出ていない",
    )
    check(
        page.locator(".backdrop img, .backdrop script").count() == 0,
        f"{kind} シートに img/script ができた",
    )
    page.locator(".sheet button", has_text="閉じる").click()
    page.wait_for_selector(".sheet", state="detached")


def browser_main(shots: pathlib.Path | None) -> int:
    """子プロセスで動く本体。失敗は JSON で標準出力へ。"""
    from playwright.sync_api import sync_playwright

    chrome = find_chrome()
    if chrome is None:
        print(
            json.dumps(
                {"skip": "Chromium（~/.cache/ms-playwright/chromium-*）が見つからない"},
                ensure_ascii=False,
            )
        )
        return SKIP_CODE
    fails: list[str] = []
    merged_id, evil_id = (
        "r1a2b3c4d/p1111111111111111",
        "r1a2b3c4d/p2222222222222222",
    )

    def check(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path=chrome)
        # 反例: 検査の仕掛け（__pwned）が、実際に実行された onerror を検出できること
        probe = br.new_page()
        probe.set_content('<img src="x" onerror="window.__pwned=1">')
        probe.wait_for_function("window.__pwned === 1", timeout=3000)
        probe.close()

        for kind, size in (
            ("pc", {"width": 1280, "height": 900}),
            ("sp", {"width": 393, "height": 852}),
        ):
            sp = kind == "sp"
            srv, base = serve()  # 状態を持つので、画面の種類ごとに立て直す
            ctx = br.new_context(viewport=size, has_touch=sp, is_mobile=sp, color_scheme="light")
            page = ctx.new_page()
            errs: list[str] = []
            page.on("pageerror", lambda e, errs=errs: errs.append(f"pageerror: {e}"))
            page.on(
                "console",
                lambda m, errs=errs: (
                    errs.append(f"console: {m.text}") if m.type in ("error", "warning") else None
                ),
            )
            page.on(
                "request",
                lambda r, errs=errs, base=base: (
                    errs.append(f"外部通信: {r.url}")
                    if not r.url.startswith((base, "data:"))
                    else None
                ),
            )

            def text(page=page) -> str:
                return page.inner_text("#app")

            def pwned(page=page) -> bool:
                return page.evaluate("window.__pwned !== undefined")

            page.goto(base + "/")
            page.wait_for_selector(".prlist")
            t = text()
            for s in ("feature/add-search", "example-app", "統合済み", "bugfix/fix-typo"):
                check(s in t, f"{kind} 一覧に {s!r} が無い")
            row = page.locator(".prrow", has_text="feature/add-search")
            check(row.locator(".chip").count() == 0, f"{kind} open の行にチップが出ている")
            check(
                page.locator(".prrow", has_text="bugfix/fix-typo").locator(".chip").count() == 1,
                f"{kind} 統合済みのチップが 1 つでない",
            )
            check(EVIL in t, f"{kind} 敵対的なブランチ名が文字として出ていない")
            check(
                page.locator("#app img, #app script").count() == 0,
                f"{kind} 一覧に img/script 要素ができた",
            )
            check(not pwned(), f"{kind} 一覧で敵対的な文字列が実行された")

            row.locator("a").click()
            page.wait_for_selector("text=コミット (2)")
            t = text()
            for s in (
                "feat: 検索ボックスを追加",
                "src/search.ts",
                "chore: 検索の下準備",
                "変更ファイル (2)",
            ):
                check(s in t, f"{kind} 概要に {s!r} が無い")
            if shots:
                page.screenshot(path=str(shots / f"{kind}-overview.png"), full_page=True)
            flow_overview(page, kind, check, shots)

            page.locator(".tabs a", has_text="差分").click()
            page.wait_for_selector("table.diff")
            t = text()
            for s in ("export function search(q: string) {", "@@ -1,3 +1,5 @@", "src/search.ts"):
                check(s in t, f"{kind} 差分に {s!r} が無い")
            split_btn = page.locator("button", has_text="左右並び")
            if sp:
                check(not split_btn.is_visible(), "sp で左右並びのボタンが見えている")
            else:
                split_btn.click()
                check(
                    page.locator("table.diff.split").count() == 1, "pc で左右並びに切り替わらない"
                )
                page.locator("button", has_text="1 列").first.click()
                check(page.locator("table.diff.unified").count() == 1, "pc で 1 列表示に戻らない")
            if shots:
                page.screenshot(path=str(shots / f"{kind}-files.png"), full_page=True)
            flow_diff_comment(page, kind, check, shots)
            if sp:
                page.locator(".filetree summary").click()
            page.locator(".tree a", has_text="src/app.ts").click()
            page.wait_for_selector("table.diff")
            # 前のファイルの表が残っている間は wait_for_selector が即座に返るので、見出しが変わるのを待つ
            page.wait_for_function(
                "() => (document.querySelector('.fh')?.innerText || '').includes('src/app.ts')"
            )
            check(
                "src/app.ts" in page.inner_text(".fh"),
                f"{kind} ファイルを選んでも見出しが変わらない",
            )
            w = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            check(w[0] <= w[1], f"{kind} 横にはみ出している {w}")
            check(
                "○ 未送信" in page.locator(".thread", has_text="app.ts の 1 行目").inner_text(),
                f"{kind} app.ts の未送信スレッドが表示されない",
            )
            flow_send(page, kind, base, check, shots)
            flow_stale_and_resend(page, kind, base, srv.state, check)

            # 統合済みの PR
            page.goto(f"{base}/#/pr/{merged_id}")
            page.wait_for_selector("text=変更ファイル (1)")
            check(
                "✓ 統合済み" in page.inner_text(".prhead"), f"{kind} 統合済みの概要にチップが無い"
            )
            check(
                "統合済み" in page.inner_text(".revbar")
                and page.locator(".revbar button, #app textarea").count() == 0,
                f"{kind} 統合済みの PR で入力や送信ができてしまう",
            )

            # 敵対的な PR: 概要・差分
            page.goto(f"{base}/#/pr/{evil_id}")
            page.wait_for_selector("text=変更ファイル (1)")
            check(
                EVIL in page.inner_text("h1"),
                f"{kind} 概要の見出しに敵対的な文字列が文字として出ていない",
            )
            check(EVIL in text(), f"{kind} 概要のコミット件名・パスが文字として出ていない")
            flow_hostile_review(page, kind, check)
            page.locator(".tabs a", has_text="差分").click()
            page.wait_for_selector("table.diff")
            check(
                EVIL in page.inner_text("tr.thr"),
                f"{kind} 差分のスレッドの敵対的な本文が出ていない",
            )
            check(
                "<script>window.__pwned=1</script>" in page.inner_text("table.diff"),
                f"{kind} 差分の行が文字として出ていない",
            )
            check(
                page.locator("#app img, #app script").count() == 0,
                f"{kind} 差分に img/script 要素ができた",
            )
            check(not pwned(), f"{kind} 差分で敵対的な文字列が実行された")

            # エラー表示（存在しない PR は 404 → 日本語で出る）
            page.goto(f"{base}/#/pr/r00000000/p0000000000000000")
            page.wait_for_selector(".alertbox")
            check(
                "見つかりません" in page.inner_text(".alertbox"), f"{kind} エラーが日本語で出ない"
            )
            errs = [
                e for e in errs if "404" not in e and "409" not in e
            ]  # 意図した 404/409 の資源エラー
            check(errs == [], f"{kind} console/通信の異常: {errs}")
            ctx.close()
            srv.shutdown()
        br.close()
    print(json.dumps({"fails": fails}, ensure_ascii=False))
    return 1 if fails else 0


def test_browser_smoke() -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv が無いので、ブラウザの smoke を実行できない")
    if find_chrome() is None:
        pytest.skip("Chromium（~/.cache/ms-playwright/chromium-*）が無い")
    cmd = [
        uv,
        "run",
        "--offline",
        "--no-project",
        "--with",
        "playwright",
        "--with",
        "pytest",
        "python",
        str(pathlib.Path(__file__)),
        "--browser",
    ]
    res = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", timeout=240, check=False
    )
    if res.returncode == SKIP_CODE:
        pytest.skip(res.stdout.strip())
    if res.returncode != 0 and "fails" not in res.stdout:
        if "Traceback" in res.stderr:
            pytest.fail(f"ブラウザ試験が異常終了した:\n{res.stderr.strip()[-1500:]}")
        pytest.skip(
            f"playwright を起動できない（オフラインで取得できない等）: {res.stderr.strip()[-300:]}"
        )
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["fails"] == [], "\n".join(out["fails"])


if __name__ == "__main__":
    if "--browser" in sys.argv:
        shot_dir = None
        if "--shots" in sys.argv:
            shot_dir = pathlib.Path(sys.argv[sys.argv.index("--shots") + 1])
            shot_dir.mkdir(parents=True, exist_ok=True)
        sys.exit(browser_main(shot_dir))
    sys.exit(pytest.main([__file__, "-q"]))
