"""scripts/ci_policy.py（保護パス判定・PR タイトル検証・ci-gate 集約判定）の試験。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_policy.py"

_spec = importlib.util.spec_from_file_location("ci_policy", SCRIPT)
assert _spec is not None and _spec.loader is not None
policy = importlib.util.module_from_spec(_spec)
sys.modules["ci_policy"] = policy
_spec.loader.exec_module(policy)


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/workflows/nested/release.yml",
        ".gitattributes",
        ".gitleaks.toml",
        ".gitleaksignore",
        ".pre-commit-config.yaml",
        ".python-version",
        "mise.toml",
        "pyproject.toml",
        "home/.chezmoi.toml.tmpl",
        "home/.chezmoiexternal.toml.tmpl",
        "home/.chezmoiignore.tmpl",
        "home/.chezmoitemplates/modify_pi_permission_config.py.tmpl",
        "home/.chezmoitemplates/modify_pi_stock_settings.py.tmpl",
        "home/.chezmoitemplates/pi-mcp-servers.toml",
        "home/.chezmoitemplates/pi-permission-policy.json",
        "home/dot_cc-safety-net/rules/dotfiles-guard/rulebook.json",
        "home/dot_config/dotfiles-ai/private_app.pem.tmpl",
        "home/dot_config/pi-sandbox/runner.toml",
        "home/dot_local/bin/executable_pib",
        "home/dot_local/bin/executable_pib-shell",
        "home/dot_local/bin/executable_pi-sandbox-runner",
        "home/dot_pi/agent/agents/worker.md",
        "home/dot_pi/agent/extensions/pi-permission-system/modify_config.json.py.tmpl",
        "home/dot_pi/agent/local-packages/t3-usage-status/src/index.ts",
        "home/dot_pi/agent/modify_mcp.json.py.tmpl",
        "home/dot_pi/agent/modify_settings.json.py.tmpl",
        "home/.chezmoiscripts/100_linux/run_once_after_121_ubuntu.sh.tmpl",
        "scripts/agents/validate_mcp.py",
        "scripts/agents/validate_skills.py",
        "scripts/check_staged_drop.py",
        "scripts/gitleaks_prepush.py",
        "scripts/lint_templates.py",
        "scripts/verify.py",
        "scripts/verify_stamp.py",
        "scripts/ci_policy.py",
        "scripts/ai_pr.py",
        "scripts/isolated_smoke.py",
        "scripts/chezmoi_safe_update.py",
        "test/agents/agents_common.py",
        "test/agents/conftest.py",
        "test/test_verify.py",
        "test/test_verify_stamp.py",
        "test/test_pi_permission_decisions.py",
        "test/agents/pi_stock/permission_cases.json",
        "test/test_pi_sandbox_runner.py",
        "test/test_pi_sandbox_toggle.py",
        "test/test_ci_policy.py",
        "test/test_ai_pr.py",
        "test/test_isolated_smoke.py",
        "test/test_chezmoi_safe_update.py",
        # Windows パス区切り・大文字小文字・./ 付きでもすり抜けないこと
        r".github\workflows\ci.yml",
        "HOME/.chezmoitemplates/PI-PERMISSION-POLICY.JSON",
        "./home/.chezmoitemplates/pi-permission-policy.json",
        "home/dot_pi/agent/extensions/../extensions/x.py",
    ],
)
def test_protected_paths_are_detected(path: str):
    assert policy.is_protected_path(path), path


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        "README.md",
        "home/dot_vimrc",
        "home/dot_agents/skills/commit/SKILL.md",
        ".agents/skills/dotfiles-conventions/SKILL.md",
        "home/dot_pi/agent/prompts/fleet.md",
        "home/dot_pi/agent/AGENTS.md.tmpl",
        "home/dot_config/shell/shellrc.sh.tmpl",
        "docs/spec/development.md",
        "docs/adr/0044-github-app-auto-merge-and-3os-ci.md",
        "home/dot_local/bin/executable_pk",
        "home/dot_local/bin/executable_pi-t3",
    ],
)
def test_non_protected_paths_allow_auto_merge(path: str):
    assert not policy.is_protected_path(path), path


@pytest.mark.parametrize(
    "title",
    [
        "fix(vim): SSH 経由では unnamedplus を無効にする",
        "feat: 3 OS CI と ci-gate を追加する",
        "docs(adr): ADR-0044 を起票する",
        "chore(deps)!: Python を 3.13 に固定する",
    ],
)
def test_valid_conventional_titles_pass(title: str):
    assert policy.validate_pr_title(title) is None


@pytest.mark.parametrize(
    "title",
    [
        "",
        "Update dot_vimrc",
        "fix(vim): 末尾ピリオドあり.",
        "fix(vim): " + "a" * 70,
        "fix(vim): 1行目\n2行目",
        "unknown: 未知のタイプ",
    ],
)
def test_invalid_titles_are_rejected(title: str):
    assert policy.validate_pr_title(title) is not None


def test_evaluate_gate_requires_strict_success_and_blocks_skipped():
    base = {"static": "success", "linux": "success", "windows": "success", "macos": "success"}
    assert policy.evaluate_gate(base, protected_required=False)[0] is True

    # 依存ジョブが skipped / cancelled / failure なら絶対に通過させない
    for bad in ("skipped", "cancelled", "failure", ""):
        broken = dict(base, windows=bad)
        ok, reasons = policy.evaluate_gate(broken, protected_required=False)
        assert ok is False
        assert any("windows" in r for r in reasons)

    # 保護パス変更があるときは承認ジョブの success が必須
    ok, reasons = policy.evaluate_gate(base, protected_required=True, approval_result="skipped")
    assert ok is False
    assert any("承認" in r for r in reasons)

    ok, _ = policy.evaluate_gate(base, protected_required=True, approval_result="success")
    assert ok is True


def test_cli_check_paths_writes_github_output(tmp_path, monkeypatch, capsys):
    out_file = tmp_path / "gh_out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))
    rc = policy.main(["check-paths", "home/dot_vimrc", "home/dot_pi/agent/extensions/foo.py"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["protected"] is True
    assert payload["protected_paths"] == ["home/dot_pi/agent/extensions/foo.py"]
    assert "protected=true\n" in out_file.read_text(encoding="utf-8")


def test_cli_check_gate_exit_codes():
    assert (
        policy.main(
            [
                "check-gate",
                "--job",
                "static=success",
                "--job",
                "linux=success",
                "--protected",
                "false",
            ]
        )
        == 0
    )
    assert (
        policy.main(
            [
                "check-gate",
                "--job",
                "static=success",
                "--job",
                "linux=skipped",
                "--protected",
                "false",
            ]
        )
        == 1
    )
    assert (
        policy.main(
            [
                "check-gate",
                "--job",
                "static=success",
                "--protected",
                "true",
                "--approval",
                "skipped",
            ]
        )
        == 1
    )


def test_junit_gate_rejects_zero_tests_and_excessive_skips(tmp_path):
    ok_xml = tmp_path / "ok.xml"
    ok_xml.write_text('<testsuites><testsuite tests="10" failures="0" errors="0" skipped="1"/></testsuites>', encoding="utf-8")
    assert policy.main(["check-junit", str(ok_xml), "--min-passed", "9", "--max-skipped", "1"]) == 0
    assert policy.main(["check-junit", str(ok_xml), "--min-passed", "10", "--max-skipped", "1"]) == 1
    assert policy.main(["check-junit", str(ok_xml), "--min-passed", "1", "--max-skipped", "0"]) == 1

    empty_xml = tmp_path / "empty.xml"
    empty_xml.write_text('<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>', encoding="utf-8")
    assert policy.main(["check-junit", str(empty_xml), "--min-passed", "0", "--max-skipped", "0"]) == 1


def test_ci_workflow_structure_keeps_always_gate_and_trusted_base():
    yaml = pytest.importorskip("yaml")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    jobs = wf["jobs"]
    gate = jobs["ci-gate"]
    assert gate["if"] == "always()"
    expected_needs = set(jobs.keys()) - {"ci-gate"}
    assert set(gate["needs"]) == expected_needs
    checkout_step = gate["steps"][0]
    assert "pull_request.base.sha" in checkout_step["with"]["ref"]
    # policy ジョブが base コミットの ci_policy.py を取り出していること
    policy_script = "\n".join(str(s.get("run", "")) for s in jobs["policy"]["steps"])
    assert 'git show "${BASE_SHA}:scripts/ci_policy.py"' in policy_script
    assert "git ls-tree" in policy_script
    assert "gitleaks git --log-opts" in policy_script
