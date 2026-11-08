"""pi の配布物（箱へ入れるもの）を、許可リスト方式で作る。dotfiles 固有。

ホームの pi 関連（~/.pi/agent・~/.config/pi）から、許可した名前だけを複製する。認証・履歴・ホスト固有の設定は入れない。
複製後に、秘密らしいファイル名・内容が無いことを走査し、あれば DistError で止める（C1）。
配置の元は chezmoi の source state: home/dot_pi/agent/（extensions・prompts・AGENTS.md）、
home/dot_config/pi/（harness・commit-confirm）。
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from kcage import model, template

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
    "rules.json",  # ホスト用の生成物。箱用は build_box_dist が作り直す
    "*.e2e-bak",  # 試験の退避ファイル
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


# ---- 箱の中のフルガード（箱用 rules.json と起動スクリプト）----
# see docs/spec/sandbox/incus-box.md#箱の中のフルガード

DIST = template.DIST_DEST
LAUNCHER_REL = "bin/kcage-pi"
LAUNCHER_PATH = f"{DIST}/{LAUNCHER_REL}"
HARNESS_REL = ".config/pi/harness"
BOX_EXT_DIR = ".pi/agent/extensions"
# pi の起動の基本形（pis の BASE_FLAGS と同じ。project trust は拒否、組み込みツールと自動発見の拡張は無効）
BOX_BASE_FLAGS = ("--no-approve", "-nbt", "-ne", "-e", "builtin:mcp")
# 箱では PR ビューアと台帳に繋がらないので、役割のツールから外す
BOX_DROP_TOOLS = ("pr_summary", "work")
# 箱の AI が書き換えてはいけないもの（配布物・モデルと認証の設定）
BOX_WRITE_DENY = (
    f"{DIST}/**",
    "~/.pi/agent/models.json",
    "~/.pi/agent/auth.json",
)
BOX_EXTERNAL_READ = (DIST,)
# 箱の既定: ask は許可に落ちる。deny と必須確認（[pi.confirm]・[pi.integrate]）は残る
BOX_ENV = (("PI_HARNESS_BYPASS", "1"),)
# generate.py が読む局所設定を、存在しない場所へ向ける（ホストの局所設定を混ぜない。空文字は既定へ戻るので使えない）
NO_LOCAL_CONFIG = "/nonexistent/kcage-no-local.toml"
GENERATE_PY = Path(__file__).resolve().parents[3] / "agents" / "generate.py"

RulesGenerator = Callable[[Path], dict[str, Any]]


def generate_rules(common: Path) -> dict[str, Any]:
    """scripts/agents/generate.py で、箱（HOME=/home/ubuntu）向けの rules.json を dict で作る。

    common はホストの描画済み common.toml。ホストの局所設定は混ぜない。
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": model.BOX_HOME,
        "AGENTS_LOCAL_CONFIG": NO_LOCAL_CONFIG,
    }
    proc = subprocess.run(
        [sys.executable, str(GENERATE_PY), "--target", "pi-harness", "--common", str(common)],
        input="{}",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise DistError(f"箱用の rules.json を生成できない: {proc.stderr.strip()[-300:]}")
    data = json.loads(proc.stdout)
    if not isinstance(data, dict):
        raise DistError("箱用の rules.json が dict でない")
    return data


def _uniq_add(items: list[Any], extra: Iterable[str]) -> list[Any]:
    out = list(items)
    for e in extra:
        if e not in out:
            out.append(e)
    return out


def apply_box_overlay(rules: Mapping[str, Any]) -> dict[str, Any]:
    """ホスト用の rules.json を箱用に直す（ホストの方針の生成物は変えず、ここで調整する）。

    無いキーは作らない。判定の形（judge.common.file・judge.common.pi）が違えば DistError。
    """
    out: dict[str, Any] = json.loads(json.dumps(rules))  # 深いコピー
    out["post_edit"] = []  # 箱に無いスクリプトを実行しない
    out["mcp"] = []  # 箱に uv が無い
    tools = out.get("profile_tools")
    if isinstance(tools, dict):
        out["profile_tools"] = {
            role: [t for t in names if t not in BOX_DROP_TOOLS] for role, names in tools.items()
        }
    try:
        common = out["judge"]["common"]
        file_ = common["file"]
        file_["write_deny_globs"] = _uniq_add(file_.get("write_deny_globs", []), BOX_WRITE_DENY)
        ext = common["pi"]["external_read"]
        ext["paths"] = _uniq_add(ext.get("paths", []), BOX_EXTERNAL_READ)
    except (KeyError, TypeError) as exc:
        raise DistError(f"rules.json の形が想定と違う（{exc!r}）") from exc
    return out


def rules_json_text(rules: Mapping[str, Any]) -> str:
    return json.dumps(rules, indent=2, ensure_ascii=False) + "\n"


def launcher_text(extensions: Iterable[str]) -> str:
    """箱の pi の起動スクリプト（/opt/kcage-dist/bin/kcage-pi）の中身。純粋な関数。

    settings.json の extensions には頼らず、-ne で自動発見を切って、判定器と自作の拡張を絶対パスの -e で渡す
    （読めなければ pi が止まる。素の settings.json への依存で fail-open にならない）。
    """
    harness = f"{DIST}/{HARNESS_REL}"
    args: list[str] = list(BOX_BASE_FLAGS)
    for name in extensions:
        args += ["-e", f"{DIST}/{BOX_EXT_DIR}/{name}/index.ts"]
    args += ["-e", harness]
    env = " ".join(f"{k}={shlex.quote(v)}" for k, v in BOX_ENV)
    cmd = " ".join(shlex.quote(a) for a in args)
    return (
        "#!/bin/sh\n"
        "# kcage の箱の pi をフルガードつきで起動する（kcage pi が実行する。root 所有）。\n"
        "# see docs/spec/sandbox/incus-box.md#箱の中のフルガード\n"
        "set -eu\n"
        f'[ -f {shlex.quote(harness + "/index.ts")} ] || {{ echo "kcage-pi: 判定器が無い" >&2; exit 1; }}\n'
        f'exec env {env} pi {cmd} "$@"\n'
    )


def build_box_dist(
    src_home: Path,
    dest: Path,
    *,
    generate: RulesGenerator = generate_rules,
    allow: tuple[str, ...] = DEFAULT_ALLOW,
    deny: tuple[str, ...] = DEFAULT_DENY,
) -> list[str]:
    """build_dist に、箱用の rules.json と起動スクリプトを足す。複製したファイル（dest からの相対）を返す。"""
    copied = build_dist(src_home, dest, allow=allow, deny=deny)
    try:
        rules = apply_box_overlay(generate(src_home / ".config" / "agents" / "common.toml"))
        text = rules_json_text(rules)
        host_home = str(src_home.resolve())
        if host_home in text or str(src_home) in text:
            raise DistError("箱用の rules.json にホストのホームのパスが残った")
        names = [n for n in rules.get("extensions", []) if isinstance(n, str)]
        present = [n for n in names if (dest / BOX_EXT_DIR / n / "index.ts").is_file()]
        rules_path = dest / HARNESS_REL / "rules.json"
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        rules_path.write_text(text, encoding="utf-8")
        rules_path.chmod(0o644)
        launcher = dest / LAUNCHER_REL
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text(launcher_text(present), encoding="utf-8")
        launcher.chmod(0o755)
        # 生成物を含めて走査する（rules.json は生成物なので拒否名から外す）
        findings = scan_secrets(dest, tuple(d for d in deny if d != "rules.json"))
        if findings:
            raise DistError("配布物に秘密らしいものがある: " + ", ".join(findings))
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return sorted([*copied, f"{HARNESS_REL}/rules.json", LAUNCHER_REL])
