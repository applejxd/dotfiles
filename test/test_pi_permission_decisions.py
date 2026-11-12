"""pi の権限の方針 (stock) を、実際の判定エンジンに通して、(コマンド → 判定) の表と照合する。

- ``pi-permission-policy.json`` を、``@gotgenes/pi-permission-system`` の判定エンジンに直接入れて評価する
  (YOLO は切った状態。bash は複合コマンドの分解とラッパーの床を含む)。
- ``home/dot_cc-safety-net/`` の規則を、``cc-safety-net`` の ``explain`` に通す。
- 表は ``test/agents/pi_stock/permission_cases.json``。規則を変えたら、表に例を足して回す
  (規則の書き間違いと、誤判定 = 通常の作業を止める・危険な形を通す、を開発の段階で見つける)。

pi の package が入っていない環境 (CI など) では skip する。skip は通過ではない。
see docs/spec/agent-config-generation.md#permission-system-の設定
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "home" / ".chezmoitemplates" / "pi-permission-policy.json"
CSN_RULES = ROOT / "home" / "dot_cc-safety-net" / "rules"
DRIVER = ROOT / "test" / "agents" / "pi_stock" / "permission_check.mjs"
CASES = json.loads((ROOT / "test" / "agents" / "pi_stock" / "permission_cases.json").read_text(encoding="utf-8"))

AGENT_DIR = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")
NODE_MODULES = AGENT_DIR / "npm" / "node_modules"
PERMISSION_PKG = NODE_MODULES / "@gotgenes" / "pi-permission-system"
JITI = NODE_MODULES / "jiti"
CSN_CLI = NODE_MODULES / "cc-safety-net" / "dist" / "bin" / "cc-safety-net.js"


def _alias_root() -> Path | None:
    """pi 本体の install (``@earendil-works/*`` を含む node_modules)。版を問わず、新しい方を使う。"""
    for base in (AGENT_DIR / "install" / "releases", Path(os.environ.get("PI_MANAGED_INSTALL_ROOT", "")) / "releases"):
        found = sorted(base.glob("*/node_modules/@earendil-works/pi-coding-agent")) if base.is_dir() else []
        if found:
            return found[-1].parents[1]
    return None


ALIAS_ROOT = _alias_root()

needs_engine = pytest.mark.skipif(
    not (shutil.which("node") and PERMISSION_PKG.is_dir() and JITI.is_dir() and ALIAS_ROOT),
    reason="pi-permission-system の package か node が無い (pi を入れた機械でだけ回る)",
)
needs_csn = pytest.mark.skipif(
    not (shutil.which("node") and CSN_CLI.is_file()),
    reason="cc-safety-net の package か node が無い (pi を入れた機械でだけ回る)",
)


def _home(value: str) -> str:
    """表の ``$HOME`` を、この機械のホームへ展開する (規則の ``~`` は規則の側だけが展開され、値は展開されない)。"""
    return value.replace("$HOME", str(Path.home()))


def run_engine(tmp_path: Path, *, bash=(), surface=(), access=(), alias=(), project=None, name="in") -> dict:
    payload = {
        "pkg": str(PERMISSION_PKG),
        "jiti": str(JITI),
        "aliasRoot": str(ALIAS_ROOT),
        "policy": json.loads(POLICY.read_text(encoding="utf-8")),
        "bash": list(bash),
        "surface": [[s[0], _home(s[1])] for s in surface],
        "access": [_home(c) for c in access],
        "alias": [[a[0], [_home(v) for v in a[1]]] for a in alias],
    }
    if project is not None:
        payload["project"] = project
    src = tmp_path / f"{name}.json"
    src.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    done = subprocess.run(
        ["node", str(DRIVER), str(src)], capture_output=True, text=True, encoding="utf-8", timeout=180, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def engine_result(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("perm")
    return run_engine(
        tmp,
        bash=[c["cmd"] for c in CASES["bash"]],
        surface=CASES["surface"],
        access=[c[0] for c in CASES["access"]],
        alias=CASES.get("alias", []),
    )


@needs_engine
def test_bash_decisions_match_the_table(engine_result):
    """表の (コマンド → 判定)。ずれは、規則の書き間違い・通常の作業を止める誤判定・危険な形の見逃しのどれか。"""
    bad = []
    for case, got in zip(CASES["bash"], engine_result["bash"], strict=True):
        if got["state"] != case["perm"]:
            bad.append(f"{case['cmd']!r}: 期待 {case['perm']} / 実際 {got['state']} ({got['pattern']})")
    assert not bad, "\n".join(bad)


@needs_engine
def test_every_bash_rule_is_exercised_by_the_table(engine_result):
    """方針の bash の規則は、表のどれかの例が当たる (当たらない規則は、書き間違いか、表の不足)。"""
    policy_rules = set(json.loads(POLICY.read_text(encoding="utf-8"))["permission"]["bash"]) - {"*"}
    hit = {g["pattern"] for g in engine_result["bash"]}
    assert not (policy_rules - hit), f"表のどの例も当たらない規則: {sorted(policy_rules - hit)}"


@needs_engine
def test_surface_decisions_match_the_table(engine_result):
    bad = []
    for case, got in zip(CASES["surface"], engine_result["surface"], strict=True):
        if got["action"] != case[2]:
            bad.append(f"{case[0]} {case[1]!r}: 期待 {case[2]} / 実際 {got['action']} ({got['pattern']})")
    assert not bad, "\n".join(bad)


@needs_engine
def test_alias_decisions_match_the_table(engine_result):
    """symlink の別名と解決後の実体を合わせた判定 (値のどれかに一致した、設定上で最後の規則が勝つ)。

    別名が allow に一致すれば、実体が既定の ask でも allow になる。実体側が、allow より後ろの ask に一致するときだけ ask に戻る。
    """
    bad = []
    for case, got in zip(CASES.get("alias", []), engine_result["alias"], strict=True):
        if got["action"] != case[2]:
            bad.append(f"{case[0]} {case[1]!r}: 期待 {case[2]} / 実際 {got['action']} ({got['pattern']})")
    assert not bad, "\n".join(bad)


@needs_engine
def test_bash_path_effects_match_the_table(engine_result):
    """bash のトークンの向き (read / write / unproven)。commandEffects の宣言と、それを外す旗が、意図どおりに効くこと。

    向きは surface の判定と合わせて読む: unproven は読み取りと書き込みの両方を調べ、厳しい方になる。
    """
    bad = []
    for case, got in zip(CASES["access"], engine_result["access"], strict=True):
        cmd, expected = case
        actual = [[_short(a["path"]), a["effect"]] for a in got]
        if actual != [[e[0], e[1]] for e in expected]:
            bad.append(f"{cmd!r}: 期待 {expected} / 実際 {actual}")
    assert not bad, "\n".join(bad)


def _short(path: str) -> str:
    """ホームを ``$HOME`` に戻して、表と同じ書き方にする。"""
    home = str(Path.home())
    return path.replace(home, "$HOME", 1) if path.startswith(home) else path


@needs_engine
@pytest.mark.parametrize("variant", ["project", "project_deny_write"])
def test_project_config_recipe(tmp_path, variant):
    """docs の「プロジェクト単位でデータセットを読み取り専用にする」の設定が、グローバルの方針と合成されること。"""
    case = CASES[variant]
    got = run_engine(tmp_path, surface=case["surface"], project=case["config"], name=variant)
    bad = [
        f"{s[0]} {s[1]!r}: 期待 {s[2]} / 実際 {g['action']} ({g['pattern']})"
        for s, g in zip(case["surface"], got["surface"], strict=True)
        if g["action"] != s[2]
    ]
    assert not bad, "\n".join(bad)


def _explain(home: Path, workdir: Path, cmd: str) -> tuple[str, str]:
    env = {**os.environ, "CC_SAFETY_NET_HOME": str(home)}
    done = subprocess.run(
        ["node", str(CSN_CLI), "explain", "--json", cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
        cwd=workdir,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-1000:]
    data = json.loads(done.stdout)
    return data["result"], data.get("ruleId") or ""


@needs_csn
def test_cc_safety_net_decisions_match_the_table(tmp_path):
    """cc-safety-net (リポジトリの規則つき) が、表の blocked / allowed と一致すること。"""
    home = tmp_path / "csn"
    shutil.copytree(CSN_RULES, home / "rules")
    workdir = tmp_path / "work"
    workdir.mkdir()
    cases = CASES["bash"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda c: _explain(home, workdir, c["cmd"]), cases))
    bad = [
        f"{c['cmd']!r}: 期待 {c['csn']} / 実際 {r[0]} ({r[1]})"
        for c, r in zip(cases, results, strict=True)
        if r[0] != c["csn"]
    ]
    assert not bad, "\n".join(bad)


def test_cc_safety_net_rulebook_files_are_wellformed():
    """配る規則ファイルの形 (cc-safety-net が無くても検査できる範囲)。"""
    rule = json.loads((CSN_RULES / "rule.json").read_text(encoding="utf-8"))
    assert rule["version"] == 1 and rule["rules"] == ["dotfiles-guard"]
    assert {"name": "bg_run", "cwd": "cwd"} in rule["command_tools"]  # bg_run の中身も解析させる
    book = json.loads((CSN_RULES / "dotfiles-guard" / "rulebook.json").read_text(encoding="utf-8"))
    assert book["name"] == "dotfiles-guard" and book["rulebook_version"] == 1
    assert [r["name"] for r in book["rules"]] == ["git-push"]
    assert all(r["command"] in book["allowed_commands"] for r in book["rules"])
