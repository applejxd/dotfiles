"""`scripts/models.py` (`mise run models:check` / `models:probe`。CHG-0043 段 4) の試験。

- check: 一覧に無い項目・同じ系統の新しい世代・分類不能・`reviewed_on` が古い、を警告する。
  **一覧の取得に失敗した・空のときは「問題なし」にしない (終了コード 2)**
- probe: 固定のファイルの内容が応答に含まれれば OK。`verified` は自動で書き換えない
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import stat
import sys
from pathlib import Path

import pytest
from agents_common import render_common

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "models.py"


def _load():
    spec = importlib.util.spec_from_file_location("models_tool", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["models_tool"] = mod
    spec.loader.exec_module(mod)
    return mod


mt = _load()

HEADER = "provider        model                     context  max-out  thinking  images\n"
COPILOT_LIST = HEADER + "".join(
    f"github-copilot  {m:25} 1M       128K     yes       yes\n"
    for m in ("claude-sonnet-5", "claude-sonnet-5.5", "gpt-6-sol", "gpt-6.1-sol", "gpt-6-luna")
)


@pytest.fixture(scope="module")
def personal_common(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("common") / "common.toml"
    p.write_text(render_common("applejxd"), encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def work_common(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("common-work") / "common.toml"
    p.write_text(render_common("worker"), encoding="utf-8")
    return p


def _check(common: Path, list_text: str | None, tmp_path: Path, *flags: str) -> int:
    args = ["check", "--common", str(common), *flags]
    if list_text is not None:
        lf = tmp_path / "list.txt"
        lf.write_text(list_text, encoding="utf-8")
        args += ["--list-file", str(lf)]
    return mt.main(args)


# ─── 部品 ───


def test_parse_list_groups_ids_by_provider() -> None:
    listed = mt.parse_list(COPILOT_LIST + "openai          gpt-6.1-terra  272K  128K  yes  yes\n")
    assert listed["github-copilot"] >= {"claude-sonnet-5.5", "gpt-6.1-sol"}
    assert listed["openai"] == {"gpt-6.1-terra"}
    assert "provider" not in listed  # 見出しの行は数えない


@pytest.mark.parametrize(
    ("model_id", "gen", "matches"),
    [
        ("claude-sonnet-5.5", (5, 5), ["claude-sonnet-5.6", "claude-sonnet-5"]),
        ("gpt-6.1-sol", (6, 1), ["gpt-6.10-sol", "gpt-7-sol"]),
        ("us.anthropic.claude-sonnet-5-5", (5, 5), ["us.anthropic.claude-sonnet-5-6"]),
        ("us.openai.gpt-6.1-terra", (6, 1), ["us.openai.gpt-6.2-terra"]),
    ],
)
def test_generation_is_taken_from_the_id_as_integers(model_id, gen, matches) -> None:
    import re

    regex, parsed = mt.generation_of(model_id)
    assert parsed == gen
    for cand in matches:
        assert re.match(regex, cand), cand
    other_family = re.sub(r"sonnet|sol|terra", "other", model_id)
    assert not re.match(regex, other_family)  # 別の系統にはあたらない


def test_an_id_without_a_version_is_unclassifiable() -> None:
    assert mt.generation_of("claude-sonnet-latest") is None


def test_6_10_counts_as_newer_than_6_9() -> None:
    catalog = {
        "provider": "p",
        "reviewed_on": "2026-10-27",
        "models": [{"id": "gpt-6.9-sol"}],
    }
    warnings, _ = mt.check(catalog, {"p": {"gpt-6.9-sol", "gpt-6.10-sol"}}, dt.date(2026, 10, 28))
    assert any("gpt-6.10-sol" in w for w in warnings)  # 文字列や小数で比べると、6.10 < 6.9 になる


# ─── check ───


def test_a_clean_catalog_gives_no_warning_and_exit_0(personal_common, tmp_path, capsys) -> None:
    listing = COPILOT_LIST.replace("claude-sonnet-5  ", "claude-sonnet-4  ") + (
        "github-copilot  gpt-6.1-terra             1M       128K     yes       yes\n"
    )
    today = dt.date.fromisoformat("2026-10-27")
    catalog = mt.load_catalog(personal_common)
    warnings, _ = mt.check(catalog, mt.parse_list(listing), today)
    assert warnings == []
    assert _check(personal_common, listing, tmp_path, "--days", "100000") == 0
    assert "問題なし" in capsys.readouterr().out


def test_unlisted_and_newer_generations_are_warned(personal_common, tmp_path, capsys) -> None:
    listing = (
        COPILOT_LIST
        + "github-copilot  claude-sonnet-5.6         1M  128K  yes  yes\n"
        + "github-copilot  gpt-6.2-sol               1M  128K  yes  yes\n"
    )
    assert _check(personal_common, listing, tmp_path, "--days", "100000") == 1
    out = capsys.readouterr().out
    assert "claude-sonnet-5.6" in out and "gpt-6.2-sol" in out  # 新しい世代
    assert "gpt-6.1-terra: pi の一覧に無い" in out  # 一覧に無い (動くが、確かめる)


def test_a_stale_reviewed_on_is_warned(personal_common, tmp_path, capsys) -> None:
    catalog = mt.load_catalog(personal_common)
    warnings, _ = mt.check(catalog, mt.parse_list(COPILOT_LIST), dt.date(2027, 1, 1))
    assert any("reviewed_on" in w for w in warnings)


def test_a_failed_or_empty_list_is_never_reported_as_ok(
    personal_common, work_common, tmp_path, capsys
) -> None:
    # 取得に失敗 (ファイルが無い)
    assert (
        mt.main(
            [
                "check",
                "--common",
                str(personal_common),
                "--list-file",
                str(tmp_path / "missing.txt"),
            ]
        )
        == 2
    )
    assert "問題なし" not in capsys.readouterr().out
    # 空の一覧
    assert _check(personal_common, "", tmp_path) == 2
    # 対象のプロバイダのモデルが 1 つも無い (別のプロバイダだけ)
    assert _check(work_common, COPILOT_LIST, tmp_path) == 2
    assert "問題なし" not in capsys.readouterr().out


def test_pi_failing_to_list_is_exit_2(personal_common, tmp_path, capsys) -> None:
    fake = tmp_path / "pi"
    fake.write_text("#!/bin/sh\necho boom >&2\nexit 3\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    assert mt.main(["check", "--common", str(personal_common), "--pi", str(fake)]) == 2
    assert "取得できない" in capsys.readouterr().err


# ─── probe ───


def _fake_pi(tmp_path: Path, body: str) -> Path:
    fake = tmp_path / "fakepi"
    fake.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return fake


def test_probe_ok_needs_the_fixed_word_from_the_file(personal_common, tmp_path, capsys) -> None:
    log = tmp_path / "args.log"
    good = _fake_pi(tmp_path, f'echo "$@" >> {log}\ncat probe.txt\n')
    rc = mt.main(
        [
            "probe",
            "--common",
            str(personal_common),
            "--pi",
            str(good),
            "--model",
            "gpt-6.1-sol",
            "--effort",
            "high",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "github-copilot/gpt-6.1-sol:high" in out and "OK" in out
    assert "--model github-copilot/gpt-6.1-sol:high" in log.read_text(
        encoding="utf-8"
    )  # effort の接尾辞を付けて起動する
    assert "verified は手で直す" in out  # 自動では書き換えない


def test_probe_fails_when_the_word_is_missing_or_the_command_fails(
    personal_common, tmp_path, capsys
) -> None:
    bad = _fake_pi(tmp_path, "echo I could not read it\n")
    assert (
        mt.main(
            ["probe", "--common", str(personal_common), "--pi", str(bad), "--model", "gpt-6.1-sol"]
        )
        == 1
    )
    assert "NG" in capsys.readouterr().out
    broken = _fake_pi(tmp_path, "echo boom >&2\nexit 5\n")
    assert (
        mt.main(
            [
                "probe",
                "--common",
                str(personal_common),
                "--pi",
                str(broken),
                "--model",
                "gpt-6.1-sol",
            ]
        )
        == 1
    )


def test_probe_dry_run_runs_nothing_and_default_targets_unverified(
    work_common, tmp_path, capsys
) -> None:
    marker = tmp_path / "ran"
    fake = _fake_pi(tmp_path, f"touch {marker}\n")
    assert mt.main(["probe", "--common", str(work_common), "--pi", str(fake), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert not marker.exists()
    # Bedrock は未確認のものが対象 (確認済みの Sonnet は含まない)
    assert "us.openai.gpt-6.1-terra" in out and "us.anthropic.claude-sonnet-5-5" not in out


def test_probe_refuses_too_many_runs(personal_common, tmp_path, capsys) -> None:
    fake = _fake_pi(tmp_path, "cat probe.txt\n")
    rc = mt.main(
        ["probe", "--common", str(personal_common), "--pi", str(fake), "--all", "--dry-run"]
    )
    assert rc == 0  # 3 件は、上限の範囲
