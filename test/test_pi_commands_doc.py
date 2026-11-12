"""docs/spec/pi-commands.md (stock の pi のスラッシュコマンドの早見) を、実物の登録と突き合わせる。

- pi 本体の組み込み: ``slash-commands.js`` の ``name``。
- pi 本体が組み込みで読む拡張: ``dist/extensions/*`` の ``registerCommand``。
- package のコマンド: ``pi-stock-packages`` の各 package が ``registerCommand`` で登録する名前 (変数で渡す形も解く)。
  package が 1 つでも欠けていれば、全体を skip する (一部だけ入った環境で誤って落とさない)。
- package の prompt template: pi-subagents の ``prompts/*.md``。
- このリポジトリが配る prompt template: ``home/dot_pi/agent/prompts/*.tmpl``。

pi か package が入っていない環境 (CI など) では、その部分を skip する。skip は通過ではない。
pi か package を更新してコマンドが増減したら、この試験が落ちるので、早見を直す。
see docs/spec/pi-commands.md
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "spec" / "pi-commands.md"
STOCK_PACKAGES = ROOT / "home" / ".chezmoitemplates" / "pi-stock-packages"
REPO_PROMPTS = ROOT / "home" / "dot_pi" / "agent" / "prompts"
AGENT_DIR = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")
NODE_MODULES = AGENT_DIR / "npm" / "node_modules"
# 利用者が使うコマンドではない (host の統合用)。早見には載せない
INTERNAL_COMMANDS = {"pi-subagents-bridge", "subagents-inspect-rpc"}
# 仕事用の機だけが入れる package (pi-stock-packages の is-work の中)。この機に無いのが普通なので、突き合わせから外す
WORK_ONLY_PACKAGES = {"pi-mcp-adapter"}


def doc_sections() -> dict[str, set[str]]:
    """見出しごとの、表の最初の列にある `/名前` の集合 (1 つのセルに複数あれば、すべて)。"""
    sections: dict[str, set[str]] = {}
    current = ""
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, set())
        elif line.startswith("|") and current:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # package の表は 1 列目が package 名、2 列目がコマンド (空の 1 列目は上の行の続き)
            for cell in cells[:2]:
                sections[current].update(re.findall(r"`/([a-z][a-z0-9-]*)", cell))
    return sections


def _section(prefix: str) -> set[str]:
    for name, found in doc_sections().items():
        if name.startswith(prefix):
            return found
    raise AssertionError(f"見出しが無い: {prefix}")


def installed_pi_dist() -> Path | None:
    found = sorted(
        (AGENT_DIR / "install" / "releases").glob(
            "*/node_modules/@earendil-works/pi-coding-agent/dist"
        )
    )
    return found[-1] if found else None


def stock_package_names() -> list[str]:
    names = []
    for raw in STOCK_PACKAGES.read_text(encoding="utf-8").splitlines():
        match = re.match(r"npm:(@?[^@\s]+(?:/[^@\s]+)?)@", raw.strip())
        if match and match.group(1) not in WORK_ONLY_PACKAGES:
            names.append(match.group(1))
    return names


def registered_commands(source: str) -> set[str]:
    """``registerCommand("x"``・``registerCommand(o`` (``o="x"`` と定義した変数。minify された dist) の名前。"""
    found = set(re.findall(r"registerCommand\(\s*[\"']([a-z][a-z0-9-]*)[\"']", source))
    for ident in re.findall(r"registerCommand\(\s*([A-Za-z_$][\w$]*)\s*,", source):
        found.update(
            re.findall(rf"(?<![\w$]){re.escape(ident)}\s*=\s*[\"']([a-z][a-z0-9-]*)[\"']", source)
        )
    return found


def sources(root: Path):
    for src in root.rglob("*"):
        if (
            src.suffix in (".ts", ".js", ".mjs")
            and "node_modules" not in src.relative_to(root).parts
        ):
            yield src


def test_registered_commands_resolves_a_variable_name():
    """cc-safety-net は minify された dist で、``var o="cc-safety-net"`` と ``registerCommand(o,`` に分けて登録する。"""
    source = 'var o="cc-safety-net",r="x";function t(e){e.registerCommand(o,{description:r})}'
    assert registered_commands(source) == {"cc-safety-net"}
    assert registered_commands('pi.registerCommand("bg", {') == {"bg"}
    assert registered_commands("pi.registerCommand(COMMAND_NAME, {") == set()  # 定数は別の経路 (下)


def test_the_builtin_commands_in_the_doc_match_the_installed_pi():
    dist = installed_pi_dist()
    path = dist / "core" / "slash-commands.js" if dist else None
    if path is None or not path.is_file():
        pytest.skip("pi が入っていない (slash-commands.js が無い)")
    actual = set(re.findall(r'name: "([a-z][a-z0-9-]*)"', path.read_text(encoding="utf-8")))
    assert _section("pi 本体の組み込み") == actual


def test_the_commands_of_the_extensions_bundled_in_pi_match_the_doc():
    dist = installed_pi_dist()
    if dist is None or not (dist / "extensions").is_dir():
        pytest.skip("pi が入っていない (dist/extensions が無い)")
    actual: set[str] = set()
    for src in sources(dist / "extensions"):
        actual |= registered_commands(src.read_text(encoding="utf-8", errors="ignore"))
    assert _section("pi 本体に同梱の拡張") == actual


def test_the_package_commands_in_the_doc_match_the_installed_packages():
    names = stock_package_names()
    missing = [n for n in names if not (NODE_MODULES / n).is_dir()]
    if missing:
        pytest.skip(f"stock の package が揃っていない (未導入: {', '.join(missing)})")
    actual: set[str] = set()
    constants = ""
    for name in names:
        for src in sources(NODE_MODULES / name):
            text = src.read_text(encoding="utf-8", errors="ignore")
            actual |= registered_commands(text)
            if src.name == "types.ts":
                constants += text
    # rpiv-todo は、定数 (COMMAND_NAME) でコマンド名を登録する
    actual |= set(re.findall(r'COMMAND_NAME\s*=\s*"([a-z][a-z0-9-]*)"', constants))
    assert _section("package のコマンド") == actual - INTERNAL_COMMANDS


def test_the_package_prompt_templates_in_the_doc_match_pi_subagents():
    prompts = NODE_MODULES / "pi-subagents" / "prompts"
    if not prompts.is_dir():
        pytest.skip("pi-subagents が入っていない")
    actual = {p.stem for p in prompts.glob("*.md")}
    assert _section("package が同梱する prompt template") == actual


def test_the_repo_prompt_templates_in_the_doc_match_what_the_repository_ships():
    actual = {p.name.removesuffix(".md.tmpl") for p in REPO_PROMPTS.glob("*.md.tmpl")}
    assert _section("このリポジトリが配る prompt template") == actual


def test_commands_listed_as_missing_in_stock_do_not_exist_there():
    """「stock には無いコマンド」の表のものが、stock のどこにも登録されていない (早見の主張の誤りを防ぐ)。"""
    missing = _section("stock には無いコマンド")
    present = (
        _section("pi 本体の組み込み")
        | _section("pi 本体に同梱の拡張")
        | _section("package のコマンド")
        | _section("package が同梱する prompt template")
        | _section("このリポジトリが配る prompt template")
    )
    assert not (missing & present), missing & present
