"""pi の配布物（箱へ入れるもの）を、許可リスト方式で作る。dotfiles 固有。

ホームの pi 関連（~/.pi/agent・~/.config/pi）から、許可した名前だけを複製する。認証・履歴・ホスト固有の設定は入れない。
複製後に、秘密らしいファイル名・内容が無いことを走査し、あれば DistError で止める（C1）。
配置の元は chezmoi の source state: home/dot_pi/agent/（extensions・prompts・AGENTS.md）、
home/dot_config/pi/（harness・commit-confirm）。
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

# src_home からの相対パス。ここに無いものは入れない（許可リスト）
DEFAULT_ALLOW: tuple[str, ...] = (
    ".pi/agent/extensions",
    ".pi/agent/prompts",
    ".pi/agent/skills",
    ".pi/agent/AGENTS.md",
    ".config/pi/harness",
    ".config/pi/commit-confirm",
)
# 許可したディレクトリの中でも複製しない名前（パスの各要素・ファイル名への fnmatch）
DEFAULT_DENY: tuple[str, ...] = (
    "auth.json",
    "sessions",
    "*.jsonl",
    ".env",
    ".env.*",
    "mcp.json",  # 認証値を含みうる
    "models.json",  # 箱用に生成する
    "history",
    "*.history",
    "settings.json",  # 箱用に生成する
    "node_modules",
    "__pycache__",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    ".git",
)
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"""["']?(?:refresh_token|access_token)["']?\s*[:=]\s*["'][A-Za-z0-9._-]{20,}["']"""
    ),
    re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]{20,}"),
)
MAX_SCAN_BYTES = 2_000_000


class DistError(RuntimeError):
    """配布物に秘密らしいものが残った。"""


def is_denied(rel: Path, deny: Iterable[str]) -> bool:
    pats = list(deny)
    return any(fnmatch.fnmatch(part, pat) for part in rel.parts for pat in pats)


def _copy_tree(src: Path, dest: Path, base: Path, deny: tuple[str, ...], out: list[str]) -> None:
    if src.is_symlink():
        return  # symlink は辿らない（外のファイルを引き込まない）
    rel = src.relative_to(base)
    if is_denied(rel, deny):
        return
    if src.is_dir():
        for child in sorted(src.iterdir()):
            _copy_tree(child, dest, base, deny, out)
    elif src.is_file():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        target.chmod(0o755 if src.stat().st_mode & 0o111 else 0o644)
        out.append(rel.as_posix())


def scan_secrets(root: Path, deny: tuple[str, ...] = DEFAULT_DENY) -> list[str]:
    """root の下に、拒否名のファイル・秘密らしい内容があれば、相対パス（理由）を返す。内容は返さない。"""
    found: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if is_denied(rel, deny):
            found.append(f"{rel.as_posix()}（拒否名）")
            continue
        if p.stat().st_size > MAX_SCAN_BYTES:
            continue
        text = p.read_bytes().decode("utf-8", errors="replace")
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                found.append(f"{rel.as_posix()}（秘密らしい内容）")
                break
    return found


def build_dist(
    src_home: Path,
    dest: Path,
    *,
    allow: tuple[str, ...] = DEFAULT_ALLOW,
    deny: tuple[str, ...] = DEFAULT_DENY,
) -> list[str]:
    """許可リストの名前だけを src_home から dest へ複製する。複製したファイル（dest からの相対）を返す。

    複製後に秘密を走査し、見つかったら dest を消して DistError を投げる。
    """
    src_home = src_home.resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copied: list[str] = []
    for name in allow:
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            raise DistError(f"許可リストの名前が不正: {name}")
        src = src_home / rel
        if not src.exists() or src.is_symlink():
            continue
        if src.is_dir():
            for child in sorted(src.rglob("*")):
                if child.is_symlink() or not child.is_file():
                    continue
                crel = child.relative_to(src_home)
                if is_denied(crel.relative_to(rel), deny):
                    continue
                target = dest / crel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(child, target)
                target.chmod(0o755 if child.stat().st_mode & 0o111 else 0o644)
                copied.append(crel.as_posix())
        else:
            _copy_tree(src, dest, src_home, deny, copied)
    findings = scan_secrets(dest, deny)
    if findings:
        shutil.rmtree(dest)
        raise DistError("配布物に秘密らしいものがある: " + ", ".join(findings))
    return sorted(copied)


def minimal_settings(extra: Mapping[str, object] | None = None) -> dict[str, object]:
    """箱用の pi の settings（秘密を含まない最小のもの）。httpProxy などは net 側が差し込む。

    キーは pi の docs/settings.md による。
    """
    base: dict[str, object] = {"theme": "system", "defaultThinkingLevel": "medium"}
    if extra:
        base.update(extra)
    return base


def settings_json(extra: Mapping[str, object] | None = None) -> str:
    return json.dumps(minimal_settings(extra), ensure_ascii=False, indent=2) + "\n"
