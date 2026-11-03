"""PR ビューアの統合器（merge.ts）の失敗注入の試験（CHG-0062 §3.5 の契約が「正しい状態」の定義）。

偽の git（シェルスクリプト）を PATH の先頭に置き、統合の中の k 番目の git 呼び出しだけを壊して、
どこで壊れても利用者のデータが壊れた状態で残らないことを実 git で確かめる。
方式: A=実行せず失敗 / B=実行したが失敗と報告 / C1・C2=実行の前・後に統合器の node を kill -9。
名前・メールは架空（Example Dev <you@example.com>）。Windows は未検証（偽 git は sh）。
"""

from __future__ import annotations

import atexit
import functools
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest
from test_pi_judge_ts import _node
from test_pr_viewer_merge import CLI, World
from test_pr_viewer_server import _commit, _git

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

REAL_GIT = shutil.which("git") or "git"

# 偽の git。k 番目（隣の k ファイル）の呼び出しだけを方式（隣の mode ファイル）で壊す。実 git は絶対パスで呼ぶ（再帰しない）。
# 統合器は子の環境変数を絞るので、設定は環境変数ではなくスクリプトの隣のファイルで渡す。
FAKE_GIT = """#!/bin/sh
set -u
FAULT_DIR=$(cd "$(dirname "$0")/.." && pwd)
FAULT_REAL_GIT=@REAL@
FAULT_K=$(cat "$FAULT_DIR/k")
FAULT_MODE=$(cat "$FAULT_DIR/mode")
n=$(cat "$FAULT_DIR/count" 2>/dev/null || echo 0)
n=$((n + 1))
echo "$n" > "$FAULT_DIR/count"
echo "$n $*" >> "$FAULT_DIR/calls.log"
if [ "$n" != "$FAULT_K" ]; then exec "$FAULT_REAL_GIT" "$@"; fi
case "$FAULT_MODE" in
fail)
    echo "fatal: injected failure" >&2
    exit 1
    ;;
lie)
    "$FAULT_REAL_GIT" "$@"
    exit 1
    ;;
kill_before)
    kill -9 "$PPID"
    exit 1
    ;;
kill_after)
    "$FAULT_REAL_GIT" "$@"
    kill -9 "$PPID"
    exit 1
    ;;
esac
exec "$FAULT_REAL_GIT" "$@"
"""

# 呼び出し行からサブコマンドを取り出すための、固定の先頭引数
_SUBCOMMANDS = {
    "rev-parse",
    "config",
    "merge-base",
    "merge-tree",
    "diff-tree",
    "worktree",
    "symbolic-ref",
    "status",
    "commit-tree",
    "merge",
    "update-ref",
}


def _subcommand(line: str) -> str:
    """`<n> <args...>` の行から git のサブコマンド名を返す（`-c X` の組と先頭のオプションを飛ばす）。"""
    toks = line.split()[1:]
    if "--version" in toks:
        return "version"  # 統合前の git の版の確認（P1）
    i = 0
    while i < len(toks):
        if toks[i] == "-c":
            i += 2
        elif toks[i].startswith("-"):
            i += 1
        else:
            break
    if i < len(toks) and toks[i] == "worktree" and toks[i + 1 : i + 2] == ["list"]:
        return "worktree list"
    return toks[i] if i < len(toks) else "?"


# ---------------------------------------------------------------- 舞台（使い捨てのリポジトリ）


def _build(tmp: Path, layout: str) -> World:
    """develop へ統合する feature を持つリポジトリ。利用者の未コミットの作業（統合と無関係）を置いておく。

    layout="wt": develop が主の作業ツリーで checkout 中（merge --ff-only の経路）。
    layout="bare": develop はどの worktree でも checkout されていない（update-ref の経路）。
    """
    w = World(tmp)
    w.feature(
        "feature/a",
        {"README.md": "base\nfeature\n", "newdir/sub/a.txt": "a\n", "docs/x.md": "x\n"},
    )
    _commit(w.repo, {"other.txt": "other2\n"}, "develop だけが進む")  # 本物の 2 親の merge にする
    if layout == "bare":
        _git(w.repo, "checkout", "-q", "-b", "scratch")
    (w.repo / "other.txt").write_text("other2\n利用者の編集\n", encoding="utf-8")  # 無関係な dirty
    (w.repo / "memo").mkdir()
    (w.repo / "memo" / "note.txt").write_text(
        "消してはいけない\n", encoding="utf-8"
    )  # 無関係な untracked
    (w.repo / "junk.ign").write_text("ignored\n", encoding="utf-8")  # 無関係な ignored
    return w


def _snap(w: World) -> dict[str, str]:
    """作業ツリー（.git 以外）の全ファイルと空でないディレクトリ・空ディレクトリの内容の写し。"""
    res: dict[str, str] = {}
    for root, dirs, files in os.walk(w.repo):
        if ".git" in dirs:
            dirs.remove(".git")
        for d in dirs:
            if not any((Path(root) / d).iterdir()):
                res[os.path.relpath(Path(root) / d, w.repo) + "/"] = "<dir>"
        for f in files:
            p = Path(root) / f
            res[os.path.relpath(p, w.repo)] = p.read_bytes().hex()
    return res


def _hooks(w: World) -> list[str]:
    hd = w.git_dir() / "hooks"
    return sorted(p.name for p in hd.iterdir()) if hd.exists() else []


def _refs(w: World, skip_develop: bool = True) -> str:
    out = _git(w.repo, "for-each-ref", "--format=%(refname) %(objectname)")
    if skip_develop:
        out = "\n".join(x for x in out.splitlines() if not x.startswith("refs/heads/develop "))
    return out


def _obs(w: World) -> dict:
    gd = w.git_dir()
    return {
        "develop": w.rev("develop"),
        "tree": _git(w.repo, "rev-parse", "develop^{tree}").strip(),
        "head": _git(w.repo, "symbolic-ref", "HEAD").strip(),
        "refs": _refs(w),
        "config": (gd / "config").read_bytes(),
        "hooks": _hooks(w),
        "snap": _snap(w),
        "status": w.status(),
        "index": _git(w.repo, "ls-files", "-s"),
    }


def _fsck_ok(w: World) -> bool:
    return (
        subprocess.run(
            [REAL_GIT, "-C", str(w.repo), "fsck", "--no-dangling"],
            capture_output=True,
            env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"},
            check=False,
        ).returncode
        == 0
    )


def _leftovers(w: World) -> dict[str, bool]:
    gd = w.git_dir()
    return {
        n: (gd / n).exists()
        for n in ("index.lock", "pr-viewer-merge.lock", "pr-viewer-merge.state")
    }


# ---------------------------------------------------------------- 偽 git を挟んだ実行


def _install_fake(w: World) -> Path:
    fault = w.tmp / "fault"
    (fault / "bin").mkdir(parents=True)
    (fault / "tmp").mkdir()
    script = fault / "bin" / "git"
    script.write_text(FAKE_GIT.replace("@REAL@", REAL_GIT), encoding="utf-8", newline="\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return fault


def _run_merge(w: World, fault: Path, mode: str = "", k: int = 0, timeout: int = 90):
    """偽 git を PATH の先頭にして merge を 1 回実行する。結果は (終了コード, JSON, 呼び出しの行)。"""
    env = w.env()
    env.update(
        PATH=f"{fault / 'bin'}{os.pathsep}{env['PATH']}",
        TMPDIR=str(fault / "tmp"),  # kill された node が残す一時ディレクトリを閉じ込める
    )
    (fault / "mode").write_text(mode, encoding="utf-8")
    (fault / "k").write_text(str(k), encoding="utf-8")
    (fault / "count").unlink(missing_ok=True)
    (fault / "calls.log").unlink(missing_ok=True)
    proc = subprocess.run(
        [_node(), str(CLI), "merge", str(w.repo), "--source", "feature/a", "--message-file", "-"],
        input="feat: a を統合\n\n本文\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=w.tmp,
        timeout=timeout,
        check=False,
    )
    out = proc.stdout.strip()
    try:
        obj = json.loads(out.splitlines()[-1]) if out else None
    except ValueError:
        obj = {"unparsable": out}
    calls = fault / "calls.log"
    assert calls.exists() or mode.startswith("kill"), (proc.returncode, proc.stdout, proc.stderr)
    log = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return proc.returncode, obj, log


@functools.cache
def _baseline(layout: str) -> dict:
    """注入なしで 1 回統合して、呼び出しの列と、成功した後の期待値（tree・作業ツリー・status）を得る。"""
    tmp = Path(tempfile.mkdtemp(prefix="merge-faults-base-"))
    atexit.register(shutil.rmtree, tmp, True)
    w = _build(tmp, layout)
    before = _obs(w)
    gd_before = _gitdir_names(w)
    rc, out, log = _run_merge(w, _install_fake(w))
    assert rc == 0 and out["ok"], out
    after = _obs(w)
    return {
        "before": before,
        "after": after,
        "calls": [_subcommand(x) for x in log],
        "raw": log,
        "gitdir_before": gd_before,
        "gitdir_new": _gitdir_names(w) - gd_before,
    }


# 注入なしの統合が呼ぶ git のサブコマンド（k = 1..N）。統合器の手順が変わったら、下の試験が落ちて k の対応の見直しを促す
_COMMON = [
    "version",  # 1 git の版（P1）
    "rev-parse",  # 2 common-dir
    "config",  # 3 .git/config の外部コード検査（P1）
    "config",  # 4 .git/config の未対応設定の検査（P1）
    "rev-parse",  # 5 source
    "rev-parse",  # 6 target
    "merge-base",  # 7 is-ancestor
    "merge-tree",  # 8
    "merge-base",  # 9
    "diff-tree",  # 10
    "diff-tree",  # 11 --raw（P1。変わるパスの確認）
    "check-attr",  # 12 filter 属性の確認（P1）
    "worktree list",  # 13
]
# 統合器が何も変える前に行う確認の呼び出しの数（k がここまでなら、失敗は「何も変えず failed」でなければならない）
PREFLIGHT_CALLS = 13
# P1 で増えた確認の呼び出し（version・config 2 回・diff-tree --raw・check-attr）。失敗を「後続を進めて良い」と読むと危険なもの
P1_ADDED_CALLS = (1, 3, 4, 11, 12)
EXPECTED_CALLS = {
    "wt": [
        *_COMMON,
        "rev-parse",  # 14 target の worktree の git-dir
        "symbolic-ref",  # 15
        "status",  # 16
        "status",  # 17 --ignored
        "config",  # 18 identity
        "rev-parse",  # 19 source（最終の検査）
        "rev-parse",  # 20 target
        "symbolic-ref",  # 21
        "status",  # 22
        "status",  # 23
        "commit-tree",  # 24
        "symbolic-ref",  # 25 ff の直前の HEAD 確認
        "merge",  # 26 --ff-only
        "rev-parse",  # 27 反映の確認
    ],
    "bare": [
        *_COMMON,
        "config",  # 14 identity
        "rev-parse",  # 15
        "rev-parse",  # 16
        "commit-tree",  # 17
        "update-ref",  # 18 CAS
        "rev-parse",  # 19 反映の確認
    ],
}
LAYOUTS = tuple(EXPECTED_CALLS)
MODES = {"A": "fail", "B": "lie", "C1": "kill_before", "C2": "kill_after"}


@pytest.mark.parametrize("layout", LAYOUTS)
def test_baseline_call_sequence_is_recorded(layout):
    base = _baseline(layout)
    assert base["calls"] == EXPECTED_CALLS[layout], base["raw"]
    assert _fsck_ok_dir(base["before"]) in (True, None)


def _fsck_ok_dir(_obs_dict: dict) -> None:
    return None


# ---------------------------------------------------------------- 不変条件


def _gitdir_names(w: World) -> set[str]:
    return {p.name for p in w.git_dir().iterdir()}


def _stable(w: World, base: dict, now: dict, problems: list[str]) -> None:
    """どの場合でも変わってはいけないもの: develop 以外の ref・config・hooks・HEAD・オブジェクトの整合。"""
    before = base["before"]
    for key in ("refs", "config", "hooks", "head"):
        if now[key] != before[key]:
            problems.append(f"{key} が変わった")
    if not _fsck_ok(w):
        problems.append("git fsck が通らない")
    stray = _gitdir_names(w) - base["gitdir_before"] - base["gitdir_new"]
    stray -= {"pr-viewer-merge.lock", "pr-viewer-merge.state"}
    if stray:
        problems.append(f"想定外のファイルが .git に残った: {sorted(stray)}")


def _is_original(now: dict, base: dict) -> bool:
    b = base["before"]
    return now["snap"] == b["snap"] and now["status"] == b["status"] and now["index"] == b["index"]


def _is_merged(now: dict, base: dict) -> bool:
    a = base["after"]
    return (
        now["tree"] == a["tree"]
        and now["snap"] == a["snap"]
        and now["status"] == a["status"]
        and now["index"] == a["index"]
    )


def _recover(w: World):
    rc, out, proc = w.cli("recover")
    return rc, out, proc


def _diagnosis_ok(out: dict | None) -> bool:
    """recover の結果が、JSON の診断（成功、または原因つきの拒否）になっているか。"""
    if not isinstance(out, dict):
        return False
    if out.get("ok") is True:
        return out.get("state") in ("clean", "completed", "cleared")
    return (isinstance(out.get("details"), dict) and "cause" in out["details"]) or out.get(
        "code"
    ) in ("busy", "bad_input")


def _retry_works(w: World, base: dict, problems: list[str], state_left: bool) -> None:
    """develop が元のままのとき、（必要なら recover の後に）もう一度統合でき、期待どおりの結果になる。"""
    if state_left:
        rc, out, _ = w.merge("feature/a")
        if rc != 2 or out.get("code") != "recover_needed":
            problems.append(f"状態ファイルが残っているのに新しい統合を断らない: {rc} {out}")
            return
        rc, out, _ = _recover(w)
        if not (rc == 0 and out.get("ok")):
            problems.append(f"元の状態なのに recover が解除しない: {rc} {out}")
            return
    rc, out, _ = w.merge("feature/a")
    if not (rc == 0 and out.get("ok")):
        problems.append(f"やり直しの統合が成功しない: {rc} {out}")
        return
    now = _obs(w)
    if not _is_merged(now, base):
        problems.append("やり直しの統合の後の作業ツリーが、期待と違う")
    if any(_leftovers(w).values()):
        problems.append(f"やり直しの後に残りがある: {_leftovers(w)}")


def _check_returned(w: World, base: dict, rc: int, out: dict | None) -> list[str]:
    """統合器が正常に返った（方式 A・B）後の不変条件。破れの一覧を返す（空なら契約どおり）。"""
    problems: list[str] = []
    now = _obs(w)
    left = _leftovers(w)
    _stable(w, base, now, problems)
    if not isinstance(out, dict) or rc not in (0, 2):
        problems.append(f"JSON の結果で正常に返らなかった: rc={rc} {out}")
        return problems
    if left["index.lock"]:
        problems.append("index.lock が残った")
    if left["pr-viewer-merge.lock"]:
        problems.append("排他のロックが残った（正常な返却では残らない）")
    old = base["before"]["develop"]
    if out.get("ok"):
        # 成功: develop が merge commit へ進み、作業ツリーが統合後の状態で clean（無関係な作業は残る）
        if now["develop"] != out["result"]["commit"]:
            problems.append("ok:true なのに develop が返ったコミットを指さない")
        if _git(w.repo, "rev-list", "--parents", "-n", "1", "develop").split()[1] != old:
            problems.append("merge commit の第 1 親が元の develop でない")
        if not _is_merged(now, base):
            problems.append("ok:true なのに作業ツリー・index が統合後の状態でない（中間状態）")
        if left["pr-viewer-merge.state"]:
            problems.append("成功なのに状態ファイルが残った")
        return problems
    # 反映の確認だけが読めなかった: 「失敗」とも「先に進んでいる」とも言わず、状態ファイルを残して recover に確かめさせる（§3.5）
    if out.get("code") == "unverified":
        if now["develop"] != base["after"]["develop"] and not _is_merged(now, base):
            problems.append(
                "unverified だが、develop が進んだのに作業ツリー・index が統合後の状態でない（中間状態）"
            )
        if not left["pr-viewer-merge.state"]:
            problems.append("unverified なのに状態ファイルが無い（recover で確かめられない）")
            return problems
        r_rc, r_out, _ = _recover(w)
        if not r_out.get("ok") or r_out.get("state") != "completed":
            problems.append(
                f"unverified の後の recover が「統合済み」として解除しない: {r_rc} {r_out}"
            )
        if any(_leftovers(w).values()):
            problems.append(f"recover の後に残りがある: {_leftovers(w)}")
        return problems
    # 失敗の返却
    state_left = left["pr-viewer-merge.state"]
    if now["develop"] == old:
        if not _is_original(now, base):
            # §3.5: 作業ツリーが無傷と確かめられないときは状態ファイルを残し、recover が診断する（それは契約どおり）
            if not state_left:
                problems.append(
                    "失敗を返し、develop は元のままだが、作業ツリー・index が変わっていて、状態ファイルも無い"
                )
            else:
                r_rc, r_out, _ = _recover(w)
                if not _diagnosis_ok(r_out) or r_out.get("ok"):
                    problems.append(
                        f"作業ツリーが変わっているのに recover が診断を返さない: {r_rc} {r_out}"
                    )
            return problems
        if not _is_original(now, base):  # 到達しない（上で返す）
            problems.append("元の状態でない")
        _retry_works(w, base, problems, state_left)
        return problems
    if now["tree"] == base["after"]["tree"]:
        # 失敗を返したのに develop が進んでいる。§3.5 は「失敗を返すのは反映されていないとき」としか許さない
        problems.append(
            f"失敗（{out.get('code')}）を返したのに develop が merge commit へ進んでいる"
        )
        if not _is_merged(now, base):
            problems.append(
                "develop が進んだのに作業ツリー・index が統合後の状態でない（中間状態）"
            )
        return problems
    problems.append("develop が元でも統合後でもない")
    return problems


def _check_crashed(w: World, base: dict, rc: int) -> list[str]:
    """統合器の node が kill -9 された後の不変条件。recover が診断を返し、利用者のファイルが残っている。"""
    problems: list[str] = []
    if rc != -9:
        problems.append(f"kill -9 の想定どおりに終わらなかった: rc={rc}")
    now = _obs(w)
    left = _leftovers(w)
    _stable(w, base, now, problems)
    if left["index.lock"]:
        problems.append("index.lock が残った")
    old = base["before"]["develop"]
    merged = now["develop"] != old
    if merged and not _is_merged(now, base):
        problems.append("develop は進んだが、作業ツリー・index が統合後の状態でない")
    if not merged and not _is_original(now, base):
        problems.append("develop は元のままなのに、作業ツリー・index が変わった")
    if base["before"]["snap"]["memo/note.txt"] != now["snap"].get("memo/note.txt"):
        problems.append("統合前の untracked のファイルが失われた")
    if left["pr-viewer-merge.state"] or left["pr-viewer-merge.lock"]:
        # 排他も状態も残っている間は、新しい統合を断って何も変えない（§3.5 排他・状態ファイル）
        m_rc, m_out, _ = w.merge("feature/a")
        if (
            not (m_rc == 2 and m_out.get("code") == "recover_needed")
            or _obs(w)["develop"] != now["develop"]
        ):
            problems.append(f"残りがある間の統合が recover_needed で断られない: {m_rc} {m_out}")
    r_rc, r_out, _ = _recover(w)
    if not _diagnosis_ok(r_out):
        problems.append(f"recover が診断を返さない: {r_rc} {r_out}")
        return problems
    if not r_out.get("ok"):
        problems.append(f"整合した状態なのに recover が診断だけを返し解除しない: {r_out}")
        return problems
    if any(_leftovers(w).values()):
        problems.append(f"recover の後に残りがある: {_leftovers(w)}")
    p_rc, p_out, _ = w.plan("feature/a")
    expect_code = "already_merged" if merged else None
    if merged and p_out.get("code") != expect_code:
        problems.append(f"recover の後の plan が想定外: {p_rc} {p_out}")
    if not merged:
        if not p_out.get("ok"):
            problems.append(f"recover の後の plan が通らない: {p_rc} {p_out}")
        else:
            _retry_works(w, base, problems, state_left=False)
    return problems


# ---------------------------------------------------------------- 全ステップの失敗注入


def _scenario_id(layout: str, method: str, k: int) -> str:
    return f"{layout}-{method}-k{k:02d}-{EXPECTED_CALLS[layout][k - 1].replace(' ', '_')}"


CASES = [
    pytest.param(layout, method, k, id=_scenario_id(layout, method, k))
    for layout in LAYOUTS
    for method in MODES
    for k in range(1, len(EXPECTED_CALLS[layout]) + 1)
]


@pytest.mark.parametrize(("layout", "method", "k"), CASES)
def test_fault_at_every_git_call_never_leaves_broken_state(tmp_path, layout, method, k):
    w = _build(tmp_path, layout)
    # commit の oid は時刻で変わるので、期待値のうち oid に依らないもの（tree・作業ツリー）だけを基準から借り、統合前は自分の写しを使う
    base = {**_baseline(layout), "before": _obs(w), "gitdir_before": _gitdir_names(w)}
    fault = _install_fake(w)
    rc, out, log = _run_merge(w, fault, MODES[method], k)
    assert len(log) >= k, f"k 番目の呼び出しに届かなかった: {log}"
    problems = (
        _check_crashed(w, base, rc) if method.startswith("C") else _check_returned(w, base, rc, out)
    )
    assert not problems, (
        f"{layout}/{method}/k={k}（{EXPECTED_CALLS[layout][k - 1]}）: {problems}（結果: {rc} {out}）"
    )


@pytest.mark.parametrize("method", ["A", "B"])
@pytest.mark.parametrize("layout", LAYOUTS)
def test_unreadable_final_ref_check_is_reported_as_unverified(tmp_path, layout, method):
    """反映の確認（最後の rev-parse）だけが失敗したとき、「先に進んでいる」と誤報せず unverified を返し、recover が済みと確かめる。"""
    k = len(EXPECTED_CALLS[layout])
    w = _build(tmp_path, layout)
    base = {**_baseline(layout), "before": _obs(w), "gitdir_before": _gitdir_names(w)}
    rc, out, _ = _run_merge(w, _install_fake(w), MODES[method], k)
    assert out and out.get("code") == "unverified", (rc, out)
    assert not _check_returned(w, base, rc, out)


@pytest.mark.parametrize("method", ["A", "B"])
@pytest.mark.parametrize("layout", LAYOUTS)
def test_preflight_git_failure_refuses_with_failed_and_changes_nothing(tmp_path, layout, method):
    """P1 の確認（版・config・check-attr・diff-tree --raw など）の git が壊れたら、何も変えず failed で断る（状態ファイルも残さない）。"""
    assert EXPECTED_CALLS[layout][PREFLIGHT_CALLS - 1] == "worktree list"
    for k in P1_ADDED_CALLS:
        (tmp_path / f"k{k}").mkdir()
        w = _build(tmp_path / f"k{k}", layout)
        base = {**_baseline(layout), "before": _obs(w), "gitdir_before": _gitdir_names(w)}
        rc, out, _ = _run_merge(w, _install_fake(w), MODES[method], k)
        where = f"{layout}/{method}/k={k}（{EXPECTED_CALLS[layout][k - 1]}）"
        assert rc == 2 and isinstance(out, dict), (where, rc, out)
        # P1 で増えた diff-tree --raw（11）・check-attr（12）は必ず failed。その他は安全側の専用コードで断ってよい
        assert out.get("ok") is False, (where, out)
        if k in (11, 12):
            assert out.get("code") == "failed", (where, out)
        now = _obs(w)
        assert now["develop"] == base["before"]["develop"], where
        assert _is_original(now, base), where
        assert not any(_leftovers(w).values()), (where, _leftovers(w))
        problems: list[str] = []
        _stable(w, base, now, problems)
        assert not problems, (where, problems)


# ---------------------------------------------------------------- ファイルシステムの失敗（root では権限が効かないので skip）

needs_perm = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root では書き込み禁止の権限が効かない"
)


def _chmod_tree(root: Path, mode: int) -> None:
    """root 以下のディレクトリ（と root 自身）の権限を変える。"""
    for dirpath, dirnames, _ in os.walk(root, topdown=False):
        for d in dirnames:
            os.chmod(Path(dirpath) / d, mode)
    os.chmod(root, mode)


def _unchanged(w: World, before: dict, problems: list[str]) -> None:
    now = _obs(w)
    for key in ("develop", "refs", "config", "hooks", "head", "snap", "status", "index"):
        if now[key] != before[key]:
            problems.append(f"{key} が変わった")
    if any(_leftovers(w).values()):
        problems.append(f"残りがある: {_leftovers(w)}")


@needs_perm
@pytest.mark.parametrize("cmd", ["plan", "merge"])
def test_unwritable_object_store_fails_and_changes_nothing(tmp_path, cmd):
    """(a) .git/objects に書けない（merge-tree が object を書けない）→ 失敗で何も変わらない。"""
    w = _build(tmp_path, "wt")
    before = _obs(w)
    objects = w.git_dir() / "objects"
    _chmod_tree(objects, 0o555)
    try:
        if cmd == "plan":
            rc, out, _ = w.plan("feature/a")
        else:
            rc, out, _ = w.merge("feature/a")
    finally:
        _chmod_tree(objects, 0o755)  # 後始末（権限を必ず戻す）
    assert rc == 2 and out["ok"] is False and out["code"] == "failed", (rc, out)
    problems: list[str] = []
    _unchanged(w, before, problems)
    assert _fsck_ok(w)
    assert not problems, problems


@needs_perm
def test_unwritable_worktree_dir_never_leaves_a_half_written_tree(tmp_path):
    """(b) 統合で更新されるファイルのあるディレクトリに書けない → 半端に書き換わったままにならない。

    §3.5: 失敗でも作業ツリーが無傷と確かめられたときだけ状態を消す。無傷でなければ状態を残し、recover が診断する。
    """
    w = World(tmp_path)
    _commit(w.repo, {"locked/f.txt": "v1\n"}, "locked を足す")
    w.feature(
        "feature/a", {"README.md": "base\nfeature\n", "locked/f.txt": "v2\n", "zzz.txt": "z\n"}
    )
    (w.repo / "memo").mkdir()
    (w.repo / "memo" / "note.txt").write_text("消してはいけない\n", encoding="utf-8")
    before = _obs(w)
    locked = w.repo / "locked"
    locked.chmod(0o555)
    try:
        rc, out, _ = w.merge("feature/a")
        after = _obs(w)
        left = _leftovers(w)
        snap_locked = {p: v for p, v in after["snap"].items() if p.startswith("locked")}
        recovered = _recover(w) if left["pr-viewer-merge.state"] else None
    finally:
        locked.chmod(0o755)
    assert rc == 2 and out["ok"] is False, (rc, out)
    assert not left["index.lock"] and not left["pr-viewer-merge.lock"], left
    assert after["develop"] == before["develop"], "失敗を返したのに develop が進んだ"
    assert after["refs"] == before["refs"] and after["config"] == before["config"]
    assert _fsck_ok(w)
    assert snap_locked == {p: v for p, v in before["snap"].items() if p.startswith("locked")}
    if after["snap"] != before["snap"] or after["status"] != before["status"]:
        # 作業ツリーが半端に変わった: 状態ファイルが残り、recover が何を戻すかを診断で示す
        assert left["pr-viewer-merge.state"], "作業ツリーが変わったのに状態ファイルが無い"
        _r_rc, r_out, _ = recovered
        assert r_out["ok"] is False and r_out["details"]["cause"] == "worktree_not_clean", r_out
        listed = set(r_out["details"]["paths"])
        changed = {
            p
            for p in set(before["snap"]) | set(after["snap"])
            if before["snap"].get(p) != after["snap"].get(p)
        }
        assert changed <= {p for p in listed} | {p.rsplit("/", 1)[0] for p in listed if "/" in p}, (
            changed,
            listed,
        )
    # 利用者の無関係な作業は残る
    assert after["snap"]["memo/note.txt"] == before["snap"]["memo/note.txt"]
    assert after["snap"]["README.md"] in (
        before["snap"]["README.md"],
        _baseline("wt")["after"]["snap"]["README.md"],
    )


def test_existing_index_lock_is_refused_and_kept(tmp_path):
    """(c) index.lock が既にある → 分かりやすい拒否（busy）で、そのファイルを消さない。"""
    w = _build(tmp_path, "wt")
    lock = w.git_dir() / "index.lock"
    lock.write_text("他の git の書き込み中\n", encoding="utf-8")
    before = _obs(w)
    for cmd in ("merge", "plan"):
        rc, out, _ = w.merge("feature/a") if cmd == "merge" else w.plan("feature/a")
        assert rc == 2 and out["code"] == "busy", (cmd, rc, out)
        assert lock.read_text(encoding="utf-8") == "他の git の書き込み中\n"
    assert _obs(w) == before
    assert not _leftovers(w)["pr-viewer-merge.lock"] and not _leftovers(w)["pr-viewer-merge.state"]
    # recover も index.lock を消さない（診断の対象にしない: 状態が無いので clean）
    _r_rc, r_out, _ = _recover(w)
    assert r_out["ok"] and lock.exists()


@pytest.mark.parametrize("what", ["dirty", "untracked"])
def test_overlapping_local_changes_are_refused(tmp_path, what):
    """(d) 作業ツリーの dirty / untracked が統合対象のパスと重なる → 事前検査で断り、利用者のファイルを残す。"""
    w = _build(tmp_path, "wt")
    if what == "dirty":
        target = w.repo / "README.md"
        target.write_text("base\n利用者の編集\n", encoding="utf-8")
    else:
        target = w.repo / "newdir" / "sub" / "a.txt"
        target.parent.mkdir(parents=True)
        target.write_text("利用者のファイル\n", encoding="utf-8")
    before = _obs(w)
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "dirty", (rc, out)
    assert _obs(w) == before
    assert target.read_text(encoding="utf-8").startswith(("base\n利用者", "利用者"))
    assert not any(_leftovers(w).values())
