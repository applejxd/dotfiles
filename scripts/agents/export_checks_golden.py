"""bashrules (bash 検査の各関数) の正解データを書き出す。

``export_policy_golden.py`` は正規化・照合までの部品を残す。ここでは、その上に載る層
(``bashrules/`` の約 3,900 行) を、食い違ったときに原因の関数を特定できる粒度で残す:

- ``heredoc``: ``split_heredoc_body`` の出力と、記録された引用付き heredoc の本文
- ``expand_cd``: ``expand_cd_targets``
- ``commands``: ``_commands`` (正規化したセグメントを ``shellparse.parse`` した結果)
- ``write_targets``: ``_write_targets``
- ``check``: ``DENY_CHECKS`` / ``ASK_CHECKS`` / ``PATH_CHECKS`` の各関数の戻り値 (理由の文字列)。
  ``None`` は書かない (大半が None)。PATH_CHECKS は ``cd`` 展開した形にも掛ける (``name@cd``)。
  例外は ``{"error": "<型名>"}`` で残す (decide() は例外を deny にする)

入力は ``export_policy_golden.corpus()`` と同じ。1 コマンドごとに状態を初期化し、``decide()`` と
同じ前処理 (``set_payload_cwd`` → ``split_heredoc_body``) の後で各関数を呼ぶ。
workspace のパスは ``${ROOT}`` に置き換える。

使い方::

    uv run --no-project --with pytest,pyyaml python scripts/agents/export_checks_golden.py
    uv run --no-project --with pytest,pyyaml python scripts/agents/export_checks_golden.py --check

``golden/tables.json`` (``tables.toml`` の JSON 版。TS 版が読む) も書く。

see docs/spec/pi-decide.md#ts-版への移植
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "test" / "agents" / "golden"
OUT = GOLDEN / "checks_golden.jsonl"
TABLES_OUT = GOLDEN / "tables.json"

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import export_policy_golden as base  # noqa: E402  (先に環境を整える)
from bashrules import ASK_CHECKS, DENY_CHECKS, PATH_CHECKS, _shared  # noqa: E402
from bashrules.policy import check_policy_loaded  # noqa: E402

PLACEHOLDER = "${ROOT}"


def _checks() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for check in [*DENY_CHECKS, *ASK_CHECKS, *PATH_CHECKS]:
        if check is check_policy_loaded:  # 環境の確認で、コマンドに依らない
            continue
        out.setdefault(check.__name__, check)
    return out


def _mask(value: Any) -> Any:
    """workspace の実パスを ``${ROOT}`` に置き換える (環境に依らない正解データにする)。"""
    if isinstance(value, str):
        return value.replace(str(ROOT), PLACEHOLDER)
    if isinstance(value, list):
        return [_mask(v) for v in value]
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    return value


def _call(fn: Any, arg: str) -> Any:
    try:
        return {"ok": fn(arg)}
    except Exception as exc:
        return {"error": type(exc).__name__}


def _command_json(command: Any) -> dict[str, Any]:
    return {
        "words": [[w.raw, w.value] for w in command.words],
        "redirects": [
            [r.fd, r.op, None if r.target is None else [r.target.raw, r.target.value]]
            for r in command.redirects
        ],
    }


def build() -> list[str]:
    checks = _checks()
    path_names = {c.__name__ for c in PATH_CHECKS}
    entries: list[dict[str, Any]] = []
    for command in base.corpus():
        _shared._LITERAL_HEREDOC_BODIES.clear()
        _shared.set_payload_cwd(str(ROOT))
        try:
            text = _shared.split_heredoc_body(command)
        except Exception:
            text = command  # decide() は例外を飲み込んで元の文字列で続ける
        entries.append(
            {
                "fn": "heredoc",
                "arg": command,
                "out": text,
                "literal": list(_shared._LITERAL_HEREDOC_BODIES),
            }
        )
        cd_variant = ""
        with contextlib.suppress(Exception):
            cd_variant = _shared.expand_cd_targets(text)
        entries.append({"fn": "expand_cd", "arg": text, "out": cd_variant})
        res = _call(lambda a: [_command_json(c) for c in _shared._commands(a)], text)
        entries.append({"fn": "commands", "arg": text, **res})
        entries.append({"fn": "write_targets", "arg": text, **_call(_shared._write_targets, text)})
        for name, check in checks.items():
            res = _call(check, text)
            if res.get("ok") is not None:
                entries.append({"fn": "check", "name": name, "arg": text, **res})
            if name in path_names and cd_variant:
                res = _call(check, cd_variant)
                if res.get("ok") is not None:
                    entries.append({"fn": "check", "name": f"{name}@cd", "arg": cd_variant, **res})
    return [json.dumps(_mask(e), ensure_ascii=False, sort_keys=True) for e in entries]


def tables_json() -> str:
    path = ROOT / "home" / "dot_claude" / "hooks" / "lib" / "bashrules" / "tables.toml"
    with path.open("rb") as f:
        data = tomllib.load(f)
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="書き出さず、いまのファイルが最新か確かめる"
    )
    args = parser.parse_args()
    lines = build()
    text = "\n".join(lines) + "\n"
    tables = tables_json()
    if args.check:
        stale = [
            p
            for p, t in ((OUT, text), (TABLES_OUT, tables))
            if (p.read_text(encoding="utf-8") if p.is_file() else "") != t
        ]
        for p in stale:
            print(f"古い: {p.relative_to(ROOT)} (引数なしで書き出し直す)")
        if not stale:
            print(f"最新: {len(lines)} 件")
        return 1 if stale else 0
    GOLDEN.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    TABLES_OUT.write_text(tables, encoding="utf-8", newline="\n")
    print(f"{len(lines)} 件を書き出した: {OUT.relative_to(ROOT)} ({len(text) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
