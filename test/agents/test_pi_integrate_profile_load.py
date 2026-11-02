"""pi.json のローダー (harness/integrate-profile-load.ts) の試験。使い捨ての実 git リポジトリで確かめる。

HEAD の blob だけを読む。作業ツリーの編集は無視する。fixture には架空の名前だけを使う。
see docs/change/0057-per-project-integrate.md
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "integrate_profile_driver.mjs"
IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
REL = ".agents/config/pi.json"
SECRET = "SECRET-TOKEN-XYZ"
DEFAULTS = {
    "protectedRefs": ["main", "develop", "production", "release/*", "hotfix/*"],
    "target": "production",
    "sourcePrefixes": ["feature/", "bugfix/"],
    "freeZonePrefixes": ["feature/"],
}


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *IDENT, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return out.stdout


def _run(payload: dict) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(out.stdout)


def _load(cwd: Path) -> dict:
    return _run({"fn": "load", "cwd": str(cwd), "defaults": DEFAULTS})


def _cfg(**integrate) -> str:
    return json.dumps({"integrate": integrate})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    return path


def _commit_cfg(repo: Path, text: str, msg: str = "cfg") -> str:
    p = repo / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(repo, "add", REL)
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", f"HEAD:{REL}").strip()


def _assert_default(r: dict, code: str | None = None):
    assert r["profile"]["source"] == "default", r
    assert r["profile"]["target"] == "production"
    assert r["overridden"] is False
    if code is None:
        assert r["diagnostics"] == []
    else:
        assert [d["code"] for d in r["diagnostics"]] == [code], r


def test_no_head_is_no_config(repo: Path):
    (repo / REL).parent.mkdir(parents=True)
    (repo / REL).write_text(_cfg(target="develop"), encoding="utf-8")  # 未コミット: HEAD が無い
    r = _load(repo)
    _assert_default(r)
    assert r["blob"] is None


def test_no_file_is_no_config(repo: Path):
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    r = _load(repo)
    _assert_default(r)
    assert r["blob"] is None


def test_not_a_repo_is_no_config(tmp_path: Path):
    r = _load(tmp_path)
    _assert_default(r)
    assert r["blob"] is None


def test_committed_config_is_applied(repo: Path):
    oid = _commit_cfg(repo, _cfg(target="develop", source_prefixes=["feat/"]))
    r = _load(repo)
    assert r["profile"]["source"] == "project"
    assert r["profile"]["target"] == "develop"
    assert r["profile"]["sourcePrefixes"] == ["feat/"]
    assert r["overridden"] is True
    assert r["blob"] == oid


def test_subdirectory_cwd_reads_the_repo_config(repo: Path):
    _commit_cfg(repo, _cfg(target="develop"))
    (repo / "sub").mkdir()
    r = _load(repo / "sub")
    assert r["profile"]["target"] == "develop"


def test_worktree_edit_is_ignored_until_committed(repo: Path):
    oid = _commit_cfg(repo, _cfg(target="develop"))
    (repo / REL).write_text(_cfg(target="main"), encoding="utf-8")
    r = _load(repo)
    assert r["profile"]["target"] == "develop"
    assert r["blob"] == oid
    (repo / REL).unlink()  # 消しても HEAD の内容のまま
    assert _load(repo)["profile"]["target"] == "develop"


def test_worktree_file_without_commit_is_ignored(repo: Path):
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    (repo / REL).parent.mkdir(parents=True)
    (repo / REL).write_text(_cfg(target="develop"), encoding="utf-8")
    _assert_default(_load(repo))


def test_other_branch_without_file(repo: Path):
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "other")
    _commit_cfg(repo, _cfg(target="develop"))
    assert _load(repo)["profile"]["target"] == "develop"
    _git(repo, "checkout", "-q", "main")
    assert not (repo / REL).exists()
    r = _load(repo)
    _assert_default(r)
    assert r["blob"] is None


def test_blob_change_after_commit_changes_result(repo: Path):
    oid1 = _commit_cfg(repo, _cfg(target="develop"))
    oid2 = _commit_cfg(repo, _cfg(target="main"), "cfg2")
    assert oid1 != oid2
    r = _run(
        {
            "fn": "seq",
            "cwd": str(repo),
            "defaults": DEFAULTS,
            "steps": [{"load": True}, {"git": ["reset", "-q", "--hard", "HEAD~1"]}, {"load": True}],
        }
    )
    a, b = r["loads"]
    assert (a["profile"]["target"], a["blob"]) == ("main", oid2)
    assert (b["profile"]["target"], b["blob"]) == ("develop", oid1)


def test_empty_or_deleted_after_commit_is_default(repo: Path):
    _commit_cfg(repo, _cfg(target="develop"))
    _commit_cfg(repo, "", "empty")
    _assert_default(_load(repo))
    _commit_cfg(repo, _cfg(target="develop"), "back")
    _git(repo, "rm", "-q", REL)
    _git(repo, "commit", "-q", "-m", "rm")
    _assert_default(_load(repo))


def test_cache_is_keyed_by_blob_id(repo: Path):
    oid = _commit_cfg(repo, _cfg(target="develop"))
    r = _run(
        {
            "fn": "seq",
            "cwd": str(repo),
            "defaults": DEFAULTS,
            "steps": [{"load": True}, {"load": True}, {"load": True}],
        }
    )
    assert [x["blob"] for x in r["loads"]] == [oid] * 3
    assert all(x["profile"]["target"] == "develop" for x in r["loads"])
    assert r["calls"].count("ls-tree") == 3  # 発見は毎回 1 回
    assert r["calls"].count("cat-file") == 1  # 同じ blob は読み直さない


def test_same_content_new_commit_reuses_cache(repo: Path):
    _commit_cfg(repo, _cfg(target="develop"))
    _git(repo, "commit", "-q", "--allow-empty", "-m", "noop")
    r = _run(
        {
            "fn": "seq",
            "cwd": str(repo),
            "defaults": DEFAULTS,
            "steps": [
                {"load": True},
                {"git": ["commit", "-q", "--allow-empty", "-m", "x"]},
                {"load": True},
            ],
        }
    )
    assert r["calls"].count("cat-file") == 1


def test_changed_blob_is_read_again(repo: Path):
    _commit_cfg(repo, _cfg(target="develop"))
    r = _run(
        {
            "fn": "seq",
            "cwd": str(repo),
            "defaults": DEFAULTS,
            "steps": [
                {"load": True},
                {"git": ["commit", "-q", "--allow-empty", "-m", "x"]},
                {"load": True},
            ],
        }
    )
    assert r["calls"].count("cat-file") == 1
    # blob が変わる場合 (別の内容をコミット) は再読する
    p = repo / REL
    p.write_text(_cfg(target="main"), encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "chg")
    r2 = _run({"fn": "seq", "cwd": str(repo), "defaults": DEFAULTS, "steps": [{"load": True}]})
    assert r2["loads"][0]["profile"]["target"] == "main"


def test_no_config_costs_one_git_call(repo: Path):
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    r = _run({"fn": "seq", "cwd": str(repo), "defaults": DEFAULTS, "steps": [{"load": True}]})
    assert r["calls"] == ["ls-tree"]


def test_symlink_is_invalid(repo: Path, tmp_path: Path):
    target = tmp_path / "elsewhere.json"
    target.write_text(_cfg(target="develop"), encoding="utf-8")
    (repo / ".agents" / "config").mkdir(parents=True)
    # symlink (モード 120000) を、OS の symlink に頼らず index に直接足す
    oid = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo,
        input=str(target),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{oid},{REL}")
    _git(repo, "commit", "-q", "-m", "link")
    assert "120000" in _git(repo, "ls-tree", "HEAD", "--", REL)
    r = _load(repo)
    _assert_default(r, "not_regular_file")
    assert r["blob"] == oid


def test_submodule_mode_is_invalid(repo: Path):
    fake = "1" * 40
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{fake},{REL}")
    _git(repo, "commit", "-q", "-m", "sub")
    assert "160000" in _git(repo, "ls-tree", "HEAD", "--", REL)
    r = _load(repo)
    _assert_default(r, "not_regular_file")


def test_directory_in_place_of_file_is_invalid(repo: Path):
    p = repo / REL / "x"
    p.parent.mkdir(parents=True)
    p.write_text("{}", encoding="utf-8")
    _git(repo, "add", REL)
    _git(repo, "commit", "-q", "-m", "dir")
    r = _load(repo)
    _assert_default(r, "not_regular_file")


def test_oversize_is_invalid(repo: Path):
    _commit_cfg(repo, _cfg(target="develop") + " " * 5000)
    _assert_default(_load(repo), "too_large")


def test_invalid_content_has_code_only(repo: Path):
    _commit_cfg(repo, "{" + SECRET)
    r = _load(repo)
    _assert_default(r, "invalid_json")
    assert SECRET not in json.dumps(r["diagnostics"])


def test_protected_refs_key_is_invalid(repo: Path):
    _commit_cfg(repo, json.dumps({"integrate": {"protected_refs": []}}))
    _assert_default(_load(repo), "protected_refs_not_allowed")


def test_executable_mode_is_accepted(repo: Path):
    p = repo / REL
    p.parent.mkdir(parents=True)
    p.write_text(_cfg(target="develop"), encoding="utf-8")
    _git(repo, "add", REL)
    _git(repo, "update-index", "--chmod=+x", REL)
    _git(repo, "commit", "-q", "-m", "x")
    assert _load(repo)["profile"]["target"] == "develop"


def test_oversize_blob_is_not_read(repo: Path):
    """サイズ上限は ls-tree の時点で見る (大きな blob を cat-file で読まない)。"""
    _commit_cfg(repo, _cfg(target="develop") + " " * 5000)
    r = _run({"fn": "seq", "cwd": str(repo), "defaults": DEFAULTS, "steps": [{"load": True}]})
    assert r["calls"] == ["ls-tree"], r
    _assert_default(r["loads"][0], "too_large")


def test_cache_is_keyed_by_the_global_defaults_too(repo: Path):
    """同じ blob でも、全体の保護が変われば検査し直す (古い検査結果を使わない)。"""
    _commit_cfg(repo, _cfg(free_zone_prefixes=["staging/"]))
    stricter = {**DEFAULTS, "protectedRefs": [*DEFAULTS["protectedRefs"], "staging/*"]}
    r = _run(
        {
            "fn": "seq",
            "cwd": str(repo),
            "defaults": DEFAULTS,
            "steps": [{"load": True}, {"load": True, "defaults": stricter}],
        }
    )
    first, second = r["loads"]
    assert first["profile"]["source"] == "project" and first["profile"]["freeZonePrefixes"] == [
        "staging/"
    ]
    _assert_default(second, "prefix_overlaps_protected")


def test_unexpected_ls_tree_path_is_not_trusted():
    fake = {"ls-tree": {"ok": True, "stdout": f"100644 blob {'a' * 40} 20\tother/file\n"}}
    r = _run({"fn": "fake", "cwd": ".", "defaults": DEFAULTS, "outputs": fake})
    _assert_default(r, "ls_tree_unparsed")


def test_cat_file_failure_is_reported():
    fake = {
        "ls-tree": {"ok": True, "stdout": f"100644 blob {'b' * 40} 20\t{REL}\n"},
        "cat-file": {"ok": False, "reason": "boom"},
    }
    r = _run({"fn": "fake", "cwd": ".", "defaults": DEFAULTS, "outputs": fake})
    _assert_default(r, "read_failed")


def test_git_dir_env_does_not_redirect(repo: Path, tmp_path: Path):
    """GIT_DIR を継承して別のリポジトリを見ない (gitrun の repoTargetEnv)。"""
    _commit_cfg(repo, _cfg(target="develop"))
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    _git(other, "commit", "-q", "--allow-empty", "-m", "i")
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    import os

    env = {**os.environ, "GIT_DIR": str(other / ".git")}
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps({"fn": "load", "cwd": str(repo), "defaults": DEFAULTS}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
        env=env,
    )
    assert json.loads(out.stdout)["profile"]["target"] == "develop"


# --- replace refs を使わない (S2) ------------------------------------------------------


def test_reads_never_use_replace_objects():
    """ls-tree / cat-file はどちらも、サブコマンドの前に --no-replace-objects を付ける。"""
    fake = {
        "ls-tree": {"ok": True, "stdout": f"100644 blob {'b' * 40} 20\t{REL}\n"},
        "cat-file": {"ok": True, "stdout": _cfg(target="develop")},
    }
    r = _run({"fn": "fake", "cwd": ".", "defaults": DEFAULTS, "outputs": fake, "record": True})
    assert [a[:2] for a in r["seen"]] == [
        ["--no-replace-objects", "ls-tree"],
        ["--no-replace-objects", "cat-file"],
    ], r


def _replaced_setup(repo: Path, head_cfg: str | None, replacement_cfg: str) -> str:
    """HEAD のコミットを、別のコミット (広い設定) に git replace する。replace 前の HEAD の blob ID を返す。"""
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    if head_cfg is not None:
        _commit_cfg(repo, head_cfg)
    head = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "-b", "side")
    _commit_cfg(repo, replacement_cfg, "wide")
    wide = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "main")
    _git(repo, "replace", head, wide)
    # 置換は効いている (素の git は置換後の内容を返す)
    assert REL in _git(repo, "ls-tree", "-r", "--name-only", "HEAD")
    return head


def test_a_replaced_head_commit_does_not_change_the_result_with_an_empty_cache(repo: Path):
    _replaced_setup(repo, None, _cfg(target="develop"))
    r = _load(repo)
    _assert_default(r)
    assert r["blob"] is None


def test_a_replaced_head_commit_does_not_change_an_already_read_result(repo: Path):
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    narrow = _commit_cfg(repo, _cfg(target="develop"))
    head = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "-b", "side")
    _commit_cfg(repo, _cfg(target="release/x"), "wide")
    wide = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "main")
    r = _run(
        {
            "fn": "seq",
            "cwd": str(repo),
            "defaults": DEFAULTS,
            "steps": [{"load": True}, {"git": ["replace", head, wide]}, {"load": True}],
        }
    )
    assert [x["blob"] for x in r["loads"]] == [narrow, narrow], r
    assert [x["profile"]["target"] for x in r["loads"]] == ["develop", "develop"]


# --- 読み取りの失敗 (S3): readFailed ----------------------------------------------------


def test_read_failed_is_set_only_when_git_fails():
    ok_line = f"100644 blob {'b' * 40} 20\t{REL}\n"
    cases = {
        "ls_tree_fails": ({"ls-tree": {"ok": False, "reason": "boom"}}, True),
        "cat_file_fails": (
            {"ls-tree": {"ok": True, "stdout": ok_line}, "cat-file": {"ok": False, "reason": "x"}},
            True,
        ),
        "unparsed_size": (
            {"ls-tree": {"ok": True, "stdout": f"100644 blob {'d' * 40}     BAD\t{REL}\n"}},
            True,
        ),  # 欠けた blob
        "no_file": ({"ls-tree": {"ok": True, "stdout": ""}}, False),
        "invalid_content": (
            {"ls-tree": {"ok": True, "stdout": ok_line}, "cat-file": {"ok": True, "stdout": "{"}},
            False,
        ),
        "not_regular": (
            {"ls-tree": {"ok": True, "stdout": f"120000 blob {'c' * 40} 9\t{REL}\n"}},
            False,
        ),
        "valid": (
            {
                "ls-tree": {"ok": True, "stdout": ok_line},
                "cat-file": {"ok": True, "stdout": _cfg()},
            },
            False,
        ),
    }
    got = {}
    for name, (outputs, _) in cases.items():
        got[name] = _run({"fn": "fake", "cwd": ".", "defaults": DEFAULTS, "outputs": outputs})[
            "readFailed"
        ]
    assert got == {name: want for name, (_, want) in cases.items()}, got
