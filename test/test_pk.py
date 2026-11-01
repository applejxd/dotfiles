"""home/dot_local/bin/executable_pk: 補助スクリプト (.tmp/keep/<話題>/) の短い入口。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PK = ROOT / "home" / "dot_local" / "bin" / "executable_pk"


def make_topic(root: Path, name: str, scripts: dict[str, str], mtime: int | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    for fname, body in scripts.items():
        (d / fname).write_text(body, encoding="utf-8")
    if mtime is not None:
        os.utime(d, (mtime, mtime))
    return d


def pk(root: Path, *args: str, cwd: Path | None = None, env_extra: dict[str, str] | None = None):
    env = {k: v for k, v in os.environ.items() if k != "PK_ROOT"}
    env["HOME"] = str(root.parent / "home")  # 実際のホームの置き場を読まない
    if root is not None:
        env["PK_ROOT"] = str(root)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(PK), *args],
        cwd=cwd or root.parent,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


@pytest.fixture
def keep(tmp_path: Path) -> Path:
    root = tmp_path / "keep"
    root.mkdir()
    return root


ECHO = '# {desc}\nset -eu\necho "args=$*"\nexit 3\n'


def test_runs_the_entry_with_arguments_and_passes_the_exit_code(keep):
    make_topic(keep, "pending-e2e", {"e2e.sh": ECHO.format(desc="試験の道具")})
    r = pk(keep, "pending-e2e", "status", "x y")
    assert r.returncode == 3
    assert r.stdout.strip() == "args=status x y"
    assert "→ sh" in r.stderr and "e2e.sh" in r.stderr  # 実行前に、実際のパスを示す


def test_unique_partial_match_runs_and_ambiguous_does_not(keep):
    marker = keep.parent / "ran"
    body = f"touch {marker}\n"
    make_topic(keep, "pending-e2e", {"a.sh": body})
    make_topic(keep, "pending-cleanup", {"b.sh": body})
    ok = pk(keep, "e2e")
    assert ok.returncode == 0 and marker.exists()
    marker.unlink()
    amb = pk(keep, "pending")
    assert amb.returncode == 2
    assert "pending-e2e" in amb.stderr and "pending-cleanup" in amb.stderr
    assert not marker.exists(), "曖昧なのに実行された"


def test_run_sh_is_preferred_over_other_scripts(keep):
    make_topic(keep, "t", {"run.sh": "echo run\n", "other.sh": "echo other\n"})
    assert pk(keep, "t").stdout.strip() == "run"


def test_several_scripts_without_run_sh_is_refused(keep):
    marker = keep.parent / "ran"
    make_topic(keep, "t", {"a.sh": f"touch {marker}\n", "b.sh": f"touch {marker}\n"})
    r = pk(keep, "t")
    assert r.returncode == 2 and "run.sh" in r.stderr
    assert not marker.exists()


def test_dry_run_shows_the_head_comment_and_does_not_execute(keep):
    marker = keep.parent / "ran"
    make_topic(keep, "t", {"x.sh": f"set -eu\n# 1 行目の説明\n# 2 行目\ntouch {marker}\n"})
    r = pk(keep, "-n", "t")
    assert r.returncode == 0
    assert "x.sh" in r.stdout and "# 1 行目の説明" in r.stdout and "# 2 行目" in r.stdout
    assert not marker.exists(), "-n なのに実行された"


@pytest.mark.parametrize("bad", ["..", "a/b", "a\\b", "."])
def test_path_like_topic_names_are_refused(keep, bad):
    marker = keep.parent / "ran"
    (keep.parent / "x.sh").write_text(f"touch {marker}\n", encoding="utf-8")
    r = pk(keep, bad)
    assert r.returncode == 2
    assert not marker.exists()


def test_an_entry_symlinked_outside_the_root_is_refused(keep):
    marker = keep.parent / "ran"
    outside = keep.parent / "outside.sh"
    outside.write_text(f"touch {marker}\n", encoding="utf-8")
    d = make_topic(keep, "t", {})
    (d / "run.sh").symlink_to(outside)
    r = pk(keep, "t")
    assert r.returncode == 2 and "外" in r.stderr
    assert not marker.exists(), "置き場の外のスクリプトが実行された"


def test_no_arguments_shows_usage_and_the_topics_with_descriptions_newest_first(keep):
    make_topic(keep, "old-topic", {"a.sh": "# 古い話題の説明\n"}, mtime=1_000_000_000)
    make_topic(
        keep, "new-topic", {"b.sh": "#!/bin/sh\nset -eu\n# 新しい話題の説明\n"}, mtime=1_900_000_000
    )
    make_topic(keep, "commit-draft", {})  # スクリプトの無い話題は出さない
    r = pk(keep)
    assert r.returncode == 0
    out = r.stdout.splitlines()
    assert out[0].startswith("使い方: pk")
    names = [ln.split()[0] for ln in out[1:]]
    assert names == ["new-topic", "old-topic"], out
    assert "新しい話題の説明" in r.stdout and "古い話題の説明" in r.stdout


def test_long_descriptions_are_clipped_for_a_narrow_screen(keep):
    make_topic(keep, "t", {"a.sh": "# " + "あ" * 80 + "\n"})
    line = pk(keep).stdout.splitlines()[1]
    assert line.endswith("...")
    width = sum(2 if ord(c) > 0x2E80 else 1 for c in line)
    assert width <= 60, (width, line)


def test_complete_emits_name_and_escaped_description(keep):
    make_topic(keep, "t", {"a.sh": "# 例: a:b の説明\n"})
    r = pk(keep, "--complete")
    assert r.returncode == 0
    assert r.stdout.strip() == "t:例\\: a\\:b の説明"


def test_root_falls_back_to_the_nearest_dot_tmp_keep_upward(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".tmp" / "keep").mkdir(parents=True)
    make_topic(repo / ".tmp" / "keep", "found", {"a.sh": "echo here\n"})
    sub = repo / "sub" / "dir"
    sub.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if k != "PK_ROOT"}
    env["HOME"] = str(tmp_path / "home")
    r = subprocess.run(
        [sys.executable, str(PK), "found"],
        cwd=sub,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert r.returncode == 0 and r.stdout.strip() == "here", r.stderr


def test_unknown_topic_lists_the_candidates(keep):
    make_topic(keep, "known", {"a.sh": "# 説明\n"})
    r = pk(keep, "nope")
    assert r.returncode == 2 and "known" in r.stderr
