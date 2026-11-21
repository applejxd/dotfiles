"""modify script が、旧版の書いた cp932 のファイルを読めることを検証する。

2026-11-20 より前の日本語 Windows では、modify script が cp932 のバイト列を書いていた
(標準入出力がロケールのコードページだったため)。その後 UTF-8 に固定したが、すでに cp932 で
できた対象ファイルを UTF-8 として読めず、chezmoi apply / update が
`UnicodeDecodeError` で止まった。入力は UTF-8 で読み、読めなければ cp932 として読み直す。
see docs/spec/agent-config-generation.md#modify-スクリプトの文字コード

実機の chezmoi apply は行わない。Windows の既定のコードページは、子プロセスへ
`PYTHONIOENCODING=cp932` を渡して近似する (Linux でも再現できる)。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME_SRC = ROOT / "home"
# 標準入力の JSON を読んで返す modify script のうち、対象ファイルが日本語を含みうる 5 つ
MODIFY_SCRIPTS = (
    "dot_pi/agent/modify_settings.json.py.tmpl",
    "dot_pi/agent/modify_compaction.json.py.tmpl",
    "dot_pi/agent/modify_pi-plan-mode.json.py.tmpl",
    "dot_pi/agent/extensions/pi-permission-system/modify_config.json.py.tmpl",
    "dot_pi/agent/extensions/subagent/modify_config.json.py.tmpl",
)
NOTE = "利用者が書いた日本語のメモ"


def chezmoi_bin() -> str:
    found = shutil.which("chezmoi")
    if found is None:
        pytest.skip("chezmoi is not installed")
    return found


def render(name: str, home: Path) -> str:
    context = {
        "chezmoi": {
            "os": "linux",
            "username": "tester",
            "kernel": {"osrelease": "Linux"},
            "homeDir": str(home),
            "workingTree": str(ROOT),
        }
    }
    template = (HOME_SRC / name).read_text(encoding="utf-8")
    wrapped = "{{ with " + json.dumps(json.dumps(context)) + " | fromJson }}" + template + "{{ end }}"
    result = subprocess.run(
        [chezmoi_bin(), "--source", str(ROOT), "execute-template"],
        input=wrapped,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture(scope="module", params=MODIFY_SCRIPTS)
def script(request, tmp_path_factory) -> Path:
    work = tmp_path_factory.mktemp("modify")
    path = work / "modify.py"
    path.write_text(render(request.param, work), encoding="utf-8")
    return path


def run(script: Path, stdin: bytes) -> subprocess.CompletedProcess[bytes]:
    # Windows の既定のコードページ (cp932) を近似する
    env = {**os.environ, "PYTHONIOENCODING": "cp932"}
    env.pop("PYTHONUTF8", None)
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        env=env,
        check=False,
    )


def dump(data: object, *, newline: str = "\n") -> str:
    return json.dumps(data, indent=2, ensure_ascii=False).replace("\n", newline) + newline


def test_cp932_input_is_migrated_to_utf8(script: Path):
    """旧版が書いた cp932 のファイルを読み、同じ内容を UTF-8 で返す (CRLF の入力でも)。"""
    legacy = dump({"note": NOTE}, newline="\r\n").encode("cp932")

    result = run(script, legacy)

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert json.loads(result.stdout.decode("utf-8"))["note"] == NOTE


def test_cp932_input_gives_the_same_output_as_utf8_input(script: Path):
    """移行後は、UTF-8 の入力と同じ結果になる (apply を重ねても変わらない)。"""
    from_cp932 = run(script, dump({"note": NOTE}).encode("cp932"))
    from_utf8 = run(script, dump({"note": NOTE}).encode("utf-8"))

    assert from_cp932.returncode == 0, from_cp932.stderr.decode(errors="replace")
    assert from_cp932.stdout == from_utf8.stdout

    again = run(script, from_cp932.stdout)
    assert again.stdout == from_cp932.stdout


def test_utf8_input_keeps_the_users_keys(script: Path):
    """UTF-8 の入力の挙動は変えない (利用者のキーを保つ)。"""
    result = run(script, dump({"note": NOTE}).encode("utf-8"))

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert json.loads(result.stdout.decode("utf-8"))["note"] == NOTE


def test_broken_cp932_input_is_left_alone_as_utf8(script: Path):
    """壊れた JSON は触らない。ただし文字コードは UTF-8 にそろえて返す。"""
    broken = '{"note": "' + NOTE + '"'  # 閉じていない

    result = run(script, broken.encode("cp932"))

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.decode("utf-8") == broken


def test_undecodable_input_fails_loudly(script: Path):
    """UTF-8 でも cp932 でも読めないバイト列は、黙って壊さず止める。"""
    # 0x81 は UTF-8 では継続バイト、cp932 では先頭バイト。後ろの 0x20 は cp932 の 2 バイト目になれない
    # (0xff・0xfe は、Windows の cp932 では私用領域の文字に読めてしまうので使えない)
    result = run(script, b'{"note": "\x81\x20"}')

    assert result.returncode != 0
    assert b"UnicodeDecodeError" in result.stderr


def test_broken_input_newlines_are_normalized_like_text_stdin(script: Path):
    """壊れた JSON の改行は、text の標準入力と同じに LF へそろえる (CRLF・単独の CR・混在)。

    Windows の text の標準出力は LF を CRLF にするので、比べる前に CRLF を LF へ戻す。
    LF へそろえていないと、Windows では CR が重なり (CR CR LF)、Linux では CRLF が残って、一致しない。
    """
    broken = '{"note": "' + NOTE + '"\r\n, "a"\r, "b"\n, "c"\r\n'  # 閉じていない

    for encoding in ("utf-8", "cp932"):
        result = run(script, broken.encode(encoding))

        assert result.returncode == 0, result.stderr.decode(errors="replace")
        out = result.stdout.decode("utf-8").replace("\r\n", "\n")
        assert out == broken.replace("\r\n", "\n").replace("\r", "\n"), encoding


def test_utf8_bom_input_is_passed_through(script: Path):
    """BOM つきの UTF-8 は JSON として読めない入力 (従来どおり) なので、そのまま返す。"""
    raw = b"\xef\xbb\xbf" + dump({"note": NOTE}).encode("utf-8")

    result = run(script, raw)

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.replace(b"\r\n", b"\n") == raw.replace(b"\r\n", b"\n")
