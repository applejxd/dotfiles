"""PR ビューア 段 1 の画面（apps/pr-viewer/web/）の試験。

1. 静的検査: 描画の安全規則（XSS を防ぐ規則）と配信の規則（CSP）に違反する記述が無いこと。
   検査関数そのものが違反を検出できることを、違反の断片で先に確かめる。
2. 描画の smoke: 契約どおりの JSON を返す小さな HTTP サーバと web/ を配信し、ヘッドレス Chromium で
   一覧・概要・差分を開く。敵対的な文字列が文字として表示され、実行されないことも確かめる。
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


# --- 実ファイル ---


def test_web_dir_has_files() -> None:
    names = {p.name for p in web_files()}
    assert {"index.html", "app.css", "api.js", "core.js"} <= names


def test_only_allowed_file_kinds() -> None:
    """サーバの許可リスト（index.html・app.css・*.js）に載る種類だけ置く。"""
    for p in web_files():
        assert p.name in ("index.html", "app.css") or p.suffix == ".js", p.name


@pytest.mark.parametrize("path", [p for p in WEB.glob("*.js")], ids=lambda p: p.name)
def test_js_has_no_forbidden_api(path: pathlib.Path) -> None:
    assert scan(path.read_text(encoding="utf-8"), JS_RULES) == []


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


def api_response(path: str) -> tuple[int, dict]:
    """契約の 4 エンドポイントを fixture から返す。"""
    u = urllib.parse.urlparse(path)
    parts = [p for p in u.path.split("/") if p]
    err = (404, {"error": {"code": "not_found", "message": "見つかりません。"}})
    if parts == ["api", "repos"]:
        return 200, load_fixture("repos.json")
    if parts == ["api", "prs"]:
        return 200, load_fixture("prs.json")
    if len(parts) in (4, 5) and parts[:2] == ["api", "prs"]:
        pr = next(
            (p for p in load_fixture("prs.json")["prs"] if p["id"] == f"{parts[2]}/{parts[3]}"),
            None,
        )
        if pr is None:
            return err
        if len(parts) == 4:
            return 200, {"pr": pr, **load_fixture(f"detail_{parts[3]}.json")}
        if parts[4] == "diff":
            q = urllib.parse.parse_qs(u.query)
            if "path" not in q:
                return 400, {
                    "error": {"code": "bad_request", "message": "指定が正しくありません。"}
                }
            return 200, load_fixture(f"diff_{parts[3]}.json")
    return err


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

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            code, data = api_response(self.path)
            self._send(
                code,
                json.dumps(data, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )
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
    srv, base = serve()
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
                lambda r, errs=errs: (
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

            # 統合済みの PR
            page.goto(f"{base}/#/pr/{merged_id}")
            page.wait_for_selector("text=変更ファイル (1)")
            check(
                "✓ 統合済み" in page.inner_text(".prhead"), f"{kind} 統合済みの概要にチップが無い"
            )

            # 敵対的な PR: 概要・差分
            page.goto(f"{base}/#/pr/{evil_id}")
            page.wait_for_selector("text=変更ファイル (1)")
            check(
                EVIL in page.inner_text("h1"),
                f"{kind} 概要の見出しに敵対的な文字列が文字として出ていない",
            )
            check(EVIL in text(), f"{kind} 概要のコミット件名・パスが文字として出ていない")
            page.locator(".tabs a", has_text="差分").click()
            page.wait_for_selector("table.diff")
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
            errs = [e for e in errs if "404" not in e]  # 404 の資源エラーはこの意図した操作で出る
            check(errs == [], f"{kind} console/通信の異常: {errs}")
            ctx.close()
        br.close()
    srv.shutdown()
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
