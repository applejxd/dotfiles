"""統合器の事前検査の試験（git 堅牢化 P1）: git の版・扱わないリポジトリの設定・扱わない変更。

統合器（merge.ts）は git の配管で develop を動かすので、前提が崩れたときは**何も書く前に**、理由が分かる形で断る。
git は最新版を使う前提で、古い版への互換は作らない（最小の版を下回るときだけ断る）。名前・メールは架空。
"""

from __future__ import annotations

import os
import shutil

import pytest
from test_pi_judge_ts import _node
from test_pr_viewer_merge import World, _no_leftovers
from test_pr_viewer_server import _commit, _git

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def _fake_git_version(w: World, line: str) -> None:
    """CLI の PATH の先頭に、--version だけ偽装して、あとは本物へ渡す git を置く（試験の準備の git は本物のまま）。"""
    real = shutil.which("git")
    assert real
    bindir = w.tmp / "fakebin"
    bindir.mkdir()
    script = bindir / "git"
    script.write_text(
        f'#!/bin/sh\nfor a in "$@"; do\n  if [ "$a" = "--version" ]; then echo "{line}"; exit 0; fi\ndone\nexec "{real}" "$@"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    base = w.env()
    w.env = lambda: {**base, "PATH": f"{bindir}{os.pathsep}{base['PATH']}"}  # type: ignore[method-assign]


def _refused(w: World, source: str, code: str) -> None:
    """plan も merge も同じ理由で断り、何も動かさない。"""
    before = (w.rev(), _git(w.repo, "for-each-ref"), w.status())
    for rc, out, _ in (w.plan(source), w.merge(source)):
        assert rc == 2 and out["ok"] is False and out["code"] == code, out
    assert (w.rev(), _git(w.repo, "for-each-ref"), w.status()) == before
    _no_leftovers(w)


# ---------------------------------------------------------------- git の版


@pytest.mark.parametrize(
    "line",
    ["git version 2.39.9", "git version 2.9.0", "git version 1.99.0", "git version", "garbage", ""],
)
def test_an_old_or_unreadable_git_version_is_refused_before_anything_runs(w, line):
    w.feature("feature/a", {"a.txt": "a\n"})
    _fake_git_version(w, line)
    _refused(w, "feature/a", "git_version")


@pytest.mark.parametrize(
    "line",
    [
        "git version 2.40.0",  # 境界（最小）
        "git version 2.43.0",
        "git version 3.0.0",
        "git version 2.45.1.windows.1",
        "git version 2.50.1 (Apple Git-155)",
    ],
)
def test_a_recent_git_version_is_accepted(w, line):
    w.feature("feature/a", {"a.txt": "a\n"})
    _fake_git_version(w, line)
    rc, out, _ = w.plan("feature/a")
    assert rc == 0 and out["ok"], out


# ---------------------------------------------------------------- 扱わないリポジトリの設定（sparse checkout）


@pytest.mark.parametrize("value", ["true", "yes", "on", "1", "TRUE"])
def test_sparse_checkout_repositories_are_refused(w, value):
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "config", "core.sparseCheckout", value)
    _refused(w, "feature/a", "unsupported_repo")


def test_sparse_checkout_without_a_value_counts_as_true(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    with (w.git_dir() / "config").open("a", encoding="utf-8") as f:
        f.write("[core]\n\tsparseCheckout\n")
    _refused(w, "feature/a", "unsupported_repo")


def test_sparse_checkout_in_the_worktree_config_is_refused(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    (w.git_dir() / "config.worktree").write_text(
        "[core]\n\tsparseCheckout = true\n", encoding="utf-8"
    )
    _refused(w, "feature/a", "unsupported_repo")


@pytest.mark.parametrize("value", ["false", "no", "off", "0"])
def test_sparse_checkout_turned_off_is_accepted(w, value):
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "config", "core.sparseCheckout", value)
    rc, out, _ = w.plan("feature/a")
    assert rc == 0 and out["ok"], out


# ---------------------------------------------------------------- 扱わない変更（サブモジュール・filter 属性）


def _gitlink_feature(w: World, name: str, update: bool = False) -> None:
    _git(w.repo, "checkout", "-q", "-b", name, "develop")
    _git(w.repo, "update-index", "--add", "--cacheinfo", f"160000,{w.rev()},vendor/lib")
    _git(w.repo, "commit", "-q", "-m", f"feat: {name}")
    _git(w.repo, "checkout", "-q", "develop")


def test_a_change_that_adds_a_submodule_is_refused(w):
    _gitlink_feature(w, "feature/sub")
    _refused(w, "feature/sub", "unsupported_change")


def test_a_change_that_updates_a_submodule_is_refused(w):
    # develop にサブモジュールがあり、feature がその指す commit を変える
    _git(w.repo, "update-index", "--add", "--cacheinfo", f"160000,{w.rev()},vendor/lib")
    _git(w.repo, "commit", "-q", "-m", "chore: サブモジュールを足す")
    _git(w.repo, "checkout", "-q", "-b", "feature/bump", "develop")
    newer = _git(
        w.repo, "rev-parse", "develop"
    ).strip()  # develop の gitlink は、この 1 つ前の commit を指している
    _git(w.repo, "update-index", "--cacheinfo", f"160000,{newer},vendor/lib")
    _git(w.repo, "commit", "-q", "-m", "chore: サブモジュールを進める")
    _git(w.repo, "checkout", "-q", "develop")
    _refused(w, "feature/bump", "unsupported_change")


def test_a_change_that_removes_a_submodule_is_refused(w):
    _git(w.repo, "update-index", "--add", "--cacheinfo", f"160000,{w.rev()},vendor/lib")
    _git(w.repo, "commit", "-q", "-m", "chore: サブモジュールを足す")
    _git(w.repo, "checkout", "-q", "-b", "feature/drop", "develop")
    _git(w.repo, "update-index", "--force-remove", "vendor/lib")
    _git(w.repo, "commit", "-q", "-m", "chore: サブモジュールを外す")
    _git(w.repo, "checkout", "-q", "develop")
    _refused(w, "feature/drop", "unsupported_change")


def test_a_change_without_submodules_is_accepted(w):
    w.feature("feature/a", {"a.txt": "a\n", "dir/b.txt": "b\n"})
    rc, out, _ = w.plan("feature/a")
    assert rc == 0 and out["ok"], out


def test_a_file_with_a_filter_attribute_is_refused(w):
    w.feature(
        "feature/lfs",
        {".gitattributes": "*.bin filter=lfs diff=lfs merge=lfs -text\n", "a.bin": "pointer\n"},
        force=True,
    )
    _refused(w, "feature/lfs", "unsupported_change")


def test_a_filter_attribute_defined_on_the_target_side_is_found_too(w):
    """.gitattributes が target 側にあり、feature は対象のファイルだけを変える（結果の tree で見る）。"""
    _commit(
        w.repo, {".gitattributes": "*.bin filter=lfs\n", "x.bin": "one\n"}, "chore: filter 属性"
    )
    w.feature("feature/bin", {"x.bin": "two\n"})
    _refused(w, "feature/bin", "unsupported_change")


def test_attributes_other_than_filter_and_an_unset_filter_are_accepted(w):
    _commit(
        w.repo,
        {".gitattributes": "*.txt text eol=lf\n*.dat -filter\n*.md diff=markdown\n"},
        "chore: 属性",
    )
    w.feature("feature/a", {"a.txt": "a\n", "b.dat": "b\n", "c.md": "c\n"})
    rc, out, _ = w.plan("feature/a")
    assert rc == 0 and out["ok"], out
    rc, out, _ = w.merge("feature/a")
    assert rc == 0 and out["ok"], out


# ---------------------------------------------------------------- 確認を実行できないときは、通さずに断る


@pytest.mark.parametrize("fail_on", [("check-attr",), ("diff-tree", "--raw")])
def test_a_failed_check_never_lets_the_change_through(w, fail_on):
    """扱えない変更かを確かめる git が失敗したとき、「問題なし」として統合しない。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    real = shutil.which("git")
    assert real
    bindir = w.tmp / "failbin"
    bindir.mkdir()
    conds = " && ".join(f'case " $* " in *" {a} "*) ;; *) false;; esac' for a in fail_on)
    script = bindir / "git"
    script.write_text(
        f'#!/bin/sh\nif {conds}; then exit 1; fi\nexec "{real}" "$@"\n', encoding="utf-8"
    )
    script.chmod(0o755)
    base = w.env()
    w.env = lambda: {**base, "PATH": f"{bindir}{os.pathsep}{base['PATH']}"}  # type: ignore[method-assign]
    _refused(w, "feature/a", "failed")
