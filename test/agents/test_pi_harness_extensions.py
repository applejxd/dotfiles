"""ハーネスへ明示の ``-e`` で足した拡張が、判定・伏字化の中でどう扱われるかを、偽のモデルで試す。

pi が無い環境では skip する (``test_pi_harness.py`` と同じ)。
see docs/research/agents/pi-extension-under-harness.md
"""

from __future__ import annotations

import json
import shutil

from agents_common import agents_config_dir
from test_pi_harness import FIXTURES, SECRET, bash_call, env, run_pi  # noqa: F401

EXT = ("-e", str(FIXTURES / "ext_tool.ts"))
CALL = [{"name": "ext_search", "args": {"query": "hello"}}]


def _config_listing(env, tool):
    """役割 implementer の tools に ``tool`` を足した common.toml を置いた設定の置き場を返す。"""
    dst = env["tmp"] / "cfg"
    shutil.copytree(agents_config_dir(), dst)
    path = dst / "common.toml"
    text = path.read_text(encoding="utf-8")
    old = 'tools = ["bash", "read", "edit", "write", "grep", "find", "ls", "task", "mcp__*"]'
    assert old in text, "implementer の tools の行が変わった (この試験の前提を直す)"
    path.write_text(text.replace(old, old[:-1] + f', "{tool}"]'), encoding="utf-8")
    return str(dst)


def test_extension_tool_is_denied_unless_the_role_lists_it(env):
    loaded, ran = env["tmp"] / "loaded", env["tmp"] / "ran"
    proc = run_pi(env, CALL, extra=EXT, EXT_LOADED_FILE=str(loaded), EXT_RAN_FILE=str(ran))

    # -ne でも明示の -e は読まれ、ツールはモデルに宣言される。だが役割に無ければ判定で拒否する
    assert loaded.exists()
    assert '"ext_search"' in proc.stdout
    assert "は ext_search を使えない" in proc.stdout, proc.stdout
    assert not ran.exists()
    # bypass でも deny は通らない
    proc = run_pi(env, CALL, extra=EXT, PI_HARNESS_BYPASS="1", EXT_RAN_FILE=str(ran))
    assert "は ext_search を使えない" in proc.stdout, proc.stdout
    assert not ran.exists()


def test_listed_extension_tool_is_asked_and_its_result_is_redacted(env):
    ran = env["tmp"] / "ran"
    cfg = _config_listing(env, "ext_search")
    common = dict(EXT_RAN_FILE=str(ran), EXT_SECRET=SECRET, AGENTS_CONFIG_DIR=cfg)

    # 役割に載せても、規則が無ければ既定の確認になる (UI の無い起動では拒否)
    proc = run_pi(env, CALL, extra=EXT, **common)
    assert "not approved:" in proc.stdout, proc.stdout
    assert not ran.exists()

    # bypass で実行させると、ハーネスの tool_result が結果の秘密を伏せる
    proc = run_pi(env, CALL, extra=EXT, mode="json", PI_HARNESS_BYPASS="1", **common)
    assert ran.exists()
    assert "伏字" in proc.stdout
    assert SECRET not in proc.stdout
    results = [
        json.loads(line)
        for line in proc.stdout.splitlines()
        if line.startswith("{") and '"toolName":"ext_search"' in line
    ]
    assert results


def test_extension_cannot_replace_a_guarded_tool(env):
    pwned = env["proj"] / "pwned"
    proc = run_pi(
        env,
        bash_call("wc -c /dev/null"),
        extra=(*EXT, "-e", str(FIXTURES / "mutator.ts")),
        MUTATE_TO=f"touch {pwned.as_posix()}",
        EXT_OVERRIDE="guarded_bash",
        EXT_SHELL=shutil.which("bash") or "bash",
    )

    # 同じ名前のツールを後から登録すると、読み込みの失敗で起動が止まる (許可側へは倒れない)
    assert proc.returncode != 0
    assert 'Tool "guarded_bash" conflicts' in proc.stderr, proc.stderr
    assert not pwned.exists()
