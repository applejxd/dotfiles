#!/usr/bin/env python3
"""stock の pi の MCP 設定を、宣言 (pi-mcp-servers.toml) から生成する。

Usage:
    generate.py --target pi-mcp --common PATH [--existing PATH]
    generate.py --target pi-mcp-adapter --common PATH [--existing PATH]

--existing を省くと標準入力を読む。更新後の JSON を標準出力へ出す。
利用者が ``pi mcp add`` や ``/mcp`` で足したサーバ・キーは保つ。
仕組みは docs/spec/mcp-servers.md が正本。
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError as exc:  # Python 3.10 以下には tomllib が無い
    raise SystemExit(
        "pi の MCP 設定の生成には Python 3.11 以上が必要です"
        f" (実行中: {platform.python_version()} / {sys.executable})。"
        " chezmoi の [interpreters.py] が古い python を指していると起きます。"
        " `chezmoi init` で設定を作り直すか、3.11 以上を導入してください。"
        " see docs/spec/troubleshooting.md"
    ) from exc

# ---------------------------------------------------------------------------
# MCP サーバ ([[mcp]] -> pi の mcp.json)
# ---------------------------------------------------------------------------

# 生成物の mcp.json のキー (TOML のテーブル名として使えない文字を弾く)
MCP_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
# transport ごとの必須キー。両方の形のキーを持つ定義は生成先で曖昧になるので、
# ここに無いキーは (typo も含めて) 弾く。
MCP_TRANSPORT_KEYS = {
    "http": {"url"},
    "stdio": {"command", "args"},
}
MCP_COMMON_KEYS = {"id", "purpose", "transport", "requires_env", "pi_exposure"}
# pi_exposure: mcp.json の server の exposure に、無いときだけ補う値 (merge_pi_mcp)。
# pi 組み込みの MCP の既定は codemode で、モデルに直接見えない。
MCP_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
MCP_EXPOSURES = ("direct", "codemode", "deferred", "hidden")


def mcp_servers(common: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """``[[mcp]]`` を (名前, 定義) の宣言順リストにして返す。

    ユーザ・OS による出し分けは pi-mcp-servers.toml 側の chezmoi テンプレートが
    済ませているので、ここには条件が無い (展開後の表だけを見る)。
    設定ミスは、黙って無効な定義を書き出すより apply を止める。
    """
    servers: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for server in common.get("mcp", []):
        name = server.get("id", "")
        if not name or set(name) - MCP_ID_CHARS:
            raise ValueError(
                f"[[mcp]] の id が不正: {name!r} (英数字・ハイフン・アンダースコアのみ)"
            )
        if name in seen:
            raise ValueError(f"[[mcp]] の id が重複している: {name}")
        seen.add(name)

        transport = server.get("transport")
        if transport not in MCP_TRANSPORT_KEYS:
            raise ValueError(
                f"[[mcp]] {name} の transport が未対応: {transport!r} "
                f"(対応: {', '.join(sorted(MCP_TRANSPORT_KEYS))})"
            )
        unknown = set(server) - MCP_COMMON_KEYS - MCP_TRANSPORT_KEYS[transport]
        if unknown:
            raise ValueError(
                f"[[mcp]] {name} に {transport} では使わないキーがある: "
                + ", ".join(sorted(unknown))
            )

        pi_exposure = server.get("pi_exposure")
        if pi_exposure is not None and pi_exposure not in MCP_EXPOSURES:
            raise ValueError(
                f"[[mcp]] {name} の pi_exposure が不正: {pi_exposure!r} "
                f"(対応: {', '.join(MCP_EXPOSURES)})"
            )
        required = server.get("requires_env")
        if required is not None and (
            not isinstance(required, str) or MCP_ENV_NAME.fullmatch(required) is None
        ):
            raise ValueError(f"[[mcp]] {name} の requires_env は大文字の環境変数名: {required!r}")

        entry: dict[str, Any] = {"transport": transport}
        if transport == "http":
            url = server.get("url")
            if not url:
                raise ValueError(f"[[mcp]] {name} に url が無い")
            entry["url"] = url
        else:
            command = server.get("command")
            if not command:
                raise ValueError(f"[[mcp]] {name} に command が無い")
            args = server.get("args", [])
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError(f"[[mcp]] {name} の args は文字列のリストで書く")
            entry["command"] = command
            entry["args"] = list(args)

        if pi_exposure is not None:
            entry["pi_exposure"] = pi_exposure
        servers.append((name, entry))
    return servers


def merge_pi_mcp(
    existing: dict[str, Any], common: dict[str, Any], *, with_exposure: bool = True
) -> dict[str, Any]:
    """``~/.pi/agent/mcp.json`` の ``mcpServers`` を更新する。

    ``pi mcp add`` や ``/mcp`` も書き込むので、宣言した名前だけを更新し、
    ほかのサーバは残す。宣言したサーバでも ``command`` / ``args`` だけを持ち、
    ``env`` / ``enabled`` / ``exposure`` / ``timeout`` など利用者が足したキーは保つ
    (宣言が持たない情報)。``[[mcp]]`` の ``requires_env`` は pi 本体の MCP が解釈しないので出さない。
    ``pi_exposure`` があれば server の ``exposure`` に無いときだけ補う。
    http は ``url``、stdio は ``command`` / ``args``。
    """
    out = dict(existing) if isinstance(existing, dict) else {}
    servers = dict(out.get("mcpServers") or {})
    for name, server in mcp_servers(common):
        entry = dict(servers.get(name) or {})
        if server["transport"] == "http":
            entry["url"] = server["url"]
            stale = ("command", "args")
        else:
            entry["command"] = server["command"]
            entry["args"] = server["args"]
            stale = ("url", "headers")
        for key in stale:
            entry.pop(key, None)
        if with_exposure and "pi_exposure" in server:
            # 利用者が /mcp で変えた値を保つ (無いときだけ補う)
            entry.setdefault("exposure", server["pi_exposure"])
        servers[name] = entry
    out["mcpServers"] = servers
    return out


def merge_pi_mcp_adapter(existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    """``~/.pi/agent/mcp-adapter.json`` の ``mcpServers`` を更新する (pi-mcp-adapter を入れた機だけ)。

    pi-subagents は、adapter が入っているとき、子の ``mcp:`` 指定を adapter の設定ファイル
    (``mcp-adapter.json`` など。``~/.pi/agent/mcp.json`` は読まない) から解決する。
    ``mcp.json`` と同じサーバをここにも置いて、子が検索の MCP を使えるようにする。
    ``exposure`` は pi 組み込みの MCP の概念なので出さない。
    """
    return merge_pi_mcp(existing, common, with_exposure=False)


TARGETS = {
    "pi-mcp": merge_pi_mcp,
    "pi-mcp-adapter": merge_pi_mcp_adapter,
}


def load_common(path: str) -> dict[str, Any]:
    with open(path, "rb") as f:
        return tomllib.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=sorted(TARGETS))
    parser.add_argument("--common", required=True, help="path to pi-mcp-servers.toml (rendered)")
    parser.add_argument(
        "--existing",
        default=None,
        help="path to existing JSON (defaults to stdin)",
    )
    args = parser.parse_args(argv)

    common = load_common(args.common)
    # 利用者も書くファイル。壊れていたら触らずそのまま返す (apply を止めず、利用者が直す)
    raw = (
        sys.stdin.read()
        if args.existing in (None, "-")
        else Path(args.existing).read_text(encoding="utf-8")
    )
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict):
        sys.stdout.write(raw)
        return 0

    merged = TARGETS[args.target](parsed, common)
    json.dump(merged, sys.stdout, indent=2, ensure_ascii=False, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
