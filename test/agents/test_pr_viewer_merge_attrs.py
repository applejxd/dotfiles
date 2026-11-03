"""統合器の属性（.gitattributes）の固定試験（レビュー M2・B1）。

乱数の差分試験（test_pr_viewer_merge_oracle.py）とは別に、属性の参照元に関する最小の fixture を固定する。
統合器は merge-tree に `--attr-source=<target の OID>` を渡して target の属性を読ませる。
- 属性を target の tree から読むことが、素の `git merge`（worktree の属性）と同じ結果になること
- `--attr-source` を外す・参照元を source に替える変異を、この試験が検出すること
- target の worktree の属性が未コミットで変わっているときは、merge-tree より前に断ること（B1）
名前・メールは架空。
"""

from __future__ import annotations

import pytest
from test_pi_judge_ts import _node
from test_pr_viewer_merge import World, _no_leftovers
from test_pr_viewer_server import _commit, _git

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

LINES = "1\n2\n3\n4\n5\n"


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def _read(w: World, rel: str) -> str:
    return (w.repo / rel).read_text(encoding="utf-8")


def _setup(w: World, attrs: str) -> None:
    _commit(w.repo, {".gitattributes": attrs, "f.txt": LINES}, "attrs")


def _develop_edits_line1(w: World) -> None:
    _commit(w.repo, {"f.txt": LINES.replace("1\n", "D1\n", 1)}, "develop edit")


def _feature_edits_line5(w: World, extra: dict[str, str] | None = None) -> None:
    w.feature("feature/a", {"f.txt": LINES.replace("5\n", "F5\n"), **(extra or {})})


def _real_merge_result(w: World) -> str:
    """素の git merge の結果（同じ状況で、別のクローンに対して）。衝突なら "CONFLICT"。"""
    clone = w.tmp / "oracle"
    _git(w.tmp, "clone", "-q", str(w.repo), str(clone))
    _git(clone, "config", "user.name", "Example Dev")
    _git(clone, "config", "user.email", "you@example.com")
    _git(clone, "checkout", "-q", "develop")
    proc = __import__("subprocess").run(
        ["git", "-C", str(clone), "merge", "--no-ff", "-q", "-m", "m", "origin/feature/a"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        return "CONFLICT"
    return (clone / "f.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------- target の属性が効く


def test_target_minus_merge_makes_a_nul_free_file_conflict_like_git_merge(w):
    """-merge は NUL を含まない内容にも効く。離れた行の変更でも衝突する（--attr-source を外すと衝突しなくなる）。"""
    _setup(w, "f.txt -merge\n")
    w.feature("feature/a", {"f.txt": LINES.replace("5\n", "F5\n")})
    _develop_edits_line1(w)
    assert _real_merge_result(w) == "CONFLICT"
    before = (w.rev(), w.status())
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "conflict", out
    assert (w.rev(), w.status()) == before
    _no_leftovers(w)


def test_target_binary_attribute_conflicts_like_git_merge(w):
    _setup(w, "f.txt binary\n")
    w.feature("feature/a", {"f.txt": LINES.replace("5\n", "F5\n")})
    _develop_edits_line1(w)
    assert _real_merge_result(w) == "CONFLICT"
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "conflict", out


def test_target_union_merges_the_same_line_like_git_merge(w):
    """merge=union は同じ行の変更を衝突にせず両方残す（--attr-source を外すと衝突になる）。"""
    _setup(w, "f.txt merge=union\n")
    w.feature("feature/a", {"f.txt": LINES.replace("3\n", "F3\n")})
    _commit(w.repo, {"f.txt": LINES.replace("3\n", "D3\n")}, "develop edit")
    expected = _real_merge_result(w)
    assert expected != "CONFLICT" and "F3" in expected and "D3" in expected
    rc, out, _ = w.merge("feature/a")
    assert rc == 0 and out["ok"], out
    assert _read(w, "f.txt") == expected


# ---------------------------------------------------------------- feature 側の属性は効かない


def test_attribute_added_only_by_the_feature_does_not_apply_like_git_merge(w):
    """feature だけが -merge を足しても、git merge は target の属性を使う。参照元を source にすると衝突に化ける。"""
    _commit(w.repo, {"f.txt": LINES}, "base file")
    _feature_edits_line5(w, {".gitattributes": "f.txt -merge\n"})
    _develop_edits_line1(w)
    expected = _real_merge_result(w)
    assert expected != "CONFLICT"
    rc, out, _ = w.merge("feature/a")
    assert rc == 0 and out["ok"], out
    assert _read(w, "f.txt") == expected


def test_attribute_changed_only_by_the_feature_does_not_apply(w):
    """target の union を feature が外しても、統合の判断は target の属性（union）で行われる。"""
    _setup(w, "f.txt merge=union\n")
    w.feature(
        "feature/a", {"f.txt": LINES.replace("3\n", "F3\n"), ".gitattributes": "f.txt -merge\n"}
    )
    _commit(w.repo, {"f.txt": LINES.replace("3\n", "D3\n")}, "develop edit")
    expected = _real_merge_result(w)
    # 素の git merge は target の属性（union）で f.txt を、feature 側の変更で .gitattributes を取り込む
    rc, out, _ = w.merge("feature/a")
    if expected == "CONFLICT":
        assert rc == 2
    else:
        assert rc == 0 and out["ok"], out
        assert _read(w, "f.txt") == expected


# ---------------------------------------------------------------- B1: worktree の未コミットの属性


def _refused_dirty(w: World) -> None:
    before = (w.rev(), _git(w.repo, "for-each-ref"), w.status())
    for rc, out, _ in (w.plan("feature/a"), w.merge("feature/a")):
        assert rc == 2 and out["ok"] is False and out["code"] == "dirty", out
        assert ".gitattributes" in out["reason"], out
    assert (w.rev(), _git(w.repo, "for-each-ref"), w.status()) == before
    _no_leftovers(w)


def _union_conflict_setup(w: World) -> None:
    _setup(w, "f.txt merge=union\n")
    w.feature("feature/a", {"f.txt": LINES.replace("3\n", "F3\n")})
    _commit(w.repo, {"f.txt": LINES.replace("3\n", "D3\n")}, "develop edit")


def test_uncommitted_gitattributes_edit_in_the_target_worktree_is_refused(w):
    """コミット済みは union（衝突なし）、worktree は -merge（衝突）。判定がずれるので、merge-tree の前に断る。"""
    _union_conflict_setup(w)
    (w.repo / ".gitattributes").write_text("f.txt -merge\n", encoding="utf-8")
    _refused_dirty(w)


def test_untracked_nested_gitattributes_in_the_target_worktree_is_refused(w):
    _union_conflict_setup(w)
    (w.repo / "sub").mkdir()
    (w.repo / "sub" / ".gitattributes").write_text("*.txt -merge\n", encoding="utf-8")
    _refused_dirty(w)


def test_deleted_gitattributes_in_the_target_worktree_is_refused(w):
    _union_conflict_setup(w)
    (w.repo / ".gitattributes").unlink()
    _refused_dirty(w)


def test_staged_gitattributes_edit_in_the_target_worktree_is_refused(w):
    _union_conflict_setup(w)
    (w.repo / ".gitattributes").write_text("f.txt -merge\n", encoding="utf-8")
    _git(w.repo, "add", ".gitattributes")
    _refused_dirty(w)


def test_an_unrelated_dirty_file_is_still_allowed(w):
    """対照: 属性以外の無関係な未コミットの変更は、これまでどおり許す。"""
    _union_conflict_setup(w)
    (w.repo / "other.txt").write_text("edited\n", encoding="utf-8")
    rc, out, _ = w.merge("feature/a")
    assert rc == 0 and out["ok"], out
    assert _read(w, "other.txt") == "edited\n"


def test_attr_tree_config_is_refused(w):
    """属性の参照元を変える設定（attr.tree）は扱わないので断る。"""
    _union_conflict_setup(w)
    _git(w.repo, "config", "attr.tree", "HEAD")
    before = (w.rev(), w.status())
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "unsupported_repo", out
    assert (w.rev(), w.status()) == before
    _no_leftovers(w)
