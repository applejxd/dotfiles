"""imozuru (vendor したスキル) の、この dotfiles 側の追加を検査する。上流の挙動は検査しない。

- 書き込み先を `.tmp/research/` の中に限る `confine()` (リンクの拒否・根の固定を含む)
- 外へ送る文字列の秘匿チェック `refuse_secrets()`
- 検証した IP にだけ接続する `imozuru_net` (DNS rebinding への対策)
- 4 つのスクリプトが、これらを実際に通すこと

see docs/spec/imozuru.md
"""

from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "home" / "dot_claude" / "skills" / "imozuru"
SCRIPTS = SKILL / "scripts"
PUBLIC = "93.184.215.14"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def work(tmp_path, monkeypatch):
    """作業ツリー (cwd) と、その中の置き場 .tmp/research/。"""
    monkeypatch.delenv("IMOZURU_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    root = tmp_path / ".tmp" / "research"
    root.mkdir(parents=True)
    return tmp_path, root


# ─── confine ────────────────────────────────────────────────────────


def test_confine_accepts_the_root_and_anything_inside(work):
    _, root = work
    mod = _load("imozuru_root")
    assert mod.confine(Path(".tmp/research")) == root.resolve()
    assert mod.confine(Path(".tmp/research/topic")) == (root / "topic").resolve()
    assert mod.confine(root / "topic" / "sources") == (root / "topic" / "sources").resolve()


@pytest.mark.parametrize("outside", [".", "docs", ".tmp", ".tmp/other", "../elsewhere", "/etc"])
def test_confine_refuses_everything_outside_the_root(work, outside, capsys):
    mod = _load("imozuru_root")
    with pytest.raises(SystemExit) as stop:
        mod.confine(Path(outside))
    assert stop.value.code == 2
    assert "拒否" in capsys.readouterr().err


def test_confine_refuses_dotdot_that_leaves_the_root(work):
    mod = _load("imozuru_root")
    with pytest.raises(SystemExit):
        mod.confine(Path(".tmp/research/topic/../../../escape"))


def test_confine_refuses_a_symlink_that_points_outside(work):
    tmp, root = work
    outside = tmp / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    mod = _load("imozuru_root")
    with pytest.raises(SystemExit):
        mod.confine(root / "link")
    with pytest.raises(SystemExit):
        mod.confine(root / "link" / "sources")


@pytest.mark.parametrize("child", ["watch", "sources", ".report.html.tmp", "watch.tsv"])
def test_confine_refuses_a_symlink_inside_the_topic(work, child):
    """渡したディレクトリの中の子 (これから書く先) がリンクなら、解決した先が外でも中でも拒否する。"""
    tmp, root = work
    outside = tmp / "outside"
    outside.mkdir()
    (root / "t").mkdir()
    mod = _load("imozuru_root")
    assert mod.confine(root / "t") == (root / "t").resolve()
    (root / "t" / child).symlink_to(outside, target_is_directory=True)
    with pytest.raises(SystemExit):
        mod.confine(root / "t")
    (root / "t" / child).unlink()
    (root / "other").mkdir()
    (root / "t" / child).symlink_to(root / "other", target_is_directory=True)
    with pytest.raises(SystemExit):
        mod.confine(root / "t")


def test_confine_refuses_a_root_that_is_a_symlink(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    real = tmp_path / "real"
    (real / "research").mkdir(parents=True)
    (tmp_path / ".tmp").symlink_to(real, target_is_directory=True)
    mod = _load("imozuru_root")
    with pytest.raises(SystemExit):
        mod.confine(Path(".tmp/research/topic"))


def test_confine_root_cannot_be_moved_with_an_environment_variable(work, monkeypatch):
    tmp, _ = work
    other = tmp / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("IMOZURU_ROOT", str(other))
    mod = _load("imozuru_root")
    with pytest.raises(SystemExit):
        mod.confine(other / "topic")


def test_confine_refuses_a_directory_with_too_many_entries(work, monkeypatch):
    _, root = work
    (root / "t").mkdir()
    for i in range(5):
        (root / "t" / f"f{i}.txt").write_text("x", encoding="utf-8")
    mod = _load("imozuru_root")
    monkeypatch.setattr(mod, "MAX_ENTRIES", 3)
    with pytest.raises(SystemExit):
        mod.confine(root / "t")


# ─── 秘匿チェック ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    ["ghp_" + "a" * 30, "AKIA" + "A" * 16, "password = hunter2hunter2", "http://192.168.0.5/x"],
)
def test_refuse_secrets_stops_secret_looking_text(text, capsys):
    mod = _load("imozuru_root")
    with pytest.raises(SystemExit) as stop:
        mod.refuse_secrets("検索語", text)
    assert stop.value.code == 2
    assert "外へ送らない" in capsys.readouterr().err


def test_refuse_secrets_lets_ordinary_queries_through():
    mod = _load("imozuru_root")
    mod.refuse_secrets("検索語", "berrypicking Bates 1989")
    mod.refuse_secrets("URL", "https://arxiv.org/abs/2401.12345")


def test_refuse_secrets_falls_back_when_web_search_is_missing(monkeypatch):
    mod = _load("imozuru_root")
    monkeypatch.setattr(mod, "_websearch_check", lambda: None)
    with pytest.raises(SystemExit):
        mod.refuse_secrets("検索語", "AKIA" + "B" * 16)
    mod.refuse_secrets("検索語", "berrypicking")


# ─── 接続の固定 ─────────────────────────────────────────────────────


def _infos(*addresses):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 80)) for a in addresses]


@pytest.fixture
def net(monkeypatch):
    monkeypatch.delenv("IMOZURU_ALLOW_PRIVATE", raising=False)
    mod = _load("imozuru_net")
    monkeypatch.setattr(mod.urllib.request, "getproxies", dict)
    return mod


def test_pinned_connection_goes_to_the_checked_ip_only(net, monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _infos(PUBLIC))
    monkeypatch.setattr(
        socket, "create_connection", lambda addr, *a, **k: calls.append(addr) or "sock"
    )
    assert net.connect_pinned("example.test", 80, 5) == "sock"
    assert calls == [(PUBLIC, 80)]  # 名前ではなく IP で接続する


def test_dns_rebinding_is_not_followed(net, monkeypatch):
    """1 回目は公開 IP、2 回目は 127.0.0.1 を返す名前。引くのは 1 回だけで、接続先は 1 回目の IP。"""
    answers = [_infos(PUBLIC), _infos("127.0.0.1")]
    lookups = []

    def getaddrinfo(*args, **kwargs):
        lookups.append(args[0])
        return answers[min(len(lookups) - 1, 1)]

    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(
        socket, "create_connection", lambda addr, *a, **k: calls.append(addr) or "sock"
    )
    net.connect_pinned("rebind.test", 80, 5)
    assert lookups == ["rebind.test"]
    assert calls == [(PUBLIC, 80)]


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.5",),
        ("169.254.169.254",),
        (PUBLIC, "127.0.0.1"),
        ("::ffff:127.0.0.1",),
    ],
)
def test_private_or_mixed_answers_are_refused(net, monkeypatch, addresses):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _infos(*addresses))
    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **k: pytest.fail("接続してはいけない")
    )
    with pytest.raises(OSError, match="接続しない"):
        net.connect_pinned("example.test", 80, 5)


def _opened_with(handler, request):
    """ハンドラが、この要求にどの接続クラスを使うかを調べる (通信はしない)。"""
    used = []
    handler.do_open = lambda conn, req, **kw: used.append(conn)
    if request.type == "https":
        handler.https_open(request)
    else:
        handler.http_open(request)
    return used[0]


def test_direct_requests_use_the_pinned_connection_even_when_a_proxy_is_in_the_environment(
    net, monkeypatch
):
    """環境にプロキシがあっても、no_proxy などで直接つなぐ要求には固定を掛ける (プロキシ宛てかは要求で見る)。"""
    monkeypatch.setattr(
        net.urllib.request, "getproxies", lambda: {"https": "http://127.0.0.1:3128"}
    )
    http_req = net.urllib.request.Request("http://direct.test/")
    https_req = net.urllib.request.Request("https://direct.test/")
    assert _opened_with(net.PinnedHTTPHandler(), http_req) is net._PinnedHTTPConnection
    assert _opened_with(net.PinnedHTTPSHandler(), https_req) is net._PinnedHTTPSConnection


def test_proxied_requests_keep_the_stdlib_connection(net):
    """プロキシ宛て (HTTP のプロキシ、HTTPS の CONNECT) は、プロキシが名前を引くので stdlib のまま。"""
    http_req = net.urllib.request.Request("http://far.test/")
    http_req.set_proxy("127.0.0.1:3128", "http")
    https_req = net.urllib.request.Request("https://far.test/")
    https_req.set_proxy("127.0.0.1:3128", "https")
    assert _opened_with(net.PinnedHTTPHandler(), http_req) is net.http.client.HTTPConnection
    assert _opened_with(net.PinnedHTTPSHandler(), https_req) is net.http.client.HTTPSConnection


def test_the_opener_refuses_a_name_that_resolves_inside(net, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _infos("127.0.0.1"))
    opener = net.urllib.request.build_opener(net.PinnedHTTPHandler, net.PinnedHTTPSHandler)
    with pytest.raises(urllib.error.URLError, match="接続しない"):
        opener.open("http://rebind.test:9/", timeout=2)
    with pytest.raises(urllib.error.URLError, match="接続しない"):
        opener.open("https://rebind.test:9/", timeout=2)


def test_fetch_and_watch_use_the_pinned_handlers():
    for name in ("fetch", "watch"):
        text = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
        assert "build_opener(_Redirect308, PinnedHTTPHandler, PinnedHTTPSHandler)" in text, name


def test_ytdlp_is_started_without_user_config_and_stdin():
    text = (SCRIPTS / "fetch.py").read_text(encoding="utf-8")
    assert '["yt-dlp", "--ignore-config", "--no-update"' in text
    assert 'kwargs.setdefault("stdin", subprocess.DEVNULL)' in text


# ─── スクリプト ─────────────────────────────────────────────────────


def _run(script, *args, cwd, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k != "IMOZURU_ROOT"}
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    ("script", "args"),
    [
        # 置き場の外を渡されたら、通信も書き込みもせずに止まる (URL は到達できない宛先。拒否が先に起きることを見る)
        ("fetch.py", ["../outside", "paper", "https://example.invalid/x"]),
        ("fetch.py", ["docs/sources", "paper", "https://example.invalid/x"]),
        ("report.py", ["../outside"]),
        ("watch.py", ["list", "../outside"]),
        ("watch.py", ["add", "../outside", "https://example.invalid/feed"]),
        ("watch.py", ["check", "../outside"]),
    ],
)
def test_scripts_refuse_a_directory_outside_the_root_before_doing_anything(work, script, args):
    tmp, _ = work
    proc = _run(script, *args, cwd=tmp)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "拒否" in proc.stderr, proc.stderr
    assert not (tmp.parent / "outside").exists()
    assert not (tmp / "docs").exists()


def test_scripts_refuse_a_topic_that_contains_a_symlink(work):
    tmp, root = work
    (tmp / "outside").mkdir()
    (root / "t" / "sources").mkdir(parents=True)
    (root / "t" / "watch").symlink_to(tmp / "outside", target_is_directory=True)
    for script, args in (
        ("watch.py", ["check", ".tmp/research/t"]),
        ("report.py", [".tmp/research/t"]),
        ("fetch.py", [".tmp/research/t", "paper", "https://example.invalid/x"]),
    ):
        proc = _run(script, *args, cwd=tmp)
        assert proc.returncode == 2 and "シンボリックリンク" in proc.stderr, (
            script,
            proc.stdout,
            proc.stderr,
        )
    assert not any((tmp / "outside").iterdir())


@pytest.mark.parametrize(
    ("script", "args"),
    [
        (
            "fetch.py",
            [".tmp/research/t/sources", "paper", "https://example.com/?token=abcdefghijkl"],
        ),
        ("chain.py", ["find", "ghp_" + "a" * 30]),
        ("watch.py", ["add", ".tmp/research/t", "https://example.com/feed?api_key=abcdefghijkl"]),
    ],
)
def test_scripts_refuse_secret_looking_text_before_sending(work, script, args):
    tmp, _ = work
    proc = _run(script, *args, cwd=tmp)
    assert proc.returncode == 2 and "外へ送らない" in proc.stderr, proc.stdout + proc.stderr


def test_fetch_inside_the_root_gets_past_the_confinement(work):
    """置き場の中なら拒否されない。宛先が私的アドレスなので、その検査で止まる (通信はしない)。"""
    tmp, _ = work
    proc = _run("fetch.py", ".tmp/research/t/sources", "paper", "http://127.0.0.1:9/x", cwd=tmp)
    assert "拒否" not in proc.stderr
    assert "FAIL" in proc.stdout, proc.stdout + proc.stderr
    assert (tmp / ".tmp" / "research" / "t" / "sources").is_dir()


# ─── ハードリンク ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("child", ["watch.tsv", ".report.html.tmp", "sources/paper.txt"])
def test_confine_refuses_a_hard_link_to_a_file_outside(work, child):
    """置き場の中のファイルが外の実体へのハードリンクだと、追記・上書きが外へ届く。"""
    tmp, root = work
    outside = tmp / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    (root / "t" / "sources").mkdir(parents=True)
    mod = _load("imozuru_root")
    assert mod.confine(root / "t") == (root / "t").resolve()
    os.link(outside, root / "t" / child)
    with pytest.raises(SystemExit) as stop:
        mod.confine(root / "t")
    assert stop.value.code == 2


def test_confine_accepts_ordinary_files_with_one_link(work):
    _, root = work
    (root / "t" / "sources").mkdir(parents=True)
    (root / "t" / "sources" / "paper.txt").write_text("x", encoding="utf-8")
    (root / "t" / "map.md").write_text("x", encoding="utf-8")
    mod = _load("imozuru_root")
    assert mod.confine(root / "t") == (root / "t").resolve()


# ─── YouTube (yt-dlp) ──────────────────────────────────────────────────────────────


def test_youtube_is_only_allowed_through_the_wrapper():
    mod = _load("imozuru_root")
    assert "fetch_youtube.py" in mod.youtube_problem()
    assert mod.youtube_problem(False) == mod.youtube_problem()
    assert mod.youtube_problem(True) is None


def _no_ytdlp_env(tmp):
    """yt-dlp が見つからない PATH (関門を通ったあとは「yt-dlp が無い」で止めて、通信しない)。"""
    empty = tmp / "empty-bin"
    empty.mkdir()
    return {"PATH": str(empty)}


def test_fetch_refuses_youtube_even_with_the_old_environment_variable(work):
    """fetch.py は YouTube を通さない。環境変数では切り替えられない (継承されても迂回できない)。"""
    tmp, _ = work
    proc = _run(
        "fetch.py",
        ".tmp/research/t/sources",
        "talk",
        "https://www.youtube.com/watch?v=abc",
        cwd=tmp,
        extra_env={**_no_ytdlp_env(tmp), "IMOZURU_ALLOW_YOUTUBE": "1"},
    )
    assert proc.returncode == 1 and proc.stdout.startswith("FAIL\ttalk\t"), (
        proc.stdout + proc.stderr
    )
    assert "fetch_youtube.py" in proc.stdout
    assert "yt-dlp が無い" not in proc.stdout


def test_the_youtube_wrapper_gets_past_the_gate(work):
    """fetch_youtube.py 経由なら関門を通る (ここでは yt-dlp を無い PATH にして、その先で止める)。"""
    tmp, _ = work
    proc = _run(
        "fetch_youtube.py",
        ".tmp/research/t/sources",
        "talk",
        "https://www.youtube.com/watch?v=abc",
        cwd=tmp,
        extra_env=_no_ytdlp_env(tmp),
    )
    assert proc.returncode == 1 and "yt-dlp が無い" in proc.stdout, proc.stdout + proc.stderr
    assert "fetch_youtube.py で呼ぶ" not in proc.stdout


def test_the_youtube_wrapper_still_goes_through_confine_and_secret_checks(work):
    tmp, _ = work
    proc = _run(
        "fetch_youtube.py", "../outside", "talk", "https://www.youtube.com/watch?v=abc", cwd=tmp
    )
    assert proc.returncode == 2 and "拒否" in proc.stderr
    proc = _run(
        "fetch_youtube.py",
        ".tmp/research/t/sources",
        "talk",
        "https://www.youtube.com/watch?v=abc&token=abcdefghijkl",
        cwd=tmp,
    )
    assert proc.returncode == 2 and "外へ送らない" in proc.stderr


# ─── 見張る先 (feed) の URL ───────────────────────────────────────────────


def test_watch_checks_a_stored_feed_url_for_secrets_just_before_sending(work, monkeypatch):
    """add で保存した (外部のページが示した) URL も、後の check で送る直前に検査する。"""
    monkeypatch.syspath_prepend(str(SCRIPTS))
    watch = _load("watch")
    monkeypatch.setattr(watch, "resolve", lambda host: {PUBLIC}, raising=False)
    monkeypatch.setattr(
        watch, "_OPENER", type("O", (), {"open": lambda *a, **k: pytest.fail("送ってはいけない")})()
    )
    with pytest.raises(watch.UnsafeURL, match="らしき文字列"):
        watch.fetch_final("https://example.com/feed?api_key=abcdefghijkl")
