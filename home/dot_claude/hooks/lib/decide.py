"""CLI に依存しない判定 API。pi のハーネスが呼ぶ。

``decide(request) -> response`` は allow / ask / deny と理由を必ず返し、どこで決まったか
(``source``) を添える。判定の中身は Claude / Copilot の hook と同じ ``bashrules`` と
``command_policy`` を使う。hook の出力は変えない (``check_bash.py`` はこのモジュールを使わない)。

see docs/spec/pi-decide.md
"""

from __future__ import annotations

import contextlib
import os
import shlex
import tomllib
from pathlib import Path
from typing import Any

from policy_loader import load_policy

DECISIONS = ("allow", "ask", "deny")
# 判定器が扱うツール。ハーネスは別名で登録しても、ここへは元の名前で渡す
FILE_READ_TOOLS = ("read", "grep", "find", "ls")
FILE_WRITE_TOOLS = ("edit", "write")
KNOWN_TOOLS = ("bash", *FILE_READ_TOOLS, *FILE_WRITE_TOOLS)
# 検査の上限。check_bash.py と同じ
MAX_COMMAND_LEN = 10000
# allow の一覧に当たっても、書き込みや実行時の展開の余地がある形は allow にしない
_UNSAFE_FOR_ALLOW = (">", "<", "`", "$(", "--output")


def _response(decision: str, reason: str, source: str, **extra: Any) -> dict[str, Any]:
    return {"decision": decision, "reason": reason, "source": source, **extra}


def _error(reason: str) -> dict[str, Any]:
    return _response("deny", reason, "error")


def _load_pi(path: str) -> dict[str, Any]:
    with open(path, "rb") as f:
        pi = tomllib.load(f).get("pi")
    if not isinstance(pi, dict):
        raise ValueError("[pi] がありません")
    return pi


def _profile(pi: dict[str, Any], role: str) -> dict[str, Any]:
    profiles = pi.get("profiles")
    profile = profiles.get(role) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        raise ValueError(f"役割 {role!r} が [pi.profiles] にありません")
    tools = profile.get("tools")
    default = profile.get("default")
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise ValueError(f"[pi.profiles.{role}] tools が文字列の配列ではありません")
    if default not in DECISIONS:
        raise ValueError(f"[pi.profiles.{role}] default が allow / ask / deny ではありません")
    return profile


# ─── bash ───────────────────────────────────────────────────────────


def _bash_common_deny(cmd: str) -> dict[str, Any] | None:
    """check_bash.py の deny 側と同じ順で検査する。当たれば deny の応答。"""
    from bashrules import DENY_CHECKS, PATH_CHECKS
    from bashrules._shared import expand_cd_targets
    from bashrules.policy import check_policy_deny

    for check in DENY_CHECKS:
        reason = check(cmd)
        if reason:
            source = "rule" if check is check_policy_deny else "check"
            return _response("deny", reason, source, check=check.__name__)
    cd_variant = ""
    with contextlib.suppress(Exception):
        cd_variant = expand_cd_targets(cmd)
    if cd_variant:
        for check in PATH_CHECKS:
            reason = check(cd_variant)
            if reason:
                return _response("deny", reason, "check", check=check.__name__)
    return None


def _bash_ask(cmd: str) -> dict[str, Any] | None:
    from bashrules import ASK_CHECKS
    from bashrules.policy import check_policy_ask

    for check in ASK_CHECKS:
        reason = check(cmd)
        if reason:
            source = "rule" if check is check_policy_ask else "check"
            return _response("ask", reason, source, check=check.__name__)
    return None


def _all_segments_allowed(cmd: str, patterns: list[str], policy: Any) -> str | None:
    """全セグメントが allow の一覧に当たれば、当たった最初のパターンを返す。"""
    if not patterns or any(t in cmd for t in _UNSAFE_FOR_ALLOW):
        return None
    segments = policy.normalize(cmd)
    if not segments:
        return None
    first = None
    for segment in segments:
        matched = policy.find_match(segment, patterns)
        if not matched:
            return None
        first = first or matched
    return first


def _skill_script_allowed(cmd: str, pi: dict[str, Any]) -> str | None:
    """``[pi.skill_scripts]`` の形に完全に当たれば、そのスクリプトを返す。

    generate.py の OpenCode の規則と同じ範囲: ``exact`` は引数ごと完全一致、
    ``subcommands`` はその先頭だけ、どちらも無ければ任意の引数。リダイレクトは不可。
    """
    if any(t in cmd for t in _UNSAFE_FOR_ALLOW) or any(t in cmd for t in (";", "&", "|", "\n")):
        return None
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return None
    cfg = pi.get("skill_scripts") or {}
    runners = cfg.get("runners") or {}
    for entry in cfg.get("allow") or []:
        script = str(entry.get("script", ""))
        suffix = script.rsplit(".", 1)[-1] if "." in script else ""
        paths = {script, os.path.expanduser(script)}
        for runner in runners.get(suffix) or []:
            if len(tokens) < 2 or tokens[0] != runner or tokens[1] not in paths:
                continue
            rest = tokens[2:]
            exact = entry.get("exact") or []
            subcommands = entry.get("subcommands") or []
            if exact:
                if rest == list(exact):
                    return script
            elif subcommands:
                if rest and rest[0] in subcommands:
                    return script
            else:
                return script
    return None


def _decide_bash(
    cmd: str, cwd: str, pi: dict[str, Any], policy: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(共通の禁止, 役割の確認と許可) を返す。"""
    from bashrules._shared import set_payload_cwd, split_heredoc_body
    from bashrules.policy import check_policy_loaded

    loaded = check_policy_loaded(cmd)
    if loaded:
        return _error(loaded), None
    if len(cmd) > MAX_COMMAND_LEN:
        return _error(f"コマンドが長すぎます ({len(cmd)} 文字)"), None
    set_payload_cwd(cwd)
    with contextlib.suppress(Exception):
        cmd = split_heredoc_body(cmd)
    deny = _bash_common_deny(cmd)
    if deny:
        return deny, None
    ask = _bash_ask(cmd)
    if ask:
        return None, ask
    allow_list = [str(p) for p in ((pi.get("shell") or {}).get("allow") or [])]
    matched = _all_segments_allowed(cmd, allow_list, policy)
    if matched:
        return None, _response("allow", f"`{matched}` は [pi.shell] allow にある", "rule")
    script = _skill_script_allowed(cmd, pi)
    if script:
        return None, _response("allow", f"`{script}` は [pi.skill_scripts] にある", "rule")
    return None, None


# ─── ファイル ───────────────────────────────────────────────────────


def _candidates(path: str, cwd: str) -> list[str]:
    """照合に使うパスの形: 渡されたまま・cwd で解いた絶対パス・symlink を解いた実体。"""
    expanded = os.path.expanduser(path)
    absolute = os.path.normpath(os.path.join(cwd, expanded))
    out = [path, absolute]
    with contextlib.suppress(OSError):
        out.append(os.path.realpath(absolute))
    return list(dict.fromkeys(out))


def _inside(path: str, root: str) -> bool:
    root = os.path.normpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _decide_file(
    tool: str, path: str, cwd: str, pi: dict[str, Any], policy: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    write = tool in FILE_WRITE_TOOLS
    key = "write_deny_globs" if write else "read_deny_globs"
    globs = policy.load_file_globs(key)
    if not globs:
        return _error(f"[file] {key} がありません"), None
    exceptions = policy.load_read_deny_exceptions()
    candidates = _candidates(path, cwd)
    # ディレクトリを渡す grep / find / ls は、中のファイルの形でも見る (.ssh -> .ssh/x)
    if tool in ("grep", "find", "ls"):
        candidates += [c.rstrip("/") + "/_" for c in candidates]
    for candidate in candidates:
        matched = policy.matches_read_deny(candidate, globs, exceptions)
        if matched:
            reason = f"`{path}` は [file] {key} の `{matched}` に当たる"
            return _response("deny", reason, "rule"), None

    absolute = _candidates(path, cwd)[-1]
    inside_cwd = _inside(absolute, os.path.realpath(cwd))
    if write:
        ask_globs = policy.load_file_globs("write_ask_globs")
        matched = policy.matches_any_glob(path, ask_globs) or policy.matches_any_glob(
            absolute, ask_globs
        )
        if matched:
            reason = f"`{path}` は [file] write_ask_globs の `{matched}` に当たる"
            return None, _response("ask", reason, "rule")
        if not inside_cwd:
            return None, _response("ask", f"`{path}` は作業ツリーの外への書き込み", "rule")
        return None, _response("allow", "作業ツリーの中への書き込み", "rule")

    ask_globs = policy.load_file_globs("read_ask_globs")
    matched = policy.matches_any_glob(path, ask_globs) or policy.matches_any_glob(
        absolute, ask_globs
    )
    if matched:
        reason = f"`{path}` は [file] read_ask_globs の `{matched}` に当たる"
        return None, _response("ask", reason, "rule")
    if inside_cwd:
        return None, _response("allow", "作業ツリーの中の読み取り", "rule")
    opened = [
        os.path.realpath(os.path.expanduser(str(d)))
        for d in ((pi.get("external_read") or {}).get("paths") or [])
    ]
    if any(_inside(absolute, d) for d in opened):
        return None, _response("allow", "[pi.external_read] で開けた場所の読み取り", "rule")
    return None, _response("ask", f"`{path}` は作業ツリーの外の読み取り", "rule")


# ─── 入口 ───────────────────────────────────────────────────────────


def _validate(request: Any) -> str | None:
    if not isinstance(request, dict):
        return "request がオブジェクトではありません"
    if not isinstance(request.get("tool"), str):
        return "tool が文字列ではありません"
    if not isinstance(request.get("input"), dict):
        return "input がオブジェクトではありません"
    cwd = request.get("cwd")
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        return "cwd が絶対パスではありません"
    if not isinstance(request.get("role"), str):
        return "role が文字列ではありません"
    for key in ("bypass", "boundary"):
        if not isinstance(request.get(key, False), bool):
            return f"{key} が真偽値ではありません"
    return None


def decide(request: Any) -> dict[str, Any]:
    """判定する。例外は投げず、異常はすべて ``source: error`` の deny にする。"""
    try:
        return _decide(request)
    except Exception as exc:  # 判定できない以上、安全側へ
        return _error(f"判定に失敗しました ({type(exc).__name__}: {exc})")


def _decide(request: Any) -> dict[str, Any]:
    invalid = _validate(request)
    if invalid:
        return _error(invalid)
    tool: str = request["tool"]
    tool_input: dict[str, Any] = request["input"]
    cwd: str = request["cwd"]

    imported = load_policy()
    if imported.module is None:
        return _error(f"command_policy.py を読み込めません: {imported.error}")
    policy = imported.module
    common_path = policy.default_common_path()
    if not Path(common_path).is_file():
        return _error(f"ポリシー定義が見つかりません ({common_path})")
    pi = _load_pi(common_path)
    profile = _profile(pi, request["role"])

    # 1. 共通の禁止と、2〜3 の材料
    if tool == "bash":
        cmd = tool_input.get("command")
        if not isinstance(cmd, str) or not cmd:
            return _error("bash の command がありません")
        common_deny, role_rule = _decide_bash(cmd, cwd, pi, policy)
    elif tool in FILE_READ_TOOLS or tool in FILE_WRITE_TOOLS:
        path = tool_input.get("path", "." if tool in ("grep", "find", "ls") else None)
        if not isinstance(path, str) or not path:
            return _error(f"{tool} の path がありません")
        common_deny, role_rule = _decide_file(tool, path, cwd, pi, policy)
    else:
        common_deny, role_rule = None, None
    if common_deny:
        return common_deny

    # 2. 役割のツール
    if tool not in profile["tools"]:
        return _response("deny", f"役割 {request['role']!r} は {tool} を使えない", "rule")

    # 3. 役割の確認と許可、4. 既定
    result = role_rule or _response(
        profile["default"], f"どの規則にも当たらない (役割 {request['role']!r} の既定)", "default"
    )

    # 5. bypass は ask だけを allow にする (deny はそのまま)
    if request.get("bypass") and result["decision"] == "ask":
        result = {**result, "decision": "allow", "bypassed": True}
    return result
