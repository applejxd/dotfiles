"""パスが信頼できるかの検査（標準ライブラリだけ）。root で動くコードが、利用者に差し替えられない場所だけを使うために使う。

信頼できる = パスが正規化済みで、途中にシンボリックリンクが無く、`/` から対象までの存在する各構成要素が
root 所有で、グループ・他人から書けない（mode & 0o022 == 0）。
利用者の権限で動く cli（sudo を呼ぶ前）と、root で動く uninstall.py の両方が同じ関数を使う。
"""

from __future__ import annotations

import os
import stat


class TrustError(Exception):
    pass


# uninstall.py が（間接も含めて）import するモジュール。配備コピーに無ければ sudo の前に止める
UNINSTALL_MODULES = (
    "__init__.py",
    "config.py",
    "model.py",
    "net.py",
    "plan.py",
    "policy.py",
    "setup.py",
    "trust.py",
    "uninstall.py",
)


def _lstat_mode(path: str) -> int:
    try:
        return os.lstat(path).st_mode
    except OSError:
        return 0


def missing_modules(pkg_dir: str) -> list[str]:
    """配備コピーの kcage パッケージに無い必須モジュールの一覧（通常ファイルでないものも欠けとみなす）。"""
    return [m for m in UNINSTALL_MODULES if not stat.S_ISREG(_lstat_mode(os.path.join(pkg_dir, m)))]


def _check_stat(path: str, st: os.stat_result, root_uid: int) -> None:
    if stat.S_ISLNK(st.st_mode):
        raise TrustError(f"シンボリックリンクは信頼しない: {path}")
    if st.st_uid != root_uid:
        raise TrustError(f"root 所有でない: {path}")
    if st.st_mode & 0o022:
        raise TrustError(f"グループ・他人から書ける: {path}")


def check_trusted(
    path: str, *, allow_missing: bool = False, root_uid: int = 0, start: str = "/"
) -> None:
    """path とその祖先（start より下）を検査する。満たさなければ TrustError。

    allow_missing: 存在しない構成要素に当たったら、そこで検査を終える（存在する祖先は検査済み）。
    start: 検査を始める起点（既定は `/`。`/` のときだけ `/` 自体も検査する。試験で作業ディレクトリを起点にするために使う）。
    """
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        raise TrustError(f"正規化された絶対パスでない: {path}")
    if os.path.realpath(path) != path:
        raise TrustError(f"途中にシンボリックリンクがある: {path}")
    if start != "/" and not (path == start or path.startswith(start.rstrip("/") + "/")):
        raise TrustError(f"起点の外のパス: {path}")
    chain: list[str] = []
    if start == "/":
        chain.append("/")
    rel = os.path.relpath(path, start)
    cur = start
    if rel != ".":
        for part in rel.split(os.sep):
            cur = os.path.join(cur, part)
            chain.append(cur)
    for p in chain:
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            if allow_missing:
                return
            raise TrustError(f"存在しない: {p}") from None
        except OSError as exc:
            raise TrustError(f"調べられない: {p}: {exc}") from exc
        _check_stat(p, st, root_uid)


def check_tree(root: str, *, root_uid: int = 0, start: str = "/") -> None:
    """root とその祖先、root の下のすべての実体を検査する（配備コピーの全体）。"""
    check_trusted(root, root_uid=root_uid, start=start)

    def _onerror(exc: OSError) -> None:
        raise TrustError(f"調べられない: {exc}")

    for dirpath, dirs, files in os.walk(root, followlinks=False, onerror=_onerror):
        for name in (*dirs, *files):
            p = os.path.join(dirpath, name)
            try:
                st = os.lstat(p)
            except OSError as exc:
                raise TrustError(f"調べられない: {p}: {exc}") from exc
            _check_stat(p, st, root_uid)
