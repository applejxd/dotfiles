"""CLI に依存しない判定 API。pi のフルガードが呼ぶ。

``decide(request) -> response`` は allow / ask / deny と理由を必ず返し、どこで決まったか
(``source``) を添える。判定の中身は Claude / Copilot の hook と同じ ``bashrules`` と
``command_policy`` を使う。hook の出力は変えない (``check_bash.py`` はこのモジュールを使わない)。

see docs/spec/guard/pi-decide.md
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import tomllib
from pathlib import Path
from typing import Any

from policy_loader import load_policy

DECISIONS = ("allow", "ask", "deny")
# 判定器が扱うツール。フルガードは別名で登録しても、ここへは元の名前で渡す
FILE_READ_TOOLS = ("read", "grep", "find", "ls")
FILE_WRITE_TOOLS = ("edit", "write")
# 子エージェントの起動。子は同じフルガードと判定器で動くので、役割に入っていれば allow
TASK_TOOL = "task"
# 拡張 (extensions/todo) のタスクリスト。状態をメモリに持つだけで、ファイルも外部も触らない
TODO_TOOL = "todo"
# 拡張 (extensions/ask) の利用者への質問。UI だけを使い、ファイルも外部も触らない
ASK_TOOL = "ask"
# guarded_action (承認つきの操作)。確認はツール自身が 1 回だけ取るので、判定器は役割にあれば allow
ACTION_TOOL = "action"
KNOWN_TOOLS = (
    "bash",
    *FILE_READ_TOOLS,
    *FILE_WRITE_TOOLS,
    TASK_TOOL,
    TODO_TOOL,
    ASK_TOOL,
    ACTION_TOOL,
)
# 検査の上限。check_bash.py と同じ
MAX_COMMAND_LEN = 10000
# allow の一覧に当たっても、書き込みや実行時の展開の余地がある形は allow にしない
_UNSAFE_FOR_ALLOW = (">", "<", "`", "$", "--output")
# git が任意のプログラムを起動しうるオプション。allow の一覧に当たっても allow にしない
# グローバル (git とサブコマンドの間) の -c / --config-env / --exec-path / --paginate / -p が対象。サブコマンドの後ろの -p / -c は別の意味
_GIT_GLOBAL_ARG_OPTS = frozenset(
    (
        "-C",
        "-c",
        "--config-env",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--exec-path",
        "--super-prefix",
        "--attr-source",
    )
)
_GIT_SUB_EXEC_OPTS = (
    "--upload-pack",
    "--receive-pack",
    "--ext-diff",
    "--exec",
    "--textconv",
)


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
    for key in ("shell_allow", "shell_deny"):
        value = profile.get(key)
        if value is not None and (
            not isinstance(value, list) or not all(isinstance(c, str) for c in value)
        ):
            raise ValueError(f"[pi.profiles.{role}] {key} が文字列の配列ではありません")
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


def _guide(cmd: str, pi: dict[str, Any]) -> dict[str, Any] | None:
    """``[[pi.guide]]`` (誘導) に当たれば、案内を理由にした deny。bypass でも外れない。

    正規表現は Python と JavaScript で同じ意味になるものだけを書く約束
    (OpenCode の guide plugin と共有)。
    """
    for guide in pi.get("guide") or []:
        if guide.get(
            "scope"
        ):  # scope 付き (foreground) は judge/call.ts が guarded_bash だけに当てる。ここでは評価しない
            continue
        pattern, unless = guide.get("pattern"), guide.get("unless")
        if not isinstance(pattern, str) or not isinstance(guide.get("message"), str):
            raise ValueError(f"[[pi.guide]] {guide.get('id')!r} に pattern と message が要ります")
        if re.search(pattern, cmd) and not (unless and re.search(unless, cmd)):
            return _response("deny", guide["message"], "rule", guide=guide.get("id"))
    return None


def _action_tokens(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _action_flat(text: str) -> list[str]:
    return [p for t in _action_tokens(text) for p in re.split(r"[ \t\n]+", t) if p]


_ACTION_REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+")
_ACTION_INT_RE = re.compile(r"[0-9]+")
_ACTION_VALUE_FLAGS = frozenset(
    ("-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--title", "-m", "--message")
)
_ACTION_TYPE_RANK = {"repo": 0, "int": 1, "text": 2}
_ACTION_PLACEHOLDER_TEXT = {"body": "<本文>", "message": "<件名と本文>"}


def _action_repo_in(tokens: list[str]) -> str | None:
    for i, t in enumerate(tokens):
        value = None
        if t in ("-R", "--repo"):
            value = tokens[i + 1] if i + 1 < len(tokens) else None
        elif t.startswith("--repo="):
            value = t[len("--repo=") :]
        if value is not None and _ACTION_REPO_RE.fullmatch(value):
            return value
    return None


def _action_number_in(rest: list[str]) -> int | None:
    skip = False
    for t in rest:
        if skip:
            skip = False
        elif t in _ACTION_VALUE_FLAGS:
            skip = True
        elif t.startswith("-"):
            continue
        elif _ACTION_INT_RE.fullmatch(t) and 1 <= int(t) <= 1000000000:
            return int(t)
    return None


def _action_entries(pi: dict[str, Any]) -> list[tuple[str, list[str], list[tuple[str, str]]]]:
    """``[[pi.actions]]`` を (id, replaces, 型と名前順の fields) にする。形が壊れていれば ValueError。"""
    table = pi.get("actions")
    if table is None:
        return []
    if not isinstance(table, list):
        raise ValueError("[[pi.actions]] が配列ではありません")
    out = []
    for a in table:
        if not isinstance(a, dict) or not isinstance(a.get("id"), str):
            raise ValueError("[[pi.actions]] の項目に id (文字列) が要ります")
        replaces = a.get("replaces")
        if not isinstance(replaces, list) or not all(isinstance(r, str) for r in replaces):
            raise ValueError(f"[[pi.actions]] {a['id']!r} の replaces が文字列の配列ではありません")
        fields = a.get("fields")
        if not isinstance(fields, dict):
            raise ValueError(f"[[pi.actions]] {a['id']!r} の fields が表ではありません")
        pairs = [
            (k, str(v.get("type") if isinstance(v, dict) else None)) for k, v in fields.items()
        ]
        pairs.sort(key=lambda p: (_ACTION_TYPE_RANK.get(p[1], 9), p[0]))
        out.append((a["id"], list(replaces), pairs))
    return out


def _action_deny_reason(cmd: str, pi: dict[str, Any], policy: Any) -> str | None:
    """action ツールを持つ役割の bash が、操作表の ``replaces`` に当たれば deny の理由。

    judge/actions.ts と同じ文字列を返す (差分試験で確かめる)。候補の値はコマンドから確実に分かるものだけ。
    """
    entries = _action_entries(pi)
    if not entries:
        return None
    segments = policy.normalize(cmd)
    for aid, replaces, fields in entries:
        for segment in segments:
            pattern = next((p for p in replaces if policy._pattern_matches(segment, p)), None)
            if pattern is None:
                continue
            tokens = _action_flat(segment)
            repo = _action_repo_in(tokens)
            if repo is None:
                for raw in policy.split_command_segments(cmd):
                    raws = _action_flat(raw)
                    if not any(t == "gh" or t.endswith("/gh") for t in raws):
                        continue
                    repo = _action_repo_in(raws)
                    if repo is not None:
                        break
            number = _action_number_in(_action_tokens(segment)[len(pattern.split()) :])
            parts = []
            for name, kind in fields:
                key = json.dumps(name, ensure_ascii=False)
                if kind == "repo":
                    value = json.dumps(repo or "<owner/name>", ensure_ascii=False)
                elif kind == "int":
                    value = "<N>" if number is None else str(number)
                else:
                    placeholder = _ACTION_PLACEHOLDER_TEXT.get(name, f"<{name}>")
                    value = json.dumps(placeholder, ensure_ascii=False)
                parts.append(f"{key}:{value}")
            example = (
                f'{{"action":{json.dumps(aid, ensure_ascii=False)},"params":{{{",".join(parts)}}}}}'
            )
            return (
                "投稿・コミットは guarded_action で行う（承認はそのツールが 1 回だけ取る。"
                "事前に ask やチャットで承認を取らない）。"
                f"呼び出し例（値は候補。実際の値を確認する）: guarded_action {example}"
            )
    return None


def _has_git_exec_option(cmd: str, policy: Any) -> bool:
    """git のグローバル領域の実行系オプションと、サブコマンド以降の ``_GIT_SUB_EXEC_OPTS`` があるか。
    正規化は前置オプションを落とすので、元のトークンで見る。"""
    for raw in policy.split_command_segments(cmd):
        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = [raw]
        tokens = [p for t in tokens for p in re.split(r"[ \t\n]+", t) if p]
        git = next((i for i, t in enumerate(tokens) if t.rsplit("/", 1)[-1] == "git"), None)
        if git is None:
            continue
        i = git + 1
        while i < len(tokens) and tokens[i].startswith("-"):
            t = tokens[i]
            if t.startswith(("-c", "--config-env=", "--exec-path=")) or t in (
                "-p",
                "--paginate",
                "--config-env",
                "--exec-path",
            ):
                return True
            i += 2 if t in _GIT_GLOBAL_ARG_OPTS else 1
        if any(t == o or t.startswith(o + "=") for t in tokens[i:] for o in _GIT_SUB_EXEC_OPTS):
            return True
    return False


# 代入として渡してよい環境変数の名前 (LC_ で始まる名前も可)。これ以外の `NAME=` 形のトークンがあれば allow にしない
_SAFE_ENV_NAMES = frozenset(
    (
        "LANG",
        "LC_ALL",
        "TZ",
        "NO_COLOR",
        "COLUMNS",
        "LINES",
        "TERM",
        "CI",
        "FORCE_COLOR",
        "CLICOLOR",
        "PYTHONDONTWRITEBYTECODE",
    )
)


def _has_unsafe_env_prefix(cmd: str, policy: Any) -> bool:
    """元のコマンドのどこかに、安全な名前以外の ``NAME=`` 形のトークンか、``-`` 始まりの引数を持つ ``env`` があるか。
    shlex が失敗したら True。"""
    for raw in policy.split_command_segments(cmd):
        try:
            tokens = shlex.split(raw)
        except ValueError:
            return True
        tokens = [p.lstrip("({;!") for t in tokens for p in re.split(r"[ \t\n]+", t) if p]
        for i, t in enumerate(tokens):
            m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=", t)
            if m and m.group(1) not in _SAFE_ENV_NAMES and not m.group(1).startswith("LC_"):
                return True
            if (
                t.rsplit("/", 1)[-1] == "env"
                and i + 1 < len(tokens)
                and tokens[i + 1].startswith("-")
            ):
                return True
    return False


def _all_segments_allowed(cmd: str, patterns: list[str], policy: Any) -> str | None:
    """全セグメントが allow の一覧に当たれば、当たった最初のパターンを返す。"""
    if (
        not patterns
        or any(t in cmd for t in _UNSAFE_FOR_ALLOW)
        or _has_git_exec_option(cmd, policy)
        or _has_unsafe_env_prefix(cmd, policy)
    ):
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
    cmd: str, cwd: str, pi: dict[str, Any], profile: dict[str, Any], policy: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(共通の禁止, 役割の確認と許可) を返す。"""
    from bashrules import _shared
    from bashrules._shared import set_payload_cwd, split_heredoc_body
    from bashrules.policy import check_policy_loaded

    # hook は 1 コマンド 1 プロセスだが、decide() は同じプロセスで何度も呼ばれうる。
    # split_heredoc_body が積む「引用付き heredoc の本文」の記録を残すと、前の入力で
    # 後の入力の check_pipe_to_shell が見送られる (判定が呼び出しの順に依存する)
    _shared._LITERAL_HEREDOC_BODIES.clear()

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
    guide = _guide(cmd, pi)
    if guide:
        return None, guide
    # 役割に action ツールがあるときだけ: 操作表の replaces に当たるコマンドは guarded_action へ誘導 (bypass でも外れない)
    if ACTION_TOOL in profile["tools"]:
        action_reason = _action_deny_reason(cmd, pi, policy)
        if action_reason:
            return None, _response("deny", action_reason, "rule")
    # 役割だけの禁止。共通の禁止ではないが、bypass では外れない (bypass は ask だけを変える)
    role_deny = policy.find_match(cmd, [str(c) for c in profile.get("shell_deny") or []])
    if role_deny:
        return None, _response("deny", f"`{role_deny}` はこの役割の shell_deny にある", "rule")
    ask = _bash_ask(cmd)
    if ask:
        return None, ask
    # 役割が shell_allow を持てば、[pi.shell] allow の代わりにそれを使う
    own = profile.get("shell_allow")
    allow_list = own if own is not None else (pi.get("shell") or {}).get("allow") or []
    where = "役割の shell_allow" if own is not None else "[pi.shell] allow"
    matched = _all_segments_allowed(cmd, [str(p) for p in allow_list], policy)
    if matched:
        return None, _response("allow", f"`{matched}` は {where} にある", "rule")
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


def _tool_in(tool: str, tools: list[str]) -> bool:
    """役割の tools に入っているか。末尾が ``*`` の項目は前方一致 (``mcp__*`` など)。"""
    return any(tool.startswith(t[:-1]) if t.endswith("*") else tool == t for t in tools)


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
        common_deny, role_rule = _decide_bash(cmd, cwd, pi, profile, policy)
    elif tool in FILE_READ_TOOLS or tool in FILE_WRITE_TOOLS:
        path = tool_input.get("path", "." if tool in ("grep", "find", "ls") else None)
        if not isinstance(path, str) or not path:
            return _error(f"{tool} の path がありません")
        common_deny, role_rule = _decide_file(tool, path, cwd, pi, policy)
    elif tool == TASK_TOOL:
        reason = "子エージェントは同じハーネスと判定器で動く"
        common_deny, role_rule = None, _response("allow", reason, "rule")
    elif tool == TODO_TOOL:
        reason = "タスクリストはメモリの状態だけを変える"
        common_deny, role_rule = None, _response("allow", reason, "rule")
    elif tool == ASK_TOOL:
        reason = "利用者への質問は UI だけを使う (ファイルも外部も触らない)"
        common_deny, role_rule = None, _response("allow", reason, "rule")
    elif tool == ACTION_TOOL:
        reason = "guarded_action は確認を自分で 1 回だけ取る"
        common_deny, role_rule = None, _response("allow", reason, "rule")
    else:
        common_deny, role_rule = None, None
    if common_deny:
        return common_deny

    # 2. 役割のツール
    if not _tool_in(tool, profile["tools"]):
        return _response("deny", f"役割 {request['role']!r} は {tool} を使えない", "rule")

    # 3. 役割の確認と許可、4. 既定
    result = role_rule or _response(
        profile["default"], f"どの規則にも当たらない (役割 {request['role']!r} の既定)", "default"
    )

    # 5. bypass は ask だけを allow にする (deny はそのまま)
    if request.get("bypass") and result["decision"] == "ask":
        result = {**result, "decision": "allow", "bypassed": True}
    return result
