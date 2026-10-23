"""書き込み先を `.tmp/research/` の中に限り、外へ送る文字列の秘匿チェックを行う。

上流 (MaryCache/imozuru) には無い、この dotfiles 側の追加。スクリプトを確認なしで実行できる許可に載せても、
引数のパスで作業ツリーの別の場所へ書かれたり、秘密を含む文字列が外へ出たりしないようにする。
see docs/spec/imozuru.md#書き込み先の制限
"""

from __future__ import annotations

import importlib.util
import os
import re
import stat
import sys
from pathlib import Path

# 置き場の中を調べるときの上限 (多すぎるのは異常なので拒否する)
MAX_ENTRIES = 20_000


def _refuse(message: str) -> None:
    print(f"拒否: {message}", file=sys.stderr)
    sys.exit(2)


def research_root() -> Path:
    """置き場の根。いまのディレクトリの `.tmp/research`。環境変数では変えられない (固定する)。"""
    return Path.cwd() / ".tmp" / "research"


def confine(path: Path) -> Path:
    """path が置き場の中で、リンクを含まないとき、解決したパスを返す。そうでなければ止める。

    - 根 (.tmp と .tmp/research) がシンボリックリンクなら拒否する (リポジトリが外を指すリンクを持ち込める)
    - path を解決した先が根の中でなければ拒否する (`..` やリンクでの脱出)
    - path の中 (これから書く子のパスも含む) に、シンボリックリンクが 1 つでもあれば拒否する
      (`watch/` や一時ファイルが外を指していると、書き込みがリンク先へ届く)
    - 通常ファイルのハードリンク (リンク数 2 以上) も拒否する
      (追記・上書きが、置き場の外の同じ実体へ届く)
    """
    root = research_root()
    for part in (root.parent, root):
        if part.is_symlink():
            _refuse(f"{part} がシンボリックリンク。置き場の根はリンクにしない")
    root = root.resolve()
    resolved = Path(path).expanduser().resolve()
    if resolved != root and root not in resolved.parents:
        _refuse(f"{resolved} は {root} の外。調べものの置き場は {root} の中にする")
    if resolved.is_file() and resolved.lstat().st_nlink > 1:
        _refuse(f"{resolved} がハードリンク。置き場の中にリンクを置かない")
    seen = 0
    for dirpath, dirnames, filenames in os.walk(resolved, followlinks=False):
        for name in (*dirnames, *filenames):
            seen += 1
            entry = Path(dirpath) / name
            if entry.is_symlink():
                _refuse(f"{entry} がシンボリックリンク。置き場の中にリンクを置かない")
            info = entry.lstat()
            if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                _refuse(f"{entry} がハードリンク。置き場の中にリンクを置かない")
            if seen > MAX_ENTRIES:
                _refuse(f"{resolved} の中のファイルが {MAX_ENTRIES} 件を超える")
    return resolved


# ─── 外へ送る文字列の秘匿チェック ─────────────────────────────────────────

# 兄弟のスキル web-search が読めないときの代替。web-search の SECRET_PATTERNS / LONG_TOKEN と同じ内容
_FALLBACK = [
    ("秘密鍵", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS のアクセスキー", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "GitHub のトークン",
        re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    ),
    (
        "API キー",
        re.compile(
            r"\bsk-[A-Za-z0-9_-]{20,}\b|\bxox[baprs]-[A-Za-z0-9-]{10,}\b|\bAIza[0-9A-Za-z_-]{30,}\b"
        ),
    ),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.")),
    (
        "代入された秘密",
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key)\b\s*[:=]\s*\S{6,}"
        ),
    ),
    (
        "内部アドレス",
        re.compile(
            r"\b(10\.\d{1,3}|192\.168|172\.(1[6-9]|2\d|3[01])|169\.254)\.\d{1,3}\.\d{1,3}\b"
            r"|\b[\w-]+\.(internal|corp|intranet|local)\b"
        ),
    ),
]
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/_=-]{40,}")
_SLUG_PART = re.compile(r"[a-z]{1,20}|\d{1,8}")
_URL_IN_TEXT = re.compile(r"https?://\S+", re.IGNORECASE)


def _is_slug(token: str) -> bool:
    """web-search の `is_slug` と同じ (英小文字の語と数字を `-` `_` `/` でつないだ 4 つ以上の列)。URL の中だけで使う。"""
    parts = [p for p in re.split(r"[-_/]", token) if p]
    return len(parts) >= 4 and all(_SLUG_PART.fullmatch(p) for p in parts)


def _websearch_check():
    """兄弟のスキル web-search の `check_query` を借りる (パターンを二重に持たない)。無ければ None。"""
    path = Path(__file__).resolve().parents[2] / "web-search" / "scripts" / "websearch.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("imozuru_websearch", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclass などが自分のモジュールを引くので、先に登録する
        spec.loader.exec_module(module)
        return module.check_query
    except Exception:  # 読めなければ内蔵の検査に落とす
        return None


def secret_reason(text: str) -> str | None:
    """秘密らしきものが含まれていれば、理由を返す。"""
    check = _websearch_check()
    if check is not None:
        return check(text)
    for label, pattern in _FALLBACK:
        if pattern.search(text):
            return label
    url_spans = [m.span() for m in _URL_IN_TEXT.finditer(text)]
    for found in _LONG_TOKEN.finditer(text):
        token = found.group()
        if any(s <= found.start() < e for s, e in url_spans):
            token = "/".join(seg for seg in token.split("/") if not _is_slug(seg))
        if len(token) < 40:
            continue
        if re.search(r"\d", token) and re.search(r"[A-Za-z]", token):
            return "長いトークンらしき文字列"
    return None


def refuse_secrets(what: str, text: str) -> None:
    """text に秘密らしきものがあれば、外へ送らずに止める (終了コード 2)。"""
    reason = secret_reason(text)
    if reason:
        _refuse(
            f"{what} に「{reason}」らしき文字列が含まれるので、外へ送らない。その部分を外して言い換える"
        )


# ─── YouTube (yt-dlp) ──────────────────────────────────────────────────────


def youtube_problem(via_wrapper: bool = False) -> str | None:
    """YouTube の字幕を取ってよい条件を満たさない理由を、満たすときは None を返す。

    yt-dlp は自分で通信し、宛先をこちらで確かめられない。fetch.py は確認なしの許可に載るので、
    YouTube は許可に載せない別スクリプト fetch_youtube.py (via_wrapper=True で呼ぶ) だけが通す。
    環境変数では切り替えない (親プロセスから継承されると確認を迂回できる)。
    fetch_youtube.py は個人の PC (applejxd) にだけ chezmoi が配る (会社の PC にはスクリプト自体が無い)。
    """
    if not via_wrapper:
        return (
            "YouTube は yt-dlp が自分で通信し、宛先を確かめられない。"
            "取るなら fetch_youtube.py で呼ぶ（確認が出る。個人の PC (applejxd) にだけある）"
        )
    return None
