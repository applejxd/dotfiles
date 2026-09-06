"""Regression tests for Herdr integration scripts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WINDOWS_SCRIPT = (
    ROOT
    / "home"
    / ".chezmoiscripts"
    / "300_windows"
    / "run_after_343_herdr_integration.ps1.tmpl"
)


def test_windows_skill_replace_uses_nonempty_backup_path():
    source = WINDOWS_SCRIPT.read_text(encoding="utf-8")

    assert "[System.IO.File]::Replace($skillTempPath, $skillPath, $null)" not in source
    assert (
        "[System.IO.File]::Replace($skillTempPath, $skillPath, $skillBackupPath)" in source
    )
    assert "Remove-Item -LiteralPath $skillBackupPath -Force" in source
