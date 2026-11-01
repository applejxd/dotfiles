"""index.ts への git_integrate の接続 (CHG-0055 P8c の最後の配線)。実際の pi (faux モデル) に、フルガードを載せて確かめる。

契約 (C1): ``[pi.pending] enabled`` と ``[pi.integrate] enabled`` の**両方が true**のときだけ、git_integrate が見える・使える。
どちらかが false のときは、ツールの説明・システムプロンプト・拒否の理由に、git_integrate を足さない (従来と同一)。
承認側の再判定 (authorize) と、TUI だけに出す案内は、実際の pi では回せないので、配線の有無を静的に見る。
see docs/change/0055-async-approval.md
"""

# ruff: noqa: F811
# fixture (env) を他の試験ファイルから import するので、引数名の再定義を許す
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_harness import HARNESS_SRC, PI, _rpc_outcome, bash_call, env, run_pi  # noqa: F401

pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

ALL_MODES = ["tui", "rpc", "print", "json", "text"]
# システムプロンプトには作業ディレクトリ (試験名を含む) が入るので、操作の id ではなくラベルで見る
LABEL = "保護ブランチへの統合 (squash)"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.test",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.test",
}


def _switches(env, *, pending: bool, integrate: bool, modes=None, confirm_timeout=None) -> None:
    """rules.json の judge.common.pi に、キルスイッチ (と、必要なら統合の確認) を入れる。"""
    path = env["harness"] / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    pi = rules["judge"]["common"].setdefault("pi", {})
    pi.setdefault("pending", {})["enabled"] = pending
    if modes is not None:
        pi["pending"]["modes"] = modes
    pi.setdefault("integrate", {})["enabled"] = integrate
    if confirm_timeout is not None:
        pi["confirm"] = {"timeout_seconds": confirm_timeout, "integration": True}
        pi["integrate"]["protected_refs"] = ["main", "master", "develop", "release/*", "hotfix/*"]
    path.write_text(json.dumps(rules), encoding="utf-8")


def _tool_descriptions(env) -> dict[str, str]:
    proc = run_pi(env, [], FAUX_DUMP_TOOLS="1")
    assert proc.returncode == 0, proc.stderr
    hit = re.search(r"TOOLDEFS=(\[.*\])", proc.stdout, re.S)
    assert hit, proc.stdout + proc.stderr
    return {d["name"]: d["description"] or "" for d in json.loads(hit.group(1))}


def _system_prompt(env) -> str:
    proc = run_pi(env, [], FAUX_DUMP_PROMPT="1")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


# --- C1: どちらかが false なら、何も足さない ---


@pytest.mark.parametrize(("pending", "integrate"), [(False, False), (True, False), (False, True)])
def test_git_integrate_is_invisible_unless_both_switches_are_on(env, pending, integrate):
    _switches(env, pending=pending, integrate=integrate)
    descs = _tool_descriptions(env)
    assert "guarded_action" in descs  # 承認つきの操作そのものは従来どおり
    assert "git_integrate" not in descs["guarded_action"]
    assert "git_integrate" not in descs["guarded_bash"]
    assert "/pending approve" not in descs["guarded_bash"]
    prompt = _system_prompt(env)
    assert LABEL not in prompt


def test_default_rules_are_the_enabled_ones(env):
    # 同梱の設定 (F4) は両方 true。既定の説明は、スイッチを明示的に true にしたときと同じ (false の側は上の試験が固定する)
    base = _tool_descriptions(env)
    _switches(env, pending=True, integrate=True)
    assert _tool_descriptions(env) == base


# --- 両方 true: 見える ---


def test_git_integrate_is_visible_when_both_switches_are_on(env):
    _switches(env, pending=True, integrate=True)
    descs = _tool_descriptions(env)
    assert "git_integrate" in descs["guarded_action"]
    assert (
        "git_integrate" in descs["guarded_bash"]
        and "git flow feature finish" in descs["guarded_bash"]
    )
    assert "- guarded_action: " in _system_prompt(env)
    assert LABEL in _system_prompt(env)
    # bash の説明の追記は bash だけ
    for name, text in descs.items():
        if name not in ("guarded_bash", "guarded_action"):
            assert "git_integrate" not in text, name


def _feature_worktree(tmp: Path) -> tuple[Path, Path]:
    """develop を持つ本体と、その linked worktree (feature/x、コミット 1 つ)。"""
    main, wt = tmp / "repo", tmp / "repo-wt"
    main.mkdir()
    genv = {**os.environ, **GIT_ENV}

    def git(cwd: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=genv,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    git(main, "init", "-q", "-b", "develop")
    (main / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "seed")
    git(main, "worktree", "add", "-q", "-b", "feature/x", str(wt))
    (wt / "x.txt").write_text("x\n", encoding="utf-8")
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", "x")
    return main, wt


def _git_out(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return done.stdout.strip()


CALL = [
    {
        "name": "guarded_action",
        "args": {
            "action": "git_integrate",
            "params": {"source": "feature/x", "message": "feat: x"},
        },
    }
]


def test_git_integrate_is_saved_not_run_when_both_switches_are_on(env):
    main, wt = _feature_worktree(env["tmp"])
    e = {**env, "proj": wt}
    _switches(e, pending=True, integrate=True, modes=ALL_MODES)
    develop = _git_out(main, "rev-parse", "develop")
    proc = run_pi(e, CALL)
    out = proc.stdout + proc.stderr
    assert "not approved:" in out and "保留" in out, out
    assert len(_git_out(main, "for-each-ref", "refs/pi/pending/").splitlines()) == 1, out
    assert _git_out(main, "rev-parse", "develop") == develop  # 統合は実行されない
    assert not (main / "x.txt").exists()


def test_git_integrate_is_not_callable_when_a_switch_is_off(env):
    main, wt = _feature_worktree(env["tmp"])
    e = {**env, "proj": wt}
    _switches(e, pending=True, integrate=False, modes=ALL_MODES)
    proc = run_pi(e, CALL)
    out = proc.stdout + proc.stderr
    assert "isError=true" in out and "unknown action" in out, out
    assert _git_out(main, "for-each-ref", "refs/pi/pending/") == ""


# --- 時間切れの案内は TUI だけ (RPC・print には足さない) ---

FINISH = "git flow feature finish x --squash"


@pytest.mark.parametrize("on", [False, True])
def test_the_timeout_guidance_is_tui_only(env, on):
    _switches(env, pending=on, integrate=on, modes=ALL_MODES, confirm_timeout=1)
    _, result = _rpc_outcome(env, bash_call(FINISH), [None])
    assert "not approved:" in result and "再試行せず" in result, result  # 従来の文言は保つ
    assert "git_integrate" not in result, result  # RPC は TUI でないので、足さない


# --- 配線の有無 (実際の pi では回せない箇所を、ソースで固定する) ---

INDEX = (HARNESS_SRC).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "needle",
    [
        r"integrateWiring\(rules\)",
        r"\.\.\.wiring\.specs",
        r"\.\.\.wiring\.request",
        r"\.\.\.wiring\.approval",
        r"authorize:\s*\(\w+\)\s*=>\s*authorizeRecord\(",
        r"integrateAction:\s*wiring\.enabled",
        r"integrationTimeoutGuidance\(",
        r'tui:\s*ctx\.mode === "tui"',
        # 案内の条件 (TUI でしか出ないので、RPC の試験では差が出ない。部品の真理値表は test_pi_integration_gate.py)
        r"integrationTimeoutGuidance\(\{[^}]*enabled:\s*wiring\.enabled",
        r"integrationTimeoutGuidance\(\{[^}]*hasActionTool:\s*roleTools\.includes\(ACTION_TOOL\)",
    ],
)
def test_index_wires_every_piece(needle):
    assert re.search(needle, INDEX, re.S), needle


def test_registries_stay_empty():
    # 配線は登録表を埋めない (有効なときだけ index.ts が足す)
    src = (ROOT / "home/dot_config/pi/harness/pending-adapters.ts").read_text(encoding="utf-8")
    assert "PENDING_ADAPTERS: Record<string, PendingAdapter> = {};" in src
    assert "APPROVAL_ADAPTERS: Record<string, ApprovalAdapter> = {};" in src
