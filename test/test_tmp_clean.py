"""`tmp_clean.py` (作業ツリーの `.tmp/` の掃除) の試験。

自動で消してよいのは、自分で作ったと確かめられるものだけ。未知の名前・取り込み待ち (`keep/`)・
運用の置き場・持ち主の死亡を確証できない `s/` は、消さない (CHG-0042 のレビュー R1-1・R1-2・R1-5)。
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "home" / "dot_config" / "pi" / "harness" / "tmp_clean.py"


def _load():
    spec = importlib.util.spec_from_file_location("tmp_clean", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tmp_clean"] = mod
    spec.loader.exec_module(mod)
    return mod


tc = _load()
DAY = 86400
needs_proc = pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="/proc が無い")


def _age(path: Path, days: float) -> None:
    t = time.time() - days * DAY
    for p in [path, *path.rglob("*")] if path.is_dir() else [path]:
        os.utime(p, (t, t), follow_symlinks=False)


def _mk(root: Path, rel: str, text: str = "x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def tmp(tmp_path: Path) -> Path:
    root = tmp_path / ".tmp"
    root.mkdir()
    return root


def _run(root: Path, *flags: str) -> int:
    return tc.main(["--dir", str(root), *flags])


# ─── 既定は、何も消さない ───


def test_dry_run_deletes_nothing(tmp: Path) -> None:
    _mk(tmp, "tools-ext-abc/big.bin")
    _age(tmp / "tools-ext-abc", 3)
    assert _run(tmp) == 0
    assert (tmp / "tools-ext-abc").exists()


# ─── 再生成できる名前 ───


def test_disposable_names_are_removed_only_when_older_than_a_day(tmp: Path) -> None:
    _mk(tmp, "tools-ext-old/x")
    _mk(tmp, "agents-config-new/x")
    _mk(tmp, "pytest-of-someone/x")
    _age(tmp / "tools-ext-old", 2)
    _age(tmp / "pytest-of-someone", 2)
    assert _run(tmp, "--apply") == 0
    assert not (tmp / "tools-ext-old").exists()
    assert not (tmp / "pytest-of-someone").exists()
    assert (tmp / "agents-config-new").exists()  # 新しいものは残す


# ─── 未知の名前・保護 ───


def test_unknown_names_are_listed_but_not_removed_by_default(
    tmp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _mk(tmp, "my-experiment/data.txt")
    _age(tmp / "my-experiment", 30)
    assert _run(tmp, "--apply") == 0
    assert (tmp / "my-experiment").exists()
    out = capsys.readouterr().out
    assert "未知の名前" in out and "my-experiment" in out


def test_all_removes_old_unknown_names_but_keeps_recent_ones(tmp: Path) -> None:
    _mk(tmp, "old-experiment/x")
    _mk(tmp, "recent-experiment/x")
    _age(tmp / "old-experiment", 30)
    assert _run(tmp, "--all", "--apply") == 0
    assert not (tmp / "old-experiment").exists()
    assert (tmp / "recent-experiment").exists()


@pytest.mark.parametrize(
    "name",
    [
        "keep",
        "research",
        "review-loop",
        "away-shift",
        "subagents",
        "worktrees",
        "checkpoint-abc.md",
    ],
)
def test_protected_places_are_never_removed(tmp: Path, name: str) -> None:
    _mk(tmp, f"{name}/x" if not name.endswith(".md") else name)
    _age(tmp / name, 400)
    assert _run(tmp, "--all", "--apply") == 0
    assert (tmp / name).exists()


# ─── セッションの置き場 s/ ───


def _owner(root: Path, name: str, owner: dict | str | None) -> Path:
    d = root / "s" / name
    d.mkdir(parents=True)
    (d / "scratch.txt").write_text("x", encoding="utf-8")
    if isinstance(owner, dict):
        (d / ".owner").write_text(json.dumps(owner), encoding="utf-8")
    elif isinstance(owner, str):
        (d / ".owner").write_text(owner, encoding="utf-8")
    return d


@needs_proc
def test_session_dir_of_a_dead_owner_is_removed(tmp: Path) -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    owner = tc.make_owner(child.pid)
    child.kill()
    child.wait()
    d = _owner(tmp, "deadbeef", owner)
    assert _run(tmp, "--apply") == 0
    assert not d.exists()


@needs_proc
def test_session_dir_of_a_live_owner_is_kept_even_when_old(tmp: Path) -> None:
    d = _owner(tmp, "alive000", tc.make_owner())
    _age(d, 60)  # 年齢だけでは消さない
    assert _run(tmp, "--apply", "--all") == 0
    assert d.exists()


@needs_proc
def test_pid_reuse_is_detected_by_the_start_time(tmp: Path) -> None:
    owner = tc.make_owner()
    owner["start"] = str(
        int(owner["start"]) + 12345
    )  # 同じ pid だが、起動時刻が違う = 別のプロセス
    d = _owner(tmp, "reused00", owner)
    assert _run(tmp, "--apply") == 0
    assert not d.exists()


@needs_proc
@pytest.mark.parametrize(
    "mutate",
    [
        lambda o: o.update(pidns="pid:[1]"),  # 別の PID namespace
        lambda o: o.update(host=socket.gethostname() + "-other"),  # 別のホスト
        lambda o: o.update(start=""),  # 書きかけ
    ],
    ids=["other-pidns", "other-host", "incomplete"],
)
def test_session_dir_is_kept_when_death_cannot_be_proven(tmp: Path, mutate) -> None:
    owner = tc.make_owner(os.getpid())
    owner["pid"] = 2**22 + 7  # 存在しない pid でも、確証できない条件では消さない
    mutate(owner)
    d = _owner(tmp, "unknown0", owner)
    assert _run(tmp, "--apply") == 0
    assert d.exists()


@pytest.mark.parametrize(
    "text",
    [None, "", "not json", '{"pid": "x"}', "[]"],
    ids=["missing", "empty", "garbage", "bad-pid", "list"],
)
def test_session_dir_without_a_valid_owner_is_kept(tmp: Path, text) -> None:
    d = _owner(tmp, "noowner0", text)
    _age(d, 60)
    assert _run(tmp, "--apply", "--all") == 0
    assert d.exists()


# ─── 境界 ───


def test_symlinked_root_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / ".tmp"
    link.symlink_to(real)
    assert _run(link, "--apply") == 2


def test_symlink_entries_are_unlinked_without_touching_the_target(
    tmp_path: Path, tmp: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = _mk(outside, "sentinel.txt")
    link = tmp / "tools-ext-link"
    link.symlink_to(outside)
    os.utime(link, (time.time() - 3 * DAY,) * 2, follow_symlinks=False)
    assert _run(tmp, "--apply") == 0
    assert not link.exists() and not link.is_symlink()
    assert sentinel.exists()  # リンク先は消えない


def test_symlinked_sessions_dir_is_not_followed(tmp_path: Path, tmp: Path) -> None:
    outside = tmp_path / "outside"
    victim = outside / "victim"
    victim.mkdir(parents=True)
    (victim / ".owner").write_text(json.dumps(tc.make_owner(2**22 + 9)), encoding="utf-8")
    (tmp / "s").symlink_to(outside)
    assert _run(tmp, "--apply") == 0
    assert victim.exists()


def test_a_second_sweep_does_nothing_while_one_is_running(
    tmp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import fcntl

    _mk(tmp, "tools-ext-old/x")
    _age(tmp / "tools-ext-old", 3)
    with open(tmp / ".sweep.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert _run(tmp, "--apply") == 0
    assert (tmp / "tools-ext-old").exists()
    assert "実行中" in capsys.readouterr().out


def test_read_only_files_are_removed(tmp: Path) -> None:
    f = _mk(tmp, "tools-ext-ro/sub/file.txt")
    f.chmod(0o400)
    f.parent.chmod(0o500)
    _age(tmp / "tools-ext-ro", 3)
    f.parent.chmod(0o500)
    assert _run(tmp, "--apply") == 0
    assert not (tmp / "tools-ext-ro").exists()
