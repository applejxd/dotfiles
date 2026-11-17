#!/usr/bin/env python3
"""README.md を、リポジトリの実体と突き合わせて決定論的に検査する。

検査するのは「README が約束するものが、リポジトリに実在するか」と書き方の基本。
読むだけ: ネットワークに出ず、README のコマンドを実行しない。外部リンクの到達性は確かめない。
使い方: python3 check_readme.py README.md [--repo DIR] [--json] [--strict]
終了コード: error があれば 1、無ければ 0(--strict は warning でも 1)。
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import unquote

# 対象のリポジトリ(この scripts/ を含むことがある)へ .pyc を書かない
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_facts  # noqa: E402

MAX_LINE = 20000  # 1 行あたりに正規表現を当てる長さの上限
MAX_README = 600_000  # README を読む上限(バイト)。500 KiB 超は error にする
MAX_LINKED_DOCS = 50  # アンカー確認のために開く他の Markdown の数

SHELL_LANGS = {"", "bash", "sh", "shell", "console", "zsh", "terminal", "shell-session", "sh-session", "fish"}
SCRIPT_RUNNERS = {"python", "python3", "bash", "sh", "node", "ruby", "perl", "deno", "bun"}
SCRIPT_EXTS = (".py", ".sh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl")
LICENSE_NAMES = (
    ("AGPL-3.0", r"agpl"), ("LGPL-3.0", r"lgpl[- ]?v?3|lgpl-3"), ("LGPL-2.1", r"lgpl[- ]?v?2|lgpl-2"),
    ("LGPL-3.0|LGPL-2.1", r"lgpl"), ("GPL-3.0", r"gpl[- ]?v?3|gpl-3\.0"),
    ("GPL-2.0", r"gpl[- ]?v?2|gpl-2\.0"), ("Apache-2.0", r"apache"), ("MPL-2.0", r"mpl|mozilla"),
    ("BSD-3-Clause", r"bsd[- ]?3"), ("BSD-2-Clause", r"bsd[- ]?2"), ("MIT", r"\bmit\b"),
    ("ISC", r"\bisc\b"), ("Unlicense", r"unlicense"),
)
USAGE_HEADING = re.compile(
    r"install|usage|\buse\b|getting started|quick ?start|set ?up|how to|example|"
    r"インストール|使い方|使用|セットアップ|はじめ|クイックスタート|導入|環境構築|実行",
    re.I,
)
HYPE = re.compile(
    r"\b(blazing(ly)?[- ]fast|revolutionary|game[- ]chang(er|ing)|cutting[- ]edge|world[- ]class|"
    r"best[- ]in[- ]class|supercharge[sd]?)\b|最強|革命的|画期的|究極の",
    re.I,
)
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
DEST = r"<?((?:[^()\s<>]|\([^()\s]*\))+)>?"  # 括弧 1 段までを含むリンク先
TITLE = r"(?:\s+\"[^\"]*\")?\s*"
LINK = re.compile(r"(?<!!)\[((?:[^\[\]]|!\[[^\[\]]*\]\([^()]*\))*)\]\(\s*" + DEST + TITLE + r"\)")
IMAGE = re.compile(r"!\[([^\[\]]*)\]\(\s*" + DEST + TITLE + r"\)")
HTML_IMG = re.compile(r"<img\b[^<>]*>", re.I)
REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)")


def slugify(heading: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = re.sub(r"<[^>]+>", "", text).replace("`", "").replace("*", "")
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def parse_heading(line: str):
    """ATX 見出し(# 〜 ######)を、正規表現の分割なしで読む。見出しでなければ None。"""
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3 or not stripped.startswith("#"):
        return None
    level = len(stripped) - len(stripped.lstrip("#"))
    rest = stripped[level:]
    if level > 6 or (rest and rest[0] not in " \t"):
        return None
    body = rest.strip()
    if body.endswith("#"):
        head = body.rstrip("#")
        if not head or head[-1] in " \t":
            body = head.rstrip()
    return level, body


class Doc:
    """Markdown を、地の文・見出し・コードブロックに分ける(インデントによるコードは地の文として扱う)。"""

    def __init__(self, text: str):
        self.truncated = 0
        self.lines = []
        for raw in text.splitlines():
            if len(raw) > MAX_LINE:
                self.truncated += 1
            self.lines.append(raw[:MAX_LINE])
        self.prose: list[tuple[int, str]] = []
        self.blocks: list[dict] = []
        self.headings: list[tuple[int, int, str]] = []
        fence = None
        start = 1
        if self.lines and self.lines[0].strip() == "---":  # YAML front matter は読み飛ばす
            end = next((i for i, l in enumerate(self.lines[1:], 2) if l.strip() in ("---", "...")), None)
            if end:
                start = end + 1
        previous = ""
        for number, line in enumerate(self.lines, 1):
            if number < start:
                continue
            if fence is None:
                match = re.match(r"^ {0,3}(`{3,}|~{3,})([^`]*)$", line)
                if match:
                    marker = match.group(1)
                    fence = {"char": marker[0], "size": len(marker), "lang": match.group(2).strip().split(" ")[0].lower(), "line": number, "lines": []}
                    previous = ""
                    continue
            else:
                closing = re.match(r"^ {0,3}(`+|~+)\s*$", line)
                if closing and closing.group(1)[0] == fence["char"] and len(closing.group(1)) >= fence["size"]:
                    self.blocks.append(fence)
                    fence = None
                else:
                    fence["lines"].append((number, line))
                continue
            self.prose.append((number, line))
            heading = parse_heading(line)
            if heading:
                self.headings.append((number, *heading))
            elif previous.strip() and not re.match(r"^\s*([-*+]|\d+[.)]|>|\|)", previous) and not previous.startswith("    "):
                underline = line.strip()
                if len(underline) >= 2 and set(underline) == {"="} and not line.startswith("    "):
                    self.headings.append((number - 1, 1, previous.strip()))
                elif len(underline) >= 2 and set(underline) == {"-"} and not line.startswith("    "):
                    self.headings.append((number - 1, 2, previous.strip()))
            previous = line
        if fence is not None:
            self.blocks.append(fence)

    def prose_text(self) -> str:
        return "\n".join(text for _, text in self.prose)

    def anchors(self) -> set[str]:
        """GitHub の見出しアンカー。同じ見出しは -1, -2 … を付け、既出の名前とぶつからないようにする。"""
        used: set[str] = set()
        counts: dict[str, int] = {}
        for _, _, title in self.headings:
            base = slugify(title)
            slug = base
            if slug in used:
                n = counts.get(base, 0) + 1
                while f"{base}-{n}" in used:
                    n += 1
                counts[base] = n
                slug = f"{base}-{n}"
            used.add(slug)
        for match in re.finditer(r'<(?:a|h\d)\b[^<>]*\b(?:name|id)="([^"]+)"', self.prose_text()):
            used.add(match.group(1).lower())
        return used


class Checker:
    def __init__(self, readme: Path, repo: Path):
        self.readme = readme
        self.repo = repo
        self.base = readme.parent
        self.findings: list[dict] = []
        size = readme.stat().st_size
        with readme.open("rb") as handle:
            self.text = handle.read(MAX_README).decode("utf-8", errors="replace")
        self.doc = Doc(self.text)
        self.facts = collect_facts.collect(repo)
        if size > 500 * 1024:
            self.add("github-truncates", "error", 1, "500 KiB を超えている。GitHub は超えた分を表示しない(以降の検査は先頭 600 KB まで)")
        if self.doc.truncated:
            self.add("line-truncated", "info", 1, f"{MAX_LINE} 文字を超える行が {self.doc.truncated} 行ある。超えた分は検査していない")

    def add(self, id_, severity, line, message):
        self.findings.append({"id": id_, "severity": severity, "line": line, "message": message})

    def resolve(self, target: str) -> Path:
        target = unquote(target)
        if target.startswith("/"):
            return self.repo / target.lstrip("/")
        return self.base / target

    def inside(self, path: Path) -> bool:
        return collect_facts.is_inside(path, self.repo)

    def exists_anywhere(self, rel: str) -> bool:
        return any(self.inside(c) and c.exists() for c in (self.base / rel, self.repo / rel))

    # --- リンク・画像 ---------------------------------------------------
    def links(self):
        own_anchors = self.doc.anchors()
        externals: list[str] = []
        badges = 0
        anchor_cache: dict[Path, set[str]] = {}
        for number, line in self.doc.prose:
            scan = re.sub(r"`[^`]*`", "", line)
            targets = [(m.group(2), False, m.group(1)) for m in LINK.finditer(scan)]
            ref = REF_DEF.match(scan)
            if ref:
                targets.append((ref.group(1), False, ""))
            for m in IMAGE.finditer(scan):
                targets.append((m.group(2), True, m.group(1)))
            for m in HTML_IMG.finditer(scan):
                src = re.search(r'src="([^"]+)"', m.group(0))
                alt = re.search(r'alt="([^"]*)"', m.group(0))
                if src:
                    targets.append((src.group(1), True, alt.group(1) if alt else ""))
            for target, is_image, alt in targets:
                if is_image:
                    if re.search(r"shields\.io|badge|badgen|codecov\.io", target, re.I):
                        badges += 1
                    elif not alt.strip():
                        self.add("image-alt", "warning", number, f"画像に alt が無い: {target}")
                if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                    if target.lower().startswith(("http://", "https://")) and not is_image:
                        externals.append(target)
                    continue
                path_part, _, fragment = target.partition("#")
                path_part = path_part.split("?")[0]
                fragment = unquote(fragment).lower()
                if not path_part:
                    if fragment and fragment not in own_anchors:
                        self.add("anchor-missing", "error", number, f"この README に見出しが無い: #{fragment}")
                    continue
                resolved = self.resolve(path_part)
                if not self.inside(resolved):
                    self.add("link-outside-repo", "warning", number, f"リンク先がリポジトリの外を指す。検査していない: {target}")
                    continue
                if not resolved.exists():
                    kind = "image-missing" if is_image else "link-missing"
                    self.add(kind, "error", number, f"リンク先が無い: {target}")
                    continue
                if fragment and resolved.is_file() and resolved.suffix.lower() == ".md":
                    if resolved not in anchor_cache:
                        anchors = None
                        if len(anchor_cache) < MAX_LINKED_DOCS and resolved.stat().st_size <= collect_facts.MAX_READ:
                            try:
                                anchors = Doc(resolved.read_text(encoding="utf-8")).anchors()
                            except (OSError, UnicodeDecodeError):
                                anchors = None
                        anchor_cache[resolved] = anchors
                    if anchor_cache[resolved] is not None and fragment not in anchor_cache[resolved]:
                        self.add("anchor-missing", "error", number, f"{path_part} に見出しが無い: #{fragment}")
        if badges > 6:
            self.add("badges-many", "warning", 1, f"バッジが {badges} 個ある(6 個超)。判断に効くものだけに絞る")
        unique = list(dict.fromkeys(externals))
        if unique:
            shown = ", ".join(unique[:20]) + (" …" if len(unique) > 20 else "")
            self.add("external-unchecked", "info", 1, f"外部リンク {len(unique)} 件は未確認(ネットワークに出ない): {shown}")

    # --- コマンド ------------------------------------------------------
    def commands(self):
        commands = self.facts["commands"]
        names = lambda kind: {c["name"] for c in commands if c["kind"] == kind}  # noqa: E731
        make, mise, npm, just = names("make"), names("mise"), names("npm"), names("just")
        mise_files = set()
        for folder in ("mise-tasks", ".mise/tasks", ".config/mise/tasks"):
            root = self.repo / folder
            if root.is_dir():
                mise_files |= {str(p.relative_to(root).with_suffix("")) for p in root.rglob("*") if p.is_file()}
                mise_files |= {p.name for p in root.rglob("*") if p.is_file()}
        for block in self.doc.blocks:
            if block["lang"] not in SHELL_LANGS:
                continue
            moved = False
            for number, raw in block["lines"]:
                line = re.sub(r"^\s*(\$|>|#\s)\s*", "", raw).strip() if re.match(r"^\s*[$>]", raw) else raw.strip()
                if not line or line.startswith("#"):
                    continue
                for part in re.split(r"&&|\|\||;", line):
                    try:
                        tokens = shlex.split(part.strip().rstrip("\\"))
                    except ValueError:
                        continue
                    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
                        tokens = tokens[1:]
                    if not tokens:
                        continue
                    if tokens[0] == "cd":
                        moved = True
                        continue
                    if moved:
                        continue
                    self.one_command(number, tokens, make, mise, mise_files, npm, just)

    def install_args(self, tokens):
        """`pip install X` 系なら (エコシステム, X の並び)。違えば None。"""
        head, rest = tokens[0], tokens[1:]
        if head == "uv" and rest[:2] in (["pip", "install"], ["tool", "install"]):
            return "python", rest[2:]
        if head in ("python", "python3") and rest[:3] == ["-m", "pip", "install"]:
            return "python", rest[3:]
        if head in ("pip", "pip3", "pipx") and rest[:1] == ["install"]:
            return "python", rest[1:]
        if head in ("npm", "pnpm", "yarn", "bun") and rest[:1] and rest[0] in ("install", "i", "add"):
            return "node", rest[1:]
        if head == "cargo" and rest[:1] and rest[0] in ("install", "add"):
            return "rust", rest[1:]
        return None

    def install_name(self, number, tokens, plain) -> bool:
        """`pip install X` などの X が、manifest の name とも依存とも違えば warning(幻覚された名前の早期発見)。"""
        parsed = self.install_args(tokens)
        if parsed is None:
            return False
        ecosystem, args = parsed
        facts = {f["key"]: f["value"] for f in self.facts["facts"]}
        own = facts.get("name")
        if not own:
            return True
        norm = lambda n: re.sub(r"[-_.]+", "-", n.lower())  # noqa: E731
        known = {norm(own)}
        for dep in facts.get("dependencies") or []:
            known.add(norm(re.split(r"[\[<>=!~;@ ]", dep)[0]))
        skip = False
        for token in args:
            if skip:
                skip = False
                continue
            if token in ("-r", "-c", "-i", "-e", "--index-url", "--requirement", "--constraint", "--editable"):
                skip = True
                continue
            if token.startswith("-") or re.search(r"[/:$<{*]|^[.~]", token):
                continue
            if ecosystem == "node":
                name = token.rsplit("@", 1)[0] if token.count("@") >= 1 and not token.startswith("@") else token
            else:
                name = re.split(r"[\[<>=!~;@]", token, maxsplit=1)[0]
            if name and norm(name) not in known:
                self.add("install-name-differs", "warning", number, f"`{token}` は manifest の name({own})とも依存とも違う。幻覚された名前でないか、レジストリで確かめる")
        return True

    def missing(self, number, what, hint):
        self.add("command-missing", "error", number, f"{what}: {hint}")

    def one_command(self, number, tokens, make, mise, mise_files, npm, just):
        head, rest = tokens[0], tokens[1:]
        skip_flags = {"-C", "-f", "--directory", "--file", "--prefix", "--workspace", "-w", "--justfile"}
        if skip_flags & set(rest):
            return
        plain = [t for t in rest if not t.startswith("-")]
        if head == "make":
            targets, skip = [], False
            for tok in rest:
                if skip:
                    skip = False
                    if tok.isdigit():
                        continue
                if tok in ("-j", "-l", "--jobs", "-I", "-o", "-W"):
                    skip = True
                    continue
                if not tok.startswith("-") and "=" not in tok and not re.search(r"[$<{*]", tok):
                    targets.append(tok)
            for target in targets:
                if target not in make:
                    self.missing(number, f"`make {target}`", "Makefile に無い" if make else "Makefile が無いか、そのターゲットが無い")
        elif head == "mise" and plain[:1] in (["run"], ["r"]) and len(plain) > 1:
            task = plain[1]
            if not re.search(r"[$<{*]", task) and task not in mise and task not in mise_files:
                self.missing(number, f"`mise run {task}`", "mise.toml の tasks に無い")
        elif head in ("npm", "pnpm", "yarn", "bun") and plain[:1] == ["run"] and len(plain) > 1:
            if plain[1] not in npm and not re.search(r"[$<{*]", plain[1]):
                self.missing(number, f"`{head} run {plain[1]}`", "package.json の scripts に無い")
        elif head == "npm" and plain[:1] in (["test"], ["start"]):
            if plain[0] not in npm:
                self.missing(number, f"`npm {plain[0]}`", "package.json の scripts に無い")
        elif head == "just" and plain:
            if plain[0] not in just and not re.search(r"[$<{*]", plain[0]):
                self.missing(number, f"`just {plain[0]}`", "justfile に無い")
        elif self.install_name(number, tokens, plain):
            return
        else:
            words = tokens[:]
            if words[0] == "uv" and words[1:2] == ["run"]:
                words = words[2:]
                if words[:1] and words[0] in SCRIPT_RUNNERS:
                    pass
                elif words[:1] and words[0].endswith(SCRIPT_EXTS):
                    words = ["python", *words]
            if words[:1] and (words[0] in SCRIPT_RUNNERS or words[0].startswith("./")):
                args = [w for w in words[1:] if not w.startswith("-")]
                path = words[0] if words[0].startswith("./") else (args[0] if args else "")
                if "-m" in words or "-c" in words or "-e" in words:
                    return
                if path and not re.search(r"[$<{*~]|\.\.\.|^/|://", path) and (path.endswith(SCRIPT_EXTS) or "/" in path):
                    if not self.exists_anywhere(path):
                        self.missing(number, f"`{path}`", "実行するファイルが無い")

    # --- 本文 -----------------------------------------------------------
    def placeholders(self):
        todo = re.compile(
            r"\b(TODO|TBD|FIXME|XXX)\b\s*[:：)\]]|[(\[]\s*(TODO|TBD)\b|^\s*(?:[-*]\s*)?(TODO|TBD)\b|lorem ipsum|\[insert [^\[\]]*\]",
            re.I,
        )
        for number, line in self.doc.prose:
            match = todo.search(line)
            # TODO 系は大文字だけを穴埋めの跡とする(「todo リスト」のような普通の語を避ける)
            word = next((g for g in match.groups() if g), "") if match else ""
            if match and (word.isupper() or re.search(r"lorem|insert", match.group(0), re.I)):
                self.add("placeholder-todo", "error", number, f"穴埋めの跡が残っている: {line.strip()[:60]}")
        hole = re.compile(r"<\s*your[-_ ][^<>]*>|<\s*INSERT[^<>]*>|\bYOUR_[A-Z_]+\b", re.I)
        scan = list(self.doc.prose) + [item for block in self.doc.blocks for item in block["lines"]]
        for number, line in sorted(scan):
            if hole.search(line):
                self.add("placeholder-hole", "warning", number, f"利用者が置き換える穴がある(意図したものか確認): {hole.search(line).group(0)}")

    def structure(self):
        h1 = [h for h in self.doc.headings if h[1] == 1]
        html_h1 = len(re.findall(r"<h1\b", self.doc.prose_text(), re.I))
        total = len(h1) + html_h1
        if total == 0:
            self.add("h1-missing", "error", 1, "H1(# 題名)が無い")
        elif total > 1:
            self.add("h1-multiple", "error", h1[1][0] if len(h1) > 1 else 1, "H1 が複数ある")
        if h1:
            self.summary_after(h1[0][0])
        if not any(USAGE_HEADING.search(title) for _, _, title in self.doc.headings):
            self.add("usage-missing", "warning", 1, "インストール・使い方に当たる節が見当たらない")
        previous = 0
        for number, level, title in self.doc.headings:
            if previous and level > previous + 1:
                self.add("heading-skip", "warning", number, f"見出しの階層が飛んでいる(H{previous} → H{level}): {title[:40]}")
            previous = level
        emoji = [n for n, _, t in self.doc.headings if EMOJI.match(t)]
        if len(emoji) > 3:
            self.add("emoji-headings", "warning", emoji[0], f"絵文字つきの見出しが {len(emoji)} 個ある")
        if len(self.doc.lines) > 500:
            self.add("too-long", "warning", 1, f"{len(self.doc.lines)} 行ある。詳細は docs/ へ移して README は入口にする")

    def summary_after(self, h1_line: int):
        for number, line in self.doc.prose:
            if number <= h1_line:
                continue
            stripped = line.strip()
            if not stripped or re.match(r"^<[^>]*>$", stripped) or re.fullmatch(r"(\[?!\[[^\]]*\]\([^)]*\)\]?(\([^)]*\))?\s*)+", stripped):
                continue
            if stripped.startswith("#"):
                break
            return
        self.add("summary-missing", "warning", h1_line, "H1 の直後に、何のためのものかを述べる 1 行〜数行の説明が無い")

    def style(self):
        for number, line in self.doc.prose:
            match = HYPE.search(re.sub(r"`[^`]*`", "", line))
            if match:
                self.add("hype-words", "warning", number, f"誇大な言い回し: 「{match.group(0)}」。事実(数値・比較)で書く")
        for block in self.doc.blocks:
            if block["lang"] == "":
                self.add("fence-no-lang", "warning", block["line"], "コードブロックに言語の指定が無い(text なども可)")

    def inline_paths(self):
        for number, line in self.doc.prose:
            if REF_DEF.match(line):
                continue
            for match in re.finditer(r"`([^`\s]+)`", line):
                token = match.group(1)
                if not re.fullmatch(r"[\w.@/-]+", token) or "/" not in token or token.startswith(("/", "-", "~", ".../")):
                    continue
                if "..." in token or not (token.endswith("/") or re.search(r"\.\w{1,5}$", token)):
                    continue
                if re.match(r"^[\w-]+\.(com|org|io|dev|net|jp|ai)(/|$)", token) or re.match(r"^[\w.-]+/[\w.-]+$", token) and not token.endswith("/") and "." not in token.split("/")[-1]:
                    continue
                if not self.exists_anywhere(token.rstrip("/")):
                    self.add("path-missing", "warning", number, f"本文が挙げるパスがリポジトリに無い: {token}(実行時に作られるものなら無視してよい)")

    # --- license -------------------------------------------------------
    def license(self):
        info = self.facts["license"]
        claims = []
        mentioned = bool(re.search(r"licen[sc]e|ライセンス", "\n".join(t for _, t in self.doc.prose), re.I))
        section_lines: list[str] = []
        for index, (number, level, title) in enumerate(self.doc.headings):
            if re.search(r"licen[sc]e|ライセンス", title, re.I):
                end = next((n for n, lv, _ in self.doc.headings[index + 1:] if lv <= level), len(self.doc.lines) + 1)
                section_lines += [t for n, t in self.doc.prose if number < n < end]
                license_line = number
                break
        else:
            license_line = 1
        phrase = [t for _, t in self.doc.prose if re.search(r"(?i)licen[sc]ed? (under|:)|released under|license:|ライセンス[:：]", t)]
        for text in section_lines + phrase:
            for spdx, pattern in LICENSE_NAMES:
                if re.search(pattern, text, re.I):
                    claims.extend(spdx.split("|"))
                    break
        has_claim = bool(claims)  # 「未定」「選んでいない」のような記述は、license を名乗ったとは見なさない
        if has_claim and not info["present"]:
            self.add("license-missing-file", "error", license_line, "README は license を名乗るが、リポジトリに LICENSE ファイルが無い")
        elif info["present"] and info["spdx"] and claims and info["spdx"] not in claims:
            self.add("license-mismatch", "error", license_line, f"README は {sorted(set(claims))} と書くが、{info['file']} は {info['spdx']}")
        elif info["present"] and not mentioned:
            self.add("license-unmentioned", "warning", 1, f"{info['file']} があるのに README が license に触れていない")

    def run(self) -> list[dict]:
        for step in (self.links, self.commands, self.placeholders, self.structure, self.style, self.inline_paths, self.license):
            step()
        order = {"error": 0, "warning": 1, "info": 2}
        return sorted(self.findings, key=lambda f: (f["line"], order[f["severity"]], f["id"]))


def check(readme: Path, repo: Path | None = None) -> list[dict]:
    readme = Path(readme)
    return Checker(readme, Path(repo) if repo else readme.parent).run()


PROJECT_MARKERS = ("pyproject.toml", "package.json", "Cargo.toml", "go.mod", "LICENSE", "Makefile", "mise.toml", "justfile")


def find_repo(readme: Path) -> Path:
    """README のあるディレクトリが 1 つのプロジェクトなら、そこ。違えば .git のある親。無ければ README の場所。

    作業ツリーの中に別のプロジェクトが入れ子になっていても、外側の .git に引きずられないようにする。
    """
    here = readme.resolve().parent
    if any((here / name).exists() for name in PROJECT_MARKERS):
        return here
    for parent in [here, *here.parents]:
        if (parent / ".git").exists():
            return parent
    return here


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("readme", type=Path)
    parser.add_argument("--repo", type=Path, help="リポジトリのルート(既定: .git のある親、無ければ README の場所)")
    parser.add_argument("--json", action="store_true", help="JSON で出力する")
    parser.add_argument("--strict", action="store_true", help="warning でも失敗(1)にする")
    args = parser.parse_args(argv)
    if not args.readme.is_file():
        print(f"README が無い: {args.readme}", file=sys.stderr)
        return 2
    repo = args.repo or find_repo(args.readme)
    findings = check(args.readme, repo)
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("error", "warning", "info")}
    if args.json:
        print(json.dumps({"readme": str(args.readme), "repo": str(repo), "summary": counts, "findings": findings}, ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"{args.readme}:{f['line']}: {f['severity']} [{f['id']}] {f['message']}")
        print(f"\nerror {counts['error']} / warning {counts['warning']} / info {counts['info']}")
        print("この検査は存在の確認のみ。README のコマンドの実行結果・外部リンクの到達性は確かめていない。")
    return 1 if counts["error"] or (args.strict and counts["warning"]) else 0


if __name__ == "__main__":
    sys.exit(main())
