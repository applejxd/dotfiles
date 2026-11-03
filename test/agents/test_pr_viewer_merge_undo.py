"""統合の取り消し（巻き戻し）の手順が、本当に統合前の状態へ戻せることを実 git で固定する（git 堅牢化 P4）。

手順の正本は `docs/spec/pr-viewer.md` §6「統合を取り消す」。ここは、その手順どおりのコマンドで次が成り立つことを確かめる:
- 未 push で他のコミットが無いとき: develop が checkout 中なら `git reset --keep <targetOld>`、
  checkout されていなければ `git update-ref refs/heads/develop <targetOld> <統合コミット>`（期待値つき）
- push 済み・他のコミットがあるとき: `git revert -m 1 <統合コミット>`
- 統合の cleanup で消えた枝: `git branch <枝> <統合コミット>^2`
"""

from __future__ import annotations

from test_pr_viewer_merge import _git
from test_pr_viewer_merge_faults import _build, _obs


def _merge_ok(w, *extra: str) -> dict:
    rc, out, _ = w.merge("feature/a", "feat: a を統合\n\n本文\n", *extra)
    assert rc == 0 and out and out["ok"], (rc, out)
    return out["result"]


def test_reset_keep_returns_to_the_state_before_the_merge(tmp_path):
    """develop が checkout 中の未 push: `git reset --keep <targetOld>` で、統合前と同じ develop・作業ツリー・index・利用者の作業に戻る。"""
    w = _build(tmp_path, "wt")
    before = _obs(w)
    res = _merge_ok(w)
    assert res["targetOld"] == before["develop"] and _obs(w)["develop"] == res["commit"]
    _git(w.repo, "reset", "--keep", res["targetOld"])
    after = _obs(w)
    for key in ("develop", "tree", "snap", "status", "index", "refs", "config", "hooks"):
        assert after[key] == before[key], key


def test_update_ref_with_expected_value_returns_when_develop_is_not_checked_out(tmp_path):
    """develop がどの worktree でも checkout されていない: 期待値つきの `git update-ref` で戻る（別の更新が入っていれば失敗する）。"""
    w = _build(tmp_path, "bare")
    before = _obs(w)
    res = _merge_ok(w)
    _git(w.repo, "update-ref", "refs/heads/develop", res["targetOld"], res["commit"])
    after = _obs(w)
    for key in ("develop", "tree", "snap", "status", "index"):
        assert after[key] == before[key], key


def test_update_ref_refuses_when_develop_moved_after_the_merge(tmp_path):
    """統合のあとに develop が進んでいたら、期待値が合わないので update-ref は何も変えない（上書きで他のコミットを失わない）。"""
    w = _build(tmp_path, "bare")
    res = _merge_ok(w)
    _git(
        w.repo,
        "update-ref",
        "refs/heads/develop",
        _git(
            w.repo, "commit-tree", f"{res['commit']}^{{tree}}", "-p", res["commit"], "-m", "後続"
        ).strip(),
    )
    moved = w.rev("develop")
    _git(w.repo, "update-ref", "refs/heads/develop", res["targetOld"], res["commit"], check=False)
    assert w.rev("develop") == moved


def test_revert_dash_m1_returns_the_tree_even_with_later_commits(tmp_path):
    """push 済み・後続のコミットがある: `git revert -m 1 <統合コミット>` は履歴を巻き戻さず、統合前の tree へ戻す新しいコミットを作る。"""
    w = _build(tmp_path, "wt")
    before = _obs(w)
    res = _merge_ok(w)
    _git(w.repo, "revert", "-m", "1", "--no-edit", res["commit"])
    assert _git(w.repo, "rev-parse", "HEAD^{tree}").strip() == before["tree"]
    # 履歴は残る（統合コミットは祖先のまま）
    assert _git(w.repo, "merge-base", "--is-ancestor", res["commit"], "HEAD") == ""
    assert (w.repo / "memo" / "note.txt").read_text(encoding="utf-8") == "消してはいけない\n"


def test_branch_deleted_by_cleanup_is_restored_from_the_second_parent(tmp_path):
    """cleanup で消えた枝は、統合コミットの第 2 親（feature の先頭）から `git branch` で戻せる。"""
    w = _build(tmp_path, "wt")
    feature = w.rev("feature/a")
    res = _merge_ok(w, "--cleanup", "branch")
    assert "refs/heads/feature/a" not in _git(w.repo, "for-each-ref", "--format=%(refname)")
    _git(w.repo, "branch", "feature/a", f"{res['commit']}^2")
    assert w.rev("feature/a") == feature
