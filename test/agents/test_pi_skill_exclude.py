"""pi の設定 ``skills`` の除外 (``-path``) が、自動で見つかるスキルにも効くかの試験 (実 pi・偽のモデル)。

システムプロンプトの ``<available_skills>`` を見る。HOME は一時ディレクトリ。
Orca・Herdr が入れるスキルを一覧から外す設定 ([pi.settings] skills) を、生成器の出力のまま使う。
see docs/spec/guard/pi-guard.md#pi-の設定
"""

from __future__ import annotations

# ruff: noqa: F811  (env はインポートしたフィクスチャ。引数名で使うので再定義に見える)
import json

from agents_common import load_common
from test_pi_harness import PI, env, gen, run_pi  # noqa: F401

HIDDEN = ("orchestration", "orca-cli", "computer-use", "herdr")
# (置き場, 名前)。herdr は ~/.claude/skills、Orca の 3 本は ~/.agents/skills
PLACES = [(".agents/skills", n) for n in HIDDEN[:3]] + [(".claude/skills", "herdr")]
KEPT = [(".agents/skills", "keepme"), (".claude/skills", "keepme2")]


def _home_with_skills(env):
    home = env["tmp"] / "home"
    for place, name in PLACES + KEPT:
        base = home / place / name
        base.mkdir(parents=True)
        (base / "SKILL.md").write_text(
            f'---\nname: {name}\ndescription: "DESC-{name}"\n---\n# {name}\n', encoding="utf-8"
        )
    return home


def _prompt(env, skills_setting):
    home = _home_with_skills(env)
    (env["tmp"] / "agent" / "settings.json").write_text(
        json.dumps({"skills": skills_setting}), encoding="utf-8"
    )
    proc = run_pi(env, [], extra=("--no-approve",), FAUX_DUMP_PROMPT="1", HOME=str(home))
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_baseline_lists_all_auto_discovered_skills(env):
    prompt = _prompt(env, ["~/.claude/skills"])
    for _, name in PLACES + KEPT:
        assert f"<name>{name}</name>" in prompt, prompt


def test_generated_skills_setting_hides_orca_and_herdr_skills_only(env):
    setting = gen.merge_pi_settings({}, load_common())["skills"]
    prompt = _prompt(env, setting)
    for _, name in KEPT:
        assert f"<name>{name}</name>" in prompt, prompt
    for name in HIDDEN:
        assert f"<name>{name}</name>" not in prompt, prompt
