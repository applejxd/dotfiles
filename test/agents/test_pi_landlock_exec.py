"""Landlock ラッパー (``home/dot_config/pi/harness/landlock_exec.py``) の試験。

Landlock が使えない環境 (``--check`` が 3) では、実際に適用する試験を飛ばす。
"""

from __future__ import annotations

import errno
import importlib.util
import os
import re
import subprocess
import sys

import pytest
from agents_common import ROOT

WRAPPER = ROOT / "home" / "dot_config" / "pi" / "harness" / "landlock_exec.py"


def _run(args, env=None):
    return subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )


def _load():
    spec = importlib.util.spec_from_file_location("landlock_exec_under_test", WRAPPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def abi():
    proc = _run(["--check"])
    if proc.returncode != 0:
        pytest.skip("Landlock が使えない")
    m = re.fullmatch(r"landlock abi (\d+)\n?", proc.stdout)
    assert m, proc.stdout
    return int(m.group(1))


def _write_cmd(path):
    return ["sh", "-c", 'echo x > "$1"', "sh", str(path)]


def test_check(abi):
    assert abi >= 3


def test_write_allowed_only_under_path(abi, tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir()
    b.mkdir()
    ok = _run(["--write", str(a), "--", *_write_cmd(a / "f")])
    assert ok.returncode == 0, ok.stderr
    assert (a / "f").read_text() == "x\n"
    ng = _run(["--write", str(a), "--", *_write_cmd(b / "f")])
    assert ng.returncode != 0
    assert not (b / "f").exists()
    hello = _run(["--write", str(a), "--", "sh", "-c", "echo hello"])
    assert hello.returncode == 0 and hello.stdout == "hello\n"
    cat = _run(["--write", str(a), "--", "cat", "/etc/hostname"])
    assert cat.returncode == 0, cat.stderr


def test_write_file_device(abi):
    proc = _run(["--write", "/dev/null", "--", "sh", "-c", "echo x > /dev/null"])
    assert proc.returncode == 0, proc.stderr


def test_missing_write_is_usage_error_and_not_executed(tmp_path):
    marker = tmp_path / "marker"
    proc = _run(["--write", str(tmp_path / "nope"), "--", "touch", str(marker)])
    assert proc.returncode == 2
    assert proc.stderr.startswith("landlock_exec: ")
    assert not marker.exists()


def test_write_if_exists(abi, tmp_path):
    a = tmp_path / "A"
    a.mkdir()
    marker = a / "marker"
    proc = _run(
        ["--write", str(a), "--write-if-exists", str(tmp_path / "nope"), "--", "touch", str(marker)]
    )
    assert proc.returncode == 0, proc.stderr
    assert marker.exists()
    b = tmp_path / "B"
    b.mkdir()
    proc = _run(["--write-if-exists", str(b), "--", *_write_cmd(b / "f")])
    assert proc.returncode == 0, proc.stderr
    assert (b / "f").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["touch", "MARK"],
        ["--write", "{a}", "touch", "MARK"],
        ["--write"],
        ["--write", "--", "touch", "MARK"],
        ["--write-if-exists"],
        ["--write", "{a}", "--"],
        ["--"],
        [],
        ["--bogus", "--", "touch", "MARK"],
        ["--check", "--", "touch", "MARK"],
    ],
)
def test_usage_errors_do_not_execute(tmp_path, args):
    marker = tmp_path / "marker"
    a = tmp_path / "A"
    a.mkdir()
    argv = [x.replace("{a}", str(a)).replace("MARK", str(marker)) for x in args]
    proc = _run(argv)
    assert proc.returncode == 2
    assert proc.stderr.startswith("landlock_exec: ")
    assert not marker.exists()


def test_missing_command_is_127(abi, tmp_path):
    proc = _run(["--write", str(tmp_path), "--", "no-such-command-landlock-test"])
    assert proc.returncode == 127
    assert proc.stderr.startswith("landlock_exec: ")


def test_exit_code_passthrough(abi, tmp_path):
    proc = _run(["--write", str(tmp_path), "--", "sh", "-c", "exit 7"])
    assert proc.returncode == 7


def test_refer(abi, tmp_path):
    a, b, c = tmp_path / "A", tmp_path / "B", tmp_path / "C"
    for d in (a, b, c):
        d.mkdir()
    (a / "f").write_text("x")
    (a / "g").write_text("x")
    ok = _run(["--write", str(a), "--write", str(b), "--", "mv", str(a / "f"), str(b / "f")])
    assert ok.returncode == 0, ok.stderr
    assert (b / "f").exists()
    ng = _run(["--write", str(a), "--write", str(b), "--", "mv", str(a / "g"), str(c / "g")])
    assert ng.returncode != 0
    assert (a / "g").exists() and not (c / "g").exists()


def test_truncate(abi, tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir()
    b.mkdir()
    (a / "f").write_text("data")
    (b / "f").write_text("data")
    cmd = ["sh", "-c", ': > "$1"', "sh"]
    ok = _run(["--write", str(a / "f"), "--", *cmd, str(a / "f")])
    assert ok.returncode == 0, ok.stderr
    assert (a / "f").read_text() == ""
    ng = _run(["--write", str(a / "f"), "--", *cmd, str(b / "f")])
    assert ng.returncode != 0
    assert (b / "f").read_text() == "data"


def test_symlink_write_path(abi, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    proc = _run(["--write", str(link), "--", *_write_cmd(real / "f")])
    assert proc.returncode == 0, proc.stderr
    assert (real / "f").exists()
    assert str(real) not in proc.stderr


def test_env_passthrough(abi, tmp_path):
    env = {**os.environ, "LX_TEST": "value-1"}
    proc = _run(["--write", str(tmp_path), "--", "sh", "-c", "echo $LX_TEST"], env=env)
    assert proc.returncode == 0 and proc.stdout == "value-1\n"


def test_unlisted_path_is_denied(abi, tmp_path):
    a = tmp_path / "A"
    a.mkdir()
    other = tmp_path / "other.txt"
    proc = _run(["--write", str(a), "--", *_write_cmd(other)])
    assert proc.returncode != 0
    assert not other.exists()


def test_enosys_returns_3_without_exec(monkeypatch, capsys):
    mod = _load()

    def enosys(*_args):
        raise OSError(errno.ENOSYS, "ENOSYS")

    def boom(*_args):
        raise AssertionError("execvp が呼ばれた")

    monkeypatch.setattr(mod, "syscall", enosys)
    monkeypatch.setattr(mod.os, "execvp", boom)
    assert mod.main(["--", "true"]) == 3
    assert mod.main(["--check"]) == 3
    assert capsys.readouterr().err


def test_add_rule_failure_returns_3_without_exec(monkeypatch):
    mod = _load()
    ruleset_fd = os.open(os.devnull, os.O_RDONLY)

    def fake(nr, *args):
        if nr == mod.SYS_CREATE and args[2] == mod.CREATE_VERSION:
            return 3
        if nr == mod.SYS_CREATE:
            return ruleset_fd
        raise OSError(errno.EPERM, "EPERM")

    def boom(*_args):
        raise AssertionError("execvp が呼ばれた")

    monkeypatch.setattr(mod, "syscall", fake)
    monkeypatch.setattr(mod.os, "execvp", boom)
    assert mod.main(["--", "true"]) == 3


def _boom(*_args):
    raise AssertionError("execvp が呼ばれた")


def _fake_syscall(mod, abi_value, fail_nr=None):
    ruleset_fd = os.open(os.devnull, os.O_RDONLY)

    def fake(nr, *args):
        if nr == mod.SYS_CREATE and args[2] == mod.CREATE_VERSION:
            return abi_value
        if nr == fail_nr:
            raise OSError(errno.EPERM, "EPERM")
        if nr == mod.SYS_CREATE:
            return os.dup(ruleset_fd)
        return 0

    return fake


def test_abi_below_min_returns_3_without_exec(monkeypatch, capsys):
    mod = _load()
    assert mod.MIN_ABI == 3
    monkeypatch.setattr(mod, "syscall", _fake_syscall(mod, 2))
    monkeypatch.setattr(mod.os, "execvp", _boom)
    assert mod.main(["--", "true"]) == 3
    assert mod.main(["--check"]) == 3
    err = capsys.readouterr().err.splitlines()
    assert err and all(line.startswith("landlock_exec: ") for line in err)


def test_prctl_failure_returns_3_without_exec(monkeypatch, capsys):
    mod = _load()

    def bad_prctl(*_args):
        raise OSError(errno.EPERM, "EPERM")

    monkeypatch.setattr(mod, "syscall", _fake_syscall(mod, 3))
    monkeypatch.setattr(mod, "prctl", bad_prctl)
    monkeypatch.setattr(mod.os, "execvp", _boom)
    assert mod.main(["--", "true"]) == 3
    assert capsys.readouterr().err.startswith("landlock_exec: ")


def test_restrict_self_failure_returns_3_without_exec(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod, "syscall", _fake_syscall(mod, 3, fail_nr=mod.SYS_RESTRICT))
    monkeypatch.setattr(mod, "prctl", lambda *_a: None)
    monkeypatch.setattr(mod.os, "execvp", _boom)
    assert mod.main(["--", "true"]) == 3
    assert capsys.readouterr().err.startswith("landlock_exec: ")


def test_check_fails_when_restrict_self_fails(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod, "syscall", _fake_syscall(mod, 3, fail_nr=mod.SYS_RESTRICT))
    monkeypatch.setattr(mod, "prctl", lambda *_a: None)
    assert mod.main(["--check"]) == 3
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.startswith("landlock_exec: ")


@pytest.mark.parametrize("bad", ["/", "HOME", "/home", "/usr", "/dev"])
def test_too_broad_path_is_usage_error(tmp_path, bad):
    marker = tmp_path / "marker"
    home = tmp_path / "home"
    home.mkdir()
    path = str(home) if bad == "HOME" else bad
    env = {**os.environ, "HOME": "/home/landlock-test-user" if bad == "/home" else str(home)}
    for opt in ("--write", "--write-if-exists"):
        proc = _run([opt, path, "--", "touch", str(marker)], env=env)
        assert proc.returncode == 2
        assert proc.stderr.startswith("landlock_exec: ")
        assert path in proc.stderr.splitlines()[0]
        assert not marker.exists()


def test_home_ancestor_and_symlink_to_home_are_refused(tmp_path):
    home = tmp_path / "a" / "home"
    home.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(home)
    env = {**os.environ, "HOME": str(home)}
    for path in (tmp_path / "a", link):
        proc = _run(["--write", str(path), "--", "true"], env=env)
        assert proc.returncode == 2, proc.stderr


def test_specific_dev_and_below_home_are_allowed(abi, tmp_path):
    home = tmp_path / "home"
    cache = home / ".cache"
    cache.mkdir(parents=True)
    env = {**os.environ, "HOME": str(home)}
    ok = _run(["--write", "/dev/null", "--", "true"], env=env)
    assert ok.returncode == 0, ok.stderr
    ok = _run(["--write", str(cache), "--", *_write_cmd(cache / "f")], env=env)
    assert ok.returncode == 0, ok.stderr
    assert (cache / "f").exists()


def test_handled_access_by_abi():
    mod = _load()
    assert mod.handled_access(1) & mod.REFER == 0
    assert mod.handled_access(2) & mod.REFER and not mod.handled_access(2) & mod.TRUNCATE
    assert mod.handled_access(3) & mod.TRUNCATE
    assert mod.handled_access(6) == mod.handled_access(3)
    assert mod.handled_access(3) < (1 << 15)
