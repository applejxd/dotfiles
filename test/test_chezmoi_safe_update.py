"""scripts/chezmoi_safe_update.py（隔離プレフライト＋自動ファイル切り戻し＋副作用警告）の状態遷移試験。"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "chezmoi_safe_update.py"

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location("chezmoi_safe_update", SCRIPT)
assert _spec is not None and _spec.loader is not None
safe_update = importlib.util.module_from_spec(_spec)
sys.modules["chezmoi_safe_update"] = safe_update
_spec.loader.exec_module(safe_update)

needs_chezmoi = pytest.mark.skipif(not shutil.which("chezmoi"), reason="chezmoi is not installed")


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout


def _create_mini_dotfiles_repo(repo: Path, *, marker: str = "v1") -> str:
    """isolated_smoke と chezmoi apply の両方を高速に通せる最小 chezmoi リポジトリを作る。"""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".chezmoiroot").write_text("home\n", encoding="utf-8")

    home = repo / "home"
    home.mkdir(exist_ok=True)
    (home / ".chezmoi.toml.tmpl").write_text('[data]\n    marker = "ok"\n', encoding="utf-8")

    for rel in safe_update.isolated_smoke.PI_JSON_TARGETS:
        parts = rel.split("/")
        # chezmoi source 形式へ変換 (.pi -> dot_pi)
        src_parts = [f"dot_{p[1:]}" if p.startswith(".") else p for p in parts]
        fp = home.joinpath(*src_parts)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps({"version": marker}) + "\n", encoding="utf-8")

    git_cfg = home / "dot_config" / "git" / "config"
    git_cfg.parent.mkdir(parents=True, exist_ok=True)
    git_cfg.write_text("[core]\n\tautocrlf = false\n", encoding="utf-8")

    # dot_vimrc.tmpl で .chezmoi.workingTree を埋め込み、一時 worktree パスが実機 dest に焼き込まれないこと（P0 回帰）も検証する
    (home / "dot_vimrc.tmpl").write_text(
        f'" marker={marker}\n" wt={{{{ .chezmoi.workingTree }}}}\nset encoding=utf-8\nsilent! colorscheme iceberg\n'
        "if has('clipboard') && empty($SSH_CONNECTION)\n  set clipboard=unnamedplus\nendif\n",
        encoding="utf-8",
    )

    if os.name == "nt":
        prof = home / "dot_config" / "powershell" / "profile.ps1"
        prof.parent.mkdir(parents=True, exist_ok=True)
        prof.write_text(f"$global:__marker = '{marker}'\n", encoding="utf-8-sig")
    else:
        shellenv = home / "dot_config" / "shell" / "shellenv.sh"
        shellenv.parent.mkdir(parents=True, exist_ok=True)
        shellenv.write_text(f"#!/bin/sh\nexport __MARKER='{marker}'\n", encoding="utf-8")
        (home / "dot_zshenv").write_text("export __ZSH_OK=1\n", encoding="utf-8")
        pk = home / "dot_local" / "bin" / "executable_pk"
        pk.parent.mkdir(parents=True, exist_ok=True)
        pk.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n", encoding="utf-8")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"feat: init {marker}")
    return _git(repo, "rev-parse", "HEAD").strip()


@needs_chezmoi
def test_update_happy_path_preflight_failure_and_manual_rollback(tmp_path, capsys):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-q", "-b", "main", str(origin))

    seed = tmp_path / "seed"
    sha_v1 = _create_mini_dotfiles_repo(seed, marker="v1")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "-u", "origin", "main")

    # クライアント端末のクローンと隔離 $HOME（-b main を明示して git 既定ブランチ差に依存しない）
    client = tmp_path / "client-repo"
    _git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(client))
    dest = tmp_path / "dest"
    dest.mkdir()
    state_dir = tmp_path / "state"
    cz_cfg = tmp_path / "cz" / "chezmoi.toml"
    cz_state = tmp_path / "cz" / "state.boltdb"

    common = [
        "--source",
        str(client),
        "--dest",
        str(dest),
        "--state-dir",
        str(state_dir),
        "--chezmoi-config",
        str(cz_cfg),
        "--chezmoi-state",
        str(cz_state),
        "--min-entries",
        "5",
    ]

    # 1. 初回 update（v1 適用）→ 成功し last_good_sha == sha_v1 になる
    rc1 = safe_update.main(["update", *common, "--exclude-scripts"])
    captured1 = capsys.readouterr()
    assert rc1 == 0, f"stdout={captured1.out}\nstderr={captured1.err}"
    out1 = json.loads(captured1.out)
    assert out1["ok"] is True
    assert out1["last_good_sha"] == sha_v1
    assert '"version": "v1"' in (dest / ".pi" / "agent" / "settings.json").read_text(encoding="utf-8")
    vimrc_text = (dest / ".vimrc").read_text(encoding="utf-8")
    assert "safe-update-wt-" not in vimrc_text
    assert client.as_posix() in vimrc_text.replace("\\", "/")

    # 2. v2（正常な更新）を origin に push → client が ff-only で追随し適用される
    (seed / "home" / "dot_pi" / "agent" / "settings.json").write_text('{"version": "v2"}\n', encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "feat: v2")
    sha_v2 = _git(seed, "rev-parse", "HEAD").strip()
    _git(seed, "push", "-q", "origin", "main")

    rc2 = safe_update.main(["update", *common, "--exclude-scripts"])
    captured2 = capsys.readouterr()
    assert rc2 == 0, f"stdout={captured2.out}\nstderr={captured2.err}"
    out2 = json.loads(captured2.out)
    assert out2["ok"] is True
    assert out2["branch_ff_updated"] is True
    assert out2["last_good_sha"] == sha_v2
    assert '"version": "v2"' in (dest / ".pi" / "agent" / "settings.json").read_text(encoding="utf-8")

    # 3. v3（壊れた JSON を含むコミット）を origin に push → プレフライトで阻止され実機 v2 は無傷・HEAD も v2 のまま
    (seed / "home" / "dot_pi" / "agent" / "settings.json").write_text("{broken json", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "feat: broken v3")
    _git(seed, "push", "-q", "origin", "main")

    assert safe_update.main(["update", *common, "--exclude-scripts"]) == 1
    out3 = json.loads(capsys.readouterr().out)
    assert out3["ok"] is False
    assert out3["stage"] == "preflight"
    assert out3["dest_untouched"] is True
    assert '"version": "v2"' in (dest / ".pi" / "agent" / "settings.json").read_text(encoding="utf-8")
    assert _git(client, "rev-parse", "HEAD").strip() == sha_v2

    # 4. 手動 rollback で sha_v1 へ切り戻せる
    rc4 = safe_update.main(["rollback", *common, "--to", sha_v1])
    captured4 = capsys.readouterr()
    assert rc4 == 0, f"stdout={captured4.out}\nstderr={captured4.err}"
    out4 = json.loads(captured4.out)
    assert out4["ok"] is True
    assert out4["rolled_back_to"] == sha_v1
    assert '"version": "v1"' in (dest / ".pi" / "agent" / "settings.json").read_text(encoding="utf-8")
    vimrc_rb = (dest / ".vimrc").read_text(encoding="utf-8")
    assert "safe-update-wt-" not in vimrc_rb
    assert client.as_posix() in vimrc_rb.replace("\\", "/")
    assert _git(client, "branch", "--show-current").strip() == "main"
    assert _git(client, "rev-parse", "HEAD").strip() == sha_v2


@needs_chezmoi
def test_post_smoke_failure_triggers_auto_file_rollback_and_warns_script_side_effects(
    tmp_path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    sha_v1 = _create_mini_dotfiles_repo(repo, marker="v1")

    # v2 コミットを作る（run_once スクリプト付きの更新を模擬）
    (repo / "home" / "dot_pi" / "agent" / "settings.json").write_text('{"version": "v2"}\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: v2")
    sha_v2 = _git(repo, "rev-parse", "HEAD").strip()
    # client 側は一旦 v1 に戻しておく
    _git(repo, "checkout", "-q", "-B", "main", sha_v1)

    dest = tmp_path / "dest"
    dest.mkdir()
    state_dir = tmp_path / "state"
    cz_cfg = tmp_path / "cz" / "chezmoi.toml"
    cz_state = tmp_path / "cz" / "state.boltdb"

    common = [
        "--source",
        str(repo),
        "--dest",
        str(dest),
        "--state-dir",
        str(state_dir),
        "--chezmoi-config",
        str(cz_cfg),
        "--chezmoi-state",
        str(cz_state),
        "--min-entries",
        "5",
    ]

    # まず v1 を正常適用して last_good_sha を記録する
    assert safe_update.main(["update", *common, "--target", sha_v1, "--no-fetch", "--exclude-scripts"]) == 0
    capsys.readouterr()
    assert '"version": "v1"' in (dest / ".pi" / "agent" / "settings.json").read_text(encoding="utf-8")

    # 本番適用時には run_once スクリプトが予定されており、かつ本番後スモークだけ環境要因で失敗したケースを注入する
    orig_check_dest = safe_update.isolated_smoke.check_destination
    call_count = {"n": 0}

    def injected_check_dest(target_dest: Path, *, min_entries: int = 1):
        # target_dest が本番 dest の 1 回目（v2 適用直後）だけ失敗させ、ロールバック後の確認は本物を通す
        if target_dest.resolve() == dest.resolve():
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [safe_update.isolated_smoke.StepResult("injected-post-check", "failed", "simulated post-apply breakage")]
        return orig_check_dest(target_dest, min_entries=min_entries)

    monkeypatch.setattr(safe_update.isolated_smoke, "check_destination", injected_check_dest)
    monkeypatch.setattr(
        safe_update,
        "_detect_pending_scripts",
        lambda *args, **kwargs: ([".chezmoiscripts/100_linux/run_onchange_after_125_mise.sh"], True),
    )

    rc = safe_update.main(["update", *common, "--target", sha_v2, "--no-fetch"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["rolled_back"] is True
    assert out["rolled_back_to"] == sha_v1
    assert out["pending_scripts"] == [".chezmoiscripts/100_linux/run_onchange_after_125_mise.sh"]
    assert out["side_effect_warning"] is not None
    # 実機 dest のファイルは自動的に v1 へ戻っていること
    assert '"version": "v1"' in (dest / ".pi" / "agent" / "settings.json").read_text(encoding="utf-8")
    # source 本体の HEAD も v1 のまま動いていないこと
    assert _git(repo, "rev-parse", "HEAD").strip() == sha_v1


def test_dirty_source_and_concurrent_lock_are_rejected(tmp_path, capsys):
    repo = tmp_path / "repo"
    _create_mini_dotfiles_repo(repo, marker="v1")
    (repo / "home" / "dot_vimrc.tmpl").write_text("dirty\n", encoding="utf-8")

    state_dir = tmp_path / "state"
    dest = tmp_path / "dest"
    dest.mkdir()
    rc = safe_update.main(["update", "--source", str(repo), "--dest", str(dest), "--state-dir", str(state_dir), "--no-fetch"])
    assert rc == 1
    assert "未コミット" in capsys.readouterr().err

    # 排他ロック保持中は 2 本目が即座に拒否される
    with (
        safe_update._exclusive_lock(state_dir),
        pytest.raises(safe_update.SafeUpdateError, match="実行中"),
        safe_update._exclusive_lock(state_dir),
    ):
        pass


@needs_chezmoi
def test_apply_timeout_triggers_rollback_and_first_run_unverified_fallback_stops_safely(
    tmp_path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    sha_v1 = _create_mini_dotfiles_repo(repo, marker="v1")
    (repo / "home" / "dot_pi" / "agent" / "settings.json").write_text('{"version": "v2"}\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: v2")
    sha_v2 = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "-B", "main", sha_v1)

    dest = tmp_path / "dest"
    dest.mkdir()
    state_dir = tmp_path / "state"
    cz_cfg = tmp_path / "cz" / "chezmoi.toml"
    cz_state = tmp_path / "cz" / "state.boltdb"
    common = [
        "--source",
        str(repo),
        "--dest",
        str(dest),
        "--state-dir",
        str(state_dir),
        "--chezmoi-config",
        str(cz_cfg),
        "--chezmoi-state",
        str(cz_state),
        "--min-entries",
        "5",
    ]

    # 1. 初回実行（last_good_sha 未記録）で本番 apply がタイムアウト相当で失敗しても、
    #    事前検証済みの from_sha (sha_v1) へ自動ロールバックされてクラッシュしない（P1 回帰）
    real_apply = safe_update._apply_from_real_repo
    calls = {"n": 0}

    def timeout_first_apply(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, "chezmoi apply failed (exit 124): timed out after 1s"
        return real_apply(**kwargs)

    monkeypatch.setattr(safe_update, "_apply_from_real_repo", timeout_first_apply)
    rc = safe_update.main(["update", *common, "--target", sha_v2, "--no-fetch", "--exclude-scripts"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["rolled_back"] is True
    assert out["rolled_back_to"] == sha_v1
    assert "timed out" in out["reason"]
    assert '"version": "v1"' in (dest / ".pi" / "agent" / "settings.json").read_text(encoding="utf-8")
    assert "safe-update-wt-" not in (dest / ".vimrc").read_text(encoding="utf-8")
    assert _git(repo, "rev-parse", "HEAD").strip() == sha_v1

    # 2. 初回実行かつ元の HEAD 自体が壊れていた場合、壊れた HEAD を再適用せず rollback_failed を記録する
    repo_bad = tmp_path / "repo-bad"
    _create_mini_dotfiles_repo(repo_bad, marker="bad0")
    (repo_bad / "home" / "dot_pi" / "agent" / "settings.json").write_text("{broken-head", encoding="utf-8")
    _git(repo_bad, "add", "-A")
    _git(repo_bad, "commit", "-q", "-m", "chore: broken initial head")
    sha_bad = _git(repo_bad, "rev-parse", "HEAD").strip()

    (repo_bad / "home" / "dot_pi" / "agent" / "settings.json").write_text('{"version": "good"}\n', encoding="utf-8")
    _git(repo_bad, "add", "-A")
    _git(repo_bad, "commit", "-q", "-m", "fix: good target")
    sha_good = _git(repo_bad, "rev-parse", "HEAD").strip()
    _git(repo_bad, "checkout", "-q", "-B", "main", sha_bad)

    dest2 = tmp_path / "dest2"
    dest2.mkdir()
    state2 = tmp_path / "state2"
    calls["n"] = 0
    rc2 = safe_update.main(
        [
            "update",
            "--source",
            str(repo_bad),
            "--dest",
            str(dest2),
            "--state-dir",
            str(state2),
            "--chezmoi-config",
            str(tmp_path / "cz2" / "chezmoi.toml"),
            "--chezmoi-state",
            str(tmp_path / "cz2" / "state.boltdb"),
            "--min-entries",
            "5",
            "--target",
            sha_good,
            "--no-fetch",
            "--exclude-scripts",
        ]
    )
    assert rc2 == 1
    out2 = json.loads(capsys.readouterr().out)
    assert out2["rolled_back"] is False
    assert "隔離スモーク不合格" in out2["rollback_detail"]
    assert _git(repo_bad, "rev-parse", "HEAD").strip() == sha_bad
