"""scripts/isolated_smoke.py（3 OS 共通の隔離 chezmoi apply ＋ 起動スモーク）の試験。"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "isolated_smoke.py"

_spec = importlib.util.spec_from_file_location("isolated_smoke", SCRIPT)
assert _spec is not None and _spec.loader is not None
smoke = importlib.util.module_from_spec(_spec)
sys.modules["isolated_smoke"] = smoke
_spec.loader.exec_module(smoke)

needs_chezmoi = pytest.mark.skipif(not shutil.which("chezmoi"), reason="chezmoi is not installed")


def _write_minimal_valid_dest(dest: Path) -> None:
    """check_destination が全項目を通せる最小の展開先を作る。"""
    dest.mkdir(parents=True, exist_ok=True)
    for rel in smoke.PI_JSON_TARGETS:
        fp = dest / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text('{"ok": true}\n', encoding="utf-8")

    git_cfg = dest / ".config" / "git" / "config"
    git_cfg.parent.mkdir(parents=True, exist_ok=True)
    git_cfg.write_text("[core]\n\tautocrlf = false\n", encoding="utf-8")

    (dest / ".vimrc").write_text(
        "set encoding=utf-8\n"
        "silent! colorscheme iceberg\n"
        "if has('clipboard') && empty($SSH_CONNECTION)\n"
        "  set clipboard=unnamedplus\n"
        "endif\n",
        encoding="utf-8",
    )

    if os.name == "nt":
        prof = dest / ".config" / "powershell" / "profile.ps1"
        prof.parent.mkdir(parents=True, exist_ok=True)
        prof.write_text("$global:__smoke = 1\n", encoding="utf-8-sig")
    else:
        shellenv = dest / ".config" / "shell" / "shellenv.sh"
        shellenv.parent.mkdir(parents=True, exist_ok=True)
        shellenv.write_text("#!/bin/sh\nexport __SMOKE_SHELLENV=1\n", encoding="utf-8")
        (dest / ".zshenv").write_text("export __SMOKE_ZSHENV=1\n", encoding="utf-8")
        pk = dest / ".local" / "bin" / "pk"
        pk.parent.mkdir(parents=True, exist_ok=True)
        pk.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")


def test_check_destination_passes_on_valid_layout_and_detects_corruption(tmp_path):
    dest = tmp_path / "dest"
    _write_minimal_valid_dest(dest)

    steps = smoke.check_destination(dest, min_entries=5)
    failed = [s for s in steps if s.status == "failed"]
    assert not failed, failed

    # 1. Pi JSON 破損を検出する
    (dest / ".pi" / "agent" / "settings.json").write_text("{broken", encoding="utf-8")
    steps_bad_json = smoke.check_destination(dest, min_entries=5)
    by_name = {s.name: s for s in steps_bad_json}
    assert by_name["pi-json"].status == "failed"

    # 2. Vim の SSH_CONNECTION ガード違反を検出する（vim がある環境のみ）
    _write_minimal_valid_dest(dest)
    if shutil.which("vim"):
        (dest / ".vimrc").write_text("set clipboard=unnamedplus\n", encoding="utf-8")
        steps_bad_vim = smoke.check_destination(dest, min_entries=5)
        by_name_vim = {s.name: s for s in steps_bad_vim}
        # clipboard 対応ビルドなら失敗、非対応ビルドなら &clipboard=="" のためスキップ相当
        has_cb = smoke._run(["vim", "--version"]).stdout
        if "+clipboard" in has_cb:
            assert by_name_vim["vim-smoke"].status == "failed"


def test_cli_check_dest_outputs_json_and_exit_code(tmp_path, capsys):
    dest = tmp_path / "dest"
    _write_minimal_valid_dest(dest)
    rc = smoke.main(["check-dest", str(dest), "--min-entries", "5"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True

    (dest / ".config" / "git" / "config").unlink()
    rc2 = smoke.main(["check-dest", str(dest), "--min-entries", "5"])
    assert rc2 == 1
    out2 = json.loads(capsys.readouterr().out)
    assert out2["ok"] is False


@needs_chezmoi
def test_run_isolated_smoke_succeeds_on_real_repository_with_zero_residual_diff(tmp_path):
    """現在のリポジトリ全体が隔離 init + 2 回 apply + 残差分 0 + 起動スモークを通ることを検証する。"""
    report = smoke.run_isolated_smoke(ROOT, work_parent=tmp_path)
    failed = [(s.name, s.detail) for s in report.steps if s.status == "failed"]
    assert report.ok, f"隔離スモーク失敗: {failed}"
    step_map = {s.name: s.status for s in report.steps}
    assert step_map["chezmoi-init"] == "passed"
    assert step_map["chezmoi-apply-1"] == "passed"
    assert step_map["residual-diff"] == "passed"
    assert step_map["chezmoi-apply-2"] == "passed"
    assert step_map["pi-json"] == "passed"
