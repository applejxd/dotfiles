"""scripts/pr_app.py の試験（偽の systemctl・tailscale・node を PATH に置いて検査する）。"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "pr_app.py"
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux 専用")


def _fake(bindir: Path, name: str) -> None:
    """引数と cwd を `<name>.log` へ 1 行ずつ追記するだけの偽コマンド。"""
    p = bindir / name
    p.write_text(
        '#!/bin/sh\n{ echo "cwd=$(pwd)"; for a in "$@"; do echo "arg=$a"; done; echo "--"; }'
        f' >> "{bindir}/{name}.log"\nexit 0\n',
        encoding="utf-8",
    )
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def box(tmp_path: Path) -> dict:
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for n in ("systemctl", "tailscale", "node", "journalctl"):
        _fake(bindir, n)
    # 起動元の見立て（apps/pr-viewer/server.ts があるだけのチェックアウト）
    root = tmp_path / "my root"
    (root / "apps" / "pr-viewer").mkdir(parents=True)
    (root / "apps" / "pr-viewer" / "server.ts").write_text("", encoding="utf-8")
    env = {"HOME": str(home), "PATH": str(bindir), "LANG": "C.UTF-8"}
    return {"home": home, "bin": bindir, "root": root, "env": env}


def _run(box: dict, *args: str, extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**box["env"], **(extra or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )


def _log(box: dict, name: str) -> str:
    p = box["bin"] / f"{name}.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _envfile(box: dict) -> Path:
    return box["home"] / ".config" / "pr-viewer" / "env"


def _write_env(box: dict, text: str) -> None:
    _envfile(box).parent.mkdir(parents=True, exist_ok=True)
    _envfile(box).write_text(text, encoding="utf-8")


# ---- serve: 旗は既定で全部無効 ----------------------------------------------------------


def test_serve_既定では_allow_旗を付けない(box):
    r = _run(box, "serve", extra={"PRAPP_ROOT": str(box["root"])})
    assert r.returncode == 0, r.stderr
    log = _log(box, "node")
    assert "arg=apps/pr-viewer/server.ts" in log
    assert "--allow-" not in log
    assert "--allow-" not in r.stderr
    assert f"cwd={box['root']}" in log
    assert "arg=8780" in log


def test_serve_旗が_1_のときだけ_allow_を付けて警告する(box):
    _write_env(box, "PRAPP_ALLOW_MERGE=1\nPRAPP_ALLOW_JOBS=0\nPRAPP_ALLOW_CREATE=1\n")
    r = _run(box, "serve", extra={"PRAPP_ROOT": str(box["root"])})
    log = _log(box, "node")
    assert "arg=--allow-merge" in log
    assert "arg=--allow-create" in log
    assert "--allow-jobs" not in log
    assert "統合を有効" in r.stderr and "起票" in r.stderr and "変更を依頼" not in r.stderr


def test_serve_旗が_0_なら_付けない(box):
    _write_env(box, "PRAPP_ALLOW_MERGE=0\nPRAPP_ALLOW_JOBS=0\nPRAPP_ALLOW_CREATE=0\n")
    _run(box, "serve", extra={"PRAPP_ROOT": str(box["root"])})
    assert "--allow-" not in _log(box, "node")


def test_serve_環境変数が設定ファイルに優先し_リポジトリを引数で渡せる(box):
    _write_env(box, 'PRAPP_ALLOW_MERGE=1\nPRAPP_PORT=9000\nPRAPP_REPOS="/a /b"\n')
    _run(box, "serve", extra={"PRAPP_ROOT": str(box["root"]), "PRAPP_ALLOW_MERGE": "0"})
    log = _log(box, "node")
    assert "--allow-merge" not in log
    assert "arg=9000" in log and "arg=/a" in log and "arg=/b" in log
    _run(box, "serve", "/x", extra={"PRAPP_ROOT": str(box["root"])})
    assert "arg=/x" in _log(box, "node")


# ---- 起動元 -----------------------------------------------------------------------------


def test_起動元に_server_ts_が無ければ停止する(box, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(box, "serve", extra={"PRAPP_ROOT": str(empty)})
    assert r.returncode == 2
    assert "server.ts" in r.stderr
    assert _log(box, "node") == ""


def test_起動元の既定はこのスクリプトのチェックアウト(box):
    r = _run(box, "serve")
    assert r.returncode == 0, r.stderr
    assert f"cwd={REPO}" in _log(box, "node")


# ---- install ----------------------------------------------------------------------------


@linux_only
def test_install_は新規設定の旗をすべて_0_で書く(box):
    r = _run(box, "install", extra={"PRAPP_ROOT": str(box["root"])})
    assert r.returncode == 0, r.stderr
    text = _envfile(box).read_text(encoding="utf-8")
    for k in ("PRAPP_ALLOW_MERGE", "PRAPP_ALLOW_JOBS", "PRAPP_ALLOW_CREATE"):
        assert f"{k}=0\n" in text
    assert "=1" not in text
    assert f'PRAPP_REPOS="{box["root"]}"' in text
    log = _log(box, "systemctl")
    assert "arg=enable" in log and "arg=--now" in log and "arg=pr-viewer.service" in log


@linux_only
def test_install_は既存の設定を上書きしない(box):
    _write_env(box, "PRAPP_ALLOW_MERGE=1\nPRAPP_PORT=9999\n")
    _run(box, "install", extra={"PRAPP_ROOT": str(box["root"])})
    assert _envfile(box).read_text(encoding="utf-8") == "PRAPP_ALLOW_MERGE=1\nPRAPP_PORT=9999\n"


@linux_only
def test_install_はリポジトリを渡されたときだけ_REPOS_の行を直す(box):
    _write_env(box, 'PRAPP_ALLOW_MERGE=1\nPRAPP_REPOS="/old"\n')
    _run(box, "install", "/new", extra={"PRAPP_ROOT": str(box["root"])})
    assert _envfile(box).read_text(encoding="utf-8") == 'PRAPP_ALLOW_MERGE=1\nPRAPP_REPOS="/new"\n'


@linux_only
def test_ユニットの内容と空白を含むパス(box):
    r = _run(box, "install", extra={"PRAPP_ROOT": str(box["root"])})
    assert r.returncode == 0, r.stderr
    unit = (box["home"] / ".config" / "systemd" / "user" / "pr-viewer.service").read_text(
        encoding="utf-8"
    )
    assert "EnvironmentFile=-%h/.config/pr-viewer/env\n" in unit
    # ExecStart の根は起動元（ここでは PRAPP_ROOT の "my root"）。空白があっても引用される
    assert f'ExecStart=/usr/bin/env python3 "{box["root"]}/scripts/pr_app.py" serve\n' in unit


def test_ユニットの_ExecStart_は空白や引用符を引用する():
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import pr_app
    finally:
        sys.path.pop(0)
    assert pr_app.systemd_quote("/a b/c") == '"/a b/c"'
    assert pr_app.systemd_quote('/a"b') == '"/a\\"b"'
    assert pr_app.systemd_quote("/a%b") == '"/a%%b"'
    assert 'ExecStart=/usr/bin/env python3 "/x y/scripts/pr_app.py" serve' in pr_app.unit_text(
        Path("/x y")
    )


# ---- DRY_RUN ----------------------------------------------------------------------------


@linux_only
def test_dry_run_は何も実行せず何も書かない(box):
    env = {"PRAPP_DRY_RUN": "1", "PRAPP_ROOT": str(box["root"])}
    for sub in ("install", "restart", "uninstall", "expose", "unexpose", "logs", "status"):
        r = _run(box, sub, extra=env)
        assert r.returncode == 0, (sub, r.stderr)
    r = _run(box, "install", extra=env)
    assert "ExecStart=" in r.stdout and "[dry-run] systemctl --user enable --now" in r.stdout
    assert "PRAPP_ALLOW_MERGE=0" in r.stdout
    for n in ("systemctl", "tailscale", "journalctl"):
        assert _log(box, n) == "", n
    assert not _envfile(box).exists()
    assert not (box["home"] / ".config" / "systemd").exists()


# ---- expose / OS ------------------------------------------------------------------------


@linux_only
def test_expose_は_serve_だけを使い_funnel_を使わない(box):
    r = _run(box, "expose", extra={"PRAPP_PORT": "8123"})
    assert r.returncode == 0, r.stderr
    log = _log(box, "tailscale")
    assert "arg=serve" in log and "arg=--bg" in log and "arg=8123" in log
    assert "funnel" not in log.lower()


def test_linux_以外では_install_expose_が理由つきで終了コード_2(monkeypatch, capsys):
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import pr_app
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(pr_app.sys, "platform", "win32")
    monkeypatch.delenv("PRAPP_DRY_RUN", raising=False)
    for sub in ("install", "expose", "restart", "status"):
        assert pr_app.main([sub]) == 2
        assert "Linux" in capsys.readouterr().err


def test_不明なサブコマンドは使い方を出して_2(box):
    r = _run(box, "nope")
    assert r.returncode == 2 and "使い方" in r.stdout
    assert os.path.exists(SCRIPT)
