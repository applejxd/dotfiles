"""任意コード実行に繋がる形の検出。

``curl | sh`` / ``python -c`` / ``base64 -d | sh`` / リバースシェルなど、
「取得したものや文字列をそのまま実行する」パターンを扱う。
"""
from __future__ import annotations

import os
import re

from . import tables
from ._shared import (
    _FETCH_COMMAND_RE,
    _INTERPRETER_CODE_ARG_FLAGS,
    _LITERAL_HEREDOC_BODIES,
    _SENSITIVE_ENV_RE,
    _SHELL_CODE_ARG_FLAGS,
    _STDIN_CODE_INTERPRETERS,
    _STDIN_CODE_SHELLS,
    FILE_READ_COMMANDS,
    _basename,
    _cmd_name,
    _policy,
    _segments,
)
from .http import _fetched_output_paths
from .sensitive import is_sensitive_path

_INLINE_CODE_BINS = tables.as_set("rules_exec", "inline_code_bins")


_AWK_BINS = tables.as_set("rules_exec", "awk_bins")


_INLINE_CODE_FLAGS = tables.as_set("rules_exec", "inline_code_flags")


# コード片から外部コマンドを起動する形
_INLINE_EXEC_RE = re.compile(
    r"(?:os\.system|subprocess\.|popen|execSync|spawnSync|child_process|"
    r"\bsystem\s*\(|\bexec\s*\(|\bqx\s*[({/]|`[^`]+`|\bshell_exec\b|\bpassthru\b)",
    re.IGNORECASE,
)


# シェルの `$VAR` 展開を経由しない環境変数アクセス
_INLINE_ENV_READ_RE = re.compile(
    r"""os\.environ(?:\.get)?\s*[\[(]\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""
    r"""|process\.env\s*\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""
    r"""|process\.env\.([A-Za-z_][A-Za-z0-9_]*)"""
    r"""|\$ENV\{\s*['"]?([A-Za-z_][A-Za-z0-9_]*)['"]?\s*\}"""
    r"""|ENVIRON\s*\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""
    r"""|getenv\s*\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]""",
)


def check_xargs_pipe(cmd: str) -> str | None:
    """find | xargs cat/grep のような組み合わせを検出"""
    if "xargs" in cmd:
        for read_cmd in FILE_READ_COMMANDS:
            if re.search(rf"\bxargs\b.*\b{re.escape(read_cmd)}\b", cmd):
                matched = is_sensitive_path(cmd)
                if matched:
                    return (
                        f"xargs + `{read_cmd}` でセンシティブなパスを読み込もうとしています "
                        f"(パターン: {matched})"
                    )
    return None


_STDIN_CODE_FLAGS = tables.as_set("rules_exec", "stdin_code_flags")


_WRAPPER_VALUE_OPTS = tables.as_dict("rules_exec", "wrapper_value_opts")


_EXEC_WRAPPERS = set(_WRAPPER_VALUE_OPTS)


_WRAPPER_NUMERIC_ARG = tables.as_set("rules_exec", "wrapper_numeric_arg")


# コマンド置換そのものをコマンドとして起動する形 (`$(curl ...)` 単体)
_SUBST_HEAD_RE = re.compile(r"^[\"']?(?:\$\(|`)")


# プロセス置換 `<(...)` / `>(...)`
_PROC_SUBST_RE = re.compile(r"[<>]\(([^()]*(?:\([^()]*\)[^()]*)*)\)")


def _strip_exec_wrappers(
    tokens: list[str], *, keep: frozenset[str] = frozenset()
) -> list[str]:
    """`env` / `timeout 5` / `nohup` などのラッパーを剥がしたトークン列を返す。

    ``keep`` に挙げたラッパーは剥がさない。`xargs` は stdin の扱いそのものが
    判定材料なので、パイプ右辺では残す必要がある。
    """
    i = 0
    while i < len(tokens):
        name = _cmd_name(tokens[i])
        if name not in _EXEC_WRAPPERS or name in keep:
            break
        value_opts = _WRAPPER_VALUE_OPTS[name]
        numeric = name in _WRAPPER_NUMERIC_ARG
        i += 1
        while i < len(tokens):
            token = tokens[i]
            # `env -S "bash -s"` の値はコマンドラインそのもの。
            # 読み飛ばすと実行対象を見失うので、展開して解析を続ける
            split_string = None
            if token in {"-S", "--split-string"} and i + 1 < len(tokens):
                split_string = tokens[i + 1]
                rest = tokens[i + 2:]
            elif token.startswith("--split-string="):
                split_string = token.split("=", 1)[1]
                rest = tokens[i + 1:]
            elif token.startswith("-S") and len(token) > 2:
                split_string = token[2:]
                rest = tokens[i + 1:]
            if split_string is not None:
                return _strip_exec_wrappers(
                    split_string.strip("'\"").split() + rest, keep=keep
                )
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
                i += 1
                continue
            if token in value_opts:
                i += 2
                continue
            if token.startswith("-") and token != "-":
                i += 1
                continue
            if numeric and re.fullmatch(r"\d+(?:\.\d+)?[smhd]?", token):
                i += 1
                continue
            break
    return tokens[i:]


def _executable_head_tokens(part: str) -> list[str]:
    """パイプ右辺などから、実際に起動されるコマンドのトークン列を得る。"""
    tokens = [t.strip("'\"").strip("(){}") for t in part.strip().split()]
    return _strip_exec_wrappers(
        [t for t in tokens if t], keep=frozenset({"xargs"})
    )


def _reads_stdin_as_code(tokens: list[str]) -> bool:
    """このコマンドが標準入力をコードとして解釈するか。"""
    if not tokens:
        return False
    head = _cmd_name(tokens[0])
    if head == "sudo":
        return _reads_stdin_as_code(tokens[1:])
    if head == "xargs":
        # `curl ... | xargs -0 sh -c` のように、流れてきた内容がそのまま
        # コマンド文字列になる形を対象にする。
        # `find . | xargs node script.js` はスクリプトを渡しているので対象外。
        rest = tokens[1:]
        # `-I{}` は stdin の内容を後続の引数へ埋め込むので、引数の有無を
        # 問わずコードとして扱う
        replaces = any(
            token.startswith(("-I", "-i", "--replace")) for token in rest
        )
        for i, token in enumerate(rest):
            name = _cmd_name(token)
            if name in _STDIN_CODE_SHELLS or name in _STDIN_CODE_INTERPRETERS:
                if replaces:
                    return True
                after = rest[i + 1:]
                return not any(not a.startswith("-") for a in after)
        return False
    is_shell = head in _STDIN_CODE_SHELLS
    if not is_shell and head not in _STDIN_CODE_INTERPRETERS:
        return False
    args = tokens[1:]
    if is_shell and "-s" in args:
        # `bash -s` は引数があっても stdin をコードとして読む
        return True
    code_flags = _SHELL_CODE_ARG_FLAGS if is_shell else _INTERPRETER_CODE_ARG_FLAGS
    if any(arg in code_flags for arg in args):
        # `-c CODE` / `-m module` はそれ自体がコード。
        # 併記される `-` は入力データを指すのでコードではない
        return False
    if any(arg in _STDIN_CODE_FLAGS for arg in args):
        return True
    # スクリプトファイルを渡していれば stdin はデータ
    return not any(not arg.startswith("-") for arg in args)


def check_pipe_to_shell(cmd: str) -> str | None:
    """取得した内容をそのままコードとして実行していないか。

    パイプ (`curl ... | sh`) だけでなく、等価な以下の形も対象にする:

      * ``sh -c "$(curl ...)"`` / ``eval "$(curl ...)"``  コマンド置換
      * ``bash <(curl ...)``                              プロセス置換
      * ``curl ... -o f && sh f``                         保存してから実行

    逆に ``cat data.json | python3 -c '...'`` のように、インラインコードや
    スクリプトを持つインタプリタへ**データ**を流す形は対象外にする
    (コード自体は check_interpreter_inline_code が別途検査する)。
    """
    def _blocked(detail: str) -> str:
        return (
            f"取得した内容をそのままコードとして実行しようとしています ({detail})。\n"
            f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
            "内容を検証できないため許可されていません。\n"
            "一度ファイルに保存して内容を確認してから実行してください。"
        )

    # パイプの右辺が stdin をコードとして読む形。
    # `bash -c "curl ... | sh"` のように引用符の中にある形や、
    # `curl ... |\n bash` の行継続、`| env bash` のようなラッパーも拾う。
    joined = re.sub(r"\\\s*\n", " ", cmd)
    joined = re.sub(r"\|\s*\n\s*", "| ", joined)
    for chunk in re.split(r"[\n;]+", joined):
        parts = chunk.split("|")
        for part in parts[1:]:
            if _reads_stdin_as_code(_executable_head_tokens(part)):
                return _blocked("パイプ")

    if _policy is None:
        return None

    # コマンド置換・プロセス置換で取得したものを実行系に渡す形
    for segment in _policy.split_command_segments(cmd):
        bodies = list(_policy.extract_command_substitutions(segment))
        bodies.extend(m.group(1) for m in _PROC_SUBST_RE.finditer(segment))
        # 引用付き heredoc の本文はシェルが展開しないため置換ではない
        bodies = [
            body
            for body in bodies
            if not any(body in literal for literal in _LITERAL_HEREDOC_BODIES)
        ]
        if not any(_FETCH_COMMAND_RE.search(body) for body in bodies):
            continue
        tokens = segment.strip().split()
        if not tokens:
            continue
        if _SUBST_HEAD_RE.match(tokens[0]):
            return _blocked("コマンド置換・プロセス置換")
        # `env bash -c ...` / `timeout 5 sh -c ...` のようにラッパーで
        # 前置されても head を見失わないようにする
        stripped = _strip_exec_wrappers(tokens)
        if not stripped:
            continue
        head = _cmd_name(stripped[0])
        if head in _STDIN_CODE_SHELLS or head in _STDIN_CODE_INTERPRETERS:
            return _blocked("コマンド置換・プロセス置換")

    # 取得先へ保存したファイルを、同じコマンドの中で実行する形
    saved = _fetched_output_paths(cmd)
    if saved:
        def _is_saved(token: str) -> bool:
            cleaned = token.strip("'\"")
            return bool(cleaned) and (
                cleaned in saved or os.path.basename(cleaned) in saved
            )

        for segment in _segments(cmd):
            tokens = _strip_exec_wrappers(segment.split())
            if not tokens:
                continue
            # `./install.sh` のように保存したファイルを直接起動する形
            if _is_saved(tokens[0]):
                return _blocked("保存したファイルの実行")
            head = _cmd_name(tokens[0])
            if head not in _STDIN_CODE_SHELLS and head not in _STDIN_CODE_INTERPRETERS:
                continue
            # 最初の非オプション引数が実行されるスクリプト。
            # `python3 process.py data.csv` の data.csv では反応しない
            for token in tokens[1:]:
                if token.startswith("-"):
                    continue
                if _is_saved(token):
                    return _blocked("保存したファイルの実行")
                break
    return None


def _is_inline_code_segment(segment: str) -> bool:
    """このセグメントがインタプリタへコード文字列を渡す形かどうか。

    `python3 -c "..."` / `perl -e '...'` のほか、
    `uv run python -c ...` のようにランナー経由の形も拾う。
    """
    return _inline_code_head(segment) is not None


def _inline_code_head(segment: str) -> str | None:
    """インラインコードを実行するインタプリタ名を返す (無ければ None)。"""
    tokens = segment.split()
    for i, token in enumerate(tokens):
        candidate = _cmd_name(token)
        if candidate not in _INLINE_CODE_BINS:
            continue
        rest = tokens[i + 1:]
        if any(t in _INLINE_CODE_FLAGS for t in rest):
            return candidate
        # awk 系はプログラムを位置引数で受け取る (`-f` はファイル指定)
        if (
            candidate in _AWK_BINS
            and not any(t == "-f" or t.startswith(("-f", "--file")) for t in rest)
            and any(not t.startswith("-") for t in rest)
        ):
            return candidate
        return None
    return None


def check_interpreter_inline_code(cmd: str) -> str | None:
    """`python3 -c "..."` / `perl -e "..."` の中でセンシティブな操作をしていないか。

    normalize は素のコマンド列 (`os.system('git push')` の中身など) を
    取り出せないことがあるため、コード文字列そのものを検査する。
    `uv run python -c ...` のようにランナー経由でも効くよう、元の文字列全体も見る。
    """
    for segment in _segments(cmd):
        head = _inline_code_head(segment)
        if head is None:
            continue
        # コード片にセンシティブなパスや外部実行が含まれていないか
        reason = is_sensitive_path(segment)
        if reason:
            return (
                f"`{head}` のインラインコードがセンシティブなパスを参照しています ({reason})。"
            )
        if _INLINE_EXEC_RE.search(segment):
            return (
                f"`{head}` のインラインコードから外部コマンドを実行しようとしています。\n"
                f"実行しようとしているコマンド: {segment.strip()[:200]}\n"
                "スクリプトファイルに書いて内容を確認できる形にしてください。"
            )
        # `os.environ['GITHUB_TOKEN']` のように、シェルの `$VAR` 展開を
        # 経由しない環境変数アクセス
        for m in _INLINE_ENV_READ_RE.finditer(segment):
            name = next((g for g in m.groups() if g), None)
            if name and _SENSITIVE_ENV_RE.search(name):
                return (
                    f"`{head}` のインラインコードがセンシティブな環境変数 "
                    f"`{name}` を読み出そうとしています。"
                )
    return None


def check_reverse_shell(cmd: str) -> str | None:
    """リバースシェル・待ち受けソケットの形を検出する。

    `/dev/tcp` は bash 組み込みなので外部コマンドの照合では捕まらない。
    `nc` などは疎通確認に使うため、実行系・待ち受け系フラグのときだけ止める。
    """
    m = re.search(r"/dev/(?:tcp|udp)/[^/\s]+/\d+", cmd)
    if m:
        return (
            f"`{m.group(0)}` へのシェルリダイレクトはリバースシェルの形です。\n"
            "外部への接続を伴うシェル実行は許可されていません。"
        )

    listeners = {"nc", "netcat", "ncat", "socat", "telnet"}
    exec_flags = ("-e", "-c", "--exec", "--sh-exec", "--lua-exec")
    listen_flags = ("-l", "-lp", "-lvp", "--listen", "-L")
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head not in listeners:
            continue
        for token in tokens[1:]:
            if token in exec_flags or token.startswith("EXEC:"):
                return (
                    f"`{head} {token}` はコマンドを外部接続に紐付ける形です。\n"
                    "リバースシェルに繋がるため許可されていません。"
                )
            if token in listen_flags:
                return (
                    f"`{head} {token}` は待ち受けソケットを開く形です。\n"
                    "外部からの侵入経路になるため許可されていません。"
                )
    return None


def check_encoded_command(cmd: str) -> str | None:
    """デコード結果をそのままシェルへ流す形を検出する。

    `base64 -d | sh` のように、正規化では中身を判定できない経路を塞ぐ。
    """
    decoders = r"(?:base64\s+(?:-d|--decode|-D)|xxd\s+-r|uudecode|openssl\s+enc\s+-d)"
    shells = r"(?:ba|z|k|da)?sh\b|python3?\b|perl\b|ruby\b|node\b"
    if re.search(rf"{decoders}[^|]*\|\s*(?:{shells})", cmd):
        return (
            "デコード結果を直接シェルに渡そうとしています。\n"
            "内容を検査できないため許可されていません。"
            "デコード結果をファイルに書き出して確認してから実行してください。"
        )
    if re.search(r"printf\s+['\"][^'\"]*\\x[0-9a-fA-F]{2}[^'\"]*['\"]\s*\|\s*"
                 rf"(?:{shells})", cmd):
        return (
            "エスケープ列で組み立てたコマンドをシェルに渡そうとしています。\n"
            "内容を検査できないため許可されていません。"
        )
    return None
