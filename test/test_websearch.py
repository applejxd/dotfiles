"""web-search の CLI (websearch.py) を、通信なしで検証する。

see docs/spec/web-search.md
"""

from __future__ import annotations

import importlib.util
import json
import re
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "home" / "dot_claude" / "skills" / "web-search" / "scripts" / "websearch.py"
_spec = importlib.util.spec_from_file_location("websearch", SCRIPT)
assert _spec and _spec.loader
ws = importlib.util.module_from_spec(_spec)
sys.modules["websearch"] = ws  # dataclass が自分のモジュールを引く
_spec.loader.exec_module(ws)


def resp(status=200, body=None, headers=None):
    data = body if isinstance(body, bytes) else json.dumps(body if body is not None else {}).encode()
    return status, {k.lower(): v for k, v in (headers or {}).items()}, data


BRAVE_OK = {"web": {"results": [{"title": "Brave A", "url": "https://a.example/x?utm_source=z", "description": "snip A"}]}}
EXA_OK = {"results": [{"title": "Exa B", "url": "https://b.example/", "highlights": ["hi B"], "publishedDate": "2026-01-01"}]}
TAVILY_OK = {"results": [{"title": "Tavily C", "url": "https://c.example/", "content": "body C"}]}
DDG_HTML = (
    '<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fd.example%2Fp&rut=x">DDG D</a>'
    '<a class="result__snippet" href="#">snip D</a></div>'
)


class FakeHttp:
    """URL のホストごとに、順に返す応答を並べる。鍵は応答に入れない。"""

    def __init__(self, plan):
        self.plan = {host: list(items) for host, items in plan.items()}
        self.calls = []

    def __call__(self, method, url, headers=None, body=None, timeout=15.0):
        host = url.split("/")[2]
        self.calls.append((host, method, headers or {}, body, url))
        queue = self.plan.get(host)
        if not queue:
            raise AssertionError(f"想定外の呼び出し: {host}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def hosts(self):
        return [c[0] for c in self.calls]


KEYS = {"brave": "kb", "exa": "ke", "tavily": "kt", "openalex": "ko"}


def state(tmp_path, now=lambda: 1000.0):
    return ws.State(tmp_path, now)


def run(http, tmp_path, keys=KEYS, **kw):
    return ws.run_search("query", 5, http=http, key_for=keys.get, state=state(tmp_path), sleep=lambda s: None, **kw)


# ─── 鎖 ─────────────────────────────────────────────────────────────


def test_first_provider_answers_and_urls_are_normalized(tmp_path):
    http = FakeHttp({"api.search.brave.com": [resp(body=BRAVE_OK)]})
    out = run(http, tmp_path)

    assert out.provider == "brave" and http.hosts == ["api.search.brave.com"]
    assert out.results[0].title == "Brave A"
    assert http.calls[0][2]["X-Subscription-Token"] == "kb"


@pytest.mark.parametrize(
    ("status", "headers"),
    [(429, {"Retry-After": "30"}), (500, {}), (503, {}), (401, {})],
)
def test_failures_fall_back_to_the_next_provider(tmp_path, status, headers):
    http = FakeHttp({"api.search.brave.com": [resp(status, {}, headers)], "api.exa.ai": [resp(body=EXA_OK)]})
    out = run(http, tmp_path)

    assert out.provider == "exa"
    assert out.attempts[0][0] == "brave" and out.attempts[0][1] != "ok"


def test_network_error_and_timeout_fall_back(tmp_path):
    http = FakeHttp(
        {"api.search.brave.com": [ws.ProviderError("network", "TimeoutError")], "api.exa.ai": [resp(body=EXA_OK)]}
    )
    assert run(http, tmp_path).provider == "exa"


def test_missing_keys_are_skipped_without_calling(tmp_path):
    http = FakeHttp({"api.tavily.com": [resp(body=TAVILY_OK)]})
    out = run(http, tmp_path, keys={"tavily": "kt"})

    assert out.provider == "tavily" and http.hosts == ["api.tavily.com"]
    assert ("brave", "no-key") in out.attempts and ("exa", "no-key") in out.attempts


def test_keyless_duckduckgo_is_the_last_resort(tmp_path):
    http = FakeHttp({"html.duckduckgo.com": [resp(body=DDG_HTML.encode())]})
    out = run(http, tmp_path, keys={})

    assert out.provider == "duckduckgo"
    assert out.results[0].url == "https://d.example/p" and out.results[0].snippet == "snip D"


def test_quota_exhaustion_disables_the_provider_for_a_day(tmp_path):
    clock = [1000.0]
    plan = {"api.search.brave.com": [resp(402)], "api.exa.ai": [resp(body=EXA_OK)]}
    http = FakeHttp(plan)
    ws.run_search("q", 5, http=http, key_for=KEYS.get, state=ws.State(tmp_path, lambda: clock[0]), sleep=lambda s: None)
    first_calls = http.hosts.count("api.search.brave.com")
    clock[0] += 3600
    out = ws.run_search("q", 5, http=http, key_for=KEYS.get, state=ws.State(tmp_path, lambda: clock[0]), sleep=lambda s: None)

    assert out.provider == "exa" and ("brave", "disabled") in out.attempts
    assert http.hosts.count("api.search.brave.com") == first_calls  # 休止中は呼ばない
    clock[0] += 24 * 3600
    assert ws.State(tmp_path, lambda: clock[0]).disabled_until("brave") == 0.0


def test_short_retry_after_is_honored_once(tmp_path):
    slept = []
    http = FakeHttp({"api.search.brave.com": [resp(429, {}, {"Retry-After": "1"}), resp(body=BRAVE_OK)]})
    out = ws.run_search("q", 5, http=http, key_for=KEYS.get, state=state(tmp_path), sleep=slept.append)

    assert out.provider == "brave" and slept == [1.0]


def test_input_error_is_not_forwarded_to_other_providers(tmp_path):
    http = FakeHttp({"api.search.brave.com": [resp(400)]})
    with pytest.raises(ws.ProviderError) as error:
        run(http, tmp_path)

    assert error.value.kind == "input" and http.hosts == ["api.search.brave.com"]


def test_empty_result_moves_on_once_then_stops(tmp_path):
    http = FakeHttp(
        {
            "api.search.brave.com": [resp(body={"web": {"results": []}})],
            "api.exa.ai": [resp(body={"results": []})],
            "api.tavily.com": [resp(body=TAVILY_OK)],
        }
    )
    out = run(http, tmp_path)

    assert out.results == [] and out.provider == "exa"
    assert "api.tavily.com" not in http.hosts  # 2 つ目も空なら、それ以上は回さない


def test_all_providers_failing_returns_no_provider(tmp_path):
    http = FakeHttp({h: [resp(500)] for h in ("api.search.brave.com", "api.exa.ai", "api.tavily.com", "html.duckduckgo.com")})
    out = run(http, tmp_path)

    assert out.provider is None and out.results == []


def test_duplicate_urls_are_removed():
    rs = [
        ws.Result("a", "https://x.example/p/?utm_source=a#frag"),
        ws.Result("b", "https://X.example/p"),
        ws.Result("c", "https://x.example/q"),
    ]
    assert [r.title for r in ws.dedupe(rs)] == ["a", "c"]


# ─── 鍵 ─────────────────────────────────────────────────────────────


def test_keys_come_from_env_then_file_then_bw(tmp_path, monkeypatch):
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps({"brave": "from-file", "exa": "file-exa"}), encoding="utf-8")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)

        class P:
            returncode = 0
            stdout = "from-bw\n"

        return P()

    monkeypatch.setattr(ws.shutil, "which", lambda name: "/bin/bw")
    env = {"BRAVE_API_KEY": "from-env", "BW_SESSION": "s"}
    assert ws.get_key("brave", env, keys_file, fake_run) == "from-env"
    assert ws.get_key("exa", env, keys_file, fake_run) == "file-exa"
    assert ws.get_key("tavily", env, keys_file, fake_run) == "from-bw"
    assert calls == [["/bin/bw", "get", "password", "websearch-tavily", "--nointeraction"]]
    assert ws.get_key("tavily", {}, keys_file, fake_run) is None  # BW_SESSION が無ければ bw を呼ばない
    assert len(calls) == 1


def test_bw_failure_returns_none_without_leaking(tmp_path, monkeypatch):
    class P:
        returncode = 1
        stdout = "secret-looking-output"

    monkeypatch.setattr(ws.shutil, "which", lambda name: "/bin/bw")
    assert ws.get_key("brave", {"BW_SESSION": "s"}, tmp_path / "none.json", lambda *a, **k: P()) is None


# ─── 秘匿チェック ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "-----BEGIN RSA PRIVATE KEY----- abc",
        "why does AKIAIOSFODNN7EXAMPLE fail",
        "ghp_" + "a" * 36,
        "password = hunter2hunter2",
        "error at 192.168.1.20 timeout",
        "db.corp unreachable",
        "token: " + "Ab1" * 20,
    ],
)
def test_sensitive_queries_are_blocked(query):
    assert ws.check_query(query)


@pytest.mark.parametrize(
    "query",
    ["Windows 11 AllowNewsAndInterests policy", "python asyncio TaskGroup cancel behavior", "ssh-keygen -t ed25519 options"],
)
def test_ordinary_queries_pass(query):
    assert ws.check_query(query) is None


def test_blocked_query_never_reaches_a_provider(tmp_path, capsys):
    http = FakeHttp({})
    deps = {"http": http, "key_for": KEYS.get, "cache_dir": tmp_path, "now": lambda: 1.0, "sleep": lambda s: None}
    code = ws.main(["search", "password = hunter2hunter2"], deps)

    assert code == 2 and http.calls == [] and "止めた" in capsys.readouterr().err


# ─── キャッシュ・出力 ───────────────────────────────────────────────


def test_cache_avoids_a_second_call_and_is_marked(tmp_path, capsys):
    http = FakeHttp({"api.search.brave.com": [resp(body=BRAVE_OK)]})
    deps = {"http": http, "key_for": KEYS.get, "cache_dir": tmp_path, "now": lambda: 1000.0, "sleep": lambda s: None}

    assert ws.main(["search", "hello world"], deps) == 0
    first = capsys.readouterr().out
    assert ws.main(["search", "hello world"], deps) == 0
    second = capsys.readouterr().out

    assert len(http.calls) == 1
    assert "(cache)" in second and "(cache)" not in first
    assert ws.UNTRUSTED in first


def test_cache_expires(tmp_path):
    ws.cache_put(tmp_path, "k", {"x": 1}, lambda: 0.0)
    assert ws.cache_get(tmp_path, "k", lambda: ws.CACHE_TTL - 1) is not None
    assert ws.cache_get(tmp_path, "k", lambda: ws.CACHE_TTL + 1) is None


def test_json_output_has_no_keys_and_lists_attempts(tmp_path, capsys):
    http = FakeHttp({"api.search.brave.com": [resp(500)], "api.exa.ai": [resp(body=EXA_OK)]})
    deps = {"http": http, "key_for": KEYS.get, "cache_dir": tmp_path, "now": lambda: 5.0, "sleep": lambda s: None}
    assert ws.main(["search", "q", "--json", "--no-cache"], deps) == 0
    out = capsys.readouterr().out
    data = json.loads(out)

    assert data["provider"] == "exa" and data["attempts"][0] == {"provider": "brave", "status": "server"}
    assert not any(v in out for v in KEYS.values())


def test_n_is_clamped(tmp_path):
    http = FakeHttp({"api.search.brave.com": [resp(body=BRAVE_OK)]})
    deps = {"http": http, "key_for": KEYS.get, "cache_dir": tmp_path, "now": lambda: 1.0, "sleep": lambda s: None}
    ws.main(["search", "q", "-n", "500", "--no-cache"], deps)

    assert "count=20" in http.calls[0][4]


# ─── 論文 ───────────────────────────────────────────────────────────


def test_papers_rebuild_the_abstract_and_use_the_optional_key(tmp_path, capsys):
    body = {
        "results": [
            {
                "display_name": "Paper X",
                "doi": "https://doi.org/10.1/x",
                "publication_year": 2025,
                "cited_by_count": 7,
                "authorships": [{"author": {"display_name": "A. Author"}}],
                "abstract_inverted_index": {"world": [1], "hello": [0]},
                "primary_location": {"landing_page_url": "https://paper.example/x"},
            }
        ]
    }
    http = FakeHttp({"api.openalex.org": [resp(body=body)]})
    deps = {"http": http, "key_for": KEYS.get, "cache_dir": tmp_path, "now": lambda: 1.0, "sleep": lambda s: None}
    assert ws.main(["papers", "graph", "--from-year", "2024"], deps) == 0
    out = capsys.readouterr().out

    assert "Paper X" in out and "hello world" in out and "2025 / A. Author / 被引用 7" in out
    assert http.calls[0][0] == "api.openalex.org"


# ─── 取得 (SSRF) ────────────────────────────────────────────────────


def resolver_to(*addresses):
    def resolve(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]

    return resolve


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://192.168.0.1/",
        "http://[::ffff:127.0.0.1]/",
        "file:///etc/passwd",
        "ftp://example.com/",
        "http://user:pw@example.com/",
        "http://example.com:8080/",
    ],
)
def test_unsafe_urls_are_blocked_before_connecting(url):
    def resolve(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1" if host == "localhost" else "93.184.216.34", port))]

    def transport(*a):
        raise AssertionError("接続してはいけない")

    with pytest.raises(ws.Blocked):
        ws.fetch_page(url, resolver=resolve, transport=transport)


def test_a_name_resolving_to_a_private_address_is_blocked():
    with pytest.raises(ws.Blocked):
        ws.fetch_page("https://rebind.example/", resolver=resolver_to("93.184.216.34", "10.0.0.1"), transport=lambda *a: None)


def test_redirect_to_an_internal_address_is_blocked():
    answers = {
        "https://ok.example/": (302, {"location": "http://169.254.169.254/"}, b""),
    }

    def resolve(host, port, **kw):
        ip = "169.254.169.254" if host == "169.254.169.254" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    def transport(parts, address, timeout):
        return answers[f"{parts.scheme}://{parts.netloc}{parts.path}"]

    with pytest.raises(ws.Blocked):
        ws.fetch_page("https://ok.example/", resolver=resolve, transport=transport)


def test_fetch_connects_to_the_validated_address_and_extracts_text():
    seen = []
    page = b"<html><head><title>T  itle</title><style>x{}</style></head><body><script>bad()</script><p>Hello</p><p>World</p></body></html>"

    def transport(parts, address, timeout):
        seen.append(address)
        return 200, {"content-type": "text/html; charset=utf-8"}, page

    out = ws.fetch_page("https://ok.example/p", resolver=resolver_to("93.184.216.34"), transport=transport)

    assert seen == ["93.184.216.34"]
    assert out["title"] == "T itle" and "Hello" in out["text"] and "World" in out["text"]
    assert "bad()" not in out["text"] and "x{}" not in out["text"]


def test_fetch_limits_and_content_types():
    big = b"a" * 50_000

    def transport(parts, address, timeout):
        return 200, {"content-type": "text/plain"}, big

    out = ws.fetch_page("https://ok.example/", resolver=resolver_to("93.184.216.34"), transport=transport, max_chars=1000)
    assert len(out["text"]) == 1000 and out["truncated"]

    with pytest.raises(ws.Blocked):
        ws.fetch_page(
            "https://ok.example/a.pdf",
            resolver=resolver_to("93.184.216.34"),
            transport=lambda *a: (200, {"content-type": "application/pdf"}, b"%PDF"),
        )


def test_too_many_redirects_are_stopped():
    def transport(parts, address, timeout):
        return 302, {"location": "https://ok.example/again"}, b""

    with pytest.raises(ws.Blocked):
        ws.fetch_page("https://ok.example/", resolver=resolver_to("93.184.216.34"), transport=transport)


def test_status_never_prints_a_key(tmp_path, capsys):
    deps = {"key_for": KEYS.get, "cache_dir": tmp_path, "now": lambda: 1.0}
    assert ws.main(["status"], deps) == 0
    out = capsys.readouterr().out

    assert "brave: 鍵あり" in out and "duckduckgo: 鍵なし (使う)" in out
    assert not any(v in out for v in KEYS.values())


# ─── 鍵ファイルの作成 (sync-keys) ───────────────────────────────────


class FakeBw:
    def __init__(self, items, session="fake-session"):
        self.items = items
        self.session = session
        self.calls = []
        self.envs = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        self.envs.append(kw.get("env") or {})
        sub = cmd[1]

        class P:
            returncode = 0
            stdout = ""

        if sub == "sync":
            return P()
        if sub == "unlock":
            P.returncode = 0 if self.session else 1
            P.stdout = (self.session or "") + "\n"
            return P()
        value = self.items.get(cmd[3])
        P.returncode = 0 if value else 1
        P.stdout = (value or "") + "\n"
        return P()

    @property
    def subcommands(self):
        return [c[1] for c in self.calls]


@pytest.fixture
def bw_ready(monkeypatch):
    monkeypatch.setattr(ws.shutil, "which", lambda name: "/bin/bw")
    return {"BW_SESSION": "s"}


def test_sync_keys_writes_the_available_items_and_reports_the_rest(tmp_path, bw_ready, capsys):
    keys = tmp_path / "websearch-keys.json"
    bw = FakeBw({"websearch-brave": "secret-brave", "websearch-exa": "secret-exa"})
    added, missing = ws.sync_keys(bw_ready, bw, keys)

    assert added == ["brave", "exa"] and missing == ["tavily", "openalex"]
    assert json.loads(keys.read_text(encoding="utf-8")) == {"brave": "secret-brave", "exa": "secret-exa"}
    if ws.os.name != "nt":
        assert keys.stat().st_mode & 0o777 == 0o600


def test_sync_keys_keeps_existing_values_unless_forced(tmp_path, bw_ready):
    keys = tmp_path / "websearch-keys.json"
    keys.write_text(json.dumps({"brave": "old"}), encoding="utf-8")
    bw = FakeBw({"websearch-brave": "new", "websearch-exa": "e"})

    ws.sync_keys(bw_ready, bw, keys)
    assert json.loads(keys.read_text(encoding="utf-8")) == {"brave": "old", "exa": "e"}
    assert ["/bin/bw", "get", "password", "websearch-brave", "--nointeraction"] not in bw.calls  # 既にあれば bw を引かない

    ws.sync_keys(bw_ready, bw, keys, force=True)
    assert json.loads(keys.read_text(encoding="utf-8"))["brave"] == "new"


def test_sync_keys_without_a_session_or_bw_does_nothing(tmp_path, monkeypatch):
    keys = tmp_path / "websearch-keys.json"
    bw = FakeBw({"websearch-brave": "x"})
    monkeypatch.setattr(ws.shutil, "which", lambda name: "/bin/bw")
    assert ws.sync_keys({}, bw, keys)[0] == []  # BW_SESSION なし
    monkeypatch.setattr(ws.shutil, "which", lambda name: None)
    assert ws.sync_keys({"BW_SESSION": "s"}, bw, keys)[0] == []  # bw なし
    assert bw.calls == [] and not keys.exists()


def test_sync_keys_creates_no_file_when_nothing_was_found(tmp_path, bw_ready):
    keys = tmp_path / "websearch-keys.json"
    assert ws.sync_keys(bw_ready, FakeBw({}), keys) == ([], list(ws.KEY_NAMES))
    assert not keys.exists()


def test_sync_keys_command_never_prints_a_key(tmp_path, bw_ready, monkeypatch, capsys):
    keys = tmp_path / "websearch-keys.json"
    bw = FakeBw({"websearch-brave": "top-secret-value"})
    monkeypatch.setenv("BW_SESSION", "s")
    assert ws.main(["sync-keys"], {"run": bw, "keys_file": keys, "cache_dir": tmp_path}) == 0
    out = capsys.readouterr()

    assert "top-secret-value" not in out.out + out.err and "added=['brave']" in out.out
    assert json.loads(keys.read_text(encoding="utf-8"))["brave"] == "top-secret-value"


# ─── chezmoi のスクリプト (鍵ファイルの作成) ───────────────────────────

UNIX_KEYS_SCRIPT = ROOT / "home/.chezmoiscripts/400_unix/run_after_441_websearch_keys.sh.tmpl"
WINDOWS_KEYS_SCRIPT = ROOT / "home/.chezmoiscripts/300_windows/run_after_349_websearch_keys.ps1.tmpl"


@pytest.mark.parametrize("path", [UNIX_KEYS_SCRIPT, WINDOWS_KEYS_SCRIPT])
def test_key_scripts_are_personal_and_never_stop_apply(path):
    text = path.read_text(encoding="utf-8-sig")
    backslash = chr(92)

    assert "(^|" + backslash * 4 + ")applejxd$" in text  # applejxd の機械だけ (chezmoi のテンプレートでは \ を 4 つ書く)
    assert "BW_SESSION" in text and "sync-keys" in text
    assert "DOTFILES_RESYNC_WEBSEARCH_KEYS" in text
    # 認証を求めて apply を入力待ちにしない (コメントの手順以外に bw unlock を実行しない)。失敗しても 0 で終わる
    assert not [line for line in text.splitlines() if re.match(r"\s*(bw unlock|& bw|\$env:BW_SESSION\s*=)", line)]
    assert "skip" in text.lower()
    # 鍵そのものを書き出す処理が無い (書くのは websearch.py だけ)
    assert "Set-Content" not in text and "Out-File" not in text and "bw get" not in text


def test_windows_key_script_is_saved_with_a_bom():
    assert WINDOWS_KEYS_SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_sync_keys_syncs_the_vault_once_before_reading(tmp_path, bw_ready):
    bw = FakeBw({"websearch-brave": "b"})
    ws.sync_keys(bw_ready, bw, tmp_path / "k.json")

    assert bw.subcommands[0] == "sync" and bw.subcommands.count("sync") == 1
    assert bw.subcommands.count("get") == 4


def test_sync_keys_with_all_keys_present_does_not_touch_bw(tmp_path, bw_ready):
    keys = tmp_path / "k.json"
    keys.write_text(json.dumps({n: "x" for n in ws.KEY_NAMES}), encoding="utf-8")
    bw = FakeBw({})

    assert ws.sync_keys(bw_ready, bw, keys) == ([], [])
    assert bw.calls == []  # 同期もしない (apply のたびに bw を呼ばない)


def test_sync_keys_can_unlock_when_there_is_no_session(tmp_path, monkeypatch):
    monkeypatch.setattr(ws.shutil, "which", lambda name: "/bin/bw")
    keys = tmp_path / "k.json"
    bw = FakeBw({"websearch-exa": "e"}, session="unlocked")
    added, missing = ws.sync_keys({}, bw, keys, unlock=True)

    assert bw.subcommands[:2] == ["unlock", "sync"]
    assert bw.envs[1]["BW_SESSION"] == "unlocked"  # unlock で得たセッションを、以降の bw に渡す
    assert added == ["exa"] and missing == ["brave", "tavily", "openalex"]


def test_sync_keys_does_not_unlock_unless_asked_or_when_unlock_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ws.shutil, "which", lambda name: "/bin/bw")
    bw = FakeBw({"websearch-brave": "b"})
    assert ws.sync_keys({}, bw, tmp_path / "k.json", unlock=False)[0] == [] and bw.calls == []

    failing = FakeBw({"websearch-brave": "b"}, session="")
    assert ws.sync_keys({}, failing, tmp_path / "k.json", unlock=True)[0] == []
    assert failing.subcommands == ["unlock"]


def test_sync_keys_prompts_to_unlock_only_with_the_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("BW_SESSION", raising=False)
    monkeypatch.setattr(ws.shutil, "which", lambda name: "/bin/bw")
    keys = tmp_path / "k.json"
    plain = FakeBw({"websearch-brave": "b"})
    assert ws.main(["sync-keys"], {"run": plain, "keys_file": keys, "cache_dir": tmp_path}) == 0
    assert plain.calls == [] and "--unlock" in capsys.readouterr().out  # 既定 (chezmoi apply) では求めない

    asked = FakeBw({"websearch-brave": "b"})
    assert ws.main(["sync-keys", "--unlock"], {"run": asked, "keys_file": keys, "cache_dir": tmp_path}) == 0
    assert asked.subcommands[:2] == ["unlock", "sync"]
    assert json.loads(keys.read_text(encoding="utf-8")) == {"brave": "b"}


def test_search_provider_option_uses_only_that_provider_and_skips_the_cache(tmp_path, capsys):
    http = FakeHttp({"api.exa.ai": [resp(body=EXA_OK)]})
    deps = {"http": http, "key_for": KEYS.get, "cache_dir": tmp_path, "now": lambda: 1000.0, "sleep": lambda s: None}

    assert ws.main(["search", "hello", "--provider", "exa"], deps) == 0
    out = capsys.readouterr().out
    assert "provider=exa" in out and http.hosts == ["api.exa.ai"]
    assert not (tmp_path / "search").exists()  # 鍵の確認用なのでキャッシュしない

    failing = FakeHttp({"api.exa.ai": [resp(401)]})
    deps["http"] = failing
    assert ws.main(["search", "hello", "--provider", "exa"], deps) == 3
    assert failing.hosts == ["api.exa.ai"]  # 失敗しても、ほかのプロバイダへ回さない
