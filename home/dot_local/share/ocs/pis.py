"""``pis``: pi をフルガード付きで起動する入口。

標準は **サンドボックス (Fence) の中** で起動する (:func:`pi.run_sandboxed`)。
``--no-sandbox`` はフルガードだけで起動する (``-nbt -ne`` とフルガードの明示の ``-e``)。
サンドボックスを張れない OS では、黙って弱い守りに落とさず、起動を断って
``--no-sandbox`` を案内する。
起動フラグと拡張の一覧は :mod:`pi` と共有する。
see docs/spec/pi-guard.md#起動
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import pi
from .common import HOME

USAGE = "usage: pis [--bypass] [--no-sandbox] [--role <役割>] [--] [pi の引数...]"
# 外から入った内部の環境変数。子エージェントの印は pis が起動するたびに外す
INTERNAL_ENV = (
    "PI_HARNESS_CHILD",
    "PI_HARNESS_TEST_CHILD_EXT",
    "PI_HARNESS_BOUNDARY",
    "PI_HARNESS_NO_SANDBOX",
    "PI_HARNESS_ALLOWED",
    "PI_HARNESS_CANARY_READ",
    "PI_HARNESS_CANARY_WRITE",
)
ORCA_MARKER = "@orca-managed-pi-extension"


@dataclass
class Options:
    bypass: bool
    sandbox: bool
    role: str
    rest: list[str]


def fail(message: str, code: int = 1) -> None:
    print(f"pis: {message}", file=sys.stderr)
    raise SystemExit(code)


def parse(argv: list[str]) -> Options:
    """先頭の pis のオプションだけを解釈し、残りを pi (と ``--check`` など) へ渡す。"""
    bypass = no_sandbox = boundary = False
    role = ""
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--bypass":
            bypass = True
            i += 1
        elif arg == "--no-sandbox":
            no_sandbox = True
            i += 1
        elif arg == "--boundary":  # 互換 (今は標準と同じ意味)
            boundary = True
            i += 1
        elif arg == "--role":
            if i + 1 >= len(argv):
                fail("--role に役割の名前が要る", 2)
            role = argv[i + 1]
            i += 2
        elif arg == "--":
            i += 1
            break
        else:
            break
    if no_sandbox and boundary:
        fail("--no-sandbox と --boundary は同時に使えない", 2)
    return Options(bypass, not no_sandbox, role, argv[i:])


def agent_dir() -> Path:
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or HOME / ".pi/agent")


def check_installed() -> None:
    if not (pi.HARNESS / "index.ts").is_file() or not pi.RULES.is_file():
        fail(f"フルガードが無い ({pi.HARNESS})。chezmoi apply で配る")


def check_mcp_json(agent: Path) -> None:
    """``mcp.json`` のサーバはフルガードと関係なく繋がり、フルガードが抜けても判定なしで残る。"""
    path = agent / "mcp.json"
    if not path.is_file():
        return
    try:
        servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers")
    except (OSError, ValueError, AttributeError):
        servers = True  # 読めないなら止める側
    if servers:
        fail(f"{path} にサーバがある。MCP は common.toml の [[mcp]] (clis に pi) に書く")


def orca_args(agent: Path) -> list[str]:
    """Orca が置くステータス表示の拡張。Orca から起動したときに、Orca の印があるものだけ。"""
    ext = agent / "extensions" / "orca-agent-status.ts"
    if not os.environ.get("ORCA_AGENT_HOOK_PORT") or not ext.is_file():
        return []
    try:
        marked = ORCA_MARKER in ext.read_text(encoding="utf-8")
    except OSError:
        return []
    return ["-e", str(ext)] if marked else []


def environment(options: Options) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in INTERNAL_ENV}
    if options.role:
        env["PI_HARNESS_ROLE"] = options.role
    else:
        env.pop("PI_HARNESS_ROLE", None)
    env["PI_HARNESS_BYPASS"] = "1" if options.bypass else ""
    if not options.sandbox:
        env["PI_HARNESS_NO_SANDBOX"] = "1"  # フッターの表示用 (安全の根拠にはしない)
    return env


def plain_command(options: Options, agent: Path) -> list[str]:
    """素の起動の pi のコマンド。作業先の ``.pi/`` は読まず、拡張は明示したものだけ。"""
    return [
        "pi",
        *pi.BASE_FLAGS,
        *orca_args(agent),
        *pi.extension_args(agent),
        *pi.skill_args(),
        "-e",
        str(pi.HARNESS),
        *options.rest,
    ]


def main(argv: list[str] | None = None) -> int:
    options = parse(list(sys.argv[1:] if argv is None else argv))
    check_installed()
    agent = agent_dir()
    check_mcp_json(agent)
    env = environment(options)
    if options.sandbox:
        if sys.platform != "linux":
            fail(
                "この OS ではサンドボックスを張れないので起動しない。"
                "守りがフルガードだけでよければ pis --no-sandbox を使う"
            )
        os.environ.clear()
        os.environ.update(env)
        return pi.run_sandboxed(options.rest)
    print("pis: サンドボックス無しで起動する (守りはフルガードだけ)", file=sys.stderr)
    if shutil.which("pi", path=env.get("PATH")) is None:
        fail("pi が PATH に無い")
    command = plain_command(options, agent)
    os.execvpe(command[0], command, env)
    return 0  # execvpe は戻らない
