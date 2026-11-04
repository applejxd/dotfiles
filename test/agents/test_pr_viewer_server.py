"""PR ビューア 段 1 のサーバ (``apps/pr-viewer/server.ts``。案件 CHG-0060)。

使い捨てのリポジトリを ``tmp_path`` に作り、node の型除去でサーバを起動して HTTP で確かめる
(node 22.18 未満では飛ばす)。確かめるのは、承認の前に外部のコードを動かさないこと (敵対的な設定のリポジトリ)、
読み取り専用であること、契約 (``.tmp/keep/prv-app/api-contract.md``) どおりの応答、入力・Host の検査、パスを漏らさないこと。

see docs/change/0060-local-pr-viewer.md
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import pty
import select
import subprocess
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

APP = ROOT / "apps" / "pr-viewer"
SERVER = APP / "server.ts"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

_clock = [1_700_000_000]


def _git(repo: Path, *args: str, check: bool = True) -> str:
    """試験の準備用の素の git。利用者の設定は読まない。コミットの時刻は 1 分ずつ進める。"""
    _clock[0] += 60
    stamp = f"{_clock[0]} +0000"
    env = {
        **{
            k: v
            for k, v in os.environ.items()
            if k not in ("GIT_PAGER", "PAGER", "GIT_EXTERNAL_DIFF")
        },
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Example Dev",
        "GIT_AUTHOR_EMAIL": "you@example.com",
        "GIT_COMMITTER_NAME": "Example Dev",
        "GIT_COMMITTER_EMAIL": "you@example.com",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if check:
        assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout


def _commit(repo: Path, files: dict[str, str | bytes], message: str) -> None:
    for name, body in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _init(path: Path, default: str = "develop") -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", default)
    return path


def _repo_id(repo: Path) -> str:
    common = (repo / ".git").resolve()
    return "r" + hashlib.sha256(str(common).encode()).hexdigest()[:8]


def _pr_key(branch: str) -> str:
    return "p" + hashlib.sha256(f"v1\0refs/heads/{branch}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------- サーバの起動


class Server:
    def __init__(self, args: list[str]):
        self.proc = subprocess.Popen(
            [_node(), str(SERVER), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
        )
        ready, _, _ = select.select([self.proc.stdout], [], [], 30)
        assert ready, "サーバが 30 秒以内に起動しなかった"
        self.line = self.proc.stdout.readline().strip()
        assert self.line.startswith("listening http://127.0.0.1:"), self.line
        self.port = int(self.line.rsplit(":", 1)[1])

    def request(self, path: str, method: str = "GET", host: str | None = "127.0.0.1"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        if host is not None:
            conn.putheader("Host", host)
        conn.endheaders()
        resp = conn.getresponse()
        body = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, headers, body

    def get(self, path: str, **kw):
        status, _, body = self.request(path, **kw)
        return status, json.loads(body.decode("utf-8"))

    def stop(self) -> int:
        self.proc.terminate()
        try:
            code = self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            code = self.proc.wait()
        self.proc.stdout.close()
        self.proc.stderr.close()
        return code


def _web_dir(path: Path) -> Path:
    web = path / "web"
    (web / "sub").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    (web / "app.css").write_text("body{}", encoding="utf-8")
    (web / "app.js").write_text("console.log(1)", encoding="utf-8")
    (web / "secret.txt").write_text("secret", encoding="utf-8")
    (web / "sub" / "x.js").write_text("1", encoding="utf-8")
    (path / "outside.js").write_text("outside", encoding="utf-8")
    (web / "link.js").symlink_to(path / "outside.js")
    return web


# ---------------------------------------------------------------- 通常のリポジトリ


class World:
    pass


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("world")
    w = World()
    w.base = base
    repo = _init(base / "example-app")
    w.repo = repo
    old_lines = "".join(f"古い行 {i}\n" for i in range(30))
    _commit(
        repo, {"README.md": "hello\nworld\n", "old.txt": old_lines, "keep.txt": "keep\n"}, "init"
    )
    # feature/alpha: 変更・改名・日本語と空白のパス・バイナリ (2 コミット)
    _git(repo, "switch", "-q", "-c", "feature/alpha")
    _commit(
        repo,
        {"README.md": "hello\nbrave\nworld\n", "docs/日本語 ファイル.txt": "こんにちは\n"},
        "feat: alpha 1",
    )
    _git(repo, "mv", "old.txt", "new.txt")
    _commit(
        repo,
        {
            "new.txt": old_lines.replace("古い行 3\n", "新しい行 3\n"),
            "bin.dat": b"\x00\x01\x02\xff",
        },
        "feat: alpha 2",
    )
    # feature/beta: 巨大な diff
    _git(repo, "switch", "-q", "develop")
    _git(repo, "switch", "-q", "-c", "feature/beta")
    _commit(
        repo,
        {"big.txt": "".join(f"line {i} lorem ipsum dolor sit amet\n" for i in range(20000))},
        "feat: beta",
    )
    # bugfix/gamma
    _git(repo, "switch", "-q", "develop")
    _git(repo, "switch", "-q", "-c", "bugfix/gamma")
    _commit(repo, {"keep.txt": "keep\nfixed\n"}, "fix: gamma")
    # feature/done: 統合済み
    _git(repo, "switch", "-q", "develop")
    _git(repo, "switch", "-q", "-c", "feature/done")
    _commit(repo, {"done.txt": "done\n"}, "feat: done")
    _git(repo, "switch", "-q", "develop")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge done", "feature/done")
    _commit(repo, {"after.txt": "after\n"}, "chore: after")
    # target の決め方: main だけ・master だけ・develop と main・どれも無い
    w.main_only = _init(base / "app-main", "main")
    _commit(w.main_only, {"a.txt": "a\n"}, "init")
    _git(w.main_only, "switch", "-q", "-c", "feature/m")
    _commit(w.main_only, {"a.txt": "a\nm\n"}, "feat: m")
    w.master_only = _init(base / "app-master", "master")
    _commit(w.master_only, {"a.txt": "a\n"}, "init")
    _git(w.master_only, "switch", "-q", "-c", "feature/s")
    _commit(w.master_only, {"a.txt": "a\ns\n"}, "feat: s")
    w.both = _init(base / "app-both", "main")
    _commit(w.both, {"a.txt": "a\n"}, "init")
    _git(w.both, "branch", "develop")
    _git(w.both, "switch", "-q", "-c", "feature/b")
    _commit(w.both, {"a.txt": "a\nb\n"}, "feat: b")
    w.none = _init(base / "app-none", "trunk")
    _commit(w.none, {"a.txt": "a\n"}, "init")
    _git(w.none, "switch", "-q", "-c", "feature/n")
    _commit(w.none, {"a.txt": "a\nn\n"}, "feat: n")
    _git(repo, "switch", "-q", "develop")

    w.web = _web_dir(base)
    repos = [repo, w.main_only, w.master_only, w.both, w.none]
    args: list[str] = []
    for r in repos:
        args += ["--repo", str(r)]
    w.snapshot_before = _snapshot(repo)
    w.server = Server(
        [*args, "--port", "0", "--web-dir", str(w.web), "--allow-host", "viewer.example.net"]
    )
    yield w
    w.server.stop()


def _snapshot(repo: Path) -> dict[str, str]:
    """読み取りで変わってはいけないもの: ref・HEAD・設定・index。"""
    return {
        "refs": _git(repo, "for-each-ref"),
        "head": (repo / ".git" / "HEAD").read_text(encoding="utf-8"),
        "config": (repo / ".git" / "config").read_text(encoding="utf-8"),
        "index": hashlib.sha256((repo / ".git" / "index").read_bytes()).hexdigest(),
    }


def _prs(w: World) -> dict[str, dict]:
    status, body = w.server.get("/api/prs")
    assert status == 200
    return {p["id"]: p for p in body["prs"]}


def _pr(w: World, repo: Path, branch: str) -> dict:
    return _prs(w)[f"{_repo_id(repo)}/{_pr_key(branch)}"]


# ---------------------------------------------------------------- 正常系


def test_repos_lists_name_and_target_but_not_paths(world):
    status, body = world.server.get("/api/repos")
    assert status == 200
    by_name = {r["name"]: r for r in body["repos"]}
    assert by_name["example-app"] == {
        "repoId": _repo_id(world.repo),
        "name": "example-app",
        "target": "develop",
        "unpushed": None,  # 上流が無いリポジトリ（A3 で足した後方互換の項目）
        "targetOid": _git(world.repo, "rev-parse", "develop").strip(),
    }
    # 統合先が無いリポジトリ (trunk だけ) は一覧に出さない
    assert "app-none" not in by_name


def test_target_is_develop_then_main_then_master(world):
    _, body = world.server.get("/api/repos")
    targets = {r["name"]: r["target"] for r in body["repos"]}
    assert targets["app-main"] == "main" and targets["app-master"] == "master"
    assert targets["app-both"] == "develop"


def test_unusable_repo_is_an_error_for_its_prs(world):
    status, body = world.server.get(f"/api/prs/{_repo_id(world.none)}/{_pr_key('feature/n')}")
    assert status == 404 and body["error"]["code"] == "repo_unusable"


def test_prs_cover_feature_and_bugfix_and_are_newest_first(world):
    status, body = world.server.get("/api/prs")
    assert status == 200
    mine = [p for p in body["prs"] if p["repoId"] == _repo_id(world.repo)]
    # feature/done は統合済み (develop の祖先で 0 コミット) でレビューの記録も無いので、一覧に出さない
    assert {p["branch"] for p in mine} == {
        "feature/alpha",
        "feature/beta",
        "bugfix/gamma",
    }
    times = [p["lastCommit"]["at"] for p in body["prs"]]
    assert times == sorted(times, reverse=True)
    alpha = _pr(world, world.repo, "feature/alpha")
    assert alpha["state"] == "open" and alpha["commits"] == 2 and alpha["target"] == "develop"
    assert (
        alpha["id"] == f"{alpha['repoId']}/{alpha['prKey']}" and alpha["repoName"] == "example-app"
    )
    assert (
        alpha["lastCommit"]["subject"] == "feat: alpha 2"
        and alpha["lastCommit"]["author"] == "Example Dev"
    )
    for k in ("sourceOid", "targetOid", "baseOid"):
        assert len(alpha[k]) == 40
    assert alpha["baseOid"] == _git(world.repo, "merge-base", "develop", "feature/alpha").strip()


def test_pr_detail_has_commits_and_files_with_rename_binary_and_odd_paths(world):
    alpha = _pr(world, world.repo, "feature/alpha")
    status, body = world.server.get(f"/api/prs/{alpha['id']}")
    assert status == 200 and body["filesTruncated"] is False
    assert [c["subject"] for c in body["commits"]] == ["feat: alpha 2", "feat: alpha 1"]
    files = {f["path"]: f for f in body["files"]}
    assert files["new.txt"]["status"] == "R" and files["new.txt"]["oldPath"] == "old.txt"
    assert files["bin.dat"]["binary"] is True and files["bin.dat"]["oldPath"] is None
    assert files["README.md"]["status"] == "M" and files["README.md"]["additions"] == 1
    odd = files["docs/日本語 ファイル.txt"]
    assert odd["status"] == "A" and odd["additions"] == 1
    assert alpha["files"] == len(body["files"]) and alpha["additions"] == sum(
        f["additions"] for f in body["files"]
    )


def test_diff_returns_structured_hunks(world):
    alpha = _pr(world, world.repo, "feature/alpha")
    status, body = world.server.get(f"/api/prs/{alpha['id']}/diff?path=README.md")
    assert status == 200 and body["binary"] is False and body["truncated"] is False
    (h,) = body["hunks"]
    assert (h["oldStart"], h["oldLines"], h["newStart"], h["newLines"]) == (1, 2, 1, 3)
    assert h["lines"] == [
        {"t": " ", "o": 1, "n": 1, "s": "hello"},
        {"t": "+", "o": None, "n": 2, "s": "brave"},
        {"t": " ", "o": 2, "n": 3, "s": "world"},
    ]


def test_diff_of_renamed_japanese_and_binary_files(world):
    alpha = _pr(world, world.repo, "feature/alpha")
    _, ren = world.server.get(f"/api/prs/{alpha['id']}/diff?path=new.txt")
    changed = [ln for h in ren["hunks"] for ln in h["lines"] if ln["t"] != " "]
    assert {(ln["t"], ln["s"]) for ln in changed} == {("-", "古い行 3"), ("+", "新しい行 3")}
    _, ja = world.server.get(
        f"/api/prs/{alpha['id']}/diff?path=docs/%E6%97%A5%E6%9C%AC%E8%AA%9E%20%E3%83%95%E3%82%A1%E3%82%A4%E3%83%AB.txt"
    )
    assert ja["hunks"][0]["lines"] == [{"t": "+", "o": None, "n": 1, "s": "こんにちは"}]
    _, binary = world.server.get(f"/api/prs/{alpha['id']}/diff?path=bin.dat")
    assert {k: v for k, v in binary.items() if k not in ("oldBlob", "newBlob")} == {
        "path": "bin.dat",
        "binary": True,
        "truncated": False,
        "hunks": [],
    }
    assert binary["oldBlob"] is None and len(binary["newBlob"]) == 40  # 段 2: 追加されたファイル


def test_huge_diff_is_truncated_at_a_whole_line(world):
    beta = _pr(world, world.repo, "feature/beta")
    assert beta["additions"] == 20000
    status, body = world.server.get(f"/api/prs/{beta['id']}/diff?path=big.txt")
    assert status == 200 and body["truncated"] is True
    lines = body["hunks"][0]["lines"]
    assert 1000 < len(lines) < 20000
    assert all(
        ln["s"].startswith("line ") and ln["s"].endswith("dolor sit amet") for ln in lines
    )  # 行の途中で切れていない


def test_merged_pr_detail_is_empty(world):
    # 一覧には出ないが、ID を直接指定すれば読める (統合済みで 0 コミットなので中身は空)
    done_id = f"{_repo_id(world.repo)}/{_pr_key('feature/done')}"
    status, body = world.server.get(f"/api/prs/{done_id}")
    assert status == 200 and body["files"] == [] and body["commits"] == []
    assert body["pr"]["state"] == "merged" and body["pr"]["commits"] == 0


# ---------------------------------------------------------------- 読み取り専用


def test_get_does_not_change_refs_head_config_or_index(world):
    before = _snapshot(world.repo)
    for p in _prs(world).values():
        world.server.get(f"/api/prs/{p['id']}")
        world.server.get(f"/api/prs/{p['id']}/diff?path=README.md")
    world.server.get("/api/repos")
    assert _snapshot(world.repo) == before == world.snapshot_before


# ---------------------------------------------------------------- 入力の検査


@pytest.mark.parametrize(
    "path",
    ["../x", "a/../b", "..", "a%00b", "a%0Ab", "a%0Db", "/etc/passwd", "", "x" * 5000],
)
def test_bad_path_is_400(world, path):
    alpha = _pr(world, world.repo, "feature/alpha")
    status, body = world.server.get(f"/api/prs/{alpha['id']}/diff?path={path}")
    assert status == 400 and body["error"]["code"] == "bad_path"


def test_missing_path_param_is_400(world):
    alpha = _pr(world, world.repo, "feature/alpha")
    status, _ = world.server.get(f"/api/prs/{alpha['id']}/diff")
    assert status == 400


@pytest.mark.parametrize(
    "path", ["keep.txt", "nope.txt", "--output=/tmp/x", ":(top)README.md", "*"]
)
def test_path_not_in_the_branch_diff_is_404(world, path):
    alpha = _pr(world, world.repo, "feature/alpha")
    status, body = world.server.get(f"/api/prs/{alpha['id']}/diff?path={path}")
    assert status == 404 and body["error"]["code"] == "not_in_diff"


@pytest.mark.parametrize(
    ("repo_id", "pr_key", "status"),
    [
        ("rXYZ", "p0123456789abcdef", 400),
        ("r0123456789", "p0123456789abcdef", 400),
        ("r01234567", "pXYZ", 400),
        ("r01234567", "p0123456789abcdef0", 400),
        ("r00000000", "p0123456789abcdef", 404),
    ],
)
def test_ids_are_checked_for_shape_and_registration(world, repo_id, pr_key, status):
    got, body = world.server.get(f"/api/prs/{repo_id}/{pr_key}")
    assert got == status and body["error"]["code"]
    got, _ = world.server.get(f"/api/prs/{repo_id}/{pr_key}/diff?path=a")
    assert got in (400, 404)


def test_unknown_pr_key_in_a_known_repo_is_404(world):
    got, body = world.server.get(f"/api/prs/{_repo_id(world.repo)}/p0123456789abcdef")
    assert got == 404 and body["error"]["code"] == "not_found"


def test_unknown_api_path_is_404_json(world):
    for p in ("/api/nope", "/api/prs/", "/nope"):
        status, body = world.server.get(p)
        assert status == 404 and "error" in body


# ---------------------------------------------------------------- Host・メソッド・待ち受け


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.0.0.1:8780",
        "localhost",
        "localhost:3000",
        "my-pc.tail1234.ts.net",
        "my-pc.tail1234.ts.net:443",
        "viewer.example.net",
    ],
)
def test_allowed_hosts(world, host):
    status, _ = world.server.get("/api/repos", host=host)
    assert status == 200


@pytest.mark.parametrize(
    "host",
    [
        "evil.example.com",
        "127.0.0.1.evil.com",
        "localhost.evil.com",
        "ts.net",
        "evil.ts.net.evil.com",
        "[::1]",
        "0.0.0.0",
        "",
    ],
)
def test_rejected_hosts_are_403(world, host):
    status, body = world.server.get("/api/repos", host=host)
    assert status == 403 and body["error"]["code"] == "forbidden_host"


def test_missing_host_header_is_refused(world):
    # HTTP/1.1 で Host が無いときは、node 自身が 400 で断る (いずれにせよ中身は返らない)
    status, _, body = world.server.request("/api/repos", host=None)
    assert status in (400, 403) and b"repos" not in body


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def test_non_read_methods_are_405(world, method):
    status, headers, body = world.server.request("/api/repos", method=method)
    assert status == 405 and headers["allow"] == "GET, HEAD"
    assert json.loads(body)["error"]["code"] == "method_not_allowed"


def test_head_has_headers_and_no_body(world):
    status, headers, body = world.server.request("/api/repos", method="HEAD")
    assert status == 200 and body == b"" and headers["cache-control"] == "no-store"


def test_listens_on_loopback_only(world):
    assert world.server.line == f"listening http://127.0.0.1:{world.server.port}"
    source = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (APP / "server.ts", APP / "routes.ts", APP / "git-view.ts")
    )
    for bad in ("0.0.0.0", '"::"', "listen(opts.port)"):
        assert bad not in source
    assert 'const HOST = "127.0.0.1"' in source and "8780" in source


# ---------------------------------------------------------------- パスを漏らさない


def test_no_absolute_path_in_any_response(world):
    texts: list[str] = []
    alpha = _pr(world, world.repo, "feature/alpha")
    paths = [
        "/api/repos",
        "/api/prs",
        f"/api/prs/{alpha['id']}",
        f"/api/prs/{alpha['id']}/diff?path=README.md",
        f"/api/prs/{alpha['id']}/diff?path=../x",
        f"/api/prs/{alpha['id']}/diff?path=nope",
        f"/api/prs/{_repo_id(world.none)}/{_pr_key('feature/n')}",
        "/api/prs/r00000000/p0123456789abcdef",
        "/nope",
        "/web/secret.txt",
    ]
    for p in paths:
        _, _, body = world.server.request(p)
        texts.append(body.decode("utf-8"))
    _, _, body = world.server.request("/api/repos", method="POST")
    texts.append(body.decode("utf-8"))
    joined = "\n".join(texts)
    for needle in (
        str(world.base),
        str(world.repo.resolve()),
        str(world.base.resolve()),
        "/tmp/",
        "/home/",
    ):
        assert needle not in joined
    assert "node:" not in joined and "Error:" not in joined


# ---------------------------------------------------------------- 静的ファイル


def test_static_allowlist_and_headers(world):
    status, headers, body = world.server.request("/")
    assert (
        status == 200
        and body.startswith(b"<!doctype html>")
        and headers["content-type"].startswith("text/html")
    )
    assert headers["content-security-policy"] == (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer" and headers["cache-control"] == "no-store"
    assert world.server.request("/web/app.css")[0] == 200
    status, headers, _ = world.server.request("/web/app.js")
    assert status == 200 and headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize(
    "path",
    [
        "/web/secret.txt",
        "/web/sub",
        "/web/sub/x.js",
        "/web/",
        "/web/..%2fsecret.txt",
        "/web/%2e%2e/secret.txt",
        "/web/..%2f..%2foutside.js",
        "/web/link.js",  # シンボリックリンクは返さない
        "/web/.js",
        "/web/app.js%00.txt",
        "/web/%E3%81%82.js",
    ],
)
def test_static_refuses_everything_outside_the_allowlist(world, path):
    status, headers, body = world.server.request(path)
    assert status == 404 and json.loads(body)["error"]["code"] == "not_found"
    assert headers["content-type"].startswith("application/json")


def test_missing_web_dir_is_json_404(world, tmp_path):
    srv = Server(["--repo", str(world.repo), "--port", "0", "--web-dir", str(tmp_path / "none")])
    try:
        status, body = srv.get("/")
        assert status == 404 and body["error"]["code"] == "not_found"
        assert str(tmp_path) not in json.dumps(body)
    finally:
        srv.stop()


# ---------------------------------------------------------------- 起動・終了・上限


def test_start_refuses_a_non_git_path(tmp_path):
    (tmp_path / "plain").mkdir()
    proc = subprocess.run(
        [_node(), str(SERVER), "--repo", str(tmp_path / "plain"), "--port", "0"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 2 and "listening" not in proc.stdout
    assert str(tmp_path) not in proc.stderr


def test_start_refuses_missing_repo_and_unknown_flags(tmp_path):
    for args in (
        [],
        ["--repo"],
        ["--repo", str(tmp_path / "nope")],
        ["--bogus", "1", "--repo", str(tmp_path)],
    ):
        proc = subprocess.run(
            [_node(), str(SERVER), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            timeout=30,
            check=False,
        )
        assert proc.returncode == 2 and "listening" not in proc.stdout


def test_sigterm_exits_cleanly(world):
    srv = Server(["--repo", str(world.repo), "--port", "0", "--web-dir", str(world.web)])
    assert srv.get("/api/repos")[0] == 200
    assert srv.stop() == 0


def test_git_output_limit_is_a_500_error(world):
    srv = Server(
        [
            "--repo",
            str(world.repo),
            "--port",
            "0",
            "--web-dir",
            str(world.web),
            "--git-max-bytes",
            "100",
        ]
    )
    try:
        status, body = srv.get("/api/prs")
        assert status == 500 and body["error"]["code"] == "git_too_large"
    finally:
        srv.stop()


def test_git_time_limit_is_a_500_error(world):
    srv = Server(
        [
            "--repo",
            str(world.repo),
            "--port",
            "0",
            "--web-dir",
            str(world.web),
            "--git-timeout-ms",
            "1",
        ]
    )
    try:
        status, body = srv.get("/api/prs")
        assert status == 500 and body["error"]["code"] == "git_timeout"
    finally:
        srv.stop()


# ---------------------------------------------------------------- 敵対的な設定のリポジトリ


def _script(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class Hostile:
    pass


@pytest.fixture(scope="module")
def hostile(tmp_path_factory):
    base = tmp_path_factory.mktemp("hostile")
    h = Hostile()
    h.marks = base / "marks"
    h.marks.mkdir()
    repo = _init(base / "example-app")
    h.repo = repo
    tools = base / "tools"
    tools.mkdir()
    m = h.marks
    fsmonitor = _script(tools / "fsmonitor.sh", f"touch {m}/fsmonitor\nexit 1")
    external = _script(tools / "external.sh", f"touch {m}/external\nexit 0")
    textconv = _script(tools / "textconv.sh", f'touch {m}/textconv\ncat "$1"')
    pager = _script(tools / "pager.sh", f"touch {m}/pager\ncat")
    smudge = _script(tools / "smudge.sh", f"touch {m}/smudge\ncat")
    hooks = base / "hooks"
    hooks.mkdir()
    _script(hooks / "reference-transaction", f"touch {m}/hooks")
    _commit(
        repo,
        {
            ".gitattributes": "*.txt diff=evil\n*.smu filter=evil\n",
            "a.txt": "one\n",
            "tracked.md": "t\n",
            "f.smu": "s\n",
        },
        "init",
    )
    _git(repo, "switch", "-q", "-c", "feature/hostile")
    _commit(repo, {"a.txt": "one\ntwo\n", "f.smu": "s\nx\n"}, "feat: hostile")
    _git(repo, "switch", "-q", "develop")
    for key, value in (
        ("core.fsmonitor", str(fsmonitor)),
        ("diff.external", str(external)),
        ("diff.evil.textconv", str(textconv)),
        ("core.pager", str(pager)),
        ("filter.evil.smudge", str(smudge)),
        ("core.hooksPath", str(hooks)),
    ):
        _git(repo, "config", key, value)
    # アプリと同じ形 (作業ツリー無し・--git-dir) でも読まれる属性: .gitattributes と同じ内容を info/attributes に置く
    info = repo / ".git" / "info"
    info.mkdir(exist_ok=True)
    (info / "attributes").write_text("*.txt diff=evil\n", encoding="utf-8")
    h.server = Server(["--repo", str(repo), "--port", "0", "--web-dir", str(_web_dir(base))])
    yield h
    h.server.stop()


def _premise_fsmonitor(repo: Path) -> None:
    (repo / "tracked.md").write_text("t\nchanged\n", encoding="utf-8")
    _git(repo, "diff", check=False)
    _git(repo, "checkout", "--", "tracked.md")


def _premise_external(repo: Path) -> None:
    _git(repo, "diff", "develop", "feature/hostile", "--", "f.smu", check=False)


def _premise_textconv(repo: Path) -> None:
    # アプリと同じ形 (作業ツリー無し・--git-dir・作業ディレクトリは別) でも、info/attributes があれば textconv が動く
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(
        [
            "git",
            f"--git-dir={repo / '.git'}",
            "diff",
            "--no-ext-diff",
            "develop",
            "feature/hostile",
            "--",
            "a.txt",
        ],
        cwd=repo.parent,
        env=env,
        capture_output=True,
        check=False,
    )


def _premise_pager(repo: Path) -> None:
    # pager は標準出力が端末のときだけ動くので、疑似端末をつないで実行する
    master, slave = pty.openpty()
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_PAGER", "PAGER")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", TERM="xterm")
    try:
        subprocess.run(
            ["git", "-p", "log", "-1"],
            cwd=repo,
            env=env,
            stdout=slave,
            stderr=slave,
            stdin=slave,
            timeout=30,
            check=False,
        )
    finally:
        os.close(slave)
        os.close(master)


def _premise_smudge(repo: Path) -> None:
    (repo / "f.smu").unlink()
    _git(repo, "checkout", "--", "f.smu")


def _premise_hooks(repo: Path) -> None:
    _git(repo, "update-ref", "refs/scratch/x", "HEAD")
    _git(repo, "update-ref", "-d", "refs/scratch/x")


PREMISES = {
    "fsmonitor": _premise_fsmonitor,
    "external": _premise_external,
    "textconv": _premise_textconv,
    "pager": _premise_pager,
    "smudge": _premise_smudge,
    "hooks": _premise_hooks,
}


@pytest.mark.parametrize("name", sorted(PREMISES))
def test_premise_plain_git_runs_the_planted_command(hostile, name):
    """前提: 素の git では、仕込んだコマンドが動いて印ができる (これが成り立たなければ次の試験は何も確かめていない)。"""
    for mark in hostile.marks.iterdir():  # 他の前提の副産物を消す
        mark.unlink()
    PREMISES[name](hostile.repo)
    assert (hostile.marks / name).exists(), f"{name}: 素の git で印ができない"
    assert _git(hostile.repo, "status", "--porcelain").strip() == ""
    for mark in hostile.marks.iterdir():
        mark.unlink()


def test_the_app_never_runs_planted_commands(hostile):
    assert list(hostile.marks.iterdir()) == []
    before = _snapshot(hostile.repo)
    status, body = hostile.server.get("/api/prs")
    assert status == 200 and len(body["prs"]) == 1
    pr = body["prs"][0]
    status, detail = hostile.server.get(f"/api/prs/{pr['id']}")
    assert status == 200 and {f["path"] for f in detail["files"]} == {"a.txt", "f.smu"}
    for path in ("a.txt", "f.smu"):
        status, diff = hostile.server.get(f"/api/prs/{pr['id']}/diff?path={path}")
        assert status == 200 and diff["hunks"][0]["lines"][-1]["t"] == "+"
    assert hostile.server.get("/api/repos")[0] == 200
    assert sorted(p.name for p in hostile.marks.iterdir()) == []
    assert _snapshot(hostile.repo) == before


def test_replace_refs_do_not_change_what_the_app_shows(tmp_path):
    """git replace で、レビューする内容を差し替えられない (--no-replace-objects)。"""
    repo = _init(tmp_path / "example-app")
    _commit(repo, {"a.txt": "base\n"}, "init")
    _git(repo, "switch", "-q", "-c", "feature/x")
    _commit(repo, {"a.txt": "base\nreal line\n"}, "feat: x")
    _git(repo, "switch", "-q", "develop")
    real = _git(repo, "rev-parse", "feature/x:a.txt").strip()
    fake_file = tmp_path / "fake.txt"
    fake_file.write_text("base\nFAKE line\n", encoding="utf-8")
    fake = _git(repo, "hash-object", "-w", str(fake_file)).strip()
    _git(repo, "replace", "-f", real, fake)
    # 前提: 素の git では、差し替えた内容が見える (これが成り立たなければ次の確認は何も確かめていない)
    assert "FAKE line" in _git(repo, "show", "feature/x:a.txt")
    server = Server(["--repo", str(repo), "--port", "0", "--web-dir", str(_web_dir(tmp_path))])
    try:
        status, body = server.get("/api/prs")
        assert status == 200 and len(body["prs"]) == 1
        status, diff = server.get(f"/api/prs/{body['prs'][0]['id']}/diff?path=a.txt")
        assert status == 200
        text = json.dumps(diff, ensure_ascii=False)
        assert "real line" in text and "FAKE" not in text
    finally:
        server.stop()


# ---------------------------------------------------------------- partial clone の自動取得 (lazy fetch)


@pytest.fixture
def lazy(tmp_path):
    """feature の変更後の blob を消し、promisor remote の ssh が印を作る形にしたリポジトリ。"""
    repo = _init(tmp_path / "example-app")
    _commit(repo, {"a.txt": "base\n"}, "init")
    _git(repo, "switch", "-q", "-c", "feature/lazy")
    _commit(repo, {"a.txt": "base\nlazy line\n"}, "feat: lazy")
    _git(repo, "switch", "-q", "develop")
    blob = _git(repo, "rev-parse", "feature/lazy:a.txt").strip()
    obj = repo / ".git" / "objects" / blob[:2] / blob[2:]
    assert obj.exists(), "blob が loose object でない"
    obj.unlink()
    marks = tmp_path / "marks"
    marks.mkdir()
    ssh = _script(tmp_path / "ssh.sh", f"touch {marks}/ssh\nexit 1")
    for key, value in (
        ("extensions.partialClone", "origin"),
        ("remote.origin.promisor", "true"),
        ("remote.origin.url", "ssh://example.invalid/x.git"),
        ("core.sshCommand", str(ssh)),
    ):
        _git(repo, "config", key, value)
    return repo, marks, tmp_path


def test_premise_plain_git_lazy_fetches(lazy):
    """前提: 素の git では、不足した blob の読み取りが ssh を起動する。"""
    repo, marks, _ = lazy
    _git(repo, "diff", "develop", "feature/lazy", "--", "a.txt", check=False)
    if not (marks / "ssh").exists():
        pytest.skip("この git の版では lazy fetch が ssh を起動しない")


def test_the_app_never_lazy_fetches(lazy):
    repo, marks, tmp_path = lazy
    server = Server(["--repo", str(repo), "--port", "0", "--web-dir", str(_web_dir(tmp_path))])
    try:
        pid = f"{_repo_id(repo)}/{_pr_key('feature/lazy')}"
        for path in (f"/api/prs/{pid}", f"/api/prs/{pid}/diff?path=a.txt"):
            status, err = server.get(path)
            assert status == 500 and err["error"]["code"].startswith("git_"), (path, status, err)
        assert list(marks.iterdir()) == []
    finally:
        server.stop()


# ---------------------------------------------------------------- 統合先の進み・両側の変更・未 push (CHG-0062 A3)

HOSTILE_NAME = "<img src=x onerror=alert(1)>.txt"


@pytest.fixture(scope="module")
def hub(tmp_path_factory):
    base = tmp_path_factory.mktemp("hub")
    repo = _init(base / "hub-app")
    _commit(repo, {"shared.txt": "a\n", "mine.txt": "m\n", "other.txt": "o\n"}, "init")
    # 分岐してから develop が進む。PR 側は shared.txt と悪意のある名前のファイルを変える
    _git(repo, "switch", "-q", "-c", "feature/a")
    _commit(repo, {"shared.txt": "a\nA\n", "mine.txt": "m\nA\n", HOSTILE_NAME: "pr\n"}, "feat: a")
    _git(repo, "switch", "-q", "develop")
    _commit(repo, {"shared.txt": "a\nD\n", HOSTILE_NAME: "dev\n"}, "chore: d1")
    _commit(repo, {"other.txt": "o\nD\n"}, "chore: d2")
    # origin は bare。取得した時点から、develop をさらに 2 コミット進める（push しない）
    origin = base / "origin.git"
    _git(base, "clone", "-q", "--bare", str(repo), str(origin))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "fetch", "-q", "origin")
    _commit(repo, {"other.txt": "o\nD\nU1\n"}, "chore: u1")
    _commit(repo, {"other.txt": "o\nD\nU1\nU2\n"}, "chore: u2")
    # develop に追いついている PR（behind 0）
    _git(repo, "switch", "-q", "-c", "feature/idle")
    _commit(repo, {"idle.txt": "i\n"}, "feat: idle")
    _git(repo, "switch", "-q", "develop")
    # 上流の無いリポジトリ
    solo = _init(base / "solo-app")
    _commit(solo, {"a.txt": "a\n"}, "init")
    srv = Server(
        ["--repo", str(repo), "--repo", str(solo), "--port", "0", "--web-dir", str(_web_dir(base))]
    )
    w = World()
    w.repo, w.solo, w.server = repo, solo, srv
    yield w
    srv.stop()


def test_behind_and_overlap_count_both_sides_changes(hub):
    pr = _pr(hub, hub.repo, "feature/a")
    assert pr["behind"] == 4  # d1・d2・u1・u2
    # 両側が変えたのは shared.txt と悪意のある名前のファイル。mine.txt・other.txt は片側だけ
    assert pr["overlap"] == {
        "count": 2,
        "paths": sorted(["shared.txt", HOSTILE_NAME]),
        "truncated": False,
    }
    # 詳細の API も同じ値を返す（API では名前が文字列のまま。エスケープも変形もしない）
    status, body = hub.server.get(f"/api/prs/{pr['id']}")
    assert status == 200 and body["pr"]["overlap"]["paths"] == pr["overlap"]["paths"]
    assert HOSTILE_NAME in body["pr"]["overlap"]["paths"]


def test_not_behind_has_empty_overlap(hub):
    pr = _pr(hub, hub.repo, "feature/idle")
    assert pr["behind"] == 0
    assert pr["overlap"] == {"count": 0, "paths": [], "truncated": False}


def test_unpushed_counts_commits_ahead_of_origin_and_is_null_without_upstream(hub):
    _, body = hub.server.get("/api/repos")
    by_name = {r["name"]: r for r in body["repos"]}
    assert by_name["hub-app"]["unpushed"] == 2
    assert by_name["solo-app"]["unpushed"] is None
    # 既存のフィールドは変わらない
    assert by_name["hub-app"]["target"] == "develop" and by_name["hub-app"]["repoId"] == _repo_id(
        hub.repo
    )


# ---------------------------------------------------------------- 含まれる枝 (includedIn。表示だけの印)


def _serve_one(repo: Path, web_base: Path) -> Server:
    return Server(
        [
            "--repo",
            str(repo),
            "--port",
            "0",
            "--web-dir",
            str(_web_dir(web_base)),
            "--allow-host",
            "x.example.net",
        ]
    )


@pytest.fixture(scope="module")
def incl(tmp_path_factory):
    base = tmp_path_factory.mktemp("incl")
    w = World()
    repo = _init(base / "incl-app")
    w.repo = repo
    _commit(repo, {"README.md": "x\n"}, "init")
    for name in ("a", "b", "c", "dup1", "gone"):
        _git(repo, "switch", "-q", "develop")
        _git(repo, "switch", "-q", "-c", f"feature/{name}")
        _commit(repo, {f"{name}.txt": f"{name}\n"}, f"feat: {name}")
    # dup1 と同じ oid の枝
    _git(repo, "branch", "feature/dup2", "feature/dup1")
    # 構成員 a・b・c・dup1 を取り込んだ統合用の枝
    _git(repo, "switch", "-q", "develop")
    _git(repo, "switch", "-q", "-c", "feature/train-1")
    for name in ("a", "b", "dup1", "c"):
        _git(repo, "merge", "-q", "--no-ff", "-m", f"merge {name}", f"feature/{name}")
    # c は train の取り込み後に追加のコミットが載るので、train には含まれない
    _git(repo, "switch", "-q", "feature/c")
    _commit(repo, {"c2.txt": "c2\n"}, "feat: c2")
    # gone は develop へ統合済み (0 コミット。一覧に出ない)
    _git(repo, "switch", "-q", "develop")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge gone", "feature/gone")
    w.server = _serve_one(repo, base)
    yield w
    w.server.stop()


def test_members_of_a_train_are_marked_included_and_the_train_is_not(incl):
    assert _pr(incl, incl.repo, "feature/a")["includedIn"] == "feature/train-1"
    assert _pr(incl, incl.repo, "feature/b")["includedIn"] == "feature/train-1"
    assert "includedIn" not in _pr(incl, incl.repo, "feature/train-1")


def test_a_branch_that_advanced_after_the_train_is_not_included(incl):
    assert "includedIn" not in _pr(incl, incl.repo, "feature/c")


def test_same_oid_member_branches_are_both_included_in_the_train(incl):
    # dup1・dup2 は同じ先頭。互いを「含む枝」とは数えず、train だけが含む枝になる
    for name in ("dup1", "dup2"):
        assert _pr(incl, incl.repo, f"feature/{name}")["includedIn"] == "feature/train-1"


def test_same_oid_pair_alone_is_not_included(tmp_path):
    repo = _init(tmp_path / "pair-app")
    _commit(repo, {"README.md": "x\n"}, "init")
    _git(repo, "switch", "-q", "-c", "feature/p")
    _commit(repo, {"p.txt": "p\n"}, "feat: p")
    _git(repo, "branch", "feature/q", "feature/p")
    srv = _serve_one(repo, tmp_path)
    try:
        _, body = srv.get("/api/prs")
        assert {p["branch"] for p in body["prs"]} == {"feature/p", "feature/q"}
        assert all("includedIn" not in p for p in body["prs"])
    finally:
        srv.stop()


def test_merged_prs_get_no_included_in(incl):
    _, body = incl.server.get("/api/prs")
    for p in body["prs"]:
        if p["state"] != "open":
            assert "includedIn" not in p
    assert "feature/gone" not in {p["branch"] for p in body["prs"]}


def test_included_pr_is_still_readable_by_id(incl):
    a = _pr(incl, incl.repo, "feature/a")
    status, body = incl.server.get(f"/api/prs/{a['id']}")
    assert status == 200 and body["pr"]["branch"] == "feature/a"
