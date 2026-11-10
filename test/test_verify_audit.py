"""scripts/verify_audit.py (閉じたモジュールの範囲を開いた試験の監査プラグイン) の試験。"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("verify_audit", SCRIPTS / "verify_audit.py")
assert _spec is not None
assert _spec.loader is not None
audit = importlib.util.module_from_spec(_spec)
sys.modules["verify_audit"] = audit
_spec.loader.exec_module(audit)

KCAGE_FILE = "scripts/kcage/example.py"
FILES = ["test/kcage/test_example.py", "test/test_other.py"]


def _recorder(tmp_path: Path):
    rec = audit.Recorder(root=str(tmp_path), patterns=("scripts/kcage/**",))
    return rec


def test_recorder_keeps_only_paths_in_the_module(tmp_path):
    rec = _recorder(tmp_path)
    rec.current = "test/test_other.py"
    rec.on_event("open", (str(tmp_path / KCAGE_FILE), "r", 0))
    rec.on_event("open", (str(tmp_path / "docs" / "a.md"), "r", 0))  # 範囲外
    rec.on_event("open", ("/etc/hostname", "r", 0))  # リポジトリ外
    rec.on_event("open", (3, "r", 0))  # fd
    rec.on_event("os.listdir", (str(tmp_path / "scripts" / "kcage"),))
    rec.on_event("socket.connect", (str(tmp_path / KCAGE_FILE),))  # 対象外の event
    assert rec.opened == {
        ("test/test_other.py", KCAGE_FILE),
        ("test/test_other.py", "scripts/kcage"),
    }


def test_recorder_ignores_events_outside_a_test(tmp_path):
    rec = _recorder(tmp_path)
    rec.on_event("open", (str(tmp_path / KCAGE_FILE), "r", 0))
    assert rec.opened == set()


def test_outside_opens_lists_only_tests_outside_the_module():
    opened = {
        ("test/kcage/test_example.py", KCAGE_FILE),  # モジュールの試験
        ("test/test_other.py", KCAGE_FILE),  # 外の試験
        ("test/test_other.py", "docs/a.md"),  # 範囲外のパスは見ない
    }
    files = FILES
    bad = audit.outside_opens(opened, files)
    assert bad == [("kcage", "test/test_other.py", KCAGE_FILE)]


def test_dump_and_read_logs_roundtrip_across_workers(tmp_path):
    out = tmp_path / "audit.log"
    for pid, test in ((1, "test/a.py"), (2, "test/b.py")):
        rec = _recorder(tmp_path)
        rec.opened = {(test, KCAGE_FILE)}
        rec.dump(Path(f"{out}.{pid}"))
    assert audit.read_logs(out) == {("test/a.py", KCAGE_FILE), ("test/b.py", KCAGE_FILE)}


def test_report_exit_code(tmp_path, capsys):
    out = tmp_path / "audit.log"
    out.with_name("audit.log.1").write_text(
        f"test/zzz_outside.py\t{KCAGE_FILE}\n", encoding="utf-8"
    )
    assert audit.main(["report", str(out)]) == 1
    assert "test/zzz_outside.py" in capsys.readouterr().out
    assert audit.main(["report", str(tmp_path / "none.log")]) == 0
    assert audit.main([]) == 2


def test_plugin_is_inactive_without_the_env_and_logs_with_it(tmp_path):
    """-p で読み込んでも環境変数が無ければ何もせず、有ればモジュール外の試験の参照をログに残す。"""
    case = tmp_path / "test_probe.py"
    target = ROOT / "scripts" / "kcage"
    case.write_text(
        "from pathlib import Path\n"
        "def test_probe():\n"
        f"    assert Path({str(target)!r}).exists()\n"
        f"    list(__import__('os').scandir({str(target)!r}))\n",
        encoding="utf-8",
    )
    out = tmp_path / "audit.log"
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
    env.pop("VERIFY_AUDIT_OUT", None)
    base = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "verify_audit",
        "-q",
        str(case),
        "-p",
        "no:cacheprovider",
    ]
    proc = subprocess.run(
        base,
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not list(tmp_path.glob("audit.log*"))
    env["VERIFY_AUDIT_OUT"] = str(out)
    proc = subprocess.run(
        base,
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    opened = audit.read_logs(out)
    assert any(p == "scripts/kcage" for _t, p in opened), opened
