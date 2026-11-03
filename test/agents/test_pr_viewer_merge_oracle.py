"""PR ビューアの統合器（merge.ts）を、素の `git merge --no-ff` と突き合わせる差分試験（CHG-0062 §3.5・git 堅牢化 P2）。

統合器は配管コマンド（merge-tree・commit-tree・merge --ff-only）で merge commit を作る。porcelain の `git merge` とは別の経路なので、
同じ履歴から同じ結果（競合の判定・結果の tree・親の順・作業ツリーの内容）になることを、乱数で作ったシナリオで確かめる。

- シナリオは seed から再現できる（`random.Random(seed)`）。失敗の表示に seed と操作の記録を出す。
- 環境変数: `MERGE_ORACLE_N`（シナリオ数。既定 40）・`MERGE_ORACLE_SEED`（開始 seed。既定 1000）。
- 外部コードを動かす設定（merge driver・filter など）は統合器が拒否する仕様なので、使わない。
名前・メールは架空（Example Dev <you@example.com>）。Windows・macOS は未検証。
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest
from test_pi_judge_ts import _node
from test_pr_viewer_server import APP, _git

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

CLI = APP / "merge-cli.ts"
SCENARIOS = int(os.environ.get("MERGE_ORACLE_N", "40"))
FIRST_SEED = int(os.environ.get("MERGE_ORACLE_SEED", "1000"))
MESSAGE = "feat: oracle の統合\n\n本文の 1 行\n"

# 設定の軸
ATTRIBUTES = {
    "none": "",
    "text-auto": "* text=auto\n",
    "eol-crlf": "*.txt text eol=crlf\n",
    "binary": "*.bin binary\n",
}
AUTOCRLF = ["false", "true", "input"]
FILEMODE = ["true", "true", "false"]
RENAMES = [None, "true", "false"]
DIR_RENAMES = [None, "true", "false", "conflict"]

# 新しく作るパスの候補（日本語・空白・ディレクトリ・属性に当たる拡張子・大文字小文字違いを含む）
NEW_NAMES = [
    "new.txt",
    "src/new.py",
    "docs/guide.md",
    "日本語/新規.txt",
    "with space/c d.txt",
    "d/z.txt",
    "d/w.bin",
    "lib/c.c",
    "Notes.TXT",
    "blob.bin",
    "empty2.dat",
    "link2",
    "deep/er/file.txt",
]

BASE_TEXT = {
    "README.md": 10,
    "notes.txt": 9,
    "src/main.py": 12,
    "src/util.py": 8,
    "d/x.txt": 10,
    "d/y.txt": 9,
    "日本語/ファイル.txt": 8,
    "with space/a b.txt": 8,
    "Case.txt": 8,
    "lib/a.c": 10,
    "lib/b.c": 10,
}


# ---------------------------------------------------------------- シナリオの生成


def _text(rng: random.Random, n: int | None = None) -> bytes:
    """行ごとに特徴のある本文（リネームの類似度判定が働く程度の長さ）。ときどき CRLF の行末にする。"""
    nl = b"\r\n" if rng.random() < 0.15 else b"\n"
    n = n or rng.randint(6, 12)
    return b"".join(
        f"line {i} {rng.randint(0, 10**6):06d} 内容\n".encode().replace(b"\n", nl) for i in range(n)
    )


def _tracked(repo: Path) -> list[str]:
    """作業ツリーにあるファイルと symlink（.git 以外）。操作の途中でも、実際の状態から選ぶ。"""
    res = []
    for dirpath, dirnames, filenames in os.walk(repo):
        if dirpath == str(repo):
            dirnames[:] = [d for d in dirnames if d != ".git"]
        for n in filenames:
            res.append(str((Path(dirpath) / n).relative_to(repo)))
        for n in dirnames:
            if (Path(dirpath) / n).is_symlink():
                res.append(str((Path(dirpath) / n).relative_to(repo)))
    return sorted(res)


def _is_link(repo: Path, rel: str) -> bool:
    return (repo / rel).is_symlink()


def _text_files(repo: Path) -> list[str]:
    res = []
    for p in _tracked(repo):
        f = repo / p
        if f.is_symlink() or not f.is_file():
            continue
        if b"\0" not in f.read_bytes():
            res.append(p)
    return res


def _free(repo: Path, rel: str) -> bool:
    """rel に新しいファイルを置けるか（祖先がファイル・symlink でなく、自身が存在しない）。"""
    parts = rel.split("/")
    for i in range(1, len(parts)):
        a = repo.joinpath(*parts[:i])
        if a.is_symlink() or a.is_file():
            return False
    return not os.path.lexists(repo / rel)


def _put(repo: Path, rel: str, data: bytes) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _prune(repo: Path, rel: str) -> None:
    """消したファイルの空の親ディレクトリを片付ける（git は空ディレクトリを持たない）。"""
    for parent in Path(rel).parents:
        d = repo / parent
        if str(parent) in ("", ".") or not d.is_dir() or any(d.iterdir()):
            break
        d.rmdir()


def _tweak(repo: Path, rel: str, rng: random.Random) -> None:
    f = repo / rel
    if f.is_symlink() or not f.is_file():
        return
    data = f.read_bytes()
    if b"\0" in data:
        return
    lines = data.split(b"\n")
    i = rng.randrange(len(lines))
    lines[i] = lines[i] + " 変更".encode()
    f.write_bytes(b"\n".join(lines))


def op_add(repo, rng):
    name = rng.choice(NEW_NAMES)
    if not _free(repo, name):
        return None
    if name.endswith(".bin"):
        data = b"\x00\x01" + bytes(rng.randrange(256) for _ in range(rng.randint(4, 40)))
    elif name.startswith("empty"):
        data = b""
    else:
        data = _text(rng)
    _put(repo, name, data)
    return f"add {name}"


def op_edit(repo, rng):
    files = _text_files(repo)
    if not files:
        return None
    rel = rng.choice(files)
    f = repo / rel
    lines = f.read_bytes().split(b"\n")
    mode = rng.choice(["insert", "delete", "change", "change"])
    i = rng.randrange(
        min(len(lines), 4)
    )  # 先頭付近に偏らせて、両側が同じ行を触る（競合する）機会を増やす
    if mode == "insert":
        lines.insert(i, b"inserted %d" % rng.randint(0, 999))
    elif mode == "delete" and len(lines) > 2:
        del lines[i]
    else:
        lines[i] = b"changed %d" % rng.randint(0, 999)
    f.write_bytes(b"\n".join(lines))
    return f"edit {mode} {rel}:{i}"


def op_delete(repo, rng):
    files = _tracked(repo)
    if not files:
        return None
    rel = rng.choice(files)
    (repo / rel).unlink()
    _prune(repo, rel)
    return f"delete {rel}"


def op_rename(repo, rng):
    files = _tracked(repo)
    if not files:
        return None
    rel = rng.choice(files)
    new = rng.choice(NEW_NAMES)
    if new == rel or not _free(repo, new):
        return None
    tweak = rng.random() < 0.5
    (repo / new).parent.mkdir(parents=True, exist_ok=True)
    os.rename(repo / rel, repo / new)
    _prune(repo, rel)
    if tweak:
        _tweak(repo, new, rng)
    return f"rename {rel} -> {new}{' (+tweak)' if tweak else ''}"


def op_copy(repo, rng):
    files = [p for p in _tracked(repo) if not _is_link(repo, p)]
    if not files:
        return None
    rel = rng.choice(files)
    new = rng.choice(NEW_NAMES)
    if not _free(repo, new):
        return None
    (repo / new).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(repo / rel, repo / new)
    if rng.random() < 0.5:
        _tweak(repo, new, rng)
    return f"copy {rel} -> {new}"


def op_chmod(repo, rng):
    files = [p for p in _tracked(repo) if not _is_link(repo, p)]
    if not files:
        return None
    rel = rng.choice(files)
    f = repo / rel
    f.chmod(f.stat().st_mode ^ 0o111)
    return f"chmod {rel}"


def op_symlink(repo, rng):
    links = [p for p in _tracked(repo) if _is_link(repo, p)]
    files = _tracked(repo)
    if not files:
        return None
    target = rng.choice(files)
    if links and rng.random() < 0.6:
        rel = rng.choice(links)
        (repo / rel).unlink()
    else:
        rel = rng.choice(["link2", "lnk/l.txt"])
        if not _free(repo, rel):
            return None
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target if "/" not in rel else "../" + target, repo / rel)
    return f"symlink {rel} -> {target}"


def op_df(repo, rng):
    """ファイル ↔ ディレクトリの置き換え（D/F）。"""
    files = _tracked(repo)
    dirs = sorted({str(Path(p).parent) for p in files if "/" in p})
    if dirs and rng.random() < 0.5:
        rel = rng.choice(dirs)
        shutil.rmtree(repo / rel)
        _prune(repo, rel)
        _put(repo, rel, _text(rng))
        return f"df dir->file {rel}"
    if not files:
        return None
    rel = rng.choice([p for p in files if p != ".gitattributes"] or files)
    (repo / rel).unlink()
    _put(repo, rel + "/inner.txt", _text(rng))
    return f"df file->dir {rel}"


def op_case_rename(repo, rng):
    files = _tracked(repo)
    if not files:
        return None
    rel = rng.choice(files)
    p = Path(rel)
    new = str(p.with_name(p.name.swapcase()))
    if new == rel or not _free(repo, new):
        return None
    os.rename(repo / rel, repo / new)
    return f"case-rename {rel} -> {new}"


def op_dir_rename(repo, rng):
    tops = sorted({p.split("/")[0] for p in _tracked(repo) if "/" in p})
    if not tops:
        return None
    top = rng.choice(tops)
    new = top + "_moved"
    if os.path.lexists(repo / new):
        return None
    os.rename(repo / top, repo / new)
    return f"dir-rename {top} -> {new}"


OPS = {
    "add": op_add,
    "edit": op_edit,
    "edit2": op_edit,
    "delete": op_delete,
    "rename": op_rename,
    "copy": op_copy,
    "chmod": op_chmod,
    "symlink": op_symlink,
    "df": op_df,
    "case_rename": op_case_rename,
    "dir_rename": op_dir_rename,
}
OP_NAMES = sorted(OPS)


def _apply_ops(repo: Path, rng: random.Random, log: list[str], count: int) -> None:
    done = 0
    for _ in range(count * 8):
        if done >= count:
            break
        name = rng.choice(OP_NAMES)
        desc = OPS[name](repo, rng)
        if desc:
            log.append(desc)
            done += 1


def _commit_all(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", msg)


class Scenario:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = random.Random(seed)
        self.attr = rng.choice(sorted(ATTRIBUTES))
        self.autocrlf = rng.choice(AUTOCRLF)
        self.filemode = rng.choice(FILEMODE)
        self.renames = rng.choice(RENAMES)
        self.dir_renames = rng.choice(DIR_RENAMES)
        self.log: list[str] = [
            f"seed={seed} attr={self.attr} autocrlf={self.autocrlf} filemode={self.filemode} "
            f"merge.renames={self.renames} merge.directoryRenames={self.dir_renames}"
        ]
        self.rng = rng

    def config(self, repo: Path) -> None:
        for k, v in [
            ("user.name", "Example Dev"),
            ("user.email", "you@example.com"),
            ("gc.auto", "0"),
            ("maintenance.auto", "false"),
            ("core.autocrlf", self.autocrlf),
            ("core.filemode", self.filemode),
            ("merge.renames", self.renames),
            ("merge.directoryRenames", self.dir_renames),
        ]:
            if v is not None:
                _git(repo, "config", k, v)

    def build(self, repo: Path) -> None:
        """土台 + develop 側 1〜3 コミット + feature/oracle 側 1〜3 コミット。最後は develop をチェックアウトした状態。"""
        rng = self.rng
        repo.mkdir(parents=True)
        _git(repo, "init", "-q", "-b", "develop")
        self.config(repo)
        for rel, n in BASE_TEXT.items():
            _put(repo, rel, _text(rng, n))
        (repo / "run.sh").write_bytes(b"#!/bin/sh\necho hi\n")
        (repo / "run.sh").chmod(0o755)
        _put(repo, "data.bin", b"\x00\x01\x02binary\x00\xff")
        _put(repo, "empty.dat", b"")
        os.symlink("README.md", repo / "link")
        if ATTRIBUTES[self.attr]:
            _put(repo, ".gitattributes", ATTRIBUTES[self.attr].encode())
        _commit_all(repo, "base")
        # 両側が同じ変更をする（収束）ための共有の乱数の種。最初のコミットで先に両側へ同じ操作を当てる
        shared = rng.randint(0, 10**9) if rng.random() < 0.3 else None
        _git(repo, "checkout", "-q", "-b", "feature/oracle")
        self._side(repo, "feature", shared)
        _git(repo, "checkout", "-q", "develop")
        self._side(repo, "develop", shared)

    def _side(self, repo: Path, name: str, shared: int | None) -> None:
        for i in range(self.rng.randint(1, 3)):
            if i == 0 and shared is not None:
                _apply_ops(repo, random.Random(shared), self.log, 1)
                self.log[-1] += " [shared]"
            n0 = len(self.log)
            _apply_ops(repo, self.rng, self.log, self.rng.randint(1, 3))
            self.log[n0:] = [f"{name}#{i}: {s}" for s in self.log[n0:]]
            _commit_all(repo, f"{name} {i}")


# ---------------------------------------------------------------- 実行・観測


def _env(home: Path) -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Example Dev",
        "GIT_AUTHOR_EMAIL": "you@example.com",
        "GIT_COMMITTER_NAME": "Example Dev",
        "GIT_COMMITTER_EMAIL": "you@example.com",
        "LC_ALL": "C",
    }


def _run(cmd: list[str], cwd: Path, env: dict[str, str], stdin: str | None = None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _attributes_changed(repo: Path, old: str) -> bool:
    """統合の結果で .gitattributes が、統合前の develop と違うか。"""
    r = subprocess.run(
        ["git", "diff", "--quiet", old, "develop", "--", ".gitattributes"], cwd=repo, check=False
    )
    return r.returncode != 0


def _norm(path: str) -> str:
    """D/F 競合で退避されるパスの接尾辞（merge は `~HEAD`、merge-tree は `~<oid>`）の違いは、仕様上の差として無視する。"""
    return re.sub(r"~(?:HEAD|feature_oracle|[0-9a-f]{40})$", "~SIDE", path)


def _snapshot(repo: Path) -> dict:
    """副作用の検査用: develop 以外の ref・設定・hook の中身。"""
    refs = {}
    for line in _git(repo, "for-each-ref", "--format=%(refname) %(objectname)").splitlines():
        ref, oid = line.split()
        if ref != "refs/heads/develop":
            refs[ref] = oid
    gd = repo / ".git"
    hooks = (
        {p.name: p.read_bytes() for p in sorted((gd / "hooks").glob("*"))}
        if (gd / "hooks").is_dir()
        else {}
    )
    return {"refs": refs, "config": (gd / "config").read_bytes(), "hooks": hooks}


def _leftovers(repo: Path) -> list[str]:
    gd = repo / ".git"
    bad = [p.name for p in gd.glob("pr-viewer-merge.*")]
    bad += [n for n in ("index.lock", "MERGE_HEAD", "MERGE_MSG", "AUTO_MERGE") if (gd / n).exists()]
    if _git(repo, "stash", "list").strip():
        bad.append("stash")
    return bad


def _tree_state(repo: Path) -> dict[str, tuple]:
    """作業ツリー（.git 以外）の、パスごとの種類・内容・モード・symlink の先。"""
    state: dict[str, tuple] = {}
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if not (dirpath == str(repo) and d == ".git")]
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            rel = str(p.relative_to(repo))
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                state[rel] = ("link", os.readlink(p))
            elif stat.S_ISDIR(st.st_mode):
                state[rel] = ("dir",)
            else:
                state[rel] = ("file", p.read_bytes(), stat.S_IMODE(st.st_mode))
    return state


def _diff_state(a: dict, b: dict) -> str:
    out = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            out.append(f"  {k}: 統合器={a.get(k)!r} oracle={b.get(k)!r}")
    return "\n".join(out[:20])


def run_scenario(tmp: Path, seed: int) -> None:
    sc = Scenario(seed)
    a, b = tmp / "a", tmp / "b"
    sc.build(a)
    shutil.copytree(a, b, symlinks=True)
    home = tmp / "home"
    home.mkdir()
    env = _env(home)
    try:
        _compare(sc, a, b, env)
    except AssertionError as e:
        raise AssertionError(
            f"[seed={seed}] {e}\n--- シナリオ ---\n" + "\n".join(sc.log) + f"\n作業場所: {tmp}"
        ) from None


def _compare(sc: Scenario, a: Path, b: Path, env: dict[str, str]) -> None:
    old = _git(a, "rev-parse", "develop").strip()
    feature = _git(a, "rev-parse", "feature/oracle").strip()
    assert _git(b, "rev-parse", "develop").strip() == old
    before = _snapshot(a)

    # (a) 統合器
    proc = _run(
        [
            _node(),
            str(CLI),
            "merge",
            str(a),
            "--source",
            "feature/oracle",
            "--message-file",
            "-",
            "--cleanup",
            "none",
        ],
        a.parent,
        env,
        MESSAGE,
    )
    out = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else None
    assert out is not None, f"統合器の出力が空: rc={proc.returncode} {proc.stderr}"

    # (b) 素の git merge
    mp = _run(["git", "merge", "--no-ff", "-q", "-m", MESSAGE, "feature/oracle"], b, env)
    unmerged = sorted(
        {_norm(ln.split("\t", 1)[1]) for ln in _git(b, "ls-files", "-u", "-z").split("\0") if ln}
    )
    # directory rename split など、未マージのパスが無いまま rc=1 で止まる競合もある（その場合は両者とも一覧が空）
    oracle_conflict = mp.returncode == 1
    if mp.returncode not in (0, 1) and "BUG: merge-ort.c" in (mp.stdout + mp.stderr):
        # oracle（素の git merge）自身が git の既知の不具合で abort した。比べる相手が無いので、理由を明示して読み飛ばす
        pytest.skip(
            f"oracle の git が merge-ort の BUG で abort した（git 側の不具合）: {(mp.stdout + mp.stderr).strip()[:160]}"
        )
    assert mp.returncode in (0, 1), (
        f"oracle の git merge が想定外: rc={mp.returncode} {mp.stdout}{mp.stderr}"
    )

    # 副作用の無さ（成功・競合どちらでも）
    assert _snapshot(a) == before, "統合器が develop 以外の ref・config・hooks を変えた"
    assert not _leftovers(a), f"残り物: {_leftovers(a)}"
    fsck = _run(["git", "fsck", "--no-dangling"], a, env)
    assert fsck.returncode == 0, f"fsck: {fsck.stdout}{fsck.stderr}"

    if oracle_conflict:
        assert not out["ok"] and out.get("code") == "conflict", (
            f"oracle は競合 {unmerged}、統合器は {out}"
        )
        assert sorted({_norm(c) for c in out["conflicts"]}) == unmerged, (
            f"競合パスの不一致: 統合器={out['conflicts']} oracle={unmerged}"
        )
        assert _git(a, "rev-parse", "develop").strip() == old, "競合なのに develop が動いた"
        assert _git(a, "status", "--porcelain=v1", "--ignored") == "", (
            "競合の拒否の後で作業ツリーが clean でない"
        )
        return

    assert out["ok"], f"oracle は競合なし、統合器は拒否: {out}"
    assert proc.returncode == 0
    # 結果の同一性
    ta, tb = (
        _git(a, "rev-parse", "develop^{tree}").strip(),
        _git(b, "rev-parse", "develop^{tree}").strip(),
    )
    assert ta == tb, f"tree の OID が違う: 統合器={ta} oracle={tb}"
    assert _git(a, "rev-list", "--parents", "-n", "1", "develop").split()[1:] == [old, feature], (
        "親の順・数が違う"
    )
    assert _git(b, "rev-list", "--parents", "-n", "1", "develop").split()[1:] == [old, feature], (
        "oracle の親が想定外"
    )
    msg_a, msg_b = (
        _git(a, "log", "-1", "--format=%B", "develop"),
        _git(b, "log", "-1", "--format=%B", "develop"),
    )
    assert msg_a == msg_b, f"メッセージが違う: {msg_a!r} / {msg_b!r}"
    assert _git(a, "ls-files", "-s") == _git(b, "ls-files", "-s"), "index の内容が違う"
    # 作業ツリー。通常は両者とも clean。ただし統合で .gitattributes が消えると、改行変換の規則が変わり、
    # git merge 自身も modified と見る（統合器の差ではない）。そのため oracle と同じであることを求める。
    st_a = _settled_status(a)
    st_b = _settled_status(b)
    assert st_a == st_b, f"統合後の status が oracle と違う: 統合器={st_a!r} oracle={st_b!r}"
    if not _attributes_changed(a, old):
        assert st_a == "", f"統合後の作業ツリーが clean でない: {st_a!r}"
    sa, sb = _tree_state(a), _tree_state(b)
    assert sa == sb, "作業ツリーの内容が違う:\n" + _diff_state(sa, sb)


# ---------------------------------------------------------------- 試験


def _settled_status(repo: Path) -> str:
    """racy git（index と同じ秒に書かれたファイルの stat が一時的に「変更」と見える）で status が揺れるのを避ける。

    空でないときは、時計が繰り上がるまで待って index を再評価し、もう 1 回見る。内容の違いはこの後の
    作業ツリーのバイト比較（_tree_state）が別に見るので、ここで維持するのは「stat の揺れで落とさない」ことだけ。
    """
    st = _git(repo, "status", "--porcelain=v1", "--ignored")
    if st == "":
        return st
    time.sleep(1.1)
    _git(repo, "update-index", "-q", "--really-refresh")
    return _git(repo, "status", "--porcelain=v1", "--ignored")


# ---------------------------------------------------------------- 試験


@pytest.mark.parametrize(
    "seed", range(FIRST_SEED, FIRST_SEED + SCENARIOS), ids=lambda s: f"seed{s}"
)
def test_merge_matches_porcelain_git_merge(tmp_path, seed):
    run_scenario(tmp_path, seed)


def test_scenarios_are_reproducible(tmp_path):
    """同じ seed から同じ履歴（commit の tree）が作られる。seed が失敗の再現に使えることの確認。"""
    trees = []
    for i in range(2):
        sc = Scenario(7)
        sc.build(tmp_path / f"r{i}")
        trees.append(
            (
                _git(tmp_path / f"r{i}", "rev-parse", "develop^{tree}"),
                _git(tmp_path / f"r{i}", "rev-parse", "feature/oracle^{tree}"),
                sc.log,
            )
        )
    assert trees[0] == trees[1]
