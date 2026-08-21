#!/usr/bin/env python3
"""Shell command normalization + policy matcher for AI CLI hooks.

Designed to back the hook layer of the permission system (Claude Code /
Copilot CLI). The CLI-side permission list is best-effort and has known bypass
bugs such as:

    cd /elsewhere && git push       # bypasses Bash(git push:*) ask/deny
    git -C /elsewhere commit ...    # bypasses Bash(git commit *) deny
    echo ok; rm -rf important       # second segment not evaluated separately

This module normalizes a raw bash command into a list of logical command
segments and checks each segment against the ``bash.deny`` / ``bash.ask``
patterns from ``common.toml``. The same lists drive both the generated
permission rules and the hook, so a rule only has to be written once.

Public API:
    load_deny(common_toml_path)             -> list[str]
    load_ask(common_toml_path)              -> list[str]
    normalize(command_str)                  -> list[str]
    find_match(command_str, patterns) -> str | None

The module is intentionally dependency-free (Python stdlib only) so it can
be imported from hooks running in minimal environments.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Iterable

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


# Common location for the source of truth managed by chezmoi.
# ``AGENTS_CONFIG_DIR`` can point at a different directory, which lets tests and
# containers exercise the hook against the repository copy instead of the
# deployed one.
def _default_config_dir() -> str:
    override = os.environ.get("AGENTS_CONFIG_DIR")
    if override:
        return override
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(config_home, "agents")


DEFAULT_COMMON_PATH = os.path.join(_default_config_dir(), "common.toml")


# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

def _load_bash_list(key: str, path: str) -> list[str]:
    """Return ``bash.<key>`` from common.toml, or an empty list if missing.

    Raises ``TypeError`` when the value is not a list of strings so that the
    hook can fail closed instead of silently matching nothing. A bare string
    would otherwise be split into characters by ``list()``.
    """
    p = Path(path)
    if not p.exists():
        return []
    with p.open("rb") as f:
        data = tomllib.load(f)
    bash = data.get("bash", {})
    if not isinstance(bash, dict):
        raise TypeError("[bash] セクションがテーブルではありません")
    value = bash.get(key, [])
    if not isinstance(value, list):
        raise TypeError(f"[bash] {key} がリストではありません: {type(value).__name__}")
    if not all(isinstance(v, str) for v in value):
        raise TypeError(f"[bash] {key} に文字列以外が含まれています")
    return list(value)


def load_deny(path: str = DEFAULT_COMMON_PATH) -> list[str]:
    """Return the ``bash.deny`` list, or an empty list if missing.

    Patterns here are hard-blocked by the hook: there is no way to approve them.
    """
    return _load_bash_list("deny", path)


def load_ask(path: str = DEFAULT_COMMON_PATH) -> list[str]:
    """Return the ``bash.ask`` list, or an empty list if missing.

    Patterns here make the hook return ``ask`` instead of ``deny``: the agent
    proposes the command, the user approves it, and the command then runs.
    ``deny`` is evaluated first, so a more specific deny pattern (for example
    ``git reset --hard``) can carve an exception out of a broader ask pattern
    (``git reset``).
    """
    return _load_bash_list("ask", path)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

# Compound operators that introduce a new logical command.
# `&` はバックグラウンド実行の区切り。`&&` を先に判定するため順序が重要。
_COMPOUND_OPS = ("&&", "||", ";;", ";", "|", "&", "\n")


def _split_compound(command: str) -> list[str]:
    """Split a shell string at compound operators outside of quotes.

    The split is intentionally conservative: it walks the string char by char,
    honoring single and double quotes and backslash escapes. It is not a full
    shell parser, but it is sufficient for the bypass patterns observed in
    Claude Code bugs (#59498, #20085 etc.).

    The original command is kept as the first element so that constructs which
    span the split points (here-strings containing newlines, function bodies,
    ``find -exec ... \\;``) can still be inspected as a whole by callers.
    """
    segments: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(command)
    in_single = False
    in_double = False
    while i < n:
        ch = command[i]
        if ch == "\\" and i + 1 < n and not in_single:
            buf.append(ch)
            buf.append(command[i + 1])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            matched_op = None
            for op in _COMPOUND_OPS:
                if command.startswith(op, i):
                    matched_op = op
                    break
            if matched_op:
                seg = "".join(buf).strip()
                if seg:
                    segments.append(seg)
                buf = []
                i += len(matched_op)
                continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        segments.append(tail)
    return segments


def _strip_cd_prefix(segment: str) -> str:
    """Strip a leading ``cd <path>`` (with optional &&) that prefixes a command.

    Examples:
        ``cd /foo && git push``    -> ``git push``
        ``cd ~/repo ; ls``         -> ``ls`` (caller already split at ``;``;
                                       this also covers the rare in-segment cd)
        ``cd /foo``                -> ``cd /foo`` (no command after, leave alone)
    """
    m = re.match(r"^\s*cd\s+\S+\s*(?:&&|;)\s*(.+)$", segment)
    if m:
        return m.group(1).strip()
    return segment


_GIT_C_RE = re.compile(r"^\s*git\s+(?:-C\s+\S+\s+)+(.+)$")


def _strip_git_dash_c(segment: str) -> str:
    """Strip ``git -C <path>`` and yield a bare ``git <subcommand>`` form.

    Examples:
        ``git -C /foo commit``                 -> ``git commit``
        ``git -C /foo -C /bar status``         -> ``git status``
    """
    m = _GIT_C_RE.match(segment)
    if m:
        return f"git {m.group(1).strip()}"
    return segment


_CD_ONLY_RE = re.compile(r"^\s*cd(\s+\S+)?\s*$")

# 先頭の環境変数代入 (FOO=1 BAR=2 cmd ...)
_ENV_ASSIGN_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|\S*)\s+)+(.+)$")

# 値をフラグ以外の位置引数として取るラッパー。
# 例: timeout 5 CMD / nice -n 5 CMD / stdbuf -oL CMD
# 数値やサイズ指定はコマンド名ではないので読み飛ばす。
_WRAPPER_POSITIONAL_ARG_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?[smhd]?$")

# コマンドをそのまま実行するラッパー。後続を評価対象に引き上げる。
# 値は「コマンド名までに読み飛ばすオプションの取り方」を表す:
#   "flags"      -> -x 形式のフラグを読み飛ばす
#   "flags+args" -> フラグとその引数 (-u user, -I{} 等) も読み飛ばす
#   "duration"   -> flags+args に加えて先頭の数値引数 (timeout 5) も読み飛ばす
_WRAPPERS: dict[str, str] = {
    "env": "flags",
    "command": "flags",
    "builtin": "flags",
    "exec": "flags",
    "nohup": "flags",
    "setsid": "flags",
    "stdbuf": "flags+args",
    "nice": "flags+args",
    "ionice": "flags+args",
    "timeout": "duration",
    "time": "flags",
    "xargs": "flags+args",
    "doas": "flags+args",
    "proot": "flags+args",
    # 実行環境を差し替えるもの
    "chroot": "flags+args",
    "unshare": "flags+args",
    "systemd-run": "flags+args",
    "runuser": "flags+args",
    "pkexec": "flags",
    "run0": "flags+args",
    "setpriv": "flags+args",
    "capsh": "flags+args",
    # 監視・計測・並列実行
    "watch": "flags+args",
    "strace": "flags+args",
    "ltrace": "flags+args",
    "perf": "flags+args",
    "valgrind": "flags+args",
    "parallel": "flags+args",
    "flock": "flags+args",
    "ssh-agent": "flags",
    "setarch": "flags+args",
    "taskset": "flags+args",
    "torify": "flags",
    "torsocks": "flags",
    # 別プロセスとして起動するもの
    "entr": "flags",
    "watchexec": "flags+args",
    # ツールランナー (`--` の後ろが実コマンドになる)
    "mise": "runner",
}

# `--` の後ろ、あるいは run/exec サブコマンドの後ろが実コマンドになるもの
_RUNNER_SUBCOMMANDS = {"exec", "run", "run-script", "x", "dlx"}

# 位置引数の中にコマンドが埋まっているもの。
# 値は「コマンドが始まる位置を探す方法」を表す。
_EMBEDDED_COMMAND_RULES: dict[str, str] = {
    "find": "after-exec",        # find . -exec CMD \;
    "screen": "after-flags",     # screen -dm CMD
    "tmux": "tmux",              # tmux new-session -d 'CMD'
    "at": "flags",               # at now <<< 'CMD'
}
# find の -exec / -execdir / -ok
_FIND_EXEC_FLAGS = {"-exec", "-execdir", "-ok", "-okdir"}

# シェルを起動して文字列を実行するもの。-c の引数を再帰的に評価する。
# script / su も -c で文字列を渡せるのでここに含める。
_SHELL_BINS = {
    "sh", "bash", "zsh", "dash", "ksh", "fish", "ash",
    "script", "su", "busybox",
}

# 文字列をそのままコードとして実行するもの
_EVAL_BINS = {"eval", "source", "."}
# 第 1 引数をコードとして登録するもの (`trap 'git push' EXIT`)
_TRAP_BINS = {"trap"}
# 変数でシェルを指す形 (`$SHELL -c '...'`)
_SHELL_VAR_RE = re.compile(r"^\$\{?(?:SHELL|BASH|ZSH)\}?$")

# サブコマンドの前に置けるグローバルオプション。
# `git --no-pager push` を `git push` として照合できるようにする。
_GLOBAL_OPTS: dict[str, str] = {
    # コマンド名 -> "flags" (値を取らない) / "flags+args" (別トークンの値を取る)
    "git": "flags+args",
    "docker": "flags+args",
    "gh": "flags+args",
    "npm": "flags+args",
    "uv": "flags+args",
    "cargo": "flags+args",
    "kubectl": "flags+args",
    "systemctl": "flags+args",
    "chezmoi": "flags+args",
}

# サブコマンドの別名。`git send-pack` は `git push` と同じ効果を持つ。
# 正規形に寄せてから照合することで、別名によるすり抜けを防ぐ。
_SUBCOMMAND_ALIASES: dict[tuple[str, str], str] = {
    ("git", "send-pack"): "push",
    ("npm", "i"): "install",
    ("npm", "rm"): "uninstall",
    ("npm", "un"): "uninstall",
    ("npm", "r"): "uninstall",
    ("docker", "container"): "container",
}

# `npm install -g` のように、後ろのフラグで意味が変わるもの。
# (コマンド名, サブコマンド, フラグ集合) -> 正規形
_FLAG_NORMALIZED: dict[tuple[str, str], tuple[set[str], str]] = {
    ("npm", "install"): ({"-g", "--global"}, "install -g"),
    ("npm", "uninstall"): ({"-g", "--global"}, "uninstall -g"),
}

# 文字列をコードとして受け取るインタプリタ。-c / -e の引数を再帰評価する。
_INTERPRETER_FLAGS: dict[str, tuple[str, ...]] = {
    "python": ("-c",),
    "perl": ("-e", "-E"),
    "ruby": ("-e",),
    "node": ("-e", "--eval", "-p", "--print"),
    "php": ("-r",),
    "deno": ("eval",),
}

# awk / gawk はプログラム本体が最初の非フラグ引数なので別扱いにする
_AWK_BINS = {"awk", "gawk", "mawk", "nawk"}
# awk のプログラム中から外部コマンドを起動する形
_AWK_SYSTEM_RE = re.compile(r'(?:system|print)\s*\(?\s*["\']?([^"\')]+)')

# グループ化・リダイレクトの飾りを落とすための文字
_GROUPING_PREFIX = "({"
_GROUPING_SUFFIX = ")}"

# 制御構文のキーワード。`if true; then git push; fi` の then 以降を露出させる。
# `case x in x) CMD;; esac` の `x)` のようなパターンラベルも落とす。
_CONTROL_KEYWORD_RE = re.compile(
    r"^(?:if|then|elif|else|fi|for|while|until|do|done|case|esac|select|"
    r"function|time|coproc|in)\b\s*"
)
# `case x in x) CMD` の `x in ` や `x)` のようなラベル。
# 通常のコマンドを削らないよう、`)` を含むラベルか `<語> in ` に限定する
_CASE_LABEL_RE = re.compile(r"^[^\s()]+\s+in\s+(?=[^\s()]*\))|^\(?[^\s()]+\)\s*")

# 先頭のリダイレクト (`> /dev/null git push` のような形)
_LEADING_REDIRECT_RE = re.compile(r"^\s*(?:[0-9]*[<>]{1,2}&?\s*\S+\s+)+(.+)$")

# コマンド置換 $(...) と `...`。ネストを 1 段扱えるようにする。
_CMD_SUBST_RE = re.compile(r"\$\(((?:[^()]|\([^()]*\))*)\)|`([^`]*)`")
# ANSI-C quoting $'...'
_ANSI_C_QUOTE_RE = re.compile(r"\$'([^']*)'")


def _basename(token: str) -> str:
    """``/usr/bin/git`` -> ``git``. パス指定でポリシーを回避させない。"""
    if "/" in token:
        return token.rsplit("/", 1)[-1]
    return token


def _strip_grouping(segment: str) -> str:
    """``(git push)`` や ``{ git push; }`` の飾りを落とす。

    ``if true; then X; fi`` のような制御構文のキーワードも取り除き、
    実際に走るコマンドを露出させる。
    """
    seg = segment.strip()
    changed = True
    while changed and seg:
        changed = False
        if seg[0] in _GROUPING_PREFIX:
            seg = seg[1:].strip()
            changed = True
        while seg and seg[-1] in _GROUPING_SUFFIX + ";&":
            seg = seg[:-1].strip()
            changed = True
        # 先頭の制御構文キーワードを剥がす (`then git push` -> `git push`)
        m = _CONTROL_KEYWORD_RE.match(seg)
        if m:
            seg = seg[m.end():].strip()
            changed = True
        # `case x in x) CMD` のラベル部分を剥がす。
        # 通常のコマンドを削らないよう、`) ` で終わるラベルか
        # `<語> in ` の形に限定する
        m = _CASE_LABEL_RE.match(seg)
        if m:
            seg = seg[m.end():].strip()
            changed = True
        # `! git push` の否定
        if seg.startswith("!"):
            seg = seg[1:].strip()
            changed = True
    return seg


def _strip_env_assignments(segment: str) -> str:
    """``GIT_DIR=/x git push`` -> ``git push``"""
    m = _ENV_ASSIGN_RE.match(segment.strip())
    if m:
        return m.group(1).strip()
    return segment


def _normalize_leading_path(segment: str) -> str:
    """``/usr/bin/git push`` -> ``git push``"""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    if not tokens:
        return segment
    head = _basename(tokens[0])
    if head == tokens[0]:
        return segment
    rest = segment.split(None, 1)
    return f"{head} {rest[1]}" if len(rest) > 1 else head


def _strip_leading_redirect(segment: str) -> str:
    """``> /dev/null git push`` -> ``git push``"""
    m = _LEADING_REDIRECT_RE.match(segment)
    if m:
        return m.group(1).strip()
    return segment


def _strip_global_options(segment: str) -> str:
    """``git --no-pager push`` -> ``git push``

    サブコマンドの前に置けるグローバルオプションを取り除き、
    ``git push`` として照合できるようにする。
    サブコマンドの別名 (``git send-pack`` -> ``git push``) や、
    後置フラグで意味が変わるもの (``npm install -g``) も正規形に寄せる。
    """
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return segment
    if len(tokens) < 2:
        return segment
    head = _basename(tokens[0])
    style = _GLOBAL_OPTS.get(head)
    if style is None:
        return segment

    i = 1
    global_flags: list[str] = []
    while i < len(tokens) and tokens[i].startswith("-"):
        token = tokens[i]
        if token == "--":
            i += 1
            break
        global_flags.append(token)
        # --git-dir=/x のように値が同じトークンなら 1 つ進める
        if "=" in token:
            i += 1
            continue
        # -c user.name=x のように値が別トークンのもの。
        # ただし後続がサブコマンドらしければ値ではない (`git -P push`)。
        if style == "flags+args" and len(token) == 2:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt is not None and _looks_like_option_value(nxt):
                global_flags.append(nxt)
                i += 2
                continue
        i += 1
    rest = tokens[i:]
    if not rest:
        return segment

    sub = rest[0]
    alias = _SUBCOMMAND_ALIASES.get((head, sub))
    if alias:
        sub = alias
        rest = [alias] + rest[1:]

    flag_rule = _FLAG_NORMALIZED.get((head, sub))
    if flag_rule:
        flags, canonical = flag_rule
        # `npm install -g x` と `npm -g install x` の両方を拾う
        tail_flags = [t for t in rest[1:] if t in flags]
        pre_flags = [t for t in global_flags if t in flags]
        if tail_flags or pre_flags:
            kept = [t for t in rest[1:] if t not in flags]
            return " ".join([head, canonical] + kept)

    return " ".join([head] + rest)


def _expand_interpreter_code(segment: str) -> list[str]:
    """``python3 -c "os.system('git push')"`` の中のコード片を返す。

    インタプリタに渡された文字列そのものを独立したコマンド候補として扱う。
    文字列の中身を厳密に解釈はできないが、``git push`` のような素の
    コマンド列が入っていれば照合できる。
    """
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return []
    if not tokens:
        return []
    head = re.sub(r"[0-9.]+$", "", _basename(tokens[0]))

    out: list[str] = []
    if head in _AWK_BINS:
        # awk 'BEGIN{system("git push")}' のようにプログラム本体から拾う
        for m in _AWK_SYSTEM_RE.finditer(segment):
            inner = m.group(1).strip()
            if inner:
                out.append(inner)
        return out

    flags = _INTERPRETER_FLAGS.get(head)
    if not flags:
        return []
    for i, token in enumerate(tokens[1:], start=1):
        if token in flags and i + 1 < len(tokens):
            code = tokens[i + 1]
            out.append(code)
            # os.system('git push') のように引用符の中にあるコマンドも拾う
            for m in re.finditer(r"""['"]([^'"]{3,})['"]""", code):
                inner = m.group(1).strip()
                if inner and " " in inner:
                    out.append(inner)
    return out


# here-string / here-doc でコードを渡す形 (`bash <<< "git push"`)
# 本体が改行を含むこともあるので DOTALL で末尾まで取る
_HERE_STRING_RE = re.compile(r"<<<\s*(.+)\Z", re.S)
# here-doc の本体を評価するためのパターン (`make -f /dev/stdin <<< '...'`)
_STDIN_SCRIPT_RE = re.compile(r"-f\s+(?:/dev/stdin|-)\b")
# プロセス置換 `<(...)` `>(...)`
_PROC_SUBST_RE = re.compile(r"[<>]\(([^()]*)\)")
# シェル関数定義 `f(){ git push; }` (後ろに呼び出しが続く形も許容)
_FUNC_DEF_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*\(\s*\)\s*\{(.*?)\}", re.S)
# alias 定義 `alias gp='git push'`
_ALIAS_DEF_RE = re.compile(
    r"alias\s+[A-Za-z_][A-Za-z0-9_]*=(?:'([^']*)'|\"([^\"]*)\"|(\S+))"
)
# 変数代入 `p=push` (後で `git $p` の展開に使う)
_VAR_ASSIGN_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=([^\s;&|]+)")
# 変数参照 `$p` / `${p}`
_VAR_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def _expand_indirect_code(segment: str, full_command: str = "") -> list[str]:
    """here-string / プロセス置換 / 関数定義 / alias 定義 / 変数展開の中身を返す。

    ``;`` による分割で定義が途中で切れることがあるため、関数・alias 定義は
    分割前の文字列 (``full_command``) からも探す。
    """
    out: list[str] = []
    sources = [segment]
    if full_command and full_command != segment:
        sources.append(full_command)

    for src in sources:
        m = _HERE_STRING_RE.search(src)
        if m:
            body = m.group(1).strip().strip("'\"")
            out.append(body)
            # `make -f /dev/stdin <<< 'all:\n\tgit push'` のように
            # here-doc 本体がスクリプトになる形は、行ごとにコマンド候補にする
            if _STDIN_SCRIPT_RE.search(src):
                for line in body.replace("\\n", "\n").replace("\\t", "\t").splitlines():
                    stripped = line.strip().lstrip("\t").strip()
                    if stripped and not stripped.endswith(":"):
                        out.append(stripped)

        for pm in _PROC_SUBST_RE.finditer(src):
            inner = pm.group(1).strip()
            if inner:
                out.append(inner)
                # `sh <(echo git push)` の echo の引数もコマンド候補にする
                out.extend(_echo_payloads(inner))

        for fm in _FUNC_DEF_RE.finditer(src):
            body = fm.group(1).strip().rstrip(";").strip()
            if body:
                out.append(body)

        for am in _ALIAS_DEF_RE.finditer(src):
            value = am.group(1) or am.group(2) or am.group(3) or ""
            value = value.strip()
            if value:
                out.append(value)

        for qm in _ANSI_C_QUOTE_RE.finditer(src):
            inner = qm.group(1).strip()
            if inner:
                out.append(inner)

    # `echo git push` を `$( )` 越しに実行する形
    # (素の `echo 'git push is denied'` は文字列表示なので対象にしない)

    # `p=push; git $p` のように同じコマンド列で定義された変数を展開する
    if full_command and _VAR_REF_RE.search(segment):
        assignments = dict(_VAR_ASSIGN_RE.findall(full_command))
        if assignments:
            def _sub(m: "re.Match[str]") -> str:
                return assignments.get(m.group(1), m.group(0))

            expanded = _VAR_REF_RE.sub(_sub, segment)
            if expanded != segment:
                out.append(expanded)

    return out


def _echo_payloads(segment: str) -> list[str]:
    """``$(echo git push)`` のように echo の出力をコマンドとして使う形を捕捉する。

    素の ``echo 'git push is denied'`` は単なる文字列表示なので対象外。
    呼び出し側がコマンド置換やプロセス置換の内側だと分かっている場合にのみ使う。
    """
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return []
    if len(tokens) < 2 or _basename(tokens[0]) not in ("echo", "printf"):
        return []
    args = [t for t in tokens[1:] if not t.startswith("-")]
    if not args:
        return []
    return [" ".join(args)]


def _expand_command_substitution(segment: str) -> list[str]:
    """``$(echo git) push`` の中身と、置換を除いた残りを評価対象として返す。

    置換部分が何を出力するかは静的には分からないので、
      * 中身そのもの (``echo $(git push)`` の ``git push`` を捕捉)
      * 置換を取り除いた残り (``$(echo git) push`` の ``push`` を捕捉)
    の両方を返す。後者だけでは `git push` にはならないが、置換で先頭コマンドを
    隠す形は「先頭トークンが不明」ということなので、残りを引数列として照合し、
    さらに置換の中身と連結した形も候補に加える。
    """
    found: list[str] = []
    inners: list[str] = []
    for m in _CMD_SUBST_RE.finditer(segment):
        inner = (m.group(1) or m.group(2) or "").strip()
        if inner:
            inners.append(inner)
            found.append(inner)
            # `$(echo git push)` は echo の引数がそのままコマンドになる
            found.extend(_echo_payloads(inner))
    if not inners:
        return found

    stripped = _CMD_SUBST_RE.sub(" ", segment).strip()
    stripped = " ".join(stripped.split())
    if stripped:
        found.append(stripped)
        # `$(echo git) push` -> 置換の出力が先頭コマンドになる想定で連結を試す。
        # 中身の最終トークン (echo の引数など) をコマンド名候補として使う。
        for inner in inners:
            inner_tokens = inner.split()
            if inner_tokens:
                found.append(f"{inner_tokens[-1]} {stripped}")
    return found


def _looks_like_option_value(token: str) -> bool:
    """``-f git`` の ``git`` のように、オプションの値ではなくコマンド名らしいかを見分ける。

    値らしい (= 読み飛ばしてよい) 場合に True。数値・パス・記号を含むものは値とみなす。
    素の英字トークンはコマンド名の可能性が高いので値とみなさない。
    """
    if token.startswith("-"):
        return False
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.+-]*", token):
        # 単純な識別子はコマンド名の可能性がある
        return False
    return True


def _looks_like_wrapper_operand(token: str) -> bool:
    """``flock <lockfile> CMD`` の lockfile のような位置引数か。

    パス・数値・記号を含むものだけを対象にし、素のコマンド名は食べない。
    """
    return _looks_like_option_value(token)


def _expand_embedded_commands(segment: str) -> list[str]:
    """``find . -exec git push \\;`` のように引数中に埋まったコマンドを返す。

    ``screen -dm CMD`` / ``tmux new-session -d 'CMD'`` /
    ``git submodule foreach 'CMD'`` / ``docker run IMAGE CMD`` も同様に扱う。
    """
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return []
    if not tokens:
        return []
    head = _basename(tokens[0])
    out: list[str] = []

    if head == "find":
        for i, token in enumerate(tokens):
            if token in _FIND_EXEC_FLAGS and i + 1 < len(tokens):
                rest = []
                for t in tokens[i + 1:]:
                    # shlex がエスケープを外すので `;` `\;` `+` のいずれも来る
                    if t in (";", "\\;", "+", "\\+", "\\"):
                        break
                    rest.append(t)
                if rest:
                    out.append(" ".join(rest))
        return out

    if head in ("screen", "tmux", "at", "batch", "entr", "watchexec"):
        # フラグとサブコマンドを読み飛ばし、残りをコマンドとみなす
        rest = [t for t in tokens[1:] if not t.startswith("-")]
        if head == "tmux" and rest and rest[0] in (
            "new-session", "new", "new-window", "neww", "send-keys", "run-shell", "run",
        ):
            rest = rest[1:]
        if rest:
            out.append(" ".join(rest))
        return out

    if head == "git" and len(tokens) >= 4 and tokens[1] == "submodule" and tokens[2] == "foreach":
        out.append(" ".join(tokens[3:]))
        return out

    if head == "docker" and len(tokens) >= 3 and tokens[1] in ("run", "exec"):
        # フラグとその値、イメージ名/コンテナ名を読み飛ばす
        i = 2
        while i < len(tokens) and tokens[i].startswith("-"):
            if "=" not in tokens[i] and len(tokens[i]) == 2 and i + 1 < len(tokens):
                i += 2
                continue
            i += 1
        i += 1  # イメージ名 / コンテナ名
        if i < len(tokens):
            out.append(" ".join(tokens[i:]))
        return out

    # `mise exec -- CMD` / `npm run x -- CMD` / `cargo run -- CMD` のように
    # `--` の後ろが実コマンドになるもの
    if "--" in tokens[1:]:
        idx = tokens.index("--", 1)
        rest = tokens[idx + 1:]
        if rest:
            out.append(" ".join(rest))

    # `uv run python -c "..."` のように run の後ろがそのままコマンドになるもの
    if head in ("uv", "mise", "npm", "pnpm", "yarn", "cargo", "go", "poetry", "rye") and len(tokens) >= 3:
        if tokens[1] in _RUNNER_SUBCOMMANDS:
            rest = [t for t in tokens[2:] if t != "--"]
            if rest:
                out.append(" ".join(rest))

    return out


def _strip_wrapper(segment: str) -> str:
    """``timeout 5 git push`` -> ``git push``、``env FOO=1 git push`` -> ``git push``"""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return segment
    if not tokens:
        return segment
    head = _basename(tokens[0])
    style = _WRAPPERS.get(head)
    if style is None:
        return segment

    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token == "--":
            i += 1
            break
        if token.startswith("-"):
            # -I{} や -u root のように値が別トークンのものを読み飛ばす。
            # ただし後続がコマンド名そのものなら値ではないので進めない
            # (`strace -f git push` の `git` を食べてしまわないように)。
            if style in ("flags+args", "duration") and "=" not in token and len(token) == 2:
                nxt = tokens[i + 1] if i + 1 < len(tokens) else None
                if nxt is not None and _looks_like_option_value(nxt):
                    i += 2
                    continue
            i += 1
            continue
        if style == "duration" and _WRAPPER_POSITIONAL_ARG_RE.match(token):
            # timeout 5 CMD / timeout 1.5s CMD
            i += 1
            continue
        if style == "flags+args" and _looks_like_wrapper_operand(token) and i + 1 < len(tokens):
            # flock <lockfile> CMD のように位置引数を取るもの
            i += 1
            continue
        if "=" in token and not token.startswith("/"):
            # env FOO=1 のような代入
            i += 1
            continue
        break
    rest = tokens[i:]
    if not rest:
        return segment
    return " ".join(shlex.quote(t) if " " in t else t for t in rest)


def _expand_shell_invocation(segment: str) -> list[str] | None:
    """``bash -c "git push"`` の中身を取り出す。対象外なら None。

    ``eval 'git push'`` のように文字列をコードとして実行するものも同様に扱う。
    """
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return None
    if not tokens:
        return None
    head = _basename(tokens[0])

    if head in _EVAL_BINS and len(tokens) > 1:
        return [" ".join(tokens[1:])]

    if head in _TRAP_BINS and len(tokens) > 1:
        # trap 'CMD' SIGNAL … の第 1 引数がコード
        return [tokens[1]]

    if head not in _SHELL_BINS and not _SHELL_VAR_RE.match(tokens[0]):
        return None
    for i, token in enumerate(tokens[1:], start=1):
        # -c / -lc / -xc のように c を含む短縮フラグ
        if token.startswith("-") and not token.startswith("--") and "c" in token:
            if i + 1 < len(tokens):
                # クォートが外れて複数トークンに割れている場合は繋ぎ直す
                return [" ".join(tokens[i + 1:])]
            return None
    return None


def _normalize_segment(segment: str) -> str:
    """先頭トークンを変える飾りを繰り返し剥がす。"""
    seg = segment
    for _ in range(8):  # apply transformations repeatedly until fixed
        new = _strip_grouping(seg)
        new = _strip_leading_redirect(new)
        new = _strip_cd_prefix(new)
        new = _strip_git_dash_c(new)
        new = _strip_env_assignments(new)
        new = _strip_wrapper(new)
        new = _normalize_leading_path(new)
        new = _strip_global_options(new)
        if new == seg:
            break
        seg = new
    return " ".join(seg.split())


# 展開の上限。病的な入力で処理時間が爆発しないように抑える
_MAX_SEGMENTS = 200
_MAX_EXPANSION_LEN = 4000


def normalize(command: str, _depth: int = 0) -> list[str]:
    """Return a list of normalized command segments suitable for matching.

    Compound operators (``&&``, ``||``, ``;``, ``|``, ``&`` and newlines) split
    the command into logical segments. Each segment is then stripped of anything
    that merely changes the leading token without changing what actually runs:

      * ``cd <path> && X``            -> ``X``
      * ``git -C <path> <sub>``       -> ``git <sub>``
      * ``(X)`` / ``{ X; }``          -> ``X``
      * ``> /dev/null X``             -> ``X``
      * ``FOO=1 X``                   -> ``X``
      * ``env`` / ``timeout`` / ``nohup`` / ``xargs`` などのラッパー -> 後続コマンド
      * ``/usr/bin/X``                -> ``X``
      * ``git --no-pager <sub>``      -> ``git <sub>`` (グローバルオプション)
      * ``bash -c "X"`` / ``eval "X"`` -> ``X`` を再帰的に評価
      * ``$(X)`` / ``` `X` ```        -> ``X`` も独立して評価

    Pure ``cd`` segments left over from compound splitting are dropped (they
    cannot match any deny pattern but would clutter the output).

    The shell wrapper itself is kept as a segment as well, so a rule targeting
    ``sh`` (for example ``curl x | sh``) still matches.
    """
    segments = _split_compound(command)
    if len(segments) > _MAX_SEGMENTS:
        # 病的に多い場合は先頭だけ見る (どのみち全部は検査しきれない)
        segments = segments[:_MAX_SEGMENTS]
    out: list[str] = []
    # 分割で壊れる構文 (改行を含む here-string、関数本体など) を拾うため、
    # 最上位では元の文字列も間接展開の入力に含める
    if (
        _depth == 0
        and command.strip()
        and len(command) <= _MAX_EXPANSION_LEN
        and command.strip() not in segments
    ):
        for inner in _expand_indirect_code(command, command):
            out.extend(normalize(inner, _depth + 1))
    for raw in segments:
        seg = _normalize_segment(raw)
        if seg and not _CD_ONLY_RE.match(seg):
            out.append(seg)
        if _depth >= 3 or len(raw) > _MAX_EXPANSION_LEN:
            continue
        # コマンド置換の中身は正規化前の文字列から拾う (クォートで消えるため)
        for inner in _expand_command_substitution(raw):
            out.extend(normalize(inner, _depth + 1))
        # here-string / プロセス置換 / 関数定義 / alias 定義 / 変数展開
        for inner in _expand_indirect_code(raw, command):
            out.extend(normalize(inner, _depth + 1))
        if seg:
            for chunk in _expand_shell_invocation(seg) or []:
                out.extend(normalize(chunk, _depth + 1))
            # python -c / perl -e などに渡されたコード片
            for chunk in _expand_interpreter_code(seg):
                out.extend(normalize(chunk, _depth + 1))
            # find -exec / screen -dm / docker run などに埋まったコマンド。
            # 正規化で末尾のエスケープが落ちることがあるので元の文字列も見る
            for source in (seg, raw):
                for chunk in _expand_embedded_commands(source):
                    out.extend(normalize(chunk, _depth + 1))
    return out


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _pattern_matches(segment: str, pattern: str) -> bool:
    """Return True if ``segment`` should be blocked by ``pattern``.

    Matching rules:
      * Pattern must appear as a contiguous run of whitespace-separated tokens
        at the start of the normalized segment. ``"git push"`` matches
        ``"git push origin main"`` but not ``"git push-fake"`` or
        ``"foo git push"``.
      * Single-token patterns (no spaces) match if the segment's first token
        equals the pattern OR if any subsequent token equals it after a path
        prefix (e.g. ``sudo`` matches ``/usr/bin/sudo`` is intentionally NOT
        supported -- patterns target logical command names).
    """
    try:
        seg_tokens = shlex.split(segment)
    except ValueError:
        seg_tokens = segment.split()
    pat_tokens = pattern.split()
    if not pat_tokens or not seg_tokens:
        return False
    if len(seg_tokens) < len(pat_tokens):
        return False
    return seg_tokens[: len(pat_tokens)] == pat_tokens


def find_match(command: str, patterns: Iterable[str]) -> str | None:
    """Return the first matching pattern, or None."""
    pats = list(patterns)
    if not pats:
        return None
    for segment in normalize(command):
        for pat in pats:
            if _pattern_matches(segment, pat):
                return pat
    return None


# ---------------------------------------------------------------------------
# CLI for quick inspection / hook integration
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", help="bash command string to check")
    parser.add_argument(
        "--common",
        default=DEFAULT_COMMON_PATH,
        help=f"path to common.toml (default: {DEFAULT_COMMON_PATH})",
    )
    args = parser.parse_args(argv)

    patterns = load_deny(args.common)
    match = find_match(args.command, patterns)
    if match is None:
        print("OK")
        return 0
    print(f"BLOCK: matched deny pattern '{match}'")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
