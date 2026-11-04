"""judge/syntax.ts (bash 構文木の読み込み・sha256 の照合・自己診断) の試験。

- node 直接: vendor を壊したとき (sha 不一致・欠損・空) は例外でなく ``{ok: false}``。壊れていない複製は読める。
- 実際の pi の中: 拡張 (``test/agents/pi/syntax_probe.ts``) から syntax.ts を読み込んで解析できる。pi が無い環境では skip する
  (skip は通過ではなく「未実測」)。実測値 (pi の版・runtime・読み込み時間・メモリ) は ``-s`` で出る。

see docs/spec/guard/pi-extensions.md#確認画面の手順の一覧
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness"
VENDOR = HARNESS / "vendor" / "mvdan-sh"
SYNTAX = HARNESS / "judge" / "syntax.ts"
DOCTOR = HARNESS / "judge" / "doctor.mjs"
DRIVER = ROOT / "test" / "agents" / "pi" / "syntax_driver.mjs"
PROBE = ROOT / "test" / "agents" / "pi" / "syntax_probe.ts"
FAUX = ROOT / "test" / "agents" / "pi" / "faux.ts"

needs_node = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


def _run(vendor_dir):
    proc = subprocess.run(
        [_node(), str(DRIVER), str(vendor_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-1000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


@pytest.fixture
def vendor_copy(tmp_path):
    dst = tmp_path / "mvdan-sh"
    shutil.copytree(VENDOR, dst)
    return dst


@needs_node
def test_valid_vendor_loads_parses_and_passes_self_diagnosis():
    out = _run(VENDOR)
    assert out["load"]["ok"] is True
    assert out["parse"] == {"ok": True, "why": "", "stmts": 1}
    assert out["diag"]["ok"] is True, out["diag"]
    # 読み込みが GopherJS の大域の書き込み (global.require) を残さない
    assert out["globalRequireLeaked"] is False


@needs_node
def test_sha_mismatch_fails_without_raising(vendor_copy):
    index = vendor_copy / "index.js"
    index.write_bytes(index.read_bytes() + b"\n")
    out = _run(vendor_copy)
    assert out["load"]["ok"] is False and "sha256" in out["load"]["why"]
    assert out["parse"]["ok"] is False and out["diag"]["ok"] is False


@needs_node
def test_same_size_tamper_is_caught(vendor_copy):
    """大きさが同じでも 1 バイト違えば落ちる (大きさでなく sha256 で照合する)。"""
    index = vendor_copy / "index.js"
    data = bytearray(index.read_bytes())
    data[-1] = data[-1] ^ 1
    index.write_bytes(bytes(data))
    assert _run(vendor_copy)["load"]["ok"] is False


@needs_node
@pytest.mark.parametrize("kind", ["missing_file", "missing_dir"])
def test_missing_vendor_fails_without_raising(vendor_copy, kind):
    target = vendor_copy
    if kind == "missing_file":
        (vendor_copy / "index.js").unlink()
    else:
        shutil.rmtree(vendor_copy)
    out = _run(target)
    assert out["load"]["ok"] is False and "読めない" in out["load"]["why"]
    assert out["parse"]["ok"] is False and out["diag"]["ok"] is False


@needs_node
def test_doctor_reports_ok_and_ng_with_exit_code():
    ok = subprocess.run(
        [_node(), str(DOCTOR)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "OK:" in ok.stdout and "期待値と一致" in ok.stdout and "メモリ増分" in ok.stdout


@needs_node
def test_doctor_ng_in_a_broken_copy(tmp_path, vendor_copy):
    """judge/・vendor/ の複製で index.js を壊すと、doctor は NG・終了コード 1・対処の一文を出す。"""
    root = tmp_path / "harness"
    (root / "judge").mkdir(parents=True)
    shutil.copy2(SYNTAX, root / "judge" / "syntax.ts")
    shutil.copy2(DOCTOR, root / "judge" / "doctor.mjs")
    (root / "vendor").mkdir()
    shutil.move(vendor_copy, root / "vendor" / "mvdan-sh")
    (root / "vendor" / "mvdan-sh" / "index.js").write_bytes(b"broken")
    ng = subprocess.run(
        [_node(), str(root / "judge" / "doctor.mjs")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert ng.returncode == 1
    assert (
        "NG:" in ng.stdout
        and "sha256" in ng.stdout
        and "`pis` の外のシェルで `chezmoi apply`" in ng.stdout
    )


# ─── 実際の pi の中 ─────────────────────────────────────────────


def _bun():
    # mise の shim は版が未設定だと失敗するので、実体 (installs/bun/<版>/bin/bun) も探す
    mise = Path.home() / ".local" / "share" / "mise" / "installs" / "bun"
    candidates = [shutil.which("bun"), *map(str, sorted(mise.glob("*/bin/bun"), reverse=True))]
    for found in candidates:
        if (
            found
            and subprocess.run([found, "--version"], capture_output=True, check=False).returncode
            == 0
        ):
            return found
    return None


@pytest.mark.skipif(_bun() is None, reason="bun (JavaScriptCore) が使えない")
def test_doctor_passes_under_bun_javascriptcore():
    proc = subprocess.run(
        [_bun(), str(DOCTOR)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    print(
        "\n[実測 bun]",
        proc.stdout.strip().splitlines()[0],
        "|",
        [x for x in proc.stdout.splitlines() if "読み込み" in x],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "JavaScriptCore" in proc.stdout and "OK:" in proc.stdout


PI = shutil.which("pi")


@pytest.mark.skipif(PI is None, reason="pi is not installed")
def test_syntax_loads_and_parses_inside_the_real_pi(tmp_path):
    out_file = tmp_path / "probe.json"
    agent = tmp_path / "agent"
    agent.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()

    env = {
        **os.environ,
        "PI_CODING_AGENT_DIR": str(agent),
        "TMPDIR": str(tmp_path),
        "FAUX_TOOL_CALLS": "[]",
        "SYNTAX_PROBE_OUT": str(out_file),
        "SYNTAX_PROBE_SRC": str(SYNTAX),
    }
    for key in [k for k in env if k.startswith(("PI_HARNESS_", "ORCA_"))]:
        env.pop(key, None)
    args = [
        PI,
        "--no-session",
        "--model",
        "faux/spike",
        "-nbt",
        "-ne",
        "-e",
        str(PROBE),
        "-e",
        str(FAUX),
        "-p",
        "go",
    ]
    proc = subprocess.run(
        args,
        cwd=proj,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    assert out_file.is_file(), (
        "拡張が結果を書かなかった: " + proc.stdout[-500:] + proc.stderr[-500:]
    )
    r = json.loads(out_file.read_text(encoding="utf-8"))
    ver = subprocess.run(
        [PI, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False
    )
    print(
        f"\n[実測] pi {(ver.stdout + ver.stderr).strip()} / runtime {r['runtime']} / 読み込み {r['loadMs']} ms /"
        f" 自己診断+解析 {r['diagAndParseMs']} ms / rss 増分 {r['rssDeltaMB']} MB"
    )
    assert r["load"]["ok"] is True, r["load"]
    assert r["diag"]["ok"] is True, r["diag"]
    assert r["parse"] == {"ok": True, "why": "", "stmts": 2}
