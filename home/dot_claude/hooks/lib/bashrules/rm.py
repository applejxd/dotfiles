"""削除 (rm / find -delete) の判定。

壊滅的な対象 (ルート・ホーム・workspace 全体・.git 配下) は deny、workspace
内と確証できるものは承認を省く。その「確証できるか」の判定が中心。
"""
from __future__ import annotations

import fnmatch
import os
import re

from . import tables
from ._shared import (
    _HOME_TOKENS,
    _basename,
    _canonical_rm_target,
    _changes_base_dir,
    _is_find_placeholder,
    _normalize,
    _policy,
    _realpath_stays_inside,
    _resolves_into_scratch,
    _segments,
    _workspace_root,
    payload_cwd,
)
from .rules_exec import _strip_exec_wrappers

_FIND_DANGEROUS_EXEC_RE = re.compile(
    r"\bfind\b.+?"
    r"(?:"
    r"-exec\s+(?:rm|unlink|shred|rmdir)\b"  # -exec rm/unlink/shred/rmdir
    r"|-delete\b"                            # -delete フラグ
    r")",
    re.IGNORECASE | re.DOTALL,
)


def check_find_dangerous(cmd: str) -> str | None:
    """`find -exec rm` や `find -delete` でファイルを削除しようとしていないか。

    削除対象がホームやシステム全体なら承認の余地なく deny する。
    """
    if not re.search(r"\bfind\b", cmd):
        return None
    if not _FIND_DANGEROUS_EXEC_RE.search(cmd):
        return None
    # 探索起点が使い捨ての一時ディレクトリ配下だけなら承認を省く
    if _find_targets_scratch_only(cmd):
        return None
    # find の探索起点が壊滅的なら deny (check_rm_root_guard 相当の扱い)
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens or _basename(tokens[0]) != "find":
            continue
        for token in tokens[1:]:
            if token.startswith("-"):
                break
            if _is_catastrophic_rm_target(token):
                return None  # deny 側で処理する
    return (
        "`find` コマンドによるファイル削除操作（-exec rm / -delete 等）です。\n"
        f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
        "削除対象を確認して問題なければ承認してください。"
    )


def check_find_root_guard(cmd: str) -> str | None:
    """`find ~ -delete` のように壊滅的な範囲を一括削除していないか。"""
    if not _FIND_DANGEROUS_EXEC_RE.search(cmd):
        return None
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens or _basename(tokens[0]) != "find":
            continue
        for token in tokens[1:]:
            if token.startswith("-"):
                break
            if _is_catastrophic_rm_target(token):
                return (
                    f"`find` が壊滅的なパス `{token}` を起点に削除しようとしています。\n"
                    "システム全体・ホーム・親ディレクトリの一括削除は承認の対象外です。"
                )
    return None


def _rm_ask_hint(cmd: str) -> str:
    """`rm` が ask になったとき、承認不要な書き方を示すヒント。

    免除は静的に読める形にしか効かない (`cd` / 変数展開 / `xargs` は不可)。
    エージェントは止められた時点でこの文面を読むので、常時読み込まれる指示に
    同じことを書くより確実で、コンテキストも消費しない。
    """
    if ".tmp" not in cmd:
        return ""
    return (
        "\n代替: 対象が ./.tmp 配下なら `rm -rf .tmp/<名前>` の形で書けば承認は"
        "不要です。\n"
        "`cd`・変数展開 (`$PWD` など)・`xargs` と混ぜると対象を静的に確認できず、"
        "承認が必要になります。"
    )


_CATASTROPHIC_DIRS = tables.as_set("rm", "catastrophic_dirs")


_WORKSPACE_ROOT_TOKENS = tables.as_set("rm", "workspace_root_tokens")


# /home/<user> や /Users/<user> のようなホームディレクトリそのもの
_HOME_DIR_RE = re.compile(r"^/(?:home|Users)/[^/]+$")


_RM_BIN_RE = re.compile(r"^(?:/\S*/)?(?:rm|rmdir|unlink)$")


def _is_catastrophic_rm_target(token: str) -> bool:
    canonical = _canonical_rm_target(token)
    if canonical is None:
        return False
    if canonical in _HOME_TOKENS or canonical == "..":
        return True
    if canonical in _CATASTROPHIC_DIRS:
        return True
    if _HOME_DIR_RE.match(canonical):
        return True
    if canonical == os.path.expanduser("~"):
        return True
    # `.git` は自身だけでなく配下も対象にする。
    # `.git/objects` や `.git/refs` を消せばリポジトリは復旧できない。
    # `.g*t` のようにドット始まりの glob で届く形も含める
    # (`build/*` の `*` まで拾わないよう、パターン側がドット始まりのときだけ)
    parts = [p for p in canonical.split("/") if p]
    for part in parts:
        if part == ".git":
            return True
        if part.startswith(".") and fnmatch.fnmatch(".git", part):
            return True
        # ブレース展開の候補に `.git` が含まれる形
        if "{" in part and ".git" in re.split(r"[{},]", part):
            return True
    # `~/.ssh` のような秘密領域そのものの削除も承認の対象外
    base = os.path.basename(canonical)
    if base in {".ssh", ".gnupg", ".aws", ".config", ".local"}:
        return True
    # `$PWD/../..` のように相対で上位へ抜ける形。
    # 実際の解決先は分からないので、`..` が 2 段以上あれば壊滅的とみなす。
    return canonical.count("..") >= 2


def _rm_is_workspace_local(cmd: str) -> bool:
    """`rm` の対象がすべて workspace 内だと確証できるか。

    確証できるときだけ承認を省いて auto / assisted の判定へ委ねる。
    次のいずれかに当たれば False を返し、従来どおり承認を求める:

      * workspace の位置が分からない (payload に ``cwd`` が無い)
      * `cd` で基点が変わる (normalize は `cd` を畳むので元の文字列で見る)
      * 変数展開・コマンド置換・ホーム参照を含む
      * 絶対パス、`..` を含むパス、glob だけのトークン
      * 解決先が workspace の外 (symlink で抜ける形も realpath で弾く)
    """
    workspace = payload_cwd()
    if not workspace or not os.path.isabs(workspace):
        return False
    workspace = os.path.normpath(workspace)
    if _policy is None:
        return False
    # 基点を変えるもの (`cd` / `pushd` / `popd` / `chdir`) が含まれたら判定しない。
    # `bash -c "cd /x && rm -rf y"` や `\cd`、`cd$IFS/x` も取りこぼさないよう、
    # コマンド文字列全体を単語境界で見る
    if re.search(r"""(?:^|[\s;&|("'\\])(?:cd|pushd|popd|chdir)(?![\w-])""", cmd):
        return False
    # 対象が標準入力から来る形は静的に読めない
    if re.search(r"(?:^|[\s;&|(])xargs(?![\w-])", cmd):
        return False

    saw_target = False
    for segment in _segments(cmd):
        tokens = _strip_exec_wrappers(segment.strip().split())
        if not tokens or not _RM_BIN_RE.match(_basename(tokens[0].strip("'\""))):
            continue
        targets = [t for t in tokens[1:] if not t.startswith("-")]
        if not targets:
            return False
        for raw in targets:
            token = raw.strip("'\"")
            if not token:
                return False
            # 展開・ブレース展開は静的に解決できない
            if any(ch in token for ch in "$`~{}"):
                return False
            if token.startswith("/"):
                return False
            components = [p for p in token.split("/") if p]
            if ".." in components:
                return False
            # `.g*t` のように glob がドットディレクトリへ届く形は読めない
            if any(
                c.startswith(".") and any(g in c for g in "*?[")
                for c in components
            ):
                return False
            # `*` だけのようなトークンは範囲が読めない
            if not re.search(r"[^*?/.\[\]]", token):
                return False
            resolved = os.path.normpath(os.path.join(workspace, token))
            if resolved != workspace and not resolved.startswith(workspace + os.sep):
                return False
            # 成分に symlink があると normpath だけでは外へ抜ける。
            # 絶対パス指定は scratch 免除が realpath で弾いているので、
            # 相対パスのこちら側も同じ基準に揃える
            if not _realpath_stays_inside(workspace, resolved):
                return False
            saw_target = True
    return saw_target


_FIND_EXEC_FLAGS = tables.as_set("rm", "find_exec_flags")


def _rm_targets_scratch_only(cmd: str) -> bool:
    """`rm` の対象がすべて scratch ディレクトリ配下だと確証できるか。"""
    workspace = _workspace_root()
    if workspace is None or _policy is None:
        return False
    if _changes_base_dir(cmd):
        return False
    if re.search(r"(?:^|[\s;&|(])xargs(?![\w-])", cmd):
        return False

    saw_target = False
    find_scratch_only: bool | None = None
    for segment in _segments(cmd):
        tokens = _strip_exec_wrappers(segment.strip().split())
        if not tokens or not _RM_BIN_RE.match(_basename(tokens[0].strip("'\""))):
            continue
        targets = [t for t in tokens[1:] if not t.startswith("-")]
        if not targets:
            return False
        # `find ... -exec rm {} +` 展開形の終端記号は削除対象ではない
        if any(_is_find_placeholder(t.strip("'\"")) for t in targets):
            targets = [t for t in targets if t.strip("'\"") not in ("+", ";", "\\;")]
        for raw in targets:
            token = raw.strip("'\"")
            if _is_find_placeholder(token):
                # `find ./.tmp -exec rm {} +` を normalize が `rm {}` に展開した形。
                # 実際の対象は find の探索起点なので、そちらで判定する
                if find_scratch_only is None:
                    find_scratch_only = _find_targets_scratch_only(cmd)
                if not find_scratch_only:
                    return False
                saw_target = True
                continue
            if not _resolves_into_scratch(token, workspace):
                return False
            saw_target = True
    return saw_target


def _find_targets_scratch_only(cmd: str) -> bool:
    """`find` の探索起点がすべて scratch 配下で、削除先も広がらないか。

    `-exec` に渡す引数が ``{}`` 以外のパスを含む形 (`-exec rm /etc/x {} +`) は
    探索起点の外を消せるので免除しない。
    """
    workspace = _workspace_root()
    if workspace is None:
        return False
    if _changes_base_dir(cmd):
        return False
    if re.search(r"(?:^|[\s;&|(])xargs(?![\w-])", cmd):
        return False

    saw_root = False
    for segment in _segments(cmd):
        tokens = segment.strip().split()
        if not tokens or _basename(tokens[0].strip("'\"")) != "find":
            continue
        rest = tokens[1:]
        roots: list[str] = []
        for token in rest:
            if token.startswith("-"):
                break
            roots.append(token)
        if not roots:
            # 起点の省略は cwd 全体が対象になる
            return False
        for root in roots:
            if not _resolves_into_scratch(root.strip("'\""), workspace):
                return False
            saw_root = True
        for index, token in enumerate(rest):
            if token not in _FIND_EXEC_FLAGS:
                continue
            # `-exec <cmd> [args...] ;|+` の args を見る
            cursor = index + 2
            while cursor < len(rest) and rest[cursor] not in (";", "\\;", "+"):
                if rest[cursor].strip("'\"") != "{}":
                    return False
                cursor += 1
    return saw_root


def _rm_ask_exempt(cmd: str) -> bool:
    return _rm_is_workspace_local(cmd) or _rm_targets_scratch_only(cmd)


def check_rm_root_guard(cmd: str) -> str | None:
    """`rm` がシステム全体・ホーム・親ディレクトリを対象にしていないか。

    `cd /elsewhere && rm -rf /` や `sh -c "rm -rf ~"` のような回避を防ぐため、
    ポリシー照合と同じ normalize を通してから各セグメントを検査する。
    normalize は shlex を通るため ``${HOME}`` の波括弧が落ちることがある。
    元の文字列も併せて検査して取りこぼさないようにする。
    """
    segments = list(_normalize(cmd)) if _policy is not None else []
    segments.append(cmd)
    for segment in segments:
        tokens = segment.split()
        if not tokens or not _RM_BIN_RE.match(_basename(tokens[0])):
            continue
        if any(t == "--no-preserve-root" for t in tokens):
            return (
                "`rm --no-preserve-root` は許可されていません。\n"
                "ルートディレクトリの削除は承認の対象外です。"
            )
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            # workspace ルートの一括削除。`find . -delete` のような探索起点とは
            # 意味が違うので、rm 側でだけ判定する
            if token.strip().strip("'\"") in _WORKSPACE_ROOT_TOKENS:
                return (
                    f"`rm` が作業ディレクトリ全体 (`{token}`) を対象にしています。\n"
                    "git 管理外のファイルまで失われるため承認の対象外です。\n"
                    "削除したい対象を具体的なパスで指定し直してください。"
                )
            if _is_catastrophic_rm_target(token):
                return (
                    f"`rm` が壊滅的なパス `{token}` を対象にしています。\n"
                    "システム全体・ホーム・親ディレクトリの削除は承認の対象外です。\n"
                    "削除したい対象を具体的なパスで指定し直してください。"
                )
    return None
