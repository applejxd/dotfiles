"""並列実装のオーケストレーション用の共通部品。標準ライブラリだけで動く (Windows でも動く書き方)。

リポジトリの形 (git-flow-next / git-flow AVH / 素の git、統合先の枝、作業枝の接頭辞、worktree の置き場) を
検出して「プロファイル」にする。検出の規則・設定の鍵は docs/spec/orchestration.md を参照。
曖昧なときは黙って推測せず、ambiguous に候補を入れて終了コード 4 で止める。
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AMBIGUOUS = 4

STANDALONE_CONFIG = ".agents/config/orchestration.gitconfig"
SHARED_CONFIG = ".gitflow"
DEFAULT_TEMPLATE = ".tmp/worktrees/{name}"
DEFAULT_PREFIX = "feature/"
# 幹の枝の候補。末尾の区間がこれに一致する枝 (production/develop など) も候補にする。
BASE_NAMES = ("main", "master", "trunk", "develop", "dev", "development")
TRUNK_NAMES = ("main", "master", "trunk")

# コマンドごとの必須項目。必要な項目が曖昧なコマンドだけが止まる。
REQUIRED_ITEMS: dict[str, tuple[str, ...]] = {
    "profile": ("integration", "topic", "worktrees"),
    "owner": (),
    "clean": ("integration", "topic"),
    "list": ("integration", "topic"),
    "start": ("integration", "topic", "worktrees"),
    "bundle": ("integration", "topic", "worktrees"),
}


class OrchError(Exception):
    """使い方・前提の違反 (code=2) や曖昧 (code=4)。"""

    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.code = code


# ---------- git の呼び出し ----------


def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """global / system の設定を読まない環境。ロケールは固定する。"""
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "LC_ALL": "C",
    }
    if extra:
        env.update(extra)
    return env


def run_git(
    args: list[str], cwd: Path | str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env if env is not None else git_env(),
        check=False,
    )


def git_out(args: list[str], cwd: Path | str) -> str | None:
    """成功したときだけ stdout (末尾の改行なし)。失敗は None。"""
    r = run_git(args, cwd)
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


# ---------- git config の読み取り ----------

Config = list[tuple[str, str]]


def _parse_config(text: str) -> Config:
    out: Config = []
    for rec in text.split("\0"):
        if rec:
            key, _, value = rec.partition("\n")
            out.append((key, value))
    return out


def read_config(cwd: Path | str, *, file: Path | None = None) -> Config:
    """local の設定 (file 無し) か、指定したファイルの設定を (キー, 値) の列で返す。"""
    if file is not None:
        if not file.is_file():
            return []
        args = ["config", "--file", str(file), "--list", "-z"]
    else:
        args = ["config", "--local", "--list", "-z"]
    r = run_git(args, cwd)
    return _parse_config(r.stdout) if r.returncode == 0 else []


def read_global_keys(cwd: Path | str) -> list[str]:
    """global の gitflow.* / orchestration.* のキー (警告用。値は使わない)。"""
    env = {**os.environ, "GIT_CONFIG_SYSTEM": os.devnull, "LC_ALL": "C"}
    r = run_git(["config", "--global", "--list", "-z"], cwd, env)
    if r.returncode != 0:
        return []
    keys = {k for k, _ in _parse_config(r.stdout) if k.startswith(("gitflow.", "orchestration."))}
    return sorted(keys)


def _orch_section(cfg: Config) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, value in cfg:
        if key.startswith("orchestration."):
            out.setdefault(key[len("orchestration.") :].lower(), []).append(value)
    return out


class _Next:
    """git-flow-next の型設定 (gitflow.branch.<X>.<attr>) を読んだもの。"""

    def __init__(self, cfg: Config) -> None:
        self.types: dict[str, str] = {}
        self.attrs: dict[str, dict[str, str]] = {}
        self.worktree_path: str | None = None
        for key, value in cfg:
            if key == "gitflow.worktreepath":
                self.worktree_path = value
            if not key.startswith("gitflow.branch."):
                continue
            rest = key[len("gitflow.branch.") :]
            if "." not in rest:  # AVH の gitflow.branch.develop など
                continue
            name, attr = rest.rsplit(".", 1)
            self.attrs.setdefault(name, {})[attr] = value
            if attr == "type":
                self.types[name] = (
                    value  # gitflow.branch.feature/x.base のような枝ごとの記録は type ではない
                )

    def present(self) -> bool:
        return bool(self.types)

    def topic_types(self) -> list[str]:
        return [n for n, t in self.types.items() if t == "topic"]


def _avh(cfg: Config) -> dict[str, str]:
    """git-flow AVH のキー。値そのものが枝名・接頭辞。"""
    out: dict[str, str] = {}
    for key, value in cfg:
        if key in ("gitflow.branch.develop", "gitflow.branch.master") or key.startswith(
            "gitflow.prefix."
        ):
            out[key] = value
    return out


# ---------- 検出 ----------


class _Ctx:
    def __init__(self) -> None:
        self.sources: dict[str, str] = {}
        self.ambiguous: list[dict[str, Any]] = []
        self.warnings: list[str] = []


def _hint(toplevel: Path, item_key: str, example: str) -> str:
    target = SHARED_CONFIG if (toplevel / SHARED_CONFIG).is_file() else STANDALONE_CONFIG
    return f"git config -f {target} orchestration.{item_key} {example}"


def _explicit(var: str, local: dict[str, list[str]], files: list[tuple[str, dict[str, list[str]]]]):
    """明示設定 (local → 共有ファイル) の値。戻り値: (値の列, 出所, 曖昧な候補)。"""
    if local.get(var):
        return local[var], "git config --local", None
    found = [(src, d[var]) for src, d in files if d.get(var)]
    if not found:
        return None, None, None
    if len(found) > 1 and found[0][1] != found[1][1]:
        return None, None, [f"{src}: {', '.join(vals)}" for src, vals in found]
    return found[0][1], found[0][0], None


def _branch_refs(cwd: Path) -> tuple[set[str], set[str]]:
    out = (
        git_out(["for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes/origin"], cwd)
        or ""
    )
    local: set[str] = set()
    remote: set[str] = set()
    for ref in out.splitlines():
        if ref.startswith("refs/heads/"):
            local.add(ref[len("refs/heads/") :])
        elif ref.startswith("refs/remotes/origin/") and ref != "refs/remotes/origin/HEAD":
            remote.add(ref[len("refs/remotes/origin/") :])
    return local, remote


def _ref_for(branch: str, local: set[str], remote: set[str]) -> str | None:
    if branch in local:
        return f"refs/heads/{branch}"
    if branch in remote:
        return f"refs/remotes/origin/{branch}"
    return None


def _is_base_like(name: str) -> bool:
    return name.rsplit("/", 1)[-1] in BASE_NAMES


def _repo_info(cwd: Path) -> dict[str, Any]:
    """リポジトリの場所。git リポジトリでない・bare・コミット無しは OrchError (2)。"""
    if git_out(["rev-parse", "--git-dir"], cwd) is None:
        raise OrchError("git リポジトリではない")
    if git_out(["rev-parse", "--is-bare-repository"], cwd) == "true":
        raise OrchError("bare リポジトリでは動かない (作業コピーが要る)")
    toplevel = git_out(["rev-parse", "--show-toplevel"], cwd)
    if toplevel is None:
        raise OrchError("作業コピーの外では動かない")
    if git_out(["rev-parse", "--verify", "-q", "HEAD"], cwd) is None:
        raise OrchError("コミットが 1 つも無い")
    common = git_out(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd) or ""
    main_wt: str | None = None
    listing = git_out(["worktree", "list", "--porcelain"], cwd) or ""
    for line in listing.splitlines():
        if line.startswith("worktree "):
            main_wt = line[len("worktree ") :]
            break
    return {
        "toplevel": str(Path(toplevel)),
        "common_dir": str(Path(common)) if common else None,
        "main_worktree": str(Path(main_wt)) if main_wt else None,
    }


def detect_profile(
    cwd: Path | str,
    *,
    integration: str | None = None,
    prefixes: list[str] | None = None,
    worktrees_dir: str | None = None,
) -> dict[str, Any]:
    """リポジトリのプロファイル (v:1) を検出する。曖昧な項目は ambiguous に入る (例外にはしない)。"""
    cwd = Path(cwd)
    repo = _repo_info(cwd)
    toplevel = Path(repo["toplevel"])
    ctx = _Ctx()

    local_cfg = read_config(cwd)
    shared_cfg = read_config(cwd, file=toplevel / SHARED_CONFIG)
    file_cfg = read_config(cwd, file=toplevel / STANDALONE_CONFIG)
    local_orch = _orch_section(local_cfg)
    files = [
        (SHARED_CONFIG + " [orchestration]", _orch_section(shared_cfg)),
        (STANDALONE_CONFIG, _orch_section(file_cfg)),
    ]

    local_next = _Next(local_cfg)
    shared_next = _Next(shared_cfg)
    avh = _avh(local_cfg)

    # flow の判定 (local の next と AVH が両方ならば曖昧)
    flow = "none"
    nxt = local_next
    if local_next.present() and avh:
        ctx.ambiguous.append(
            {
                "item": "flow",
                "candidates": ["git-flow-next", "git-flow-avh"],
                "hint": "git config --local --unset-all で片方の gitflow.* を消すか、明示設定 (orchestration.integration) を置く",
            }
        )
        ctx.sources["flow"] = "ambiguous"
    elif local_next.present():
        flow, ctx.sources["flow"] = "git-flow-next", "local gitflow.branch.*.type"
    elif avh:
        flow, ctx.sources["flow"] = (
            "git-flow-avh",
            "local gitflow.branch.develop / gitflow.prefix.*",
        )
    elif shared_next.present():
        flow, ctx.sources["flow"] = "git-flow-next", f"{SHARED_CONFIG} (未 sync)"
        nxt = shared_next
    else:
        ctx.sources["flow"] = "none"
    flow_ambiguous = bool(ctx.ambiguous)
    if flow == "git-flow-next" and nxt is local_next and not nxt.worktree_path:
        nxt.worktree_path = (
            shared_next.worktree_path
        )  # worktreePath は .gitflow にだけあることがある

    local_branches, remote_branches = _branch_refs(cwd)
    all_branches = local_branches | remote_branches

    # 主トピック型 (next)。feature、無ければ唯一の topic 型。
    primary: str | None = None
    if flow == "git-flow-next":
        topics = nxt.topic_types()
        if "feature" in topics:
            primary = "feature"
        elif len(topics) == 1:
            primary = topics[0]
        elif len(topics) > 1:
            ctx.ambiguous.append(
                {
                    "item": "topic.prefixes",
                    "candidates": [nxt.attrs[t].get("prefix", t + "/") for t in topics],
                    "hint": _hint(toplevel, "topicPrefix", "<接頭辞>"),
                }
            )

    # --- integration / trunk ---
    integ: str | None = None
    trunk: str | None = None
    values, src, amb = _explicit("integration", local_orch, files)
    if integration:
        integ, ctx.sources["integration"] = integration, "cli"
    elif amb:
        ctx.ambiguous.append(
            {
                "item": "integration",
                "candidates": amb,
                "hint": _hint(toplevel, "integration", "<枝>"),
            }
        )
    elif values:
        integ, ctx.sources["integration"] = values[-1], src or ""
    elif primary and nxt.attrs[primary].get("parent"):
        integ = nxt.attrs[primary]["parent"]
        ctx.sources["integration"] = (
            f"git-flow-next ({'local' if nxt is local_next else SHARED_CONFIG})"
        )
    elif flow == "git-flow-avh" and avh.get("gitflow.branch.develop"):
        integ, ctx.sources["integration"] = avh["gitflow.branch.develop"], "git-flow-avh"
    elif not flow_ambiguous:
        cands = sorted(b for b in all_branches if _is_base_like(b))
        origin_head = git_out(["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], cwd)
        if len(cands) == 1:
            integ, ctx.sources["integration"] = cands[0], "shape (唯一の幹の枝)"
        elif not cands and origin_head and origin_head.startswith("origin/"):
            integ, ctx.sources["integration"] = origin_head[len("origin/") :], "shape (origin/HEAD)"
        elif len(cands) > 1:
            ctx.ambiguous.append(
                {
                    "item": "integration",
                    "candidates": cands,
                    "hint": _hint(toplevel, "integration", cands[0]),
                }
            )
        else:
            ctx.warnings.append(
                "統合先の枝を検出できない (幹の枝が無い)。--integration か設定で指定する"
            )
    else:
        ctx.sources["integration"] = "ambiguous"

    if integ is not None:
        if flow == "git-flow-next" and nxt.attrs.get(integ, {}).get("parent"):
            trunk = nxt.attrs[integ]["parent"]
        elif (
            flow == "git-flow-avh"
            and avh.get("gitflow.branch.master")
            and avh["gitflow.branch.master"] != integ
        ):
            trunk = avh["gitflow.branch.master"]
        else:
            others = sorted(
                b for b in all_branches if b.rsplit("/", 1)[-1] in TRUNK_NAMES and b != integ
            )
            trunk = others[0] if len(others) == 1 else None
        ctx.sources["trunk"] = "detected" if trunk else "none"
    integ_ref = _ref_for(integ, local_branches, remote_branches) if integ else None
    if integ and integ_ref is None:
        ctx.warnings.append(f"統合先の枝 {integ} がローカルにも origin にも無い")

    # --- topic ---
    topic_prefixes: list[str] = []
    new_prefix: str | None = None
    values, src, amb = _explicit("topicprefix", local_orch, files)
    if prefixes:
        topic_prefixes, ctx.sources["topic.prefixes"] = list(prefixes), "cli"
    elif amb:
        ctx.ambiguous.append(
            {
                "item": "topic.prefixes",
                "candidates": amb,
                "hint": _hint(toplevel, "topicPrefix", "<接頭辞>"),
            }
        )
    elif values:
        topic_prefixes, ctx.sources["topic.prefixes"] = list(values), src or ""
    elif primary and nxt.attrs[primary].get("prefix"):
        topic_prefixes = [nxt.attrs[primary]["prefix"]]
        ctx.sources["topic.prefixes"] = (
            f"git-flow-next ({'local' if nxt is local_next else SHARED_CONFIG})"
        )
    elif flow == "git-flow-avh" and avh.get("gitflow.prefix.feature"):
        topic_prefixes, ctx.sources["topic.prefixes"] = (
            [avh["gitflow.prefix.feature"]],
            "git-flow-avh",
        )
    elif not any(a["item"] == "topic.prefixes" for a in ctx.ambiguous):
        found = _shape_prefixes(local_branches, integ, trunk)
        if len(found["feature_ns"]) > 1:
            ctx.ambiguous.append(
                {
                    "item": "topic.prefixes",
                    "candidates": found["feature_ns"],
                    "hint": _hint(toplevel, "topicPrefix", "<接頭辞>"),
                }
            )
        elif found["feature_ns"]:
            topic_prefixes, ctx.sources["topic.prefixes"] = (
                found["feature_ns"],
                "shape (枝名の分布)",
            )
        elif found["others"]:
            ctx.sources["topic.prefixes"] = "shape (接頭辞なし: 幹以外の枝すべて)"
        else:
            topic_prefixes, ctx.sources["topic.prefixes"] = [DEFAULT_PREFIX], "default"
    nvals, _, _ = _explicit("newprefix", local_orch, files)
    if nvals:
        new_prefix = nvals[-1]
    elif topic_prefixes:
        new_prefix = topic_prefixes[0]
    start_point = None
    if primary and nxt.attrs[primary].get("startpoint"):
        start_point = nxt.attrs[primary]["startpoint"]
    elif integ:
        start_point = integ
    also, _, _ = _explicit("alsolist", local_orch, files)

    # --- worktrees ---
    template = DEFAULT_TEMPLATE
    values, src, amb = _explicit("worktreedir", local_orch, files)
    if worktrees_dir:
        template, ctx.sources["worktrees"] = _to_template(worktrees_dir), "cli"
    elif values:
        template, ctx.sources["worktrees"] = _to_template(values[-1]), src or ""
    elif amb:
        ctx.ambiguous.append(
            {
                "item": "worktrees",
                "candidates": amb,
                "hint": _hint(toplevel, "worktreeDir", "<ディレクトリ>"),
            }
        )
    elif flow == "git-flow-next" and nxt.worktree_path:
        template = re.sub(r"\{\{\s*branchName\s*\}\}", "{name}", nxt.worktree_path)
        ctx.sources["worktrees"] = "git-flow-next gitflow.worktreePath"
    else:
        ctx.sources["worktrees"] = "default"
    base_abs, inside, ignored = _worktree_base(template, repo, cwd)

    verify, vsrc, _ = _explicit("verifycmd", local_orch, files)
    overlay, osrc, _ = _explicit("overlay", local_orch, files)
    gate, _, _ = _explicit("gatechecks", local_orch, files)
    ctx.sources["verify"] = vsrc or "none"
    ctx.sources["overlay"] = osrc or "none"

    gkeys = read_global_keys(cwd)
    if gkeys:
        ctx.warnings.append("global の設定は読まない (無視した): " + ", ".join(gkeys))

    return {
        "v": SCHEMA_VERSION,
        "flow": flow,
        "integration": {"branch": integ, "ref": integ_ref},
        "trunk": trunk,
        "topic": {
            "prefixes": topic_prefixes,
            "new_prefix": new_prefix,
            "start_point": start_point,
            "also_list": also or [],
        },
        "worktrees": {
            "template": template,
            "base_abs": base_abs,
            "inside_repo": inside,
            "ignored": ignored,
        },
        "verify": {"cmd": verify[-1]} if verify else None,
        "overlay": overlay or [],
        "gate_checks": gate or [],
        "repo": repo,
        "sources": ctx.sources,
        "ambiguous": ctx.ambiguous,
        "warnings": ctx.warnings,
    }


def _to_template(value: str) -> str:
    value = value.replace("\\", "/").rstrip("/")
    return value if "{name}" in value else value + "/{name}"


def _worktree_base(template: str, repo: dict[str, Any], cwd: Path) -> tuple[str, bool, bool | None]:
    root = Path(repo["main_worktree"] or repo["toplevel"])
    head = template.split("{name}")[0].rstrip("/")
    base = Path(head) if head else Path(".")
    base_abs = base if base.is_absolute() else root / base
    base_abs = Path(os.path.normpath(base_abs))
    try:
        base_abs.relative_to(root)
        inside = True
    except ValueError:
        inside = False
    ignored: bool | None = None
    if inside:
        ignored = run_git(["check-ignore", "-q", str(base_abs / "x")], root).returncode == 0
    return base_abs.as_posix(), inside, ignored


def _shape_prefixes(local: set[str], integ: str | None, trunk: str | None) -> dict[str, list[str]]:
    """枝名の分布から作業枝の接頭辞を拾う。名前空間が feature/ で終わるものだけが「feature の名前空間」。"""
    feature_ns: set[str] = set()
    others: set[str] = set()
    for b in local:
        if b in (integ, trunk) or _is_base_like(b):
            continue
        if "/" in b:
            ns = b.rsplit("/", 1)[0] + "/"
            (feature_ns if ns.rsplit("/", 2)[-2] == "feature" else others).add(ns)
        else:
            others.add(b)
    return {"feature_ns": sorted(feature_ns), "others": sorted(others)}


# ---------- コマンドごとの必須項目 ----------


def blocking_ambiguities(profile: dict[str, Any], command: str) -> list[dict[str, Any]]:
    """command の必須項目に当たる曖昧さだけを返す。空ならそのコマンドは進んでよい。"""
    items = REQUIRED_ITEMS.get(command, ())
    out = []
    for a in profile["ambiguous"]:
        name = a["item"]
        if name == "flow":
            hit = "integration" in items and profile["integration"]["branch"] is None
        else:
            hit = name.split(".")[0] in items
        if hit:
            out.append(a)
    return out


def format_ambiguities(ambiguous: list[dict[str, Any]]) -> str:
    lines = ["曖昧で決められない項目がある (推測しない):"]
    for a in ambiguous:
        lines.append(f"  - {a['item']}: 候補 = {', '.join(a['candidates'])}")
        lines.append(f"      設定例: {a['hint']}")
    return "\n".join(lines)
