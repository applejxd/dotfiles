"""PR ビューア 段 1・2 の画面（apps/pr-viewer/web/）の試験。

1. 静的検査: 描画の安全規則（XSS を防ぐ規則）と配信の規則（CSP）、書き込みの規則（POST に X-PRV を付ける）に違反する記述が無いこと。
   検査関数そのものが違反を検出できることを、違反の断片で先に確かめる。
2. 描画の smoke: 契約どおりの JSON を返す小さな HTTP サーバ（POST を受けて状態が変わる）と web/ を配信し、ヘッドレス Chromium で
   一覧・概要・差分・コメント入力・レビュー送信を開く。敵対的な文字列が文字として表示され、実行されないことも確かめる。
   ブラウザ部分は `uv run --with playwright python <このファイル> --browser` を子プロセスで呼ぶ（無ければ skip）。
"""

from __future__ import annotations

import glob
import hashlib
import http.server
import json
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "pr-viewer" / "web"
FIX = pathlib.Path(__file__).resolve().parent / "pr_viewer_fixtures"
MAX_LINES = 800
SKIP_CODE = 77  # ブラウザが使えないときの終了コード
BUMPED_OID = "9" * 40  # PR が更新された後の source (架空の値)

POLL_MS = 3000  # 画面の自動更新の間隔 (live.js の POLL_MS)
POLL_MAX_MS = 30000
LIVE_KEY = "paaaaaaaaaaaaaaa1"
LIVE_ID = f"r1a2b3c4d/{LIVE_KEY}"

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
    assert {
        "index.html",
        "app.css",
        "api.js",
        "core.js",
        "review.js",
        "send.js",
        "live.js",
        "merge.js",
        "create.js",
    } <= names


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


def test_merge_api_and_screen_are_wired() -> None:
    """統合 (CHG-0062 段 A2): API の 3 本と、画面の統合・既存の「承認して送る」の分離。"""
    api = (WEB / "api.js").read_text(encoding="utf-8")
    assert "/api/capabilities" in api and "/merge-plan" in api and '"/merge"' in api
    assert re.search(r"/merge\"[^;]*expect\s*:\s*m\.expect[^;]*cleanup\s*:\s*m\.cleanup", api)
    merge = (WEB / "merge.js").read_text(encoding="utf-8")
    send = (WEB / "send.js").read_text(encoding="utf-8")
    assert "PRV.api.submit" not in merge  # レビューの承認を再利用しない
    assert "PRV.openSheet" in merge and "PRV.openSheet" in send
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "/web/merge.js" in html and html.index("/web/send.js") < html.index("/web/merge.js")
    assert "承認して送る" in send


def test_merge_fixtures_follow_contract() -> None:
    oid = re.compile(r"[0-9a-f]{40}")
    assert load_fixture("capabilities.json")["targets"] == ["develop"]
    for name in ("ok", "conflict", "blocked", "riskcfg", "hostile"):
        p = load_fixture(f"merge_plan_{name}.json")
        assert {"mergeable", "refusal", "blockers", "plan", "defaults", "warnings"} <= set(p), name
        assert (p["plan"] is None) == (not p["mergeable"]), name
        if p["plan"]:
            assert oid.fullmatch(p["plan"]["source"]["oid"])
            assert oid.fullmatch(p["plan"]["target"]["oid"])
            assert p["plan"]["riskConfig"] in ("loaded", "unavailable")
    assert load_fixture("merge_plan_conflict.json")["refusal"]["conflicts"]
    assert load_fixture("merge_plan_blocked.json")["blockers"]
    assert load_fixture("merge_plan_riskcfg.json")["plan"]["riskConfig"] == "unavailable"
    for name, recorded in (("merge_ok", True), ("merge_unrecorded", False)):
        m = load_fixture(f"{name}.json")["merge"]
        assert oid.fullmatch(m["commit"]) and m["recorded"] is recorded, name


def test_fake_server_merge_routes() -> None:
    """偽物サーバ自身の確認: merge-plan・merge・版違い・枝の削除。"""
    st = ReviewState()
    base = "/api/prs/r1a2b3c4d/paaaaaaaaaaaaaaa1"
    assert api_response("/api/capabilities", st)[1]["merge"] is False
    st.caps_mode = "on"
    assert api_response("/api/capabilities", st)[1]["merge"] is True
    st.caps_mode = "404"
    assert api_response("/api/capabilities", st)[0] == 404
    assert post_response(base + "/merge-plan", {}, st)[1]["mergeable"] is True
    exp = {"source": "a" * 40, "target": "b" * 40}
    body = {"expect": exp, "message": "m", "cleanup": "branch"}
    code, res = post_response(base + "/merge", body, st)
    assert code == 200 and res["merge"]["cleanup"]["done"] == ["branch"]
    assert api_response(base, st)[0] == 404  # 枝を消した詳細は 404
    st2 = ReviewState()
    st2.bumped.add("paaaaaaaaaaaaaaa1")
    assert post_response(base + "/merge", {"expect": exp}, st2)[1]["error"]["code"] == "stale_view"


def test_create_api_and_screen_are_wired() -> None:
    """起票 (CHG-0062 段 B1): API ・画面の接続と、form を使わないこと。"""
    api = (WEB / "api.js").read_text(encoding="utf-8")
    assert '"/api/repos/" + repoId + "/features"' in api and "requestId: c.requestId" in api
    assert re.search(r"expect\s*:\s*\{\s*target\s*:\s*c\.target", api)
    assert (
        "create: b.create === true" in api and "create: false" in api
    )  # 古いサーバ・通信断は create=false
    create = (WEB / "create.js").read_text(encoding="utf-8")
    assert (
        "PRV.openSheet" in create
        and "PRV.api.createFeature" in create
        and "sessionStorage" in create
    )
    assert "PRV.api.submit" not in create and "PRV.api.merge" not in create
    for attr in ("autocapitalize", "autocorrect", "spellcheck"):
        assert attr in create
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert (
        html.index("/web/merge.js") < html.index("/web/create.js") < html.index("/web/view-list.js")
    )
    assert "PRV.createEntry" in (WEB / "view-list.js").read_text(encoding="utf-8")
    assert "PRV.briefCard" in (WEB / "view-pr.js").read_text(encoding="utf-8")


def test_create_fixtures_follow_contract() -> None:
    repos = load_fixture("create_repos.json")["repos"]
    assert all(re.fullmatch(r"[0-9a-f]{40}", r["targetOid"]) for r in repos)
    assert {r["target"] for r in repos} == {"develop", "main"}  # develop 以外は起票先にしない試験用
    assert load_fixture("create_pr_empty.json")["state"] == "empty"
    brief = load_fixture("create_review_empty.json")["brief"]
    assert {
        "rev",
        "title",
        "goal",
        "constraints",
        "scope",
        "acceptance",
        "digest",
        "bytes",
        "at",
    } <= set(brief)
    f = load_fixture("create_ok.json")["feature"]
    assert {
        "branch",
        "prKey",
        "id",
        "base",
        "worktree",
        "brief",
        "recorded",
        "replay",
        "warnings",
    } <= set(f)
    assert f["worktree"]["rel"].startswith(".tmp/worktrees/")  # 絶対パスを出さない


def test_fake_server_create_routes() -> None:
    """にせ物サーバ自身の確認: 起票 → state=empty の PR → 同じ requestId の再送は replay → 名前重複は 409。"""
    st = ReviewState()
    path = "/api/repos/r1a2b3c4d/features"
    body = {
        "name": "x",
        "requestId": "r1",
        "expect": {"target": "b" * 40},
        "brief": {"title": "t", "goal": "g"},
    }
    assert post_response(path, body, st)[0] == 403  # 既定では無効
    st.create_mode = "on"
    assert api_response("/api/capabilities", st)[1]["create"] is True
    code, res = post_response(path, body, st)
    assert code == 201 and res["feature"]["replay"] is False
    key = res["feature"]["prKey"]
    assert [p["state"] for p in api_response("/api/prs", st)[1]["prs"]][-1] == "empty"
    assert api_response(f"/api/prs/r1a2b3c4d/{key}/review", st)[1]["brief"]["title"] == "t"
    code, res = post_response(path, body, st)
    assert code == 200 and res["feature"]["replay"] is True
    assert post_response(path, {**body, "requestId": "r2"}, st)[1]["error"]["code"] == "name_used"
    assert post_response(path, {**body, "name": "y", "expect": {"target": "c" * 40}}, st)[0] == 409


def test_html_has_no_inline_code() -> None:
    assert scan((WEB / "index.html").read_text(encoding="utf-8"), HTML_RULES) == []


def test_css_is_safe() -> None:
    assert css_problems((WEB / "app.css").read_text(encoding="utf-8")) == []


def test_css_disables_ios_text_autosizing() -> None:
    """iOS Safari は横にはみ出す表の文字を自動で拡大するので、html の規則で止める。"""
    css = (WEB / "app.css").read_text(encoding="utf-8")
    m = re.search(r"(?m)^html\s*\{([^}]*)\}", css)
    assert m is not None, "html の規則が無い"
    body = m.group(1)
    assert "-webkit-text-size-adjust: 100%" in body
    assert re.search(r"(?<![-\w])text-size-adjust: 100%", body)


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
        self.review_gets: dict[str, int] = {}  # GET …/review の回数 (自動更新の試験用)
        self.fail_review = False  # True の間、GET …/review は 500 を返す
        self.last_expect: dict | None = None
        self.last_submit: dict | None = None
        self.submit_log: list[dict] = []  # 受け付けた submit の全件
        # --- 統合 (CHG-0062 段 A2) ---
        self.caps_mode = "off"  # off: merge=false / on: merge=true / 404: 古いサーバ
        self.plan_name = "merge_plan_ok.json"
        self.plan_for: dict[str, str] = {}  # key ごとの merge-plan の fixture
        self.plan_gate: dict[str, threading.Event] = {}  # セットされるまで merge-plan の応答を保留
        self.plan_calls: list[str] = []
        self.merge_mode = "ok"  # ok / ok_unrecorded / error / drop (応答を返さず切断)
        self.merge_error: tuple[int, str, str, dict] = (500, "internal", "", {})
        self.merge_gate: threading.Event | None = None  # セットされるまで merge の応答を保留
        self.merge_log: list[dict] = []
        self.merged_keys: set[str] = set()  # 統合済みにする key
        self.deleted: set[str] = set()  # 枝を消した key (詳細は 404)
        self.pr_gets: dict[str, int] = {}  # GET 詳細の回数 (キャッシュを捨てた確認用)
        # --- 起票 (CHG-0062 段 B1) ---
        self.create_mode = (
            "off"  # off: create=false / on: create=true（repos に targetOid を付ける）
        )
        self.create_resp = "ok"  # ok / error / drop (応答を返さず切断)
        self.create_error: tuple[int, str, str] = (500, "create_failed", "")
        self.create_gate: threading.Event | None = None  # セットされるまで POST の応答を保留
        self.create_log: list[dict] = []  # 届いた起票の本文の全件
        self.create_base = "b" * 40  # develop の現在の OID（変えると stale_view）
        self.taken: set[str] = {"taken"}  # 使用済みの名前
        self.created: dict[str, dict] = {}  # prKey → {pr, review, name, rid}

    def create_feature(self, payload: dict) -> tuple[int, dict]:
        """契約の POST /api/repos/<id>/features のにせ物。作った PR は state=empty で一覧に出る。"""
        self.create_log.append(payload)
        if self.create_gate is not None:
            self.create_gate.wait(10)
        if self.create_resp == "drop":
            raise DropConnection
        if self.create_resp == "error":
            status, code, msg = self.create_error
            return status, err_body(code, msg)
        if (payload.get("expect") or {}).get("target") != self.create_base:
            return 409, err_body("stale_view", "develop が更新されています。")
        name = payload["name"]
        key = "p" + hashlib.sha1(name.encode()).hexdigest()[:16]
        old = self.created.get(key)
        if old is not None and old["rid"] == payload["requestId"]:
            res = self._create_out(key, name)
            res["feature"]["replay"] = True
            return 200, res
        if old is not None or name in self.taken:
            return 409, err_body("name_used", "同じ名前の枝があります。")
        b = payload["brief"]
        pr = load_fixture("create_pr_empty.json")
        pr.update(prKey=key, id=f"r1a2b3c4d/{key}", branch=f"feature/{name}")
        rv = load_fixture("create_review_empty.json")
        rv["brief"].update(
            title=b["title"],
            goal=b["goal"],
            constraints=b.get("constraints", ""),
            scope=b.get("scope", []),
            acceptance=b.get("acceptance", ""),
        )
        self.created[key] = {"pr": pr, "review": rv, "name": name, "rid": payload["requestId"]}
        res = self._create_out(key, name)
        if (
            self.create_resp == "replay"
        ):  # 同じ依頼の再送として返す（応答を取り損なった後の表示の試験）
            res["feature"]["replay"] = True
            return 200, res
        return 201, res

    def _create_out(self, key: str, name: str) -> dict:
        res = load_fixture("create_ok.json")
        f = res["feature"]
        f.update(branch=f"feature/{name}", prKey=key, id=f"r1a2b3c4d/{key}")
        f["worktree"] = {"name": name, "rel": f".tmp/worktrees/{name}"}
        return res

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

    def pi_reply(self, key: str, thread_id: str, body: str) -> None:
        """pi がスレッドへ返信した (新しい comment と replied)。"""
        t = next(t for t in self.get(key)["threads"] if t["id"] == thread_id)
        self.seq += 1
        t["comments"].append(
            {
                "id": f"pi{self.seq}",
                "by": "pi",
                "at": "2099-02-02T00:00:00+00:00",
                "body": body,
                "anchor": None,
            }
        )
        t["status"] = "replied"

    def mark_received(self, key: str) -> None:
        """pi が送信を受け取った (batch が受領済み)。"""
        for b in self.get(key)["batches"]:
            b["received"] = True

    def mark_stale(self, key: str) -> None:
        """レビューの後に PR が進んだ (変更依頼 + 古いレビュー)。"""
        rv = self.get(key)
        rv["review"], rv["reviewStale"] = "changes", True

    def mark_merged(self, key: str) -> None:
        """PR が統合済みになった (書き込めなくなる)。"""
        self.get(key)["merged"] = True

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
        self.submit_log.append(payload)
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
    if state is not None and parts[3] in state.created:
        return state.created[parts[3]]["pr"]
    pr = next(
        (p for p in load_fixture("prs.json")["prs"] if p["id"] == f"{parts[2]}/{parts[3]}"), None
    )
    if pr is not None and state is not None and parts[3] in state.bumped:
        pr = {**pr, "sourceOid": BUMPED_OID}  # 更新後の版
    if pr is not None and state is not None:
        if parts[3] in state.deleted:
            return None
        if parts[3] in state.merged_keys:
            pr = {**pr, "state": "merged"}
    return pr


def api_response(path: str, state: ReviewState | None = None) -> tuple[int, dict]:
    """契約の GET エンドポイント（段 1 の 4 本 + review）を fixture から返す。"""
    state = state or ReviewState()
    u = urllib.parse.urlparse(path)
    parts = [p for p in u.path.split("/") if p]
    err = (404, {"error": {"code": "not_found", "message": "見つかりません。"}})
    if parts == ["api", "repos"]:
        if state.create_mode == "on":
            repos = load_fixture("create_repos.json")
            repos["repos"][0]["targetOid"] = state.create_base
            return 200, repos
        return 200, load_fixture("repos.json")
    if parts == ["api", "prs"]:
        prs = load_fixture("prs.json")
        prs["prs"] += [c["pr"] for c in state.created.values()]
        return 200, prs
    if parts == ["api", "capabilities"]:
        if state.caps_mode == "404":
            return err
        return 200, {
            **load_fixture("capabilities.json"),
            "merge": state.caps_mode == "on",
            "create": state.create_mode == "on",
        }
    if len(parts) in (4, 5) and parts[:2] == ["api", "prs"]:
        pr = find_pr(parts, state)
        if pr is None:
            return err
        made = state.created.get(parts[3])
        if len(parts) == 4:
            state.pr_gets[parts[3]] = state.pr_gets.get(parts[3], 0) + 1
            detail = load_fixture("create_detail_empty.json" if made else f"detail_{parts[3]}.json")
            return 200, {"pr": pr, **detail}
        if parts[4] == "review":
            state.review_gets[parts[3]] = state.review_gets.get(parts[3], 0) + 1
            if state.fail_review:
                return 500, err_body("internal", "内部エラー（試験）")
            if made:
                return 200, made["review"]
            return 200, state.view(parts[3])
        if parts[4] == "diff":
            q = urllib.parse.parse_qs(u.query)
            if "path" not in q:
                return 400, {
                    "error": {"code": "bad_request", "message": "指定が正しくありません。"}
                }
            return 200, load_fixture(f"diff_{parts[3]}.json")
    return err


class DropConnection(Exception):
    """応答を返さずに接続を切る (通信断の試験)。"""


CLEANUP_DONE = {"none": [], "branch": ["branch"], "branch_and_worktree": ["branch", "worktree"]}


def merge_post(parts: list[str], payload: dict, state: ReviewState, pr: dict) -> tuple[int, dict]:
    """契約 §2・§3 の merge-plan / merge の偽物。"""
    key = parts[3]
    if parts[4] == "merge-plan":
        state.plan_calls.append(key)
        gate = state.plan_gate.get(key)
        if gate is not None:
            gate.wait(10)
        return 200, load_fixture(state.plan_for.get(key) or state.plan_name)
    state.merge_log.append(payload)
    if state.merge_gate is not None:
        state.merge_gate.wait(10)
    if state.merge_mode == "drop":
        raise DropConnection
    if payload.get("expect") != {"source": pr["sourceOid"], "target": pr["targetOid"]}:
        return 409, err_body("stale_view", "表示中の版から PR が更新されています。")
    if state.merge_mode == "error":
        status, code, msg, extra = state.merge_error
        body = err_body(code, msg)
        body["error"].update(extra)
        return status, body
    res = load_fixture(
        "merge_unrecorded.json" if state.merge_mode == "ok_unrecorded" else "merge_ok.json"
    )
    cleanup = payload.get("cleanup", "none")
    res["merge"]["cleanup"] = {"requested": cleanup, "done": CLEANUP_DONE[cleanup]}
    state.merged_keys.add(key)
    if "branch" in CLEANUP_DONE[cleanup]:
        state.deleted.add(key)
    return 200, res


def post_response(path: str, payload: dict, state: ReviewState) -> tuple[int, dict]:
    parts = [p for p in urllib.parse.urlparse(path).path.split("/") if p]
    if len(parts) == 4 and parts[:2] == ["api", "repos"] and parts[3] == "features":
        if state.create_mode != "on":
            return 403, err_body("create_disabled", "起票できません。")
        return state.create_feature(payload)
    if len(parts) == 5 and parts[:2] == ["api", "prs"] and parts[4] in ("merge-plan", "merge"):
        pr = find_pr(parts, state)
        if pr is None:
            return 404, err_body("not_found", "見つかりません。")
        return merge_post(parts, payload, state, pr)
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
        try:
            code, data = post_response(self.path, payload, self.server.state)  # type: ignore[attr-defined]
        except DropConnection:
            self.close_connection = True  # 応答を返さずに切る
            return
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


def flow_approve_only(page, kind: str, base: str, state, check) -> None:
    """未送信 0 件でも「承認して送る…」から承認だけを 1 回で送れる。「レビューを送る…」の既定は変わらない。"""
    page.goto(f"{base}/#/pr/r1a2b3c4d/paaaaaaaaaaaaaaa1")
    page.wait_for_function(
        "() => document.querySelector('.revbar')?.innerText.includes('未送信 0 件')"
    )
    # 反例: 通常の入口は、これまでどおり「コメントのみ」で「送る」が無効
    page.locator(".revbar button", has_text="レビューを送る").click()
    page.wait_for_selector(".sheet")
    check(
        page.locator(".sheet button", has_text="送る").is_disabled(), f"{kind} 既定で「送る」が有効"
    )
    pressed = page.locator(".sheet .seg button[aria-pressed='true']").inner_text()
    check(pressed == "コメントのみ", f"{kind} 既定の種別が変わった: {pressed}")
    page.locator(".sheet button", has_text="閉じる").click()
    page.wait_for_selector(".sheet", state="detached")
    # 承認の入口
    btn = page.locator(".revbar button", has_text="承認して送る")
    check(btn.count() == 1, f"{kind} 「承認して送る…」が 1 つでない")
    w = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    check(w[0] <= w[1], f"{kind} 概要の固定バーで横にはみ出している {w}")
    btn.click()
    page.wait_for_selector(".sheet")
    pressed = page.locator(".sheet .seg button[aria-pressed='true']")
    check(pressed.count() == 1 and pressed.inner_text() == "承認", f"{kind} 承認が選ばれていない")
    send = page.locator(".sheet .cact button", has_text="送る")
    check(send.is_enabled(), f"{kind} 承認なのに「送る」が無効")
    before = len(state.submit_log)
    send.click()
    page.wait_for_selector(".sheet", state="detached")
    page.wait_for_selector(".revnotice")
    sent = state.submit_log[before:]
    check(len(sent) == 1, f"{kind} submit が 1 回でない: {len(sent)}")
    if sent:
        check(sent[0].get("kind") == "approve", f"{kind} kind が approve でない: {sent[0]}")
        check(bool(sent[0].get("expect")), f"{kind} expect が付いていない: {sent[0]}")


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


def flow_live(br, check) -> None:
    """画面の自動更新 (CHG-0061 S1)。Playwright の時計を止め、進める時間を試験が決める。"""
    srv, base = serve()
    st: ReviewState = srv.state  # type: ignore[attr-defined]
    ctx = br.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    # タブの見え方を試験から変えられるようにする
    page.add_init_script(
        "window.__vis = 'visible';"
        "Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => window.__vis});"
        "Object.defineProperty(document, 'hidden', {configurable: true, get: () => window.__vis !== 'visible'});"
    )

    def gets(key: str = LIVE_KEY) -> int:
        return st.review_gets.get(key, 0)

    def until(fn, what: str, timeout: float = 5.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if fn():
                return True
            time.sleep(0.05)
        check(False, f"live: 待ち切れない: {what}")
        return False

    def js(expr: str):
        return page.evaluate(expr)

    def vis(v: str) -> None:
        js(f"window.__vis = '{v}'; document.dispatchEvent(new Event('visibilitychange'))")

    def step(ms: int, expect_calls: int, what: str, key: str = LIVE_KEY) -> None:
        """時計を ms 進め、取り直しがちょうど expect_calls 回だけ増えることを確かめる。"""
        n = gets(key)
        page.clock.run_for(ms)
        if expect_calls:
            until(lambda: gets(key) >= n + expect_calls, what)
        time.sleep(0.25)  # 応答が処理されて次のタイマーが置かれるまで
        check(
            gets(key) == n + expect_calls,
            f"live: {what}: 取り直しが {gets(key) - n} 回 (期待 {expect_calls})",
        )

    def anchor() -> None:
        """時計を止めたまま、見える状態へ戻してすぐ 1 回取り直させる (この時刻から次の間隔を数える)。"""
        n = gets()
        vis("hidden")
        vis("visible")
        until(lambda: gets() >= n + 1, "anchor")
        time.sleep(0.25)

    page.clock.install(time=int(time.time() * 1000))
    page.goto(f"{base}/#/{'pr/' + LIVE_ID}")
    page.wait_for_selector(".revbar button")
    page.clock.pause_at(int(time.time() * 1000) + 5000)
    time.sleep(0.4)
    anchor()
    sel_general = ".card:has(h2:text-is('PR 全体のコメント (1)')) textarea"

    # 1. 状態が変わらないとき: 3 秒ごとに取り直すが、DOM は作り直されない
    js(
        "for (const s of ['#app textarea', '.prhead', '.revbar', '.thread', '.summary', '.live-batches li'])"
        " document.querySelector(s).setAttribute('data-mark', '1');"
    )
    step(POLL_MS - 1, 0, "3 秒の前は取り直さない")
    step(1, 1, "3 秒で 1 回")
    step(POLL_MS, 1, "続けて 3 秒で 1 回")
    check(
        js("document.querySelectorAll('[data-mark]').length") == 6,
        "live: 状態が同じのに DOM が作り直された",
    )

    # 2. 受領済みになる: 入力中の文字・フォーカス・カーソル位置が残る (反例)
    page.locator(sel_general).fill("入力中の文字です")
    js(
        "(() => { const t = document.querySelector('#app textarea'); t.focus(); t.setSelectionRange(2, 4); })()"
    )
    check("未受信" in page.inner_text(".live-batches"), "live: 前提: 最初は未受信")
    st.mark_received(LIVE_KEY)
    step(POLL_MS, 1, "受領済みを取り直す")
    until(lambda: "pi が受け取り済み" in page.inner_text(".live-batches"), "受領済みの表示")
    got = js(
        "(() => { const t = document.querySelector('#app textarea'); return [t.value, document.activeElement === t,"
        " t.selectionStart, t.selectionEnd, t.hasAttribute('data-mark')]; })()"
    )
    check(
        got == ["入力中の文字です", True, 2, 4, True],
        f"live: 受領済みの反映で入力欄が壊れた: {got}",
    )
    check(
        js(
            "!!document.querySelector('.revbar[data-mark]') && !!document.querySelector('.thread[data-mark]')"
        ),
        "live: 受領済みで固定バー・スレッドが作り直された",
    )

    # 3. pi の返信: 入力がある間はバナーだけ。押すと反映。入力が空なら自動で反映
    st.pi_reply(LIVE_KEY, "c3", "pi の返信です")
    step(POLL_MS, 1, "pi の返信を取り直す")
    banner = page.locator(".livebar button")
    until(banner.is_visible, "バナーが出る")
    check(
        "pi の返信です" not in page.inner_text(".threads"), "live: 入力中なのにスレッドが変わった"
    )
    check(
        js("document.querySelector('#app textarea').value") == "入力中の文字です",
        "live: バナーを出したとき入力が消えた",
    )
    banner.click()
    check("pi の返信です" in page.inner_text(".threads"), "live: バナーを押しても反映されない")
    check(not banner.is_visible(), "live: 反映後もバナーが残る")
    check(
        js("document.querySelector('#app textarea').value") == "入力中の文字です",
        "live: 反映したとき入力が消えた",
    )
    page.locator("#app textarea").first.fill("")
    st.pi_reply(LIVE_KEY, "c3", "空のときの返信")
    step(POLL_MS, 1, "入力が空のときの返信を取り直す")
    until(lambda: "空のときの返信" in page.inner_text(".threads"), "入力が空なら自動で反映")
    check(not banner.is_visible(), "live: 自動で反映したのにバナーが出ている")

    # 4. タブが見えない間は止まり、見える状態に戻るとすぐ 1 回
    vis("hidden")
    step(POLL_MS * 4, 0, "非表示の間は取り直さない")
    n = gets()
    vis("visible")
    until(lambda: gets() == n + 1, "見える状態に戻ったときにすぐ 1 回")
    time.sleep(0.25)
    check(gets() == n + 1, "live: 見える状態に戻った直後に 2 回以上取り直した")
    step(POLL_MS, 1, "戻った後は 3 秒間隔に戻る")

    # 7. 取り直しで PR が「進んだ (stale)」と分かっても、表示している版 (expect) は変えない
    st.mark_stale(LIVE_KEY)
    step(POLL_MS, 1, "stale の状態を取り直す")
    until(lambda: "古いレビュー" in page.inner_text(".prhead h1"), "stale のチップ")
    check("変更依頼" in page.inner_text(".revbar"), "live: 固定バーのチップが更新されない")
    pr = find_pr(["api", "prs", "r1a2b3c4d", LIVE_KEY]) or {}
    page.locator(".revbar button", has_text="レビューを送る").click()
    page.wait_for_selector(".sheet")
    page.locator(".sheet button", has_text="変更を依頼").click()
    page.locator(".sheet button", has_text="送る").click()
    page.wait_for_selector(".sheet", state="detached")
    until(lambda: st.last_expect is not None, "送信の expect")
    want = {"source": pr.get("sourceOid"), "target": pr.get("targetOid"), "base": pr.get("baseOid")}
    check(st.last_expect == want, f"live: 送信の expect が開いた版でない: {st.last_expect}")
    until(lambda: page.locator(".revnotice").count() == 1, "送信後の案内")
    time.sleep(0.25)

    # 6. 失敗: 間隔が 3 → 6 → 12 → 24 → 30 秒で頑打ち。成功で 3 秒に戻り、表示も消える
    note = page.locator(".livebar span")
    check(not note.is_visible(), "live: 失敗していないのに注意書きが出ている")
    st.fail_review = True
    anchor()  # この取り直しが 500 (1 回目の失敗)
    until(note.is_visible, "失敗の表示")
    check("更新できません" in note.inner_text(), "live: 失敗の表示が日本語でない")
    for wait_ms in (6000, 12000, 24000, 30000, 30000):
        step(wait_ms - 1, 0, f"失敗後の {wait_ms} ms の前は取り直さない")
        step(1, 1, f"失敗後の {wait_ms} ms で 1 回")
    check(note.is_visible(), "live: 失敗の間、表示が消えた")
    st.fail_review = False
    step(POLL_MAX_MS, 1, "上限 30 秒の次で成功する")
    until(lambda: not note.is_visible(), "成功で表示が消える")
    step(POLL_MS - 1, 0, "成功後は 3 秒間隔に戻る (前)")
    step(1, 1, "成功後は 3 秒間隔に戻る")

    # 5. 一覧へ戻る・別の PR へ移ると、旧ページの取り直しは止まる
    js("location.hash = '#/'")
    page.wait_for_selector(".prlist")
    time.sleep(0.6)
    step(POLL_MS * 5, 0, "一覧では取り直さない")
    vis("hidden")
    vis("visible")
    step(POLL_MS, 0, "一覧で見える状態に戻っても取り直さない")
    other = "p1111111111111111"
    js(f"location.hash = '#/pr/r1a2b3c4d/{other}'")
    page.wait_for_selector(".revbar")
    time.sleep(0.25)
    anchor_n = gets(other)
    step(POLL_MS, 1, "別の PR では、その PR を取り直す", other)
    check(gets(other) == anchor_n + 1, "live: 別の PR の取り直しが始まらない")
    old = gets()
    step(POLL_MS, 1, "別の PR の 2 回目", other)
    step(POLL_MS, 1, "別の PR の 3 回目", other)
    check(gets() == old, "live: 別の PR へ移ったのに旧の PR を取り直している")
    js("location.hash = '#/'")
    page.wait_for_selector(".prlist")
    time.sleep(0.6)  # 一覧はチップのために各 PR の review を一度読む (自動更新ではない)
    n_other = gets(other)
    n_old = gets()
    page.clock.run_for(POLL_MS * 5)
    time.sleep(0.4)
    check(gets(other) == n_other and gets() == n_old, "live: 一覧へ戻った後も取り直している")
    check(errs == [], f"live: ページのエラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_live_guards(br, check) -> None:
    """自動更新が、入力途中・開いた送信シート・開いた返信欄・書き込み可否の変化で画面を壊さない。

    flow_live の補強 (変異試験で見つかった穴)。
    """
    srv, base = serve()
    st: ReviewState = srv.state  # type: ignore[attr-defined]
    ctx = br.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    page.add_init_script(
        "window.__vis = 'visible';"
        "Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => window.__vis});"
        "Object.defineProperty(document, 'hidden', {configurable: true, get: () => window.__vis !== 'visible'});"
    )

    def gets() -> int:
        return st.review_gets.get(LIVE_KEY, 0)

    def until(fn, what: str, timeout: float = 5.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if fn():
                return True
            time.sleep(0.05)
        check(False, f"live-guards: 待ち切れない: {what}")
        return False

    def js(expr: str):
        return page.evaluate(expr)

    def vis(v: str) -> None:
        js(f"window.__vis = '{v}'; document.dispatchEvent(new Event('visibilitychange'))")

    def anchor() -> None:
        """時計を止めたまま、見える状態へ戻してすぐ 1 回取り直させる (この時刻から次の間隔を数える)。"""
        n = gets()
        vis("hidden")
        vis("visible")
        until(lambda: gets() >= n + 1, "anchor")
        time.sleep(0.25)

    def poll(what: str) -> None:
        """時計を 1 間隔進め、取り直しが 1 回増えるのを待つ。"""
        n = gets()
        page.clock.run_for(POLL_MS)
        until(lambda: gets() >= n + 1, what)
        time.sleep(0.25)

    page.clock.install(time=int(time.time() * 1000))
    page.goto(f"{base}/#/{'pr/' + LIVE_ID}")
    page.wait_for_selector(".revbar button")
    page.clock.pause_at(int(time.time() * 1000) + 5000)
    time.sleep(0.4)
    anchor()
    sel_general = ".card:has(h2:text-is('PR 全体のコメント (1)')) textarea"
    banner = page.locator(".livebar button")

    # A. 状態が変わらないときは、チップを含めて DOM を作り直さない (チップはレビューがあるときだけ出るので、先に変更依頼にする)
    st.mark_stale(LIVE_KEY)
    poll("変更依頼の状態を取り直す")
    until(
        lambda: (
            page.locator(".revchips > *").count() >= 1 and page.locator(".hchips > *").count() >= 1
        ),
        "チップが出る",
    )
    js(
        "document.querySelector('.revchips > *').setAttribute('data-mark', '1');"
        "document.querySelector('.hchips > *').setAttribute('data-mark', '1');"
    )
    poll("変化なしの取り直し 1")
    poll("変化なしの取り直し 2")
    check(
        js("document.querySelectorAll('[data-mark]').length") == 2,
        "live-guards: 状態が同じのにチップが作り直された",
    )

    # B. 送信シートが開いている間は、pi の返信でスレッドを差し替えない。閉じてバナーを押すと反映する
    page.locator(".revbar button", has_text="レビューを送る").click()
    page.wait_for_selector(".sheet")
    st.pi_reply(LIVE_KEY, "c3", "シート中の返信です")
    poll("シート中の返信を取り直す")
    until(banner.is_visible, "シート中はバナー")
    check(
        "シート中の返信です" not in page.inner_text(".threads"),
        "live-guards: 送信シートが開いているのにスレッドが変わった",
    )
    check(page.locator(".sheet").count() == 1, "live-guards: 取り直しで送信シートが閉じた")
    page.locator(".sheet button", has_text="閉じる").click()
    page.wait_for_selector(".sheet", state="detached")
    banner.click()
    check(
        "シート中の返信です" in page.inner_text(".threads"),
        "live-guards: バナーを押しても反映されない (シート)",
    )
    check(not banner.is_visible(), "live-guards: 反映後もバナーが残る (シート)")

    # C. 開いた返信欄がある間は、中身が空でもスレッドを差し替えない
    page.locator(".thread .reply button", has_text="返信").first.click()
    page.wait_for_selector(".thread textarea")
    st.pi_reply(LIVE_KEY, "c3", "返信欄中の返信です")
    poll("返信欄が開いている間の返信を取り直す")
    until(banner.is_visible, "返信欄が開いている間はバナー")
    check(
        "返信欄中の返信です" not in page.inner_text(".threads"),
        "live-guards: 返信欄が開いているのにスレッドが変わった",
    )
    check(
        page.locator(".thread textarea").count() == 1, "live-guards: 取り直しで開いた返信欄が消えた"
    )
    page.locator(".thread button", has_text="キャンセル").first.click()
    banner.click()
    check(
        "返信欄中の返信です" in page.inner_text(".threads"),
        "live-guards: バナーを押しても反映されない (返信欄)",
    )

    # D. 書き込めるかが変わっても (統合済みになる)、書きかけの欄がある間は全体を描き直さない
    page.locator(sel_general).fill("書きかけの文です")
    st.mark_merged(LIVE_KEY)
    poll("統合済みの状態を取り直す")
    until(banner.is_visible, "書き込み可否が変わるとバナー")
    kept = js("(document.querySelector('#app textarea') || {}).value")
    check(
        kept == "書きかけの文です", f"live-guards: 書き込み可否の変化で書きかけが消えた: {kept!r}"
    )
    page.locator(sel_general).fill("")
    banner.click()
    until(
        lambda: page.locator("#app textarea").count() == 0,
        "バナーを押すと書き込めない画面に描き直される",
    )
    check(
        "統合済みの PR には書き込めません" in page.inner_text(".revbar"),
        "live-guards: 統合済みの表示にならない",
    )
    check(errs == [], f"live-guards: ページのエラー: {errs}")
    ctx.close()
    srv.shutdown()


# --- 統合の承認シート (CHG-0062 段 A2) ---

HOSTILE = '<img src=x onerror="window.__pwned=1">'
KEY_A = "paaaaaaaaaaaaaaa1"
ID_A = f"r1a2b3c4d/{KEY_A}"
KEY_B = "p2222222222222222"
RECOVER_LINES = (
    "他の git・エディターの自動保存・ビルドが動いていないことを確かめる",
    "node apps/pr-viewer/merge-cli.ts recover <リポジトリのパス>",
    "画面を再読み込みする",
)
UNKNOWN = "結果を確認できません。再読み込みして PR の状態を確認してください。"
CHECK_TREE = "統合先の作業ツリーを確認してください"
# (code, HTTP, 画面に出る文言, 再試行できるか, 応答に足す項目)
MERGE_ERRORS: list[tuple[str, int, tuple[str, ...], bool, dict]] = [
    ("merge_disabled", 403, ("この画面からは統合できません",), False, {}),
    ("forbidden_origin", 403, ("この画面からは統合できません",), False, {}),
    ("bad_message", 400, ("入力に誤りがあります",), True, {}),
    ("not_found", 404, ("PR が見つかりません", "一覧へ"), False, {}),
    ("no_target", 404, ("PR が見つかりません",), False, {}),
    ("policy_target", 403, ("統合できない PR です",), False, {}),
    ("stale_view", 409, ("最新の版を読み込む",), False, {}),
    ("not_ff", 409, ("最新の版を読み込む",), False, {}),
    ("already_merged", 409, (CHECK_TREE,), False, {}),
    ("dirty", 409, (CHECK_TREE,), True, {}),
    ("head_mismatch", 409, (CHECK_TREE,), True, {}),
    ("no_identity", 409, (CHECK_TREE,), True, {}),
    (
        "conflict",
        409,
        ("衝突の解消は pi で行ってください", "conflict-a.txt", HOSTILE + ".txt"),
        False,
        {"conflicts": ["conflict-a.txt", HOSTILE + ".txt"]},
    ),
    ("busy", 409, ("しばらくして再試行してください",), True, {}),
    ("legacy_pending", 409, (), False, {}),
    ("too_large", 413, ("本文が大きすぎます",), True, {}),
]
UNCERTAIN = [("merge_failed", 500), ("internal", 500)]


def merge_page(br, kind: str = "pc"):
    """統合の試験用のサーバとページ。capabilities は merge=true。"""
    srv, base = serve()
    st: ReviewState = srv.state  # type: ignore[attr-defined]
    st.caps_mode = "on"
    sp = kind == "sp"
    size = {"width": 393, "height": 852} if sp else {"width": 1280, "height": 900}
    ctx = br.new_context(viewport=size, has_touch=sp, is_mobile=sp, color_scheme="light")
    page = ctx.new_page()
    errs: list[str] = []
    page.on("pageerror", lambda e, errs=errs: errs.append(f"pageerror: {e}"))
    page.on(
        "request",
        lambda r, errs=errs, base=base: (
            errs.append(f"外部通信: {r.url}") if not r.url.startswith((base, "data:")) else None
        ),
    )
    return srv, base, st, ctx, page, errs


def merge_open(page, base: str, key: str = KEY_A, bar: bool = False) -> None:
    """PR の概要を開き、「統合する…」でシートを開いて計画の表示を待つ。"""
    page.goto(f"{base}/#/pr/r1a2b3c4d/{key}")
    page.wait_for_selector(".revbar")
    page.locator(".mergebar button" if bar else ".mergecard button").click()
    page.wait_for_selector(".mergesheet .mergenext")


def merge_confirm(page) -> None:
    """手順 1 → 手順 2 (最終確認) へ進む。"""
    page.locator(".mergesheet .mergenext").click()
    page.wait_for_selector(".mergesheet input[type=checkbox]")


def merge_go(page) -> None:
    """チェックを入れて「統合する」を押す。"""
    page.locator(".mergesheet input[type=checkbox]").check()
    page.locator(".mergesheet .mergego").click()


def waitfor(cond, what: str, check, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    check(False, f"merge: 待ち切れない: {what}")
    return False


def flow_merge_caps(br, check) -> None:
    """capabilities: merge=false・404 (古いサーバ)・統合済みの PR ではボタンを出さない。"""
    srv, base, st, ctx, page, errs = merge_page(br)
    both = ".mergecard button, .mergebar button"
    for mode in ("off", "404"):
        st.caps_mode = mode
        page.goto(f"{base}/#/pr/r1a2b3c4d/{KEY_A}")
        page.reload()
        page.wait_for_selector(".revbar")
        check(page.locator(both).count() == 0, f"merge-caps: caps={mode} でボタンがある")
        check(
            page.locator(".revbar button", has_text="承認して送る").count() == 1,
            f"merge-caps: caps={mode} で既存のボタンが無い",
        )
    st.caps_mode = "on"
    page.reload()
    page.wait_for_selector(".revbar")
    check(
        page.locator(".mergecard button").count() == 1,
        "merge-caps: caps=on でカードのボタンが 1 つでない",
    )
    check(
        page.locator(".revbar button", has_text="承認して送る").count() == 1,
        "merge-caps: 「承認して送る…」が消えた",
    )
    page.goto(f"{base}/#/pr/r1a2b3c4d/p1111111111111111")  # 統合済み
    page.wait_for_selector("text=変更ファイル (1)")
    check(page.locator(both).count() == 0, "merge-caps: 統合済みの PR にボタンがある")
    check(errs == [], f"merge-caps: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_merge_steps(br, check) -> None:
    """手順 1・2、承認 snapshot、成功後の一覧への遷移。背景のフォーカス・キー操作。"""
    srv, base, st, ctx, page, errs = merge_page(br)
    merge_open(page, base)
    sheet = page.locator(".mergesheet")
    check(sheet.get_attribute("role") == "dialog", "merge: role=dialog でない")
    check(sheet.get_attribute("aria-modal") == "true", "merge: aria-modal でない")
    t = sheet.inner_text()
    full = sheet.text_content() or ""  # 折りたたみの中身も含む
    for s in (
        "統合できます",
        "feature/example",
        "develop",
        "aaaaaaa",
        "bbbbbbb",
        "コミット 3 件",
        "ファイル 12 件",
        "+120",
        "−8",
        "AGENTS.md",
        "変更依頼のままです。",
        "レビュー記録の下書き",
        "残す",
        "枝を削除",
        "枝と作業ツリーを削除",
        "未コミットがあれば残します",
    ):
        check(s in full, f"merge: 手順 1 に {s!r} が無い")
    for s in ("docs/index.md", "ほか 10 件", "a" * 40, "b" * 40):
        check(s in full, f"merge: 手順 1 (展開内) に {s!r} が無い")
    check("リスク設定を読み込めません" not in t, "merge: 設定を読めているのに警告が出る")
    ta = page.locator(".mergesheet textarea")
    default_msg = load_fixture("merge_plan_ok.json")["defaults"]["message"]
    check(ta.input_value() == default_msg, "merge: メッセージの既定値が違う")
    pressed = page.locator(".mergesheet .seg button[aria-pressed='true']").all_inner_texts()
    check(
        len(pressed) == 1 and pressed[0].endswith("残す"),
        f"merge: cleanup の既定が「残す」でない: {pressed}",
    )
    check(page.locator(".mergesheet form").count() == 0, "merge: form 要素がある")
    # 背景: #app は操作できない。Tab はシートの外へ出ない
    check(
        page.evaluate("document.getElementById('app').inert") is True,
        "merge: シート中も背景が操作できる",
    )
    outside = 0
    for _ in range(30):
        page.keyboard.press("Tab")
        if not page.evaluate("!!document.activeElement.closest('.mergesheet')"):
            outside += 1
    check(outside == 0, f"merge: Tab でシートの外へフォーカスが出た ({outside} 回)")
    # Esc で閉じ、開いたボタンへフォーカスが戻る。背景のタップでも閉じる (実行中でないとき)
    page.keyboard.press("Escape")
    page.wait_for_selector(".mergesheet", state="detached")
    check(
        page.evaluate("document.getElementById('app').inert") is False,
        "merge: 閉じた後も背景が inert",
    )
    check(
        page.evaluate("!!document.activeElement.closest('.mergecard')"),
        "merge: 閉じた後にフォーカスがボタンへ戻らない",
    )
    page.locator(".mergecard button").click()
    page.wait_for_selector(".mergesheet .mergenext")
    page.mouse.click(5, 5)
    page.wait_for_selector(".mergesheet", state="detached")
    # 手順 1 を編集 → 手順 2
    page.locator(".mergecard button").click()
    page.wait_for_selector(".mergesheet .mergenext")
    msg = "feat: 編集した件名\n\n本文の一行\n二行目\n三行目\n四行目"
    page.locator(".mergesheet textarea").fill(msg)
    page.locator(".mergesheet .seg button", has_text="枝を削除").first.click()
    merge_confirm(page)
    t = page.locator(".mergesheet").inner_text()
    for s in (
        "feature/example（aaaaaaa）を develop（bbbbbbb）へ merge commit で統合します",
        "feat: 編集した件名",
        "本文の一行",
        "本文の一行",
        "この内容で develop を更新することを確認しました",
        "枝",
    ):
        check(s in t, f"merge: 手順 2 に {s!r} が無い")
    check("二行目" not in t, "merge: 手順 2 のメッセージが先頭 3 行でない")
    check(page.locator(".mergesheet textarea").count() == 0, "merge: 手順 2 に編集欄がある")
    go = page.locator(".mergesheet .mergego")
    cb = page.locator(".mergesheet input[type=checkbox]")
    check(go.is_disabled(), "merge: 確認前に「統合する」が有効")
    cb.check()
    check(go.is_enabled(), "merge: 確認後も「統合する」が無効")
    cb.uncheck()
    check(go.is_disabled(), "merge: チェックを外したのに「統合する」が有効")
    cb.check()
    gb = page.locator(".mergesheet .mergebackbtn").bounding_box()
    gg = go.bounding_box()
    check(
        gb is not None and gg is not None and abs(gb["y"] - gg["y"]) + abs(gb["x"] - gg["x"]) > 40,
        f"merge: 「戻る」が「統合する」の近くにある {gb} {gg}",
    )
    # 「戻る」でチェックを外す。編集内容と cleanup は残る
    page.locator(".mergesheet .mergebackbtn").click()
    page.wait_for_selector(".mergesheet textarea")
    check(
        page.locator(".mergesheet textarea").input_value() == msg, "merge: 戻ったとき編集を失った"
    )
    still = page.locator(".mergesheet .seg button[aria-pressed='true']").inner_text()
    check(still.endswith("枝を削除"), f"merge: 戻ったとき cleanup を失った: {still}")
    merge_confirm(page)
    check(
        not page.locator(".mergesheet input[type=checkbox]").is_checked(),
        "merge: 戻った後にチェックが残る",
    )
    check(page.locator(".mergesheet .mergego").is_disabled(), "merge: 戻った後に「統合する」が有効")
    # 計画の取り直しもチェックを外す (手順 1 へ戻ってから)
    page.locator(".mergesheet .mergebackbtn").click()
    n = len(st.plan_calls)
    page.locator(".mergesheet", has_text="計画を取り直す").locator(
        "button", has_text="計画を取り直す"
    ).click()
    waitfor(lambda: len(st.plan_calls) == n + 1, "計画の取り直し", check)
    page.wait_for_selector(".mergesheet .mergenext:not([disabled])")
    check(
        page.locator(".mergesheet textarea").input_value() == msg,
        "merge: 計画の取り直しで編集を失った",
    )
    merge_confirm(page)
    merge_go(page)
    page.wait_for_selector(".mergesheet .mergeresult")
    want = {"expect": {"source": "a" * 40, "target": "b" * 40}, "message": msg, "cleanup": "branch"}
    check(st.merge_log == [want], f"merge: 送信内容が snapshot と違う: {st.merge_log}")
    t = page.locator(".mergesheet").inner_text()
    for s in (
        "統合しました",
        "fffffff",
        "後始末: branch を実行しました",
        "作業ツリーの削除は未コミットがあるため見送りました",
    ):
        check(s in t, f"merge: 成功の表示に {s!r} が無い")
    check("画面用の記録は保存できませんでした" not in t, "merge: recorded=true で記録失敗の表示")
    # 枝を消したときは一覧へ (詳細は 404 になる)
    before = st.pr_gets.get(KEY_A, 0)
    page.locator(".mergesheet button", has_text="一覧へ").click()
    page.wait_for_selector(".prlist")
    check(page.evaluate("location.hash") == "#/", "merge: 一覧へ遷移しない")
    check(page.locator(".mergesheet").count() == 0, "merge: 一覧にシートが残る")
    check(st.pr_gets.get(KEY_A, 0) == before, "merge: 枝を消したのに詳細を取り直した")
    check(len(st.merge_log) == 1, f"merge: POST が 1 回でない: {len(st.merge_log)}")
    check(errs == [], f"merge: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_merge_keep(br, check) -> None:
    """枝を残すときは PR 本体のキャッシュを捨てて取り直す。recorded:false の表示。"""
    srv, base, st, ctx, page, errs = merge_page(br)
    st.merge_mode = "ok_unrecorded"
    merge_open(page, base)
    merge_confirm(page)
    merge_go(page)
    page.wait_for_selector(".mergesheet .mergeresult")
    t = page.locator(".mergesheet").inner_text()
    check("統合は成功しました" in t, "merge: recorded=false で「統合は成功」と出ない")
    check("画面用の記録は保存できませんでした" in t, "merge: recorded=false の表示が無い")
    check(st.merge_log[0]["cleanup"] == "none", "merge: 既定の cleanup が none でない")
    before = st.pr_gets.get(KEY_A, 0)
    page.locator(".mergesheet button", has_text="最新の状態を読み込む").click()
    page.wait_for_selector(".prhead .chip:has-text('統合済み')")
    check(st.pr_gets.get(KEY_A, 0) > before, "merge: PR 本体を取り直さない (古いキャッシュ)")
    check(page.locator(".mergesheet").count() == 0, "merge: 取り直し後にシートが残る")
    check(
        page.locator(".mergecard button, .mergebar button").count() == 0,
        "merge: 統合済みなのにボタンがある",
    )
    check(errs == [], f"merge: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_merge_running(br, check) -> None:
    """実行中: 二重押下でも POST は 1 回。入力をすべて無効にし、背景・Esc・自動更新で消えない。"""
    srv, base, st, ctx, page, errs = merge_page(br)
    st.merge_gate = threading.Event()
    merge_open(page, base)
    merge_confirm(page)
    page.locator(".mergesheet input[type=checkbox]").check()
    page.locator(".mergesheet .mergego").click()
    page.evaluate(
        "(() => { const b = document.querySelector('.mergesheet .mergego'); if (b) { b.click(); b.click(); } })()"
    )
    waitfor(lambda: len(st.merge_log) >= 1, "merge の受信", check)
    time.sleep(0.3)
    check(len(st.merge_log) == 1, f"merge: 二重押下で POST が {len(st.merge_log)} 回")
    t = page.locator(".mergesheet").inner_text()
    check("統合中…（画面を閉じても処理は続きます）" in t, f"merge: 実行中の表示が無い: {t!r}")
    alld = page.evaluate(
        "[...document.querySelectorAll('.mergesheet button, .mergesheet input, .mergesheet textarea, .mergesheet select')]"
        ".every(e => e.disabled)"
    )
    check(alld is True, "merge: 実行中に無効でない入力がある")
    page.keyboard.press("Escape")
    page.mouse.click(5, 5)
    page.mouse.click(5, 5)
    check(page.locator(".mergesheet").count() == 1, "merge: 実行中に Esc / 背景のタップで閉じた")
    # 自動更新 (3 秒間隔) で pi の返信を取りなおしても、シートを消さず、スレッドを差し替えない
    st.pi_reply(KEY_A, "c3", "実行中の返信です")
    waitfor(lambda: page.locator(".livebar button").is_visible(), "バナー", check, timeout=9.0)
    check(page.locator(".mergesheet").count() == 1, "merge: 自動更新でシートが消えた")
    check(
        "実行中の返信です" not in page.locator(".threads").inner_text(),
        "merge: 実行中に画面が再描画された",
    )
    check(
        "統合中" in page.locator(".mergesheet").inner_text(),
        "merge: 自動更新で実行中の表示が消えた",
    )
    st.merge_gate.set()
    page.wait_for_selector(".mergesheet .mergeresult")
    check(len(st.merge_log) == 1, f"merge: POST が 1 回でない: {len(st.merge_log)}")
    check(errs == [], f"merge: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_merge_errors(br, check) -> None:
    """エラー表のとおりに表示する。通信断・merge_failed・internal は成功とも失敗とも決め付けない。"""
    srv, base, st, ctx, page, errs = merge_page(br)
    merge_open(page, base)
    page.locator(".mergesheet .mergeclose").click()
    page.wait_for_selector(".mergesheet", state="detached")
    cases: list[tuple] = [(c, s, w, r, x, HOSTILE) for c, s, w, r, x in MERGE_ERRORS]
    cases.append(("recover_needed", 409, RECOVER_LINES, False, {}, "/home/example/secret-repo"))
    for code, status, wants, retry, extra, message in cases:
        st.merge_mode, st.merge_error = "error", (status, code, message, extra)
        page.locator(".mergecard button").click()
        page.wait_for_selector(".mergesheet .mergenext")
        merge_confirm(page)
        merge_go(page)
        page.wait_for_selector(".mergesheet .formerr:not(:empty)")
        err = page.locator(".mergesheet .formerr").inner_text()
        for s in wants:
            check(s in err, f"merge: {code} の表示に {s!r} が無い: {err!r}")
        if code == "recover_needed":
            check(
                message not in page.locator(".mergesheet").inner_text(),
                "merge: recover_needed で実パスを出した",
            )
            check(
                page.locator(".mergesheet .formerr li").count() == 3,
                "merge: recover_needed の手順が 3 行でない",
            )
        else:
            check(
                message in err,
                f"merge: {code} のサーバの message を文字として出していない: {err!r}",
            )
        check(page.locator(".mergesheet img").count() == 0, f"merge: {code} で img 要素ができた")
        check(page.evaluate("window.__pwned === undefined"), f"merge: {code} で文字列が実行された")
        if code in ("stale_view", "not_ff"):
            check(
                page.locator(".mergesheet button", has_text="最新の版を読み込む").count() == 1,
                f"merge: {code} で取り直しボタンが無い",
            )
        cb = page.locator(".mergesheet input[type=checkbox]")
        go = page.locator(".mergesheet .mergego")
        check(not cb.is_checked(), f"merge: {code} の後もチェックが残る")
        check(go.is_disabled(), f"merge: {code} の後、チェックなしで「統合する」が有効")
        if retry:
            cb.check()
            check(go.is_enabled(), f"merge: {code} (再試行可) なのに先へ進めない")
        else:
            check(cb.is_disabled(), f"merge: {code} (再試行不可) なのにチェックできる")
        page.locator(".mergesheet .mergeclose").click()
        page.wait_for_selector(".mergesheet", state="detached")
    # 通信断・merge_failed・internal: 成功とも失敗とも決め付けず、再読み込みを案内する
    for code, status in [*UNCERTAIN, ("drop", 0)]:
        if code == "drop":
            st.merge_mode = "drop"
        else:
            st.merge_mode, st.merge_error = "error", (status, code, HOSTILE, {})
        page.locator(".mergecard button").click()
        page.wait_for_selector(".mergesheet .mergenext")
        merge_confirm(page)
        merge_go(page)
        page.wait_for_selector(".mergesheet .formerr:not(:empty)")
        t = page.locator(".mergesheet").inner_text()
        check(UNKNOWN in t, f"merge: {code} の案内が無い: {t!r}")
        check("失敗" not in t and "成功" not in t, f"merge: {code} で成功・失敗を決め付けた: {t!r}")
        check(
            page.locator(".mergesheet button", has_text="再読み込み").count() == 1,
            f"merge: {code} で再読み込みボタンが無い",
        )
        check(
            page.locator(".mergesheet .mergego").is_disabled(), f"merge: {code} の後でも再送できる"
        )
        check(page.locator(".mergesheet img").count() == 0, f"merge: {code} で img 要素ができた")
        page.locator(".mergesheet .mergeclose").click()
        page.wait_for_selector(".mergesheet", state="detached")
    # 再読み込みボタン: PR を取り直す
    st.merge_mode = "drop"
    page.locator(".mergecard button").click()
    page.wait_for_selector(".mergesheet .mergenext")
    merge_confirm(page)
    merge_go(page)
    page.wait_for_selector(".mergesheet .formerr:not(:empty)")
    before = st.pr_gets.get(KEY_A, 0)
    page.locator(".mergesheet button", has_text="再読み込み").click()
    page.wait_for_selector(".mergesheet", state="detached")
    waitfor(lambda: st.pr_gets.get(KEY_A, 0) > before, "PR の取り直し", check)
    check(errs == [], f"merge: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_merge_plans(br, check) -> None:
    """計画の応答の分岐: 衝突・blockers・リスク設定なし・敵対的な文字列・メッセージの検査。"""
    srv, base, st, ctx, page, errs = merge_page(br)
    sheet = ".mergesheet"

    def reopen(name: str, key: str = KEY_A) -> str:
        st.plan_for[key] = name
        merge_open(page, base, key)
        return page.locator(sheet).text_content() or ""

    def close() -> None:
        page.locator(".mergesheet .mergeclose").click()
        page.wait_for_selector(sheet, state="detached")

    nxt = page.locator(".mergesheet .mergenext")
    t = reopen("merge_plan_conflict.json")
    for s in (
        "統合できません",
        "統合先と衝突しています。",
        "a.txt",
        HOSTILE + ".txt",
        "衝突の解消は pi で行ってください",
    ):
        check(s in t, f"merge-plans: 衝突の表示に {s!r} が無い")
    check(nxt.is_disabled(), "merge-plans: 衝突で「確認へ」が有効")
    check(
        page.locator(".mergesheet img").count() == 0, "merge-plans: 衝突のパスで img 要素ができた"
    )
    close()
    t = reopen("merge_plan_blocked.json")
    for s in (
        "旧方式の承認待ちが残っています（試験）。",
        "旧方式の排他ロックが残っています（試験）。",
        "統合を進められません",
    ):
        check(s in t, f"merge-plans: blockers の表示に {s!r} が無い")
    check(nxt.is_disabled(), "merge-plans: blockers で「確認へ」が有効")
    close()
    t = reopen("merge_plan_riskcfg.json")
    for s in (
        "リスク設定を読み込めません",
        "アプリ自身を変更します。統合後に再起動してください",
        "古い版の下書き",
    ):
        check(s in t, f"merge-plans: 設定なしの表示に {s!r} が無い")
    check(
        "リスクのあるパスはありません" not in t, "merge-plans: 設定を読めないのにリスクなしと表示"
    )
    check(nxt.is_enabled(), "merge-plans: 「確認へ」が無効")
    close()
    t = reopen("merge_plan_hostile.json", KEY_B)
    for s in (
        "feature/" + HOSTILE,
        "<script>window.__pwned=1</script>.ts",
        "<b>AGENTS.md</b>",
        HOSTILE,
        "ほかにもあります",
    ):
        check(s in t, f"merge-plans: 敵対的な文字列 {s!r} が文字として出ていない")
    check(
        HOSTILE in page.locator(".mergesheet textarea").input_value(),
        "merge-plans: 既定のメッセージが文字として入っていない",
    )
    check(
        page.locator(".mergesheet img, .mergesheet script, .mergesheet b, .mergesheet i").count()
        == 0,
        "merge-plans: シートに敵対的な文字列から要素ができた",
    )
    check(page.evaluate("window.__pwned === undefined"), "merge-plans: 敵対的な文字列が実行された")
    merge_confirm(page)
    check(
        page.locator(".mergesheet img, .mergesheet script").count() == 0
        and HOSTILE in page.locator(sheet).inner_text(),
        "merge-plans: 手順 2 で敵対的な文字列が文字でない",
    )
    check(page.evaluate("window.__pwned === undefined"), "merge-plans: 手順 2 で実行された")
    close()
    # メッセージの検査 (契約 §3): 1、4000 文字、1 行目が空白だけは不可、制御・双方向制御文字は不可
    reopen("merge_plan_ok.json")
    ta = page.locator(".mergesheet textarea")
    for label, value, ok in (
        ("空", "", False),
        ("1 行目が空白", "  \n本文", False),
        ("4001 文字", "x" * 4001, False),
        ("4000 文字", "x" * 4000, True),
        ("双方向制御", "a\u202eb", False),
        ("制御文字", "a\u0007b", False),
        ("普通", "feat: 例\n\n本文\tタブ", True),
    ):
        ta.fill(value)
        check(
            nxt.is_enabled() == ok,
            f"merge-plans: メッセージ ({label}) で「確認へ」の有効状態が違う",
        )
    ta.fill("x" * 4001)
    check("4000" in page.locator(sheet).inner_text(), "merge-plans: 文字数の上限の案内が無い")
    ta.fill("計画の取り直しで残る編集")
    st.plan_for[KEY_A] = "merge_plan_riskcfg.json"
    page.locator(".mergesheet button", has_text="計画を取り直す").click()
    page.wait_for_function(
        "() => document.querySelector('.mergesheet').textContent.includes('リスク設定を読み込めません')"
    )
    check(
        page.locator(".mergesheet textarea").input_value() == "計画の取り直しで残る編集",
        "merge-plans: 取り直しで編集を失った",
    )
    check(errs == [], f"merge-plans: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_merge_slow_plan(br, check) -> None:
    """遅い merge-plan の応答が、別の PR のシートや閉じた後のシートへ反映されない。"""
    srv, base, st, ctx, page, errs = merge_page(br)
    st.plan_for = {KEY_A: "merge_plan_ok.json", KEY_B: "merge_plan_hostile.json"}
    gate_a = threading.Event()
    st.plan_gate[KEY_A] = gate_a
    page.goto(f"{base}/#/pr/r1a2b3c4d/{KEY_A}")
    page.wait_for_selector(".revbar")
    page.locator(".mergecard button").click()
    waitfor(lambda: KEY_A in st.plan_calls, "A の計画", check)
    check("確認中" in page.locator(".mergesheet").inner_text(), "merge-slow: 計画の待ち表示が無い")
    page.locator(".mergesheet .mergeclose").click()  # 計画を待つ間も閉じられる
    page.wait_for_selector(".mergesheet", state="detached")
    page.goto(f"{base}/#/pr/r1a2b3c4d/{KEY_B}")
    page.wait_for_function(
        "() => document.querySelector('.prhead h1')?.textContent.includes('onerror')"
    )
    page.locator(".mergecard button").click()
    page.wait_for_selector(".mergesheet .mergenext")
    gate_a.set()  # A の遅い応答が B のシートを開いている間に届く
    time.sleep(0.8)
    t = page.locator(".mergesheet").text_content() or ""
    check("feature/example" not in t, "merge-slow: 別の PR の計画がシートへ反映された")
    check("feature/" + HOSTILE in t, "merge-slow: 開いている PR の計画が消えた")
    page.locator(".mergesheet .mergeclose").click()
    page.wait_for_selector(".mergesheet", state="detached")
    gate_b = threading.Event()
    st.plan_gate[KEY_B] = gate_b
    page.locator(".mergecard button").click()
    waitfor(lambda: st.plan_calls.count(KEY_B) == 2, "B の 2 回目の計画", check)
    page.locator(".mergesheet .mergeclose").click()
    page.wait_for_selector(".mergesheet", state="detached")
    gate_b.set()  # 閉じた後に応答が届く
    time.sleep(0.8)
    check(
        page.locator(".mergesheet, .backdrop").count() == 0,
        "merge-slow: 閉じた後のシートが応答でよみがえった",
    )
    check(
        page.evaluate("document.getElementById('app').inert") is False,
        "merge-slow: 閉じた後に背景が inert",
    )
    check(errs == [], f"merge-slow: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_merge_stale(br, check) -> None:
    """確認後に PR が更新された: 確認した版 (snapshot) を送り、拒否されて取り直せる。"""
    srv, base, st, ctx, page, errs = merge_page(br)
    merge_open(page, base)
    merge_confirm(page)
    page.locator(".mergesheet input[type=checkbox]").check()
    st.bumped.add(KEY_A)
    page.locator(".mergesheet .mergego").click()
    page.wait_for_selector(".mergesheet .formerr:not(:empty)")
    check(
        len(st.merge_log) == 1
        and st.merge_log[0]["expect"] == {"source": "a" * 40, "target": "b" * 40},
        f"merge-stale: 確認した版を送っていない: {st.merge_log}",
    )
    check(len(st.merged_keys) == 0, "merge-stale: 古い版で統合された")
    page.locator(".mergesheet button", has_text="最新の版を読み込む").click()
    page.wait_for_selector(".mergesheet", state="detached")
    page.wait_for_selector(f"text={BUMPED_OID[:7]}")
    check(errs == [], f"merge-stale: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_merge_sp(br, check) -> None:
    """スマホ: 固定バーから開き、タップ領域は 44px 以上。横にはみ出さない。"""
    srv, base, _st, ctx, page, errs = merge_page(br, "sp")
    page.goto(f"{base}/#/pr/r1a2b3c4d/{KEY_A}")
    page.wait_for_selector(".revbar")
    check(page.locator(".mergebar").is_visible(), "merge-sp: 固定バーが見えない")
    check(page.locator(".mergecard").is_visible(), "merge-sp: カードが見えない")
    page.locator(".mergebar button").click()
    page.wait_for_selector(".mergesheet .mergenext")
    small = page.evaluate(
        "[...document.querySelectorAll('.mergesheet button, .mergesheet input[type=checkbox], .mergesheet summary')]"
        ".filter(e => e.getBoundingClientRect().width > 0 && e.getBoundingClientRect().height < 43.5)"
        ".map(e => e.textContent.trim() + ':' + e.getBoundingClientRect().height)"
    )
    check(small == [], f"merge-sp: タップ領域が 44px 未満: {small}")
    merge_confirm(page)
    small = page.evaluate(
        "[...document.querySelectorAll('.mergesheet button, .mergesheet label')]"
        ".filter(e => e.getBoundingClientRect().width > 0 && e.getBoundingClientRect().height < 43.5)"
        ".map(e => e.textContent.trim() + ':' + e.getBoundingClientRect().height)"
    )
    check(small == [], f"merge-sp: 手順 2 のタップ領域が 44px 未満: {small}")
    w = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    check(w[0] <= w[1], f"merge-sp: 横にはみ出している {w}")
    check(errs == [], f"merge-sp: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_merge_real(br, check) -> None:
    """実サーバ（--allow-merge）+ 実画面: 計画 → 確認 → 統合 → 結果 → 統合済みの表示まで通す。

    ほかの flow は契約から作った偽サーバで動くので、実サーバとの形のずれ・Origin / Host の食い違い
    （画面の fetch がブラウザの付ける Origin で通るか）は、ここで初めて見える。
    """
    import tempfile

    from test_pr_viewer_server import Server, _commit, _git, _init

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        repo = _init(root / "example-app")
        for key, value in (
            ("user.name", "Example Dev"),
            ("user.email", "you@example.com"),
            ("gc.auto", "0"),
            ("maintenance.auto", "false"),
        ):
            _git(repo, "config", key, value)
        _commit(repo, {"README.md": "hello\n"}, "init")
        _git(repo, "switch", "-q", "-c", "feature/real")
        _commit(repo, {"docs/real.md": "実サーバ\n"}, "feat: 実サーバで統合する")
        _git(repo, "switch", "-q", "develop")
        before = _git(repo, "rev-parse", "develop").strip()
        server = Server(
            [
                "--repo",
                str(repo),
                "--port",
                "0",
                "--allow-merge",
                "--rules-file",
                str(root / "rules.json"),
            ]
        )
        ctx = None
        try:
            base = f"http://127.0.0.1:{server.port}"
            pr_id = server.get("/api/prs")[1]["prs"][0]["id"]
            ctx = br.new_context(viewport={"width": 1280, "height": 900}, color_scheme="light")
            page = ctx.new_page()
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
            page.on(
                "response",
                lambda r: errs.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 else None,
            )
            page.goto(f"{base}/#/pr/{pr_id}")
            page.wait_for_selector(".mergecard button")
            page.locator(".mergecard button").click()
            page.wait_for_selector(".mergesheet .mergenext:not([disabled])")
            full = page.locator(".mergesheet").text_content() or ""
            for s in (
                "統合できます",
                "feature/real",
                "develop",
                "docs/real.md",
                "リスク設定を読み込めません",
            ):
                check(s in full, f"merge-real: 手順 1 に {s!r} が無い")
            msg = page.locator(".mergesheet textarea").input_value()
            check(
                msg.startswith("feat: 実サーバで統合する"),
                f"merge-real: 既定のメッセージが違う: {msg!r}",
            )
            merge_confirm(page)
            merge_go(page)
            page.wait_for_selector(".mergesheet .mergeresult, .mergesheet .formerr:not(:empty)")
            t = page.locator(".mergesheet").inner_text()
            check("統合しました" in t, f"merge-real: 成功の表示でない: {t!r}")
            after = _git(repo, "rev-list", "--parents", "-n", "1", "develop").split()
            check(
                len(after) == 3 and after[1] == before,
                f"merge-real: develop が merge commit になっていない: {after}",
            )
            check(
                _git(repo, "log", "-1", "--format=%s", "develop").strip()
                == "feat: 実サーバで統合する",
                "merge-real: 統合コミットの件名が違う",
            )
            check((repo / "docs" / "real.md").exists(), "merge-real: 作業ツリーが更新されていない")
            page.locator(".mergesheet button", has_text="最新の状態を読み込む").click()
            page.wait_for_selector(".prhead .chip:has-text('統合済み')")
            check(
                page.locator(".mergecard button, .mergebar button").count() == 0,
                "merge-real: 統合済みなのにボタンがある",
            )
            check(errs == [], f"merge-real: エラー: {errs}")
        finally:
            if ctx is not None:
                ctx.close()
            server.stop()


# ----------------------------------------------------------------- 起票 ---

HOSTILE_TITLE = '<img src=x onerror="window.__pwned=1">題'
HOSTILE_GOAL = "<script>window.__pwned=1</script>\n2 行目"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
L_NAME, L_TITLE, L_GOAL = "名前（枝名・作業ツリー名）", "題名", "目的"
L_CONS, L_SCOPE, L_ACC = (
    "守る条件（任意）",
    "担当範囲（任意。1 行に 1 つの glob）",
    "完了条件（任意）",
)


def create_page(br, kind: str = "pc"):
    """起票の試験用のサーバとページ。create=true。pc はクリップボードの読み書きを許可する。"""
    srv, base = serve()
    st: ReviewState = srv.state  # type: ignore[attr-defined]
    st.create_mode = "on"
    sp = kind == "sp"
    size = {"width": 390, "height": 844} if sp else {"width": 1280, "height": 900}
    ctx = br.new_context(
        viewport=size,
        has_touch=sp,
        is_mobile=sp,
        color_scheme="light",
        permissions=None if sp else ["clipboard-read", "clipboard-write"],
    )
    page = ctx.new_page()
    errs: list[str] = []
    page.on("pageerror", lambda e, errs=errs: errs.append(f"pageerror: {e}"))
    page.on(
        "request",
        lambda r, errs=errs, base=base: (
            errs.append(f"外部通信: {r.url}") if not r.url.startswith((base, "data:")) else None
        ),
    )
    return srv, base, st, ctx, page, errs


def create_open(page, base: str) -> None:
    """一覧を開いて「＋ 起票」でシートを開く。"""
    page.goto(f"{base}/#/")
    page.reload()
    page.wait_for_selector(".prlist")
    page.locator(".createopenbtn").click()
    page.wait_for_selector(".createsheet .createnext")


def create_fill(
    page, name="my-feat", title="題名です", goal="目的です", cons="", scope="", acc=""
) -> None:
    sheet = page.locator(".createsheet")
    for label, v in (
        (L_NAME, name),
        (L_TITLE, title),
        (L_GOAL, goal),
        (L_CONS, cons),
        (L_SCOPE, scope),
        (L_ACC, acc),
    ):
        sheet.get_by_label(label, exact=True).fill(v)


def create_confirm(page) -> None:
    page.locator(".createsheet .createnext").click()
    page.wait_for_selector(".createsheet .createsubmit")


def create_go(page) -> None:
    page.locator(".createsheet input[type=checkbox]").check()
    page.locator(".createsheet .createsubmit").click()


def flow_create_caps(br, check) -> None:
    """capabilities.create が真のときだけ「＋ 起票」を出す。古いサーバ（404）・起票先が develop でない repo は出さない。"""
    srv, base, st, ctx, page, errs = create_page(br)
    btn = ".createopenbtn"
    for mode, caps in ("off", "on"), ("on", "404"):
        st.create_mode, st.caps_mode = mode, caps
        page.goto(f"{base}/#/")
        page.reload()
        page.wait_for_selector(".prlist")
        check(
            page.locator(btn).count() == 0, f"create-caps: create={mode} caps={caps} でボタンがある"
        )
    st.create_mode, st.caps_mode = "on", "off"
    page.reload()
    page.wait_for_selector(".prlist")
    check(page.locator(btn).count() == 1, "create-caps: create=true でボタンが 1 つでない")
    check("＋ 起票" in page.locator(btn).inner_text(), "create-caps: ボタンの文言が違う")
    page.locator(btn).click()
    page.wait_for_selector(".createsheet .createnext")
    t = page.locator(".createsheet").inner_text()
    check("example-app" in t, "create-caps: 起票先の repo が無い")
    check("example-docs" not in t, "create-caps: develop でない repo が起票先に出ている")
    check(
        page.locator(".createsheet select").count() == 0,
        "create-caps: 起票先が 1 つなのに選択欄がある",
    )
    check(errs == [], f"create-caps: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_create_form(br, check) -> None:
    """手順 1: 入力欄の属性・プレビュー・サーバと同じ検査・文字数・下書き・フォーカス。"""
    srv, base, st, ctx, page, errs = create_page(br)
    create_open(page, base)
    sheet = page.locator(".createsheet")
    check(sheet.get_attribute("role") == "dialog", "create-form: role=dialog でない")
    check(sheet.get_attribute("aria-modal") == "true", "create-form: aria-modal でない")
    check(sheet.locator("form").count() == 0, "create-form: form 要素がある")
    name = sheet.get_by_label(L_NAME, exact=True)
    for attr, want in (("autocapitalize", "none"), ("autocorrect", "off"), ("spellcheck", "false")):
        check(name.get_attribute(attr) == want, f"create-form: 名前欄の {attr} が {want} でない")
    check(
        "公開リポジトリに書けない内容（秘密・組織の具体）は書かない。書いた内容は LLM と worktree に届く。"
        in sheet.inner_text(),
        "create-form: 固定文が無い",
    )
    nxt = page.locator(".createnext")
    check(nxt.is_disabled(), "create-form: 空のまま「確認へ」が有効")
    # プレビュー
    name.fill("my-feat")
    pv = page.locator(".createpreview").inner_text()
    check(
        "feature/my-feat" in pv and ".tmp/worktrees/my-feat/" in pv,
        f"create-form: プレビューが違う: {pv!r}",
    )
    # 必須を埋めると進める
    create_fill(page)
    check(nxt.is_enabled(), "create-form: 必須を埋めても「確認へ」が無効")

    def invalid(label, value, want, why) -> None:
        """label の欄に value を入れると、want を含む誤りが出て進めない。最後に直す。"""
        box = sheet.get_by_label(label, exact=True)
        old = box.input_value()
        box.fill(value)
        t = sheet.inner_text()
        check(want in t, f"create-form: {why}: {want!r} が表示されない")
        check(nxt.is_disabled(), f"create-form: {why}: 「確認へ」が有効")
        box.fill(old)
        check(nxt.is_enabled(), f"create-form: {why}: 直しても「確認へ」が無効")

    for bad in (
        "Bad",
        "a..b",
        "x.lock",
        "x.",
        "x.git",
        "con",
        "com1.txt",
        "-x",
        "a" * 65,
        "a b",
        "名前",
    ):
        invalid(L_NAME, bad, "名前", f"名前 {bad[:12]!r}")
        check(
            name.get_attribute("aria-invalid") == "false",
            f"create-form: {bad[:12]!r} の後も無効表示",
        )
    invalid(L_TITLE, "x" * 101, "100 文字まで", "題名 101 字")
    invalid(L_GOAL, "x" * 1501, "1500 文字まで", "目的 1501 字")
    invalid(L_CONS, "x" * 1501, "1500 文字まで", "守る条件 1501 字")
    invalid(L_ACC, "x" * 801, "800 文字まで", "完了条件 801 字")
    invalid(L_SCOPE, "\n".join(f"a{i}" for i in range(21)), "20 行まで", "担当範囲 21 行")
    invalid(L_SCOPE, "/etc/passwd", "相対パス", "絶対パス")
    invalid(L_SCOPE, "a/../b", "相対パス", "親への参照")
    invalid(L_SCOPE, "C:\\x", "相対パス", "ドライブ文字")
    invalid(L_SCOPE, "x" * 121, "120 文字まで", "担当範囲 121 字")
    invalid(L_GOAL, "a\u0007b", "使えない文字", "制御文字")
    invalid(L_GOAL, "a\u202eb", "使えない文字", "双方向制御文字")
    for secret, kind in (
        ("password=hunter2", "password"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
        ("ghp_" + "a" * 36, "github_token"),
        ("https://user:pw@example.com/", "url_userinfo"),
        ("Bearer " + "a" * 20, "bearer"),
    ):
        invalid(
            L_GOAL,
            f"x {secret} y",
            f"秘密らしい文字列が含まれています（種類: {kind}",
            f"秘密 {kind}",
        )
    invalid(L_SCOPE, "password=hunter2", "秘密らしい", "担当範囲の秘密")
    # 合計の上限: 各欄は上限内でも、合計 4000 字を超えれば断る
    sheet.get_by_label(L_GOAL, exact=True).fill("あ" * 1500)
    sheet.get_by_label(L_CONS, exact=True).fill("い" * 1500)
    sheet.get_by_label(L_ACC, exact=True).fill("う" * 800)
    check(nxt.is_enabled(), "create-form: 合計が上限以下なのに無効")
    invalid(L_SCOPE, "\n".join("s" * 120 for _ in range(3)), "合計は 4000 文字まで", "合計 4000 字")
    # 文字数の表示と、サロゲートペア（絵文字）は 1 文字と数える
    create_fill(page, title="😀" * 100, scope="a\nb")
    t = sheet.inner_text()
    check(
        "100 / 100 文字" in t and "2 / 20 行" in t, f"create-form: 文字数表示が違う: {t[-400:]!r}"
    )
    check(nxt.is_enabled(), "create-form: 絵文字 100 個の題名が断られる")
    # 下書き: 再読み込み後、シートを開くと入力が戻る
    create_fill(page, name="draft-name", title="下書き題", goal="下書き目的", scope="x/**")
    page.reload()
    page.wait_for_selector(".prlist")
    page.locator(".createopenbtn").click()
    page.wait_for_selector(".createsheet .createnext")
    sheet = page.locator(".createsheet")
    check(
        sheet.get_by_label(L_NAME, exact=True).input_value() == "draft-name",
        "create-form: 名前の下書きが戻らない",
    )
    check(
        sheet.get_by_label(L_GOAL, exact=True).input_value() == "下書き目的",
        "create-form: 目的の下書きが戻らない",
    )
    check(
        sheet.get_by_label(L_SCOPE, exact=True).input_value() == "x/**",
        "create-form: 担当範囲の下書きが戻らない",
    )
    # 背景は操作できない。Tab はシートの外へ出ない。Esc で閉じ、開いたボタンへフォーカスが戻る
    check(
        page.evaluate("document.getElementById('app').inert") is True,
        "create-form: シート中も背景が操作できる",
    )
    outside = 0
    for _ in range(30):
        page.keyboard.press("Tab")
        if not page.evaluate("!!document.activeElement.closest('.createsheet')"):
            outside += 1
    check(outside == 0, f"create-form: Tab でシートの外へ出た ({outside} 回)")
    page.keyboard.press("Escape")
    page.wait_for_selector(".createsheet", state="detached")
    check(
        page.evaluate("document.getElementById('app').inert") is False,
        "create-form: 閉じた後も背景が inert",
    )
    check(
        page.evaluate("document.activeElement.classList.contains('createopenbtn')"),
        "create-form: 閉じた後にフォーカスがボタンへ戻らない",
    )
    page.locator(".createopenbtn").click()
    page.wait_for_selector(".createsheet .createnext")
    page.mouse.click(5, 5)
    page.wait_for_selector(".createsheet", state="detached")
    check(st.create_log == [], "create-form: 入力だけで POST が飛んだ")
    check(errs == [], f"create-form: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_create_submit(br, check) -> None:
    """確認 → 二重送信の防止 → 結果 → PR 画面の依頼文カード → 一覧（起票のみ・題名）。敵対的な文字列も通す。"""
    srv, base, st, ctx, page, errs = create_page(br)
    page.on(
        "console",
        lambda m, errs=errs: (
            errs.append(f"console: {m.text}")
            if m.type == "error"
            and "404" not in m.text  # favicon など、意図しない資源の 404 は除く
            else None
        ),
    )
    create_open(page, base)
    create_fill(
        page,
        name="evil-feat",
        title=HOSTILE_TITLE,
        goal=HOSTILE_GOAL,
        cons="守る\n条件",
        scope=" apps/**\n\n docs/*.md \n",
        acc="完了",
    )
    create_confirm(page)
    sheet = page.locator(".createsheet")
    full = sheet.text_content() or ""
    for s in (
        "example-app",
        "feature/evil-feat",
        ".tmp/worktrees/evil-feat/",
        "develop@bbbbbbb",
        HOSTILE_TITLE,
        HOSTILE_GOAL,
    ):
        check(s in full, f"create-submit: 確認に {s!r} が無い")
    body = page.locator(".createtext").text_content() or ""
    for s in ("## 守る条件", "守る\n条件", "- apps/**", "- docs/*.md", "## 完了条件"):
        check(s in body, f"create-submit: 依頼文の全文に {s!r} が無い")
    check(
        sheet.locator("img, script, form").count() == 0,
        "create-submit: 確認に img/script/form ができた",
    )
    check(
        page.evaluate("window.__pwned === undefined"),
        "create-submit: 確認で敵対的な文字列が実行された",
    )
    go = page.locator(".createsubmit")
    cb = sheet.locator("input[type=checkbox]")
    check(go.is_disabled(), "create-submit: 確認前に「起票する」が有効")
    check(
        "公開できない内容" in sheet.locator(".confirmrow").inner_text(),
        "create-submit: 確認チェックの文言が無い",
    )
    cb.check()
    check(go.is_enabled(), "create-submit: チェック後も「起票する」が無効")
    cb.uncheck()
    check(go.is_disabled(), "create-submit: チェックを外したのに有効")
    # 「戻る」で入力を保ったまま手順 1 へ。もう一度進むとチェックは外れている
    page.locator(".createbackbtn").click()
    page.wait_for_selector(".createsheet .createnext")
    check(
        sheet.get_by_label(L_TITLE, exact=True).input_value() == HOSTILE_TITLE,
        "create-submit: 戻ったとき入力を失った",
    )
    create_confirm(page)
    check(not cb.is_checked(), "create-submit: 戻った後にチェックが残る")
    # 二重送信: 応答を保留した状態で 2 回押しても POST は 1 回
    st.create_gate = threading.Event()
    cb.check()
    page.evaluate(
        "() => { const b = document.querySelector('.createsubmit'); b.click(); b.click(); }"
    )
    waitfor(lambda: len(st.create_log) >= 1, "起票の POST", check)
    time.sleep(0.3)
    check(len(st.create_log) == 1, f"create-submit: 二重送信: {len(st.create_log)} 回")
    check("起票中" in sheet.inner_text(), "create-submit: 実行中の表示が無い")
    check(page.locator(".createsubmit").is_disabled(), "create-submit: 実行中に「起票する」が有効")
    page.keyboard.press("Escape")  # 実行中は閉じられない
    check(page.locator(".createsheet").count() == 1, "create-submit: 実行中にシートが閉じた")
    st.create_gate.set()
    page.wait_for_selector(".createsheet .createopen")
    check(len(st.create_log) == 1, f"create-submit: POST が {len(st.create_log)} 回")
    sent = st.create_log[0]
    check(
        set(sent) == {"kind", "name", "requestId", "expect", "brief"},
        f"create-submit: 本文のキー: {sorted(sent)}",
    )
    check(
        sent["kind"] == "feature" and sent["name"] == "evil-feat", "create-submit: kind/name が違う"
    )
    check(
        bool(UUID_RE.fullmatch(str(sent["requestId"]))),
        f"create-submit: requestId が uuid でない: {sent['requestId']}",
    )
    check(sent["expect"] == {"target": "b" * 40}, f"create-submit: expect が違う: {sent['expect']}")
    want = {
        "title": HOSTILE_TITLE,
        "goal": HOSTILE_GOAL,
        "constraints": "守る\n条件",
        "scope": ["apps/**", "docs/*.md"],
        "acceptance": "完了",
    }
    check(sent["brief"] == want, f"create-submit: brief が違う: {sent['brief']}")
    t = sheet.inner_text()
    for s in (
        "起票しました",
        "cd example-app/.tmp/worktrees/evil-feat && pis --new",
        "develop@bbbbbbb",
        "PR を開く",
        "依頼文をコピー",
    ):
        check(s in t, f"create-submit: 結果に {s!r} が無い")
    check("/home" not in t and "C:\\" not in t, f"create-submit: 結果に絶対パス: {t!r}")
    key = next(iter(st.created))
    href = page.locator(".createopen").get_attribute("href")
    check(href == f"#/pr/r1a2b3c4d/{key}", f"create-submit: PR を開くのリンクが違う: {href}")
    check(
        page.evaluate("sessionStorage.getItem('prv.create.draft')") is None,
        "create-submit: 成功後も下書きが残る",
    )
    page.locator(".createcopy").click()
    waitfor(lambda: "コピーしました" in sheet.inner_text(), "コピーの結果", check)
    clip = page.evaluate("navigator.clipboard.readText()")
    check(
        clip.startswith("# " + HOSTILE_TITLE) and HOSTILE_GOAL in clip and "- docs/*.md" in clip,
        f"create-submit: クリップボードが違う: {clip!r}",
    )
    check(sheet.locator("img, script").count() == 0, "create-submit: 結果に img/script ができた")
    # PR 画面
    page.locator(".createopen").click()
    page.wait_for_selector(".briefcard")
    check(page.locator(".createsheet").count() == 0, "create-submit: PR を開いてもシートが残る")
    head = page.inner_text(".prhead")
    check(
        "起票のみ" in head and "統合済み" not in head,
        f"create-submit: PR の状態チップが違う: {head!r}",
    )
    card = page.locator(".briefcard")
    check(
        "rev 1" in card.inner_text() and "01234567" in card.inner_text(),
        f"create-submit: rev/digest が無い: {card.inner_text()!r}",
    )
    check("89abcdef" not in card.inner_text(), "create-submit: digest が 8 桁を超えている")
    check(
        card.locator("details").count() == 1
        and card.locator("details").get_attribute("open") is None,
        "create-submit: 依頼文が <details>（折りたたみ）でない",
    )
    card.locator("summary").click()
    bt = page.locator(".briefbody").text_content() or ""
    check(
        HOSTILE_TITLE in bt and HOSTILE_GOAL in bt and "- apps/**" in bt,
        f"create-submit: 依頼文が文字として出ていない: {bt!r}",
    )
    check(
        page.locator("#app img, #app script").count() == 0,
        "create-submit: PR 画面に img/script ができた",
    )
    check(
        page.evaluate("window.__pwned === undefined"),
        "create-submit: PR 画面で敵対的な文字列が実行された",
    )
    check(
        page.locator(".mergecard, .mergebar").count() == 0,
        "create-submit: 起票のみの PR に統合ボタンがある",
    )
    # 一覧: 題名・「起票のみ」チップ・フィルター。「統合済み」とは別
    page.locator(".crumb a").click()
    page.wait_for_selector(".prlist .rtitle")
    row = page.locator(".prrow", has_text="feature/evil-feat")
    check(
        HOSTILE_TITLE in row.inner_text(), f"create-submit: 一覧に題名が無い: {row.inner_text()!r}"
    )
    check(
        row.locator(".chip").count() == 1 and "起票のみ" in row.inner_text(),
        "create-submit: 一覧の起票のみチップが違う",
    )
    check("統合済み" not in row.inner_text(), "create-submit: 起票のみが統合済みと表示される")
    check(
        page.locator("#app img, #app script").count() == 0,
        "create-submit: 一覧に img/script ができた",
    )
    flt = page.locator(".seg button", has_text="起票のみ")
    check("1" in flt.inner_text(), f"create-submit: 起票のみの件数: {flt.inner_text()!r}")
    flt.click()
    check(
        page.locator(".prrow").count() == 1,
        f"create-submit: 起票のみフィルターの行数: {page.locator('.prrow').count()}",
    )
    page.locator(".seg button", has_text="統合済み").click()
    check(
        page.locator(".prrow", has_text="evil-feat").count() == 0,
        "create-submit: 統合済みフィルターに起票のみが出る",
    )
    check(
        page.evaluate("window.__pwned === undefined"),
        "create-submit: 一覧で敵対的な文字列が実行された",
    )
    check(errs == [], f"create-submit: エラー: {errs}")
    ctx.close()
    srv.shutdown()


# (コード, HTTP, サーバの文言, 画面に出る文言, 「入力に戻って直す」が出るか, 再送できるか)
CREATE_ERRORS = [
    ("create_disabled", 403, "", "起票を許可していません", False, False),
    ("forbidden_funnel", 403, "", "公開経由", False, False),
    ("forbidden_origin", 403, "", "接続元", False, False),
    (
        "secret_like",
        400,
        "秘密らしい文字列が含まれています（種類: jwt）。",
        "取り除いて",
        True,
        False,
    ),
    ("bad_brief", 400, "", "依頼文の形が正しくありません", True, False),
    ("brief_too_large", 400, "", "上限", True, False),
    ("bad_name", 400, "", "名前が正しくありません", True, False),
    ("bad_expect", 400, "", "入力に誤り", False, False),
    ("name_used", 409, "", "既に使われています", True, False),
    ("busy", 409, HOSTILE_TITLE, "別の起票が実行中", False, True),
    ("unsupported_repo", 409, "", "起票できません", False, False),
    ("bad_layout", 409, "", "配置", False, False),
    ("external_code", 409, "", "外部コード", False, False),
    ("worktree_registered", 409, "", "別の名前", True, False),
    ("limit", 409, "", "上限", False, False),
    ("too_large", 413, "", "大きすぎ", False, True),
    ("create_partial", 500, "枠が残っています（試験）", "途中で止まりました", False, False),
    ("create_failed", 500, "", "結果を確認できません", False, True),
    ("internal", 500, "", "結果を確認できません", False, True),
    ("shutting_down", 503, "", "停止中", False, True),
]


def flow_create_errors(br, check) -> None:
    """エラーコードごとの日本語の文言と、戻り先・再送の可否。サーバの文言は文字として出る。"""
    srv, base, st, ctx, page, errs = create_page(br)
    page.on("console", lambda m, errs=errs: errs.append(m.text) if m.type == "error" else None)
    for code, status, msg, want, to_form, _resend in CREATE_ERRORS:
        st.create_resp, st.create_error = "error", (status, code, msg)
        create_open(page, base)
        create_fill(page, name="err-feat")
        create_confirm(page)
        create_go(page)
        page.wait_for_selector(".createsheet .formerr:not(:empty)")
        sheet = page.locator(".createsheet")
        t = page.locator(".createsheet .formerr").inner_text()
        check(want in t, f"create-errors[{code}]: {want!r} が無い: {t!r}")
        check(
            not re.search(r"[A-Za-z_]{6,}_[a-z]+", t.replace(HOSTILE_TITLE, "")),
            f"create-errors[{code}]: コードをそのまま出している: {t!r}",
        )
        if msg and code != "create_partial":
            check(msg in t, f"create-errors[{code}]: サーバの文言が無い")
        back = sheet.locator("button", has_text="入力に戻って直す")
        check(
            (back.count() == 1) == to_form,
            f"create-errors[{code}]: 「入力に戻って直す」の有無が違う",
        )
        cb = sheet.locator("input[type=checkbox]")
        check(not cb.is_checked(), f"create-errors[{code}]: 失敗後にチェックが残る")
        check(
            page.locator(".createsubmit").is_disabled(),
            f"create-errors[{code}]: 失敗後に「起票する」が有効",
        )
        if code == "create_partial":
            check(cb.is_disabled(), "create-errors[create_partial]: 残骸があるのに再送できる")
            check(
                sheet.locator("button", has_text="再読み込み").count() == 1,
                "create-errors[create_partial]: 再読み込みが無い",
            )
        else:
            cb.check()
            check(
                page.locator(".createsubmit").is_enabled(),
                f"create-errors[{code}]: チェックしても「起票する」が有効にならない",
            )
        check(
            page.locator("#app img, .createsheet img").count() == 0,
            f"create-errors[{code}]: img ができた",
        )
        check(
            page.evaluate("window.__pwned === undefined"),
            f"create-errors[{code}]: 敵対的な文字列が実行された",
        )
        if code == "name_used":
            back.click()
            page.wait_for_selector(".createsheet .createnext")
            check(
                page.evaluate("document.activeElement.classList.contains('createname')"),
                "create-errors[name_used]: 名前欄にフォーカスが無い",
            )
            check(
                page.locator(".createname").input_value() == "err-feat",
                "create-errors[name_used]: 入力を失った",
            )
    check(
        errs == [] or all("status of" in e or "Failed to load resource" in e for e in errs),
        f"create-errors: エラー: {errs}",
    )
    ctx.close()
    srv.shutdown()


def flow_create_resend(br, check) -> None:
    """結果が分からない失敗の再送は同じ requestId。内容を変えると別の requestId。replay の表示。stale_view。"""
    srv, base, st, ctx, page, errs = create_page(br)
    page.on("console", lambda m, errs=errs: errs.append(m.text) if m.type == "error" else None)
    create_open(page, base)
    create_fill(page, name="resend-feat")
    create_confirm(page)
    st.create_resp = "drop"
    create_go(page)
    page.wait_for_selector(".createsheet .formerr:not(:empty)")
    check(
        "結果を確認できません" in page.locator(".createsheet .formerr").inner_text(),
        "create-resend: 通信断の文言が無い",
    )
    check(st.created == {}, "create-resend: 通信断で作られたことになっている")
    st.create_resp = "replay"
    create_go(page)
    page.wait_for_selector(".createsheet .createopen")
    ids = [x["requestId"] for x in st.create_log]
    check(
        len(ids) == 2 and ids[0] == ids[1],
        f"create-resend: 同じ依頼の再送で requestId が変わった: {ids}",
    )
    check(
        "起票済みでした" in page.locator(".createsheet").inner_text(),
        "create-resend: replay の表示が無い",
    )
    # 内容を変えると別の依頼
    create_open(page, base)
    create_fill(page, name="resend-two")
    create_confirm(page)
    st.create_resp = "drop"
    create_go(page)
    page.wait_for_selector(".createsheet .formerr:not(:empty)")
    page.locator(".createbackbtn").click()
    page.wait_for_selector(".createsheet .createnext")
    page.get_by_label(L_TITLE, exact=True).fill("変えた題名")
    create_confirm(page)
    st.create_resp = "ok"
    create_go(page)
    page.wait_for_selector(".createsheet .createopen")
    ids = [x["requestId"] for x in st.create_log[2:]]
    check(
        len(ids) == 2 and ids[0] != ids[1], f"create-resend: 内容を変えたのに同じ requestId: {ids}"
    )
    # develop が進んだ (stale_view): 最新の基点を読み直し、入力を保ったまま確認をやり直す
    create_open(page, base)
    create_fill(page, name="stale-feat", goal="古い基点")
    create_confirm(page)
    st.create_base = "c" * 40
    create_go(page)
    page.wait_for_selector(".createsheet .formerr:not(:empty)")
    check(
        "develop が更新されました" in page.locator(".createsheet .formerr").inner_text(),
        "create-resend: stale_view の文言が無い",
    )
    page.locator(".createsheet button", has_text="最新の基点を読み込む").click()
    page.wait_for_selector(".createsheet .createnext")
    t = page.locator(".createsheet").inner_text()
    check("develop@ccccccc" in t, f"create-resend: 最新の基点が表示されない: {t[:200]!r}")
    check(
        page.locator(".createname").input_value() == "stale-feat",
        "create-resend: 基点を読み直して入力を失った",
    )
    create_confirm(page)
    check(
        "develop@ccccccc" in page.locator(".createsheet").inner_text(),
        "create-resend: 確認の基点が古い",
    )
    create_go(page)
    page.wait_for_selector(".createsheet .createopen")
    last = st.create_log[-1]
    check(
        last["expect"] == {"target": "c" * 40},
        f"create-resend: 再送の expect が古い: {last['expect']}",
    )
    check(
        st.create_log[-2]["requestId"] != last["requestId"],
        "create-resend: 基点が変わったのに同じ requestId",
    )
    check(
        errs == [] or all("Failed to load resource" in e for e in errs),
        f"create-resend: エラー: {errs}",
    )
    ctx.close()
    srv.shutdown()


def flow_create_sp(br, check) -> None:
    """スマホ幅 (390px): 入力・確認・結果の各手順で横にはみ出さない。タップ領域は 44px 以上。"""
    srv, base, _st, ctx, page, errs = create_page(br, "sp")

    def narrow(step: str) -> None:
        w = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        check(w[0] <= w[1], f"create-sp[{step}]: 横にはみ出している {w}")
        s = page.evaluate(
            "(() => { const e = document.querySelector('.createsheet'); return [e.scrollWidth, e.clientWidth]; })()"
        )
        check(s[0] <= s[1], f"create-sp[{step}]: シートが横にはみ出している {s}")
        small = page.evaluate(
            "[...document.querySelectorAll('.createsheet button, .createsheet input.cbox, .createsheet summary, "
            ".createsheet label.confirmrow, .createopen')]"
            ".filter(e => e.getBoundingClientRect().width > 0 && e.getBoundingClientRect().height < 43.5)"
            ".map(e => (e.textContent || e.className).trim() + ':' + e.getBoundingClientRect().height)"
        )
        check(small == [], f"create-sp[{step}]: タップ領域が 44px 未満: {small}")

    page.goto(f"{base}/#/")
    page.wait_for_selector(".prlist")
    check(
        page.locator(".createopenbtn").bounding_box()["height"] >= 43.5,
        "create-sp: 「＋ 起票」の高さが 44px 未満",
    )
    w = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    check(w[0] <= w[1], f"create-sp: 一覧が横にはみ出している {w}")
    page.locator(".createopenbtn").click()
    page.wait_for_selector(".createsheet .createnext")
    long_name = "n" * 64
    create_fill(
        page,
        name=long_name,
        title="t" * 100,
        goal="g" * 300,
        cons="c" * 300,
        scope="\n".join(["s" * 120, "apps/pr-viewer/web/" + "d" * 90]),
        acc="a" * 300,
    )
    narrow("form")
    create_confirm(page)
    narrow("confirm")
    create_go(page)
    page.wait_for_selector(".createsheet .createopen")
    narrow("result")
    check(
        "cd example-app/.tmp/worktrees/" + long_name in page.locator(".createcmd").inner_text(),
        "create-sp: 結果のコマンドが無い",
    )
    page.locator(".createopen").click()
    page.wait_for_selector(".briefcard")
    page.locator(".briefcard summary").click()
    w = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    check(w[0] <= w[1], f"create-sp: PR 画面が横にはみ出している {w}")
    check(
        page.locator(".briefcard summary").bounding_box()["height"] >= 43.5,
        "create-sp: 依頼文の summary が 44px 未満",
    )
    check(errs == [], f"create-sp: エラー: {errs}")
    ctx.close()
    srv.shutdown()


def flow_create_real(br, check) -> None:
    """実サーバ（--allow-create）+ 実画面: 起票 → 枝・作業ツリー・記録 → PR 画面（起票のみ・依頼文）→ 同名の再起票は断る。

    契約から作った偽サーバとの形のずれ（capabilities.create・repos[].targetOid・state=empty・brief）は、ここで初めて見える。
    """
    import tempfile

    from test_pr_viewer_server import Server, _commit, _git, _init

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        repo = _init(root / "example-app")
        for key, value in (
            ("user.name", "Example Dev"),
            ("user.email", "you@example.com"),
            ("gc.auto", "0"),
            ("maintenance.auto", "false"),
        ):
            _git(repo, "config", key, value)
        _commit(repo, {"README.md": "hello\n", ".gitignore": ".tmp/\n"}, "init")
        server = Server(
            [
                "--repo",
                str(repo),
                "--port",
                "0",
                "--allow-create",
                "--rules-file",
                str(root / "rules.json"),
            ]
        )
        ctx = None
        try:
            base = f"http://127.0.0.1:{server.port}"
            ctx = br.new_context(viewport={"width": 1280, "height": 900}, color_scheme="light")
            page = ctx.new_page()
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
            page.on(
                "response",
                lambda r: (
                    errs.append(f"HTTP {r.status}: {r.url}")
                    if r.status >= 400 and not r.url.endswith("favicon.ico")
                    else None
                ),
            )
            page.goto(f"{base}/")
            page.wait_for_selector(".createopenbtn")
            develop = _git(repo, "rev-parse", "develop").strip()
            page.locator(".createopenbtn").click()
            page.wait_for_selector(".createsheet .createnext")
            create_fill(
                page, name="real-feat", title="実サーバで起票", goal="目的の文", scope="docs/**"
            )
            create_confirm(page)
            check(
                f"develop@{develop[:7]}" in page.locator(".createsheet").inner_text(),
                "create-real: 基点の表示が実際の develop と違う",
            )
            create_go(page)
            page.wait_for_selector(".createsheet .createopen, .createsheet .formerr:not(:empty)")
            t = page.locator(".createsheet").inner_text()
            check("起票しました" in t, f"create-real: 成功の表示でない: {t!r}")
            check(str(root) not in t, "create-real: 結果に絶対パスが出ている")
            check(
                _git(repo, "rev-parse", "feature/real-feat").strip() == develop,
                "create-real: 枝が develop から作られていない",
            )
            check(
                (repo / ".tmp" / "worktrees" / "real-feat").is_dir(),
                "create-real: 作業ツリーが無い",
            )
            refs = _git(repo, "for-each-ref", "refs/pi/review", "--format=%(refname)")
            check(len(refs.split()) == 1, f"create-real: レビュー記録の ref: {refs!r}")
            page.locator(".createopen").click()
            page.wait_for_selector(".briefcard")
            check("起票のみ" in page.inner_text(".prhead"), "create-real: 起票のみのチップが無い")
            page.locator(".briefcard summary").click()
            bt = page.locator(".briefbody").text_content() or ""
            check(
                "実サーバで起票" in bt and "- docs/**" in bt, f"create-real: 依頼文が無い: {bt!r}"
            )
            page.locator(".crumb a").click()
            page.wait_for_selector(".prlist .rtitle")
            row = page.locator(".prrow", has_text="feature/real-feat")
            check(
                "起票のみ" in row.inner_text() and "実サーバで起票" in row.inner_text(),
                "create-real: 一覧の行が違う",
            )
            check("統合済み" not in row.inner_text(), "create-real: 起票のみが統合済みと表示される")
            # 同じ名前の再起票は断られる（name_used）。枝・作業ツリーは増えない
            check(errs == [], f"create-real: 400 以上の応答かエラー（再起票の前）: {errs}")
            page.locator(".createopenbtn").click()
            page.wait_for_selector(".createsheet .createnext")
            create_fill(page, name="real-feat", title="二回目", goal="二回目")
            create_confirm(page)
            create_go(page)
            page.wait_for_selector(".createsheet .formerr:not(:empty)")
            check(
                "既に使われています" in page.locator(".createsheet .formerr").inner_text(),
                "create-real: 同名の再起票が断られない",
            )
            heads = _git(repo, "for-each-ref", "refs/heads/feature", "--format=%(refname)").split()
            check(heads == ["refs/heads/feature/real-feat"], f"create-real: 枝が増えた: {heads}")
            # 400 以上の応答は失敗。ただし、この再起票の 409 1 件だけは意図したもの
            check(
                len(errs) == 1 and errs[0].startswith("HTTP 409:") and "/features" in errs[0],
                f"create-real: 想定外の 400 以上の応答・エラー: {errs}",
            )
        finally:
            if ctx is not None:
                ctx.close()
            server.stop()


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
            fs = page.evaluate("getComputedStyle(document.querySelector('table.diff')).fontSize")
            if sp:  # 幅 719px 以下は 12px 以下（iOS の自動拡大の対策と合わせる）
                check(float(fs[:-2]) <= 12, f"sp 差分の文字が 12px 以下でない: {fs}")
            else:
                check(float(fs[:-2]) == 13, f"pc 差分の文字が 13px でない: {fs}")
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
            flow_approve_only(page, kind, base, srv.state, check)
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
            check(
                "承認して送る" not in page.inner_text(".revbar"),
                f"{kind} 統合済みの PR に「承認して送る…」が出ている",
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
        flow_live(br, check)
        flow_live_guards(br, check)
        for flow in (
            flow_merge_caps,
            flow_merge_steps,
            flow_merge_keep,
            flow_merge_running,
            flow_merge_errors,
            flow_merge_plans,
            flow_merge_slow_plan,
            flow_merge_stale,
            flow_merge_sp,
            flow_merge_real,
            flow_create_caps,
            flow_create_form,
            flow_create_submit,
            flow_create_errors,
            flow_create_resend,
            flow_create_sp,
            flow_create_real,
        ):
            flow(br, check)
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
