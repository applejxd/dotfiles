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
        "live.js",
        "merge.js",
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


def test_api_handles_stale_view() -> None:
    """409 stale_view のあとは、詳細のキャッシュを捨てる。"""
    api = (WEB / "api.js").read_text(encoding="utf-8")
    assert "stale_view" in api and re.search(r"PRV\.cache\s*=\s*\{\}", api)


def test_comment_sending_is_gone_from_the_screen() -> None:
    """レビューコメントの送信は撤去した: 画面のコードに、コメント・送信の API 呼び出しも送信バーも残っていない。"""
    assert not (WEB / "send.js").exists()
    api = (WEB / "api.js").read_text(encoding="utf-8")
    assert "/comments" not in api and "/submit" not in api
    for p in WEB.glob("*.js"):
        text = p.read_text(encoding="utf-8")
        assert not re.search(
            r"PRV\.(commentForm|threadView|reviewBar|batchList|paintQueue)\b", text
        ), p.name
        assert not re.search(r"PRV\.api\.(comment|submit)\(", text), p.name
    assert "send.js" not in (WEB / "index.html").read_text(encoding="utf-8")


def test_merge_api_and_screen_are_wired() -> None:
    """統合 (CHG-0062 段 A2): API の 3 本と、画面の統合。シートの基盤は core.js にある。"""
    api = (WEB / "api.js").read_text(encoding="utf-8")
    assert "/api/capabilities" in api and "/merge-plan" in api and '"/merge"' in api
    assert re.search(r"/merge\"[^;]*expect\s*:\s*m\.expect[^;]*cleanup\s*:\s*m\.cleanup", api)
    merge = (WEB / "merge.js").read_text(encoding="utf-8")
    core = (WEB / "core.js").read_text(encoding="utf-8")
    assert "PRV.openSheet" in merge
    for name in ("openSheet", "closeSheet", "sheetOpen"):
        assert f"PRV.{name} = function" in core, name
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "/web/merge.js" in html and html.index("/web/core.js") < html.index("/web/merge.js")


def test_merge_fixtures_follow_contract() -> None:
    oid = re.compile(r"[0-9a-f]{40}")
    assert load_fixture("capabilities.json")["targets"] == ["develop"]
    for name in ("ok", "conflict", "blocked", "riskcfg", "hostile"):
        p = load_fixture(f"merge_plan_{name}.json")
        assert {"mergeable", "refusal", "blockers", "plan", "defaults"} <= set(p), name
        assert "warnings" not in p, name
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


def test_merge_sheet_shows_refusal_detail_paths() -> None:
    """拒否の原因のパス（details）を api.js が運び、merge.js が textContent で表示する（静的な配線）。"""
    api = (WEB / "api.js").read_text(encoding="utf-8")
    merge = (WEB / "merge.js").read_text(encoding="utf-8")
    assert "body.error.details" in api and "details: dt" in api
    assert "原因のファイル" in merge and "detailNodes(res.refusal.details)" in merge
    assert "detailNodes(e && e.details)" in merge
    assert "innerHTML" not in merge
    for c in ("operation_in_progress", "index_locked"):
        assert c in merge, c


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


def test_list_hides_included_branches_with_a_toggle() -> None:
    """含まれる枝 (includedIn): 既定で隠し、切り替えと件数を出す。DOM は textContent で作る（表示だけ）。"""
    lst = (WEB / "view-list.js").read_text(encoding="utf-8")
    assert "!p.includedIn" in lst and "showIncluded" in lst  # 既定で隠す
    assert 'type: "checkbox"' in lst and "localStorage" in lst and "prv.showIncluded" in lst
    assert "incN > 0" in lst and "件）" in lst  # 0 件のときは切り替えを出さない
    assert re.search(r'text: "→ " \+ pr\.includedIn \+ " に含まれる"', lst)
    pr = (WEB / "view-pr.js").read_text(encoding="utf-8")
    assert "inc.textContent = " in pr and "pr.includedIn" in pr
    assert "api.prs()" not in pr  # 概要の表示のために全件の一覧を計算しない
    assert "errorsNote" in lst and "件の PR を読めませんでした" in lst
    for text in (lst, pr):
        assert "innerHTML" not in text


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
    """試験で変わる review の状態（サーバごと。fixture を初期値にする）。"""

    def __init__(self) -> None:
        self.rv: dict[str, dict] = {}
        self.seq = 0
        self.bumped: set[str] = set()  # PR が更新された (source が変わった) ことにする key
        self.review_gets: dict[str, int] = {}  # GET …/review の回数 (自動更新の試験用)
        self.fail_review = False  # True の間、GET …/review は 500 を返す
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

    def get(self, key: str) -> dict:
        if key not in self.rv:
            self.rv[key] = load_fixture(f"review_{key}.json")
        return self.rv[key]

    def set_summary(self, key: str, done: str) -> None:
        """pi がサマリーを書き直した。"""
        s = self.get(key)["summary"]
        self.seq += 1
        self.get(key)["summary"] = {
            **s,
            "done": done,
            "at": f"2099-03-0{self.seq % 9 + 1}T00:00:00+00:00",
        }

    def mark_merged(self, key: str) -> None:
        """PR が統合済みになった (統合の入口が消える)。"""
        self.get(key)["merged"] = True


def find_pr(parts: list[str], state: ReviewState | None = None) -> dict | None:
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
        return 200, load_fixture("repos.json")
    if parts == ["api", "prs"]:
        return 200, load_fixture("prs.json")
    if parts == ["api", "capabilities"]:
        if state.caps_mode == "404":
            return err
        return 200, {
            **load_fixture("capabilities.json"),
            "merge": state.caps_mode == "on",
        }
    if len(parts) in (4, 5, 6) and parts[:2] == ["api", "prs"]:
        pr = find_pr(parts, state)
        if pr is None:
            return err
        if len(parts) == 4:
            state.pr_gets[parts[3]] = state.pr_gets.get(parts[3], 0) + 1
            detail = load_fixture(f"detail_{parts[3]}.json")
            return 200, {"pr": pr, **detail}
        if len(parts) == 6:
            return err
        if parts[4] == "review":
            state.review_gets[parts[3]] = state.review_gets.get(parts[3], 0) + 1
            if state.fail_review:
                return 500, err_body("internal", "内部エラー（試験）")
            return 200, state.get(parts[3])
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
    if len(parts) == 5 and parts[:2] == ["api", "prs"] and parts[4] in ("merge-plan", "merge"):
        pr = find_pr(parts, state)
        if pr is None:
            return 404, err_body("not_found", "見つかりません。")
        return merge_post(parts, payload, state, pr)
    if len(parts) == 5 and parts[:2] == ["api", "prs"] and parts[4] in ("comments", "submit"):
        return 405, err_body(
            "method_not_allowed", "この操作は使えません。"
        )  # コメント送信は撤去済み
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
        assert not {"oldBlob", "newBlob"} & set(body)  # コメントの位置指定用だった。撤去済み
        status, rv = api_response(f"/api/prs/{p['id']}/review")
        assert status == 200 and set(rv) == REVIEW_KEYS, p["id"]


REVIEW_KEYS = {
    "schema",
    "readonly",
    "bad",
    "stale",
    "staleParts",
    "merged",
    "summary",
}


def test_fixture_review_covers_states() -> None:
    """fixture がサマリー・統合済み・stale を含むこと。"""
    rv = load_fixture("review_paaaaaaaaaaaaaaa1.json")
    assert rv["summary"] and rv["summary"]["findings"] and rv["merged"] is False
    assert load_fixture("review_p1111111111111111.json")["merged"] is True
    assert load_fixture("review_p2222222222222222.json")["stale"] is True


def test_fake_server_state_machine() -> None:
    """偵物のサーバ自身の確認: サマリーの書き換え・統合済み。コメント送信の POST は 405。"""
    st = ReviewState()
    key = "paaaaaaaaaaaaaaa1"
    st.set_summary(key, "書き換え")
    assert st.get(key)["summary"]["done"] == "書き換え"
    st.mark_merged(key)
    assert st.get(key)["merged"] is True
    for leaf in ("comments", "submit"):
        assert post_response(f"/api/prs/r1a2b3c4d/{key}/{leaf}", {}, st)[0] == 405


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
    """概要: サマリー。コメントや送信の入口が無いこと。統合のボタンも無い（caps が off）。"""
    t = page.inner_text("#app")
    for s in (
        "pi のまとめ",
        "やったこと",
        "確認してほしい点",
        "db.find の例外処理",
        "旧定数を削除",
    ):
        check(s in t, f"{kind} 概要に {s!r} が無い")
    check(
        page.locator(".revbar, .thread, .cform, #app textarea").count() == 0,
        f"{kind} 概要にコメント・送信の部品が残っている",
    )
    check(page.locator("button", has_text="統合").count() == 0, f"{kind} 統合のボタンがある")
    ws = page.evaluate("getComputedStyle(document.querySelector('.summary .cbody')).whiteSpace")
    check(
        ws == "normal" and page.locator(".summary .cbody.md").count() >= 1,
        f"{kind} 本文が markdown 描画でない: {ws}",
    )
    shot(page, shots, f"{kind}-overview-review")


def flow_hostile_review(page, kind: str, check) -> None:
    """敵対的な review（サマリー）が文字として出る。"""
    check(
        EVIL in page.inner_text(".summary"),
        f"{kind} サマリーの敵対的な文字列が文字として出ていない",
    )
    check(
        page.locator(".summary img, .summary script").count() == 0,
        f"{kind} サマリーに img/script ができた",
    )


def flow_diff_view(page, kind: str, check, shots) -> None:
    """差分: 閲覧専用（コメントの入力・スレッド・行クリックの入力欄が無い）。"""
    check(
        page.locator(".thread, .orphans, tr.thr, tr.editor").count() == 0,
        f"{kind} 差分にスレッドが残っている",
    )
    page.locator("tr.a", has_text="return db.find(q);").locator("td.code").click()
    check(
        page.locator("tr.editor, textarea").count() == 0,
        f"{kind} 行をクリックすると入力欄が開く",
    )
    shot(page, shots, f"{kind}-diff-readonly")


def md_html(page, src: str) -> str:
    return page.evaluate("s => PRV.md(s).outerHTML", src)


def flow_markdown(br, check) -> None:
    """markdown 描画: 対応記法、XSS の反例（生 HTML・javascript: ・data: ・画像）、上限。"""
    srv, base = serve()
    ctx = br.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    page.goto(base + "/")
    page.wait_for_selector(".prlist")
    page.evaluate("window.__pwned = 0")
    # --- 反例先行: 危険な入力は要素にならず、文字として出る ---
    h = md_html(
        page, '<img src=x onerror="window.__pwned=1"> </script><script>window.__pwned=1</script>'
    )
    check("<img" not in h and "<script" not in h, f"md: 生 HTML が要素になった: {h}")
    check("&lt;img src=x onerror" in h, f"md: 生 HTML が文字として出ていない: {h}")
    for bad in (
        "javascript:alert(1)",
        "data:text/html,x",
        "JaVaScRiPt:x",
        "vbscript:x",
        "//evil.example/x",
        "/relative",
    ):
        h = md_html(page, f"[click]({bad})")
        check(
            "<a" not in h and f"[click]({bad})" in h.replace("&amp;", "&"),
            f"md: 危険なリンクが生きている {bad}: {h}",
        )
    h = md_html(page, "![alt text](https://evil.example/a.png)")
    check("<img" not in h and "[画像: alt text]" in h, f"md: 画像が文字にならない: {h}")
    h = md_html(page, "[a](https://ok.example/x) [b](#frag)")
    check(
        h.count("<a ") == 2 and 'rel="noopener noreferrer"' in h and 'target="_blank"' in h,
        f"md: リンク: {h}",
    )
    h = md_html(page, '[**x**](https://ok.example/"onmouseover=1)')
    check(
        "onmouseover"
        not in page.evaluate(
            "s => [...PRV.md(s).querySelectorAll('*')].map(e => e.getAttributeNames().join()).join()",
            '[x](https://ok.example/"onmouseover=1)',
        ),
        "md: 属性注入",
    )
    # --- 対応記法 ---
    src = (
        "# 見出し\n\n段落1\n同じ段落 `code` と **太字** と *斜体*\n\n- a\n  - a1\n- b\n\n1. x\n2. y\n\n"
        "> 引用\n\n---\n\n```js\nlet a = '<b>';\n```\n\n| h1 | h2 |\n|---|---|\n| c1 | c2 |\n"
    )
    h = md_html(page, src)
    for frag in (
        "<h4",
        "<br>",
        "<code>code</code>",
        "<strong>太字</strong>",
        "<em>斜体</em>",
        "<ul>",
        "<ol>",
        "<blockquote>",
        "<hr>",
        "<pre",
        "<table>",
        "<th>h1</th>",
        "<td>c2</td>",
        "&lt;b&gt;",
    ):
        check(frag in h, f"md: {frag!r} が無い: {h}")
    check(
        page.evaluate("s => PRV.md(s).querySelectorAll('ul ul li').length", src) == 1,
        "md: 入れ子の箇条書きが無い",
    )
    # --- 上限: 巨大・行数超過・深い入れ子は重くならず、残りは文字 ---
    t0 = page.evaluate(
        "() => { const t = performance.now(); const e = PRV.md('*a '.repeat(30000) + '\\n' + '- x\\n'.repeat(5000));"
        " window.__big = [e.querySelectorAll('li').length, !!e.querySelector('.mdrest')]; return performance.now() - t; }"
    )
    li, rest = page.evaluate("window.__big")
    check(
        t0 < 2000 and rest and li < 400,
        f"md: 巨大な入力の上限が効かない ({t0}ms, li={li}, rest={rest})",
    )
    deep = page.evaluate(
        "() => PRV.md('>>>>> deep\\n' + '- a\\n  - b\\n    - c\\n      - d').querySelectorAll('blockquote blockquote blockquote').length"
    )
    check(deep == 0, f"md: 引用の入れ子が上限を超えた {deep}")
    check(not page.evaluate("window.__pwned"), "md: 敵対的な入力が実行された")
    ctx.close()
    srv.shutdown()


def flow_hub_light(br, check) -> None:
    """CHG-0062 A3: 統合先が進んだ・衝突の可能性・未 push の表示。パスは文字として出る。"""
    srv, base = serve()
    for kind, size in (
        ("pc", {"width": 1280, "height": 900}),
        ("sp", {"width": 390, "height": 844}),
    ):
        sp = kind == "sp"
        ctx = br.new_context(viewport=size, has_touch=sp, is_mobile=sp, color_scheme="light")
        page = ctx.new_page()
        page.goto(base + "/")
        page.wait_for_selector(".prlist")
        row = page.locator(".prrow", has_text="feature/add-search")
        check(
            "develop が 3 進んだ" in row.inner_text(),
            f"{kind} hub: 一覧に「develop が N 進んだ」が無い",
        )
        check(
            page.locator(".prrow .behind").count() == 1,
            f"{kind} hub: 進んだ表示が開いている PR だけでない",
        )
        note = page.inner_text(".unpushed") if page.locator(".unpushed").count() else ""
        check(
            "2 件先" in note and "最後に取得" in note,
            f"{kind} hub: 「origin より N 件先」が無い: {note!r}",
        )
        row.locator("a").click()
        page.wait_for_selector(".behindcard")
        check(
            "develop が 3 コミット進みました" in page.inner_text(".behindcard h2"),
            f"{kind} hub: PR 画面に進んだ表示が無い",
        )
        check(
            "衝突の可能性: 25 件" in page.inner_text(".behindcard summary"),
            f"{kind} hub: 「衝突の可能性: N 件」が無い",
        )
        page.locator(".behindcard summary").click()
        check(
            page.locator(".behindcard li").count() == 3,
            f"{kind} hub: パス 2 件 + 「ほか N 件」の 3 行でない",
        )
        check(
            EVIL in page.inner_text(".behindcard"),
            f"{kind} hub: 敵対的なパスが文字として出ていない",
        )
        check(
            page.locator("#app img, #app script").count() == 0,
            f"{kind} hub: パスから img/script ができた",
        )
        check(
            page.evaluate("window.__pwned === undefined"),
            f"{kind} hub: パスの文字列が実行された",
        )
        check(
            page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
            f"{kind} hub: 横にはみ出している",
        )
        ctx.close()
    srv.shutdown()


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
    page.wait_for_selector(".summary")
    page.clock.pause_at(int(time.time() * 1000) + 5000)
    time.sleep(0.4)
    anchor()

    # 1. 状態が変わらないとき: 3 秒ごとに取り直すが、DOM は作り直されない
    js(
        "for (const s of ['.prhead', '.summary', '.live-summary'])"
        " document.querySelector(s).setAttribute('data-mark', '1');"
    )
    step(POLL_MS - 1, 0, "3 秒の前は取り直さない")
    step(1, 1, "3 秒で 1 回")
    step(POLL_MS, 1, "続けて 3 秒で 1 回")
    check(
        js("document.querySelectorAll('[data-mark]').length") == 3,
        "live: 状態が同じのに DOM が作り直された",
    )

    # 2. pi がサマリーを書き直す: 入力欄が無いのでバナー無しで自動で反映され、ヘッダーは作り直されない
    banner = page.locator(".livebar button")
    st.set_summary(LIVE_KEY, "書き直した要約です")
    step(POLL_MS, 1, "サマリーの書き直しを取り直す")
    until(lambda: "書き直した要約です" in page.inner_text(".summary"), "サマリーが自動で反映される")
    check(not banner.is_visible(), "live: サマリーの更新でバナーが出た")
    check(
        js("!!document.querySelector('.prhead[data-mark]')"),
        "live: サマリーの更新でヘッダーが作り直された",
    )

    # 4. タブが見えない間は止まり、見える状態に戻るとすぐ 1 回
    vis("hidden")
    step(POLL_MS * 4, 0, "非表示の間は取り直さない")
    n = gets()
    vis("visible")
    until(lambda: gets() == n + 1, "見える状態に戻ったときにすぐ 1 回")
    time.sleep(0.25)
    check(gets() == n + 1, "live: 見える状態に戻った直後に 2 回以上取り直した")
    step(POLL_MS, 1, "戻った後は 3 秒間隔に戻る")

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
    page.wait_for_selector(".prhead")
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
    # 統合の確認シートを開けるようにする。goto の前に切り替える（後だと、先に取得された capabilities が取り直されず、
    # 負荷が高いときに統合のカードが出ない。ハッシュだけが同じ goto は再読み込みしない）
    st.caps_mode = "on"
    page.goto(f"{base}/#/{'pr/' + LIVE_ID}")
    page.wait_for_selector(".mergecard button")
    page.clock.pause_at(int(time.time() * 1000) + 5000)
    time.sleep(0.4)
    anchor()
    banner = page.locator(".livebar button")

    # A. 状態が変わらないときは、ヘッダーと統合の入口を作り直さない
    js(
        "for (const s of ['.prhead', '.mergecard', '.summary'])"
        " document.querySelector(s).setAttribute('data-mark', '1');"
    )
    poll("変化なしの取り直し 1")
    poll("変化なしの取り直し 2")
    check(
        js("document.querySelectorAll('[data-mark]').length") == 3,
        "live-guards: 状態が同じのに画面が作り直された",
    )

    # B. 統合の確認シートが開いている間は、統合済みの切り替わりで画面を描き直さない。
    #    シートを閉じてバナーを押すと反映する
    page.locator(".mergecard button").click()
    page.wait_for_selector(".mergesheet .mergenext")
    st.mark_merged(LIVE_KEY)
    poll("シート中の統合済みを取り直す")
    until(banner.is_visible, "シート中はバナー")
    check(page.locator(".mergesheet").count() == 1, "live-guards: 取り直しで統合のシートが閉じた")
    check(
        js("!!document.querySelector('.prhead[data-mark]')"),
        "live-guards: シートが開いているのに画面全体が作り直された",
    )
    page.locator(".mergesheet .mergeclose").click()
    page.wait_for_selector(".mergesheet", state="detached")
    banner.click()
    until(lambda: not banner.is_visible(), "反映後はバナーが消える")
    check(
        js("!document.querySelector('.prhead[data-mark]')"),
        "live-guards: バナーを押しても画面が描き直されない",
    )

    # C. シートが無いときは、統合済みの切り替わりでバナー無しに自動で描き直す (別の PR で)
    other = "p2222222222222222"
    js(f"location.hash = '#/pr/r1a2b3c4d/{other}'")
    page.wait_for_selector(".summary")
    js("document.querySelector('.prhead').setAttribute('data-mark', '2')")
    st.mark_merged(other)
    page.clock.run_for(POLL_MS)
    until(lambda: js("!document.querySelector('.prhead[data-mark]')"), "シート無しで自動に描き直す")
    check(not banner.is_visible(), "live-guards: シート無しなのにバナーが出た")
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
    (
        "dirty",
        409,
        ("原因のファイル", "a.md", HOSTILE + ".ts", "ほか 3 件"),
        True,
        {"details": {"paths": ["a.md", HOSTILE + ".ts"], "pathCount": 5}},
    ),
    (
        "operation_in_progress",
        409,
        (CHECK_TREE, "進行中の操作", "CHERRY_PICK_HEAD"),
        True,
        {"details": {"op": "CHERRY_PICK_HEAD"}},
    ),
    ("index_locked", 409, (CHECK_TREE,), True, {}),
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
    page.wait_for_selector(".prhead")
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
        page.wait_for_selector(".prhead")
        check(page.locator(both).count() == 0, f"merge-caps: caps={mode} でボタンがある")
    st.caps_mode = "on"
    page.reload()
    page.wait_for_selector(".prhead")
    check(
        page.locator(".mergecard button").count() == 1,
        "merge-caps: caps=on でカードのボタンが 1 つでない",
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
    # 自動更新 (3 秒間隔) で統合済みと分かっても、シートを消さず、画面を再描画しない
    st.mark_merged(KEY_A)
    waitfor(lambda: page.locator(".livebar button").is_visible(), "バナー", check, timeout=9.0)
    check(page.locator(".mergesheet").count() == 1, "merge: 自動更新でシートが消えた")
    check(
        page.locator(".livebar button").is_visible(),
        "merge: 実行中に画面が再描画された (バナーが消えた)",
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
    page.wait_for_selector(".prhead")
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
    page.wait_for_selector(".prhead")
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


def browser_main(shots: pathlib.Path | None) -> int:
    """子プロセスで動く本体。失敗は JSON で標準出力へ。"""
    from playwright.sync_api import Error as PlaywrightError
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
        try:
            br = pw.chromium.launch(executable_path=chrome)
        except (
            PlaywrightError
        ) as exc:  # 起動そのものの失敗だけを skip にする (起動後の失敗は fails に出る)
            print(
                json.dumps(
                    {"skip": f"Chromium を起動できない: {str(exc).splitlines()[0]}"},
                    ensure_ascii=False,
                )
            )
            return SKIP_CODE
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
            flow_diff_view(page, kind, check, shots)
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
                page.locator(".thread, .revbar, #app textarea").count() == 0,
                f"{kind} app.ts の差分にコメントの部品が残っている",
            )

            # 統合済みの PR
            page.goto(f"{base}/#/pr/{merged_id}")
            page.wait_for_selector("text=変更ファイル (1)")
            check(
                "✓ 統合済み" in page.inner_text(".prhead"), f"{kind} 統合済みの概要にチップが無い"
            )
            check(
                page.locator(".revbar, #app textarea, .mergecard button, .mergebar button").count()
                == 0,
                f"{kind} 統合済みの PR で入力や統合ができてしまう",
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
                page.locator("tr.thr").count() == 0,
                f"{kind} 差分にスレッドの行がある",
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
        flow_hub_light(br, check)
        flow_markdown(br, check)
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
