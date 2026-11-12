"""pi の圧縮の設定を検証する。

- ~/.pi/agent/compaction.json (modify_compaction.json.py.tmpl): 指示の強制・onError の補い・利用者のキーの保持
- ~/.pi/agent/settings.json の compaction.modelOverrides (modify_pi_stock_settings.py.tmpl) の補い方
- pi-stock-packages に pi-compaction が入ること・compaction.json を除外しないこと
実機の chezmoi apply は行わない。
see docs/spec/agent-config-generation.md#圧縮の設定
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME_SRC = ROOT / "home"
COMPACTION_CONFIG = ".pi/agent/compaction.json"
COMPACTION_MODIFY = "dot_pi/agent/modify_compaction.json.py.tmpl"
SETTINGS_MODIFY = "dot_pi/agent/modify_settings.json.py.tmpl"
SONNET = "github-copilot/claude-sonnet-5.5"
# 発動点 = 窓 - reserveTokens。窓 100 万のモデルは 30 万 (70 万で発動)
RESERVE = 300000
WINDOW_1M_MODELS = (
    SONNET,
    "github-copilot/claude-opus-5.5",
    "github-copilot/claude-sonnet-5",
    "github-copilot/gpt-6-sol",
    "github-copilot/gpt-5.3-codex",
    "github-copilot/gemini-3.8-flash",
)
BRIEF_MARKERS = (
    "続きの作業のための brief",
    "1. 利用者の依頼・目的（ほぼ逐語で）",
    "2. 利用者の指示・好み・制約・確定した決定",
    "8. 行き止まり",
    "10. 参照すべきファイル",
    "観察を作らない。",
    "利用者の指示と好みは、削らない。",
)


def chezmoi_bin() -> str:
    found = shutil.which("chezmoi")
    if found is None:
        pytest.skip("chezmoi is not installed")
    return found


def render(template: str, home: Path) -> str:
    context = {
        "chezmoi": {
            "os": "linux",
            "username": "tester",
            "kernel": {"osrelease": "Linux"},
            "homeDir": str(home),
            "workingTree": str(ROOT),
        }
    }
    wrapped = (
        "{{ with " + json.dumps(json.dumps(context)) + " | fromJson }}" + template + "{{ end }}"
    )
    env = dict(os.environ)
    result = subprocess.run(
        [chezmoi_bin(), "--source", str(ROOT), "execute-template"],
        input=wrapped,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def render_file(name: str, home: Path, **kw) -> str:
    return render((HOME_SRC / name).read_text(encoding="utf-8"), home, **kw)


def make_script(tmp_path: Path, name: str) -> Path:
    script = tmp_path / (Path(name).name + ".py")
    script.write_text(render_file(name, tmp_path), encoding="utf-8")
    return script


def run_script(script: Path, stdin: str) -> str:
    result = subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


@pytest.fixture
def compaction_script(tmp_path: Path) -> Path:
    return make_script(tmp_path, COMPACTION_MODIFY)


@pytest.fixture
def settings_script(tmp_path: Path) -> Path:
    return make_script(tmp_path, SETTINGS_MODIFY)


def run_compaction(script: Path, current: object) -> dict:
    stdin = current if isinstance(current, str) else json.dumps(current)
    return json.loads(run_script(script, stdin))


def run_settings(script: Path, current: object) -> dict:
    stdin = current if isinstance(current, str) else json.dumps(current)
    return json.loads(run_script(script, stdin))


# --- compaction.json ----------------------------------------------------


def test_compaction_from_empty_input_has_instructions_and_on_error(compaction_script):
    out = run_compaction(compaction_script, "")
    assert set(out) == {"defaults"}
    assert set(out["defaults"]) == {"instructions", "onError"}
    assert out["defaults"]["onError"] == "default"
    for marker in BRIEF_MARKERS:
        assert marker in out["defaults"]["instructions"], marker


def test_compaction_instructions_list_ten_items_in_order(compaction_script):
    text = run_compaction(compaction_script, "")["defaults"]["instructions"]
    positions = [text.index(f"{n}. ") for n in range(1, 11)]
    assert positions == sorted(positions)


def test_compaction_does_not_set_auto_model_effort_style(compaction_script):
    defaults = run_compaction(compaction_script, "")["defaults"]
    for key in ("auto", "model", "effort", "style"):
        assert key not in defaults, key
    assert "thresholdTokens" not in json.dumps(defaults)
    assert "thresholdPercent" not in json.dumps(defaults)


def test_compaction_forces_instructions_but_keeps_user_values(compaction_script):
    current = {
        "defaults": {
            "instructions": "古い指示",
            "onError": "cancel",
            "auto": {"enabled": True, "thresholdPercent": 50},
            "effort": "low",
            "model": "current",
            "style": "native",
        },
        "models": {"github-copilot/x": {"effort": "high"}},
        "$schema": "https://example.invalid/schema.json",
    }
    out = run_compaction(compaction_script, current)
    d = out["defaults"]
    assert d["instructions"] != "古い指示"
    assert BRIEF_MARKERS[0] in d["instructions"]
    assert d["onError"] == "cancel"  # 利用者の値は保つ (無いときだけ補う)
    assert d["auto"] == {"enabled": True, "thresholdPercent": 50}
    assert (d["effort"], d["model"], d["style"]) == ("low", "current", "native")
    assert out["models"] == current["models"]
    assert out["$schema"] == current["$schema"]


def test_compaction_replaces_non_object_defaults(compaction_script):
    out = run_compaction(compaction_script, {"defaults": "壊れた形", "models": {}})
    assert out["defaults"]["onError"] == "default"
    assert out["models"] == {}


def test_compaction_is_idempotent(compaction_script):
    first = run_script(compaction_script, "")
    assert run_script(compaction_script, first) == first
    user = json.dumps({"defaults": {"onError": "cancel", "effort": "low"}, "models": {"a/b": {}}})
    once = run_script(compaction_script, user)
    assert run_script(compaction_script, once) == once


@pytest.mark.parametrize("broken", ["{broken", "[1, 2]", '"text"', "null"])
def test_compaction_leaves_broken_input_alone(compaction_script, broken):
    assert run_script(compaction_script, broken) == broken


# --- settings.json の compaction.modelOverrides -------------------------------


def test_settings_adds_reserve_tokens_for_one_million_window_models(settings_script):
    out = run_settings(settings_script, "")
    overrides = out["compaction"]["modelOverrides"]
    assert set(overrides) == set(WINDOW_1M_MODELS)
    for model in WINDOW_1M_MODELS:
        assert overrides[model] == {"reserveTokens": RESERVE}, model
    # 発動点 = 窓 (100 万) - reserveTokens = 70 万
    assert 1_000_000 - overrides[SONNET]["reserveTokens"] == 700_000


def test_settings_does_not_touch_other_window_models(settings_script):
    overrides = run_settings(settings_script, "")["compaction"]["modelOverrides"]
    assert "github-copilot/claude-haiku-4.5" not in overrides  # 窓 20 万


def test_settings_keeps_user_reserve_tokens_and_other_compaction_keys(settings_script):
    current = {
        "compaction": {
            "enabled": True,
            "reserveTokens": 20000,
            "keepRecentTokens": 30000,
            "modelOverrides": {
                SONNET: {"reserveTokens": 500000, "keepRecentTokens": 1234},
                "github-copilot/claude-opus-5.5": {"keepRecentTokens": 99},
                "other/model": {"reserveTokens": 1},
            },
        }
    }
    out = run_settings(settings_script, current)["compaction"]
    assert out["enabled"] is True
    assert out["reserveTokens"] == 20000
    assert out["keepRecentTokens"] == 30000
    ov = out["modelOverrides"]
    assert ov[SONNET] == {"reserveTokens": 500000, "keepRecentTokens": 1234}  # 利用者の値を保つ
    assert ov["github-copilot/claude-opus-5.5"] == {
        "keepRecentTokens": 99,
        "reserveTokens": RESERVE,
    }
    assert ov["other/model"] == {"reserveTokens": 1}
    assert ov["github-copilot/gpt-6-sol"] == {"reserveTokens": RESERVE}


def test_settings_compaction_is_idempotent(settings_script):
    first = run_script(settings_script, "")
    assert run_script(settings_script, first) == first


def test_settings_leaves_unexpected_compaction_shapes_alone(settings_script):
    for shape in ("text", 5, [1], {"modelOverrides": "x"}):
        out = run_settings(settings_script, {"compaction": shape})
        assert out["compaction"] == shape, shape
    out = run_settings(settings_script, {"compaction": {"modelOverrides": {SONNET: "x"}}})
    assert out["compaction"]["modelOverrides"][SONNET] == "x"
    assert out["compaction"]["modelOverrides"]["github-copilot/gpt-6-sol"] == {
        "reserveTokens": RESERVE
    }


def test_settings_still_leaves_broken_input_alone(settings_script):
    assert run_script(settings_script, "{broken") == "{broken"


# --- package と配備の範囲 -------------------------------------------------


def test_stock_packages_include_pi_compaction_pinned(tmp_path):
    text = render('{{ includeTemplate "pi-stock-packages" . }}', tmp_path)
    assert "npm:@thgilciffart/pi-compaction@0.3.1" in {line.strip() for line in text.splitlines()}


def test_deploys_compaction_config(tmp_path):
    ignore = {
        line.strip()
        for line in render_file(".chezmoiignore.tmpl", tmp_path).splitlines()
    }
    assert COMPACTION_CONFIG not in ignore
