"""共通ユーティリティと、ルール全体で使う実行時の土台。

ここには「どのルールからも使える汎用処理」だけを置く。個々の判定は各ルール
モジュール (http.py / rm.py / rules_*.py など) にある。

- コマンド文字列の正規化・分割 (``_normalize`` / ``_segments``)
- パス判定のヘルパ (``_basename`` / ``_realpath_stays_inside``)
- ``command_policy`` (common.toml を読む層) への参照 ``_policy``
- PreToolUse payload の cwd (``payload_cwd`` / ``set_payload_cwd``)
"""
from __future__ import annotations

import os
import re
import sys
from functools import lru_cache

from . import tables

# ─── ポリシー層の読み込み ────────────────────────────────────────────
# ~/.config/agents/ (chezmoi 管理) にあるポリシーモジュールを import する。
# AGENTS_CONFIG_DIR で差し替え可能 (テスト・コンテナから repo の実体を指すため)
_AGENTS_DIR = os.environ.get("AGENTS_CONFIG_DIR")
if not _AGENTS_DIR:
    _CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    _AGENTS_DIR = os.path.join(_CONFIG_HOME, "agents")
sys.path.insert(0, _AGENTS_DIR)
_POLICY_IMPORT_ERROR: str | None = None
try:
    import command_policy as _policy
except Exception as _exc:  # pragma: no cover - 構文エラー等も拾う
    _policy = None  # type: ignore[assignment]
    _POLICY_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"


# ─── PreToolUse payload の cwd ───────────────────────────────────────
# workspace ルート。check_bash.py の main() が set_payload_cwd() で設定する。
# 別モジュールから読むため直接の変数参照ではなく関数経由にしている
# (``from ._shared import _PAYLOAD_CWD`` では代入前の None が固定されるため)。
_PAYLOAD_CWD: str | None = None


def set_payload_cwd(value: str | None) -> None:
    global _PAYLOAD_CWD
    _PAYLOAD_CWD = value


def payload_cwd() -> str | None:
    return _PAYLOAD_CWD


# PreToolUse payload の cwd (workspace ルート)。main() で設定する
_PAYLOAD_CWD: str | None = None


# ─── ポリシー呼び出しのキャッシュ ───────────────────────────────────
# hook は 1 プロセスにつき 1 コマンドしか検査せず、normalize もポリシー定義も
# 同じ入力なら同じ結果になる。キャッシュしないと 1 コマンドあたり normalize が
# 28 回、common.toml の tomllib パースが 4 回走る。
@lru_cache(maxsize=64)
def _normalize(command: str) -> tuple[str, ...]:
    if _policy is None:
        return ()
    return tuple(_policy.normalize(command))


_SENSITIVE_SUFFIXES = tables.as_tuple("_shared", "sensitive_suffixes")


def _looks_like_path(token: str) -> bool:
    """引数がパスらしいか。検索語や通常の単語を除外するための判定。"""
    if "/" in token or os.sep in token or token.startswith("~"):
        return True
    if token.startswith(".") and len(token) > 1:
        return True
    # foo.pem のように既知の拡張子を持つもの
    return token.lower().endswith(_SENSITIVE_SUFFIXES)


def _normalize_guard_path(token: str) -> str:
    """Keep native path semantics, but use slash-separated guard patterns."""
    expanded = token.strip("'\"").replace("~", os.path.expanduser("~"), 1)
    return os.path.normcase(os.path.normpath(expanded)).replace(os.sep, "/")


FILE_READ_COMMANDS = tables.as_list("_shared", "file_read_commands")


# 環境変数名としてセンシティブなもの。
# PAT / KEY / AUTH は単語として現れるときだけ拾う ($PATH や $MONKEY に当てない)。
_SENSITIVE_ENV_RE = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|PASSPHRASE|CREDENTIAL|SESSION"
    r"|API[_-]?KEY|PRIV(?:ATE)?[_-]?KEY|ACCESS[_-]?KEY"
    r"|(?:^|[_-])(?:PAT|KEY|AUTH)S?(?:[_-]|$))",
    re.IGNORECASE,
)


_WRITE_DEST_LAST_COMMANDS = tables.as_set("_shared", "write_dest_last_commands")


_WRITE_ALL_ARGS_COMMANDS = tables.as_set("_shared", "write_all_args_commands")


def _write_targets(cmd: str) -> list[str]:
    """コマンドが書き込み・変更しようとしているトークンを返す。"""
    targets: list[str] = []
    # `>| path` (noclobber 上書き) も拾う。`>&2` の fd 複製は対象外
    for m in re.finditer(r"[0-9]*>{1,2}\|?\s*([^\s&][^\s;&|)<>]*)", cmd):
        targets.append(m.group(1))
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        for token in tokens[1:]:
            if token.startswith("of="):
                targets.append(token[3:])
        args = [t for t in tokens[1:] if not t.startswith("-")]
        if not args:
            continue
        if head == "sed":
            # in-place 指定が無ければ読み取りのみ
            if any(t.startswith("-i") for t in tokens[1:]):
                targets.extend(args)
        elif head in _WRITE_DEST_LAST_COMMANDS:
            targets.append(args[-1])
        elif head in _WRITE_ALL_ARGS_COMMANDS:
            targets.extend(args)
    return targets


_CURL_FORM_FLAGS = tables.as_set("_shared", "curl_form_flags")


_CURL_UPLOAD_FLAGS = tables.as_set("_shared", "curl_upload_flags")


def _take_option_value(
    args: list[str], index: int, token: str, short: str | None, long: str
) -> tuple[str | None, int]:
    """Return an attached/separate option value and the next index."""
    if token.startswith(f"{long}="):
        return token[len(long) + 1:], index + 1
    if short and token.startswith(short) and token != short:
        return token[len(short):], index + 1
    if token == long or (short and token == short):
        if index + 1 >= len(args):
            return None, index + 1
        return args[index + 1], index + 2
    return None, index


def _payload_source(kind: str, value: str) -> str | None:
    """Extract a local file referenced by a curl/wget payload option."""
    if kind in _CURL_UPLOAD_FLAGS or kind in {"--post-file", "--body-file"}:
        return value
    if kind in _CURL_FORM_FLAGS:
        candidate = value.split("=", 1)[-1]
        if candidate.startswith(("@", "<")):
            return candidate[1:].split(";", 1)[0]
        return None
    if value.startswith("@"):
        return value[1:]
    if kind == "--data-urlencode" and "@" in value:
        return value.split("@", 1)[1]
    return None


def _option_value(token: str, short: str, long: str) -> str | None:
    """Return an attached option value, or None when the token does not match."""
    if token.startswith(f"{long}="):
        return token[len(long) + 1:]
    if token.startswith(short) and token != short:
        return token[len(short):]
    return None


@lru_cache(maxsize=64)
def _segments(cmd: str) -> tuple[str, ...]:
    """normalize 済みセグメント + 元の文字列を返す。

    normalize は shlex を通るのでクォートや ``${VAR}`` の形が変わる。
    パターン照合では元の文字列も併せて見て取りこぼさないようにする。
    """
    segs = list(_normalize(cmd)) if _policy is not None else []
    segs.append(cmd)
    return tuple(segs)


_FETCH_COMMAND_RE = re.compile(r"\b(?:curl|wget)\b")


_STDIN_CODE_SHELLS = tables.as_set("_shared", "stdin_code_shells")


_STDIN_CODE_INTERPRETERS = tables.as_set("_shared", "stdin_code_interpreters")


_INTERPRETER_CODE_ARG_FLAGS = tables.as_set("_shared", "interpreter_code_arg_flags")


_SHELL_CODE_ARG_FLAGS = tables.as_set("_shared", "shell_code_arg_flags")


def _cmd_name(token: str) -> str:
    """トークンからコマンド名を取り出す (`python3` -> `python`)。

    `.` (source の別名) は 1 文字なのでバージョン接尾辞の除去をしない。
    除去すると空文字になり `_STDIN_CODE_SHELLS` の `.` と一致しなくなる。
    """
    name = _basename(token.strip("'\""))
    if len(name) > 1:
        name = re.sub(r"[0-9.]+$", "", name)
    return name


_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


# 区切り子を引用した heredoc (`<<'PY'`) でインタプリタへ渡る本文。
# シェルが展開しないので、中の `$(...)` はコマンド置換ではなくリテラル。
# split_heredoc_body が記録し、check_pipe_to_shell が除外に使う。
_LITERAL_HEREDOC_BODIES: list[str] = []


_HEREDOC_SHELL_BINS = tables.as_set("_shared", "heredoc_shell_bins")


_HEREDOC_CODE_BINS = tables.as_set("_shared", "heredoc_code_bins")


def split_heredoc_body(cmd: str) -> str:
    """heredoc 本文のうち実行されない部分を取り除いた検査対象を返す。

    `cat <<'EOF' > note.md` の本文はファイルに書かれるだけでシェルには
    渡らない。これをコマンドとして照合すると、ドキュメントに書いた
    危険なコマンドの例示で誤検知する。本文が実行される形のときだけ残す。
    インタプリタに渡る本文は `-c` 形式に組み替えて、インラインコードの
    チェックが効くようにする。
    """
    lines = cmd.split("\n")
    kept: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        matches = _HEREDOC_RE.findall(line)
        i += 1
        if not matches:
            continue

        kind = None
        for token in line.split():
            head = re.sub(r"[0-9.]+$", "", _basename(token.strip("'\"()`;|&")))
            if head in _HEREDOC_SHELL_BINS:
                kind = "shell"
                break
            if head in _HEREDOC_CODE_BINS:
                kind = "code"
                break

        delimiters = {delim for _, delim in matches}
        # `<<'EOF'` / `<<"EOF"` のように区切り子を引用すると、シェルは
        # 本文中の `$(...)` や `` ` `` を展開しない
        quoted = any(quote for quote, _ in matches)
        body: list[str] = []
        while i < len(lines) and lines[i].strip() not in delimiters:
            body.append(lines[i])
            i += 1
        if i < len(lines):
            terminator = lines[i]
            i += 1
        else:
            terminator = None

        if kind == "shell":
            # `bash <<'EOF'` は本文を bash 自身が解釈するので、区切り子を
            # 引用していても `$(...)` は実行時に展開される
            kept.extend(body)
        elif kind == "code":
            code = " ".join(part.strip() for part in body)
            if quoted:
                # `python3 - <<'PY'` の本文はシェルが展開しない。
                # コード中の `$(...)` は文字列リテラルであって置換ではない
                _LITERAL_HEREDOC_BODIES.append(code)
            kept.append("python3 -c " + code)
        if terminator is not None:
            kept.append(terminator)
    return "\n".join(kept)


def expand_cd_targets(cmd: str) -> str:
    """`cd <dir> && <cmd> <relpath>` の相対パスを結合した変種を返す。

    `cd ~/.ssh && cat id_rsa` のように、作業ディレクトリを移してから
    相対パスで触ると、パス単体ではセンシティブ判定に掛からない。
    検査用に `cat ~/.ssh/id_rsa` 相当の文字列を組み立てて併せて見る。
    """
    variants: list[str] = []
    for chunk in re.split(r"\n+", cmd):
        parts = re.split(r"&&|\|\||;", chunk)
        cwd = None
        for part in parts:
            tokens = part.split()
            if not tokens:
                continue
            head = _basename(tokens[0])
            if head == "cd" and len(tokens) >= 2:
                cwd = tokens[1].strip("'\"")
                continue
            if cwd is None:
                continue
            rebuilt = [tokens[0]]
            for token in tokens[1:]:
                if token.startswith(("-", "/", "~", "$")):
                    rebuilt.append(token)
                else:
                    rebuilt.append(f"{cwd.rstrip('/')}/{token}")
            variants.append(" ".join(rebuilt))
    return "\n".join(variants)


_HOME_TOKENS = tables.as_set("_shared", "home_tokens")


def _basename(token: str) -> str:
    """``/bin/rm`` -> ``rm``"""
    return token.rsplit("/", 1)[-1] if "/" in token else token


def _canonical_rm_target(raw: str) -> str | None:
    """rm の引数を guard 比較用の正準形にする。

    末尾の ``/*`` と ``/`` を畳む (``/etc/*`` は ``/etc`` と同じ危険度)。
    """
    token = raw.strip().strip("'\"")
    if not token:
        return None
    while token.endswith("/*"):
        token = token[:-2] or "/"
    while len(token) > 1 and token.endswith("/"):
        token = token[:-1]
    return token or None


def _realpath_stays_inside(root: str, path: str) -> bool:
    """``path`` が realpath 解決後も ``root`` の内側に留まるか。

    途中の成分が symlink だと ``normpath`` の比較だけでは外へ抜ける
    (`.tmp/link/item` の `link` が外を指す形)。未作成のパスは realpath が
    素通しになるので、存在する範囲の解決結果で判定する。
    ``root`` 側も realpath に揃えるので、workspace 自体が symlink 配下に
    あっても誤判定しない。
    """
    real_root = os.path.realpath(root)
    real = os.path.realpath(path)
    return real == real_root or real.startswith(real_root + os.sep)


_SCRATCH_DIR_NAMES = tables.as_tuple("_shared", "scratch_dir_names")


def _workspace_root() -> str | None:
    """PreToolUse payload の ``cwd``。取れない・相対なら None (fail-closed)。"""
    workspace = _PAYLOAD_CWD
    if not workspace or not os.path.isabs(workspace):
        return None
    return os.path.normpath(workspace)


def _changes_base_dir(cmd: str) -> bool:
    """`cd` / `pushd` などで基点が変わるか。変わると相対パスを解決できない。"""
    return bool(
        re.search(r"""(?:^|[\s;&|("'\\])(?:cd|pushd|popd|chdir)(?![\w-])""", cmd)
    )


def _resolves_into_scratch(token: str, workspace: str) -> bool:
    """``token`` が ``<workspace>/.tmp`` 自身か、その配下に解決するか。

    ``_rm_is_workspace_local`` と違い絶対パスも受け付ける (解決先が scratch の
    内側だと確証できれば範囲は同じだけ狭いため)。展開・``..`` は解決できない
    ので拒否し、途中の symlink で外へ抜ける形は realpath で弾く。
    """
    canonical = _canonical_rm_target(token)
    if canonical is None:
        return False
    if any(ch in canonical for ch in "$`~{}"):
        return False
    components = [p for p in canonical.split("/") if p]
    if ".." in components:
        return False
    resolved = os.path.normpath(os.path.join(workspace, canonical))
    for name in _SCRATCH_DIR_NAMES:
        root = os.path.join(workspace, name)
        if resolved != root and not resolved.startswith(root + os.sep):
            continue
        # scratch ルート自体が外を指す symlink なら、配下はすべて workspace の
        # 外にある。root を基準に比べると内側と誤判定するので先に弾く
        if not _realpath_stays_inside(workspace, root):
            return False
        # `.tmp/link` が外を指す symlink なら realpath が scratch の外へ出る。
        # 未作成のパスは realpath が素通しになるので、そのまま内側と判定される
        if _realpath_stays_inside(root, resolved):
            return True
    return False


def _is_find_placeholder(token: str) -> bool:
    """`find -exec` の ``{}`` プレースホルダか。

    ``normalize()`` は shlex を通す過程で ``{}`` を ``{`` に削ることがあるので、
    波括弧だけで構成されたトークンをまとめて扱う。
    """
    return bool(token) and set(token) <= {"{", "}"}
