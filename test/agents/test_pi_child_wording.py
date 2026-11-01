"""子 (explore / review / plan / worker) の役割の system の文言。see docs/spec/guard/pi-subagents.md"""

from __future__ import annotations

import pytest
from agents_common import load_common

ROLES = ("explore", "review", "plan", "worker")


def _systems() -> list[tuple[str, str, str]]:
    raw = load_common()["pi"]["agents"]
    out = []
    for name in ROLES:
        for key in ("system", "plain_system"):
            if raw[name].get(key):
                out.append((name, key, raw[name][key]))
    return out


@pytest.mark.parametrize(("name", "key", "text"), _systems())
def test_every_system_says_to_reply_in_japanese(name, key, text):
    assert "日本語" in text, (name, key)


def test_worker_does_not_predict_that_commands_are_refused():
    text = load_common()["pi"]["agents"]["worker"]["system"]
    assert "確認なしでは実行できないことが多い" not in text
    assert "拒否されたら" in text
    assert "次の候補" in text


def test_worker_may_use_tmpdir_for_scratch_files():
    text = load_common()["pi"]["agents"]["worker"]["system"]
    assert "$TMPDIR" in text
    assert ".tmp/keep" in text
    # $TMPDIR が作業ツリーの外のときは .tmp/ の下。例外は使い捨て用ディレクトリに限る
    assert "作業ツリーの外" in text
    assert "作業ツリーの `.tmp/` の下" in text
    assert "使い捨て用ディレクトリに限る" in text


@pytest.mark.parametrize(("name", "key", "text"), [s for s in _systems() if s[0] != "worker"])
def test_read_only_roles_do_not_run_tests_or_builds(name, key, text):
    assert "試験・ビルドは実行しません" in text, (name, key)


def test_worker_runs_tests_and_reports_output():
    text = load_common()["pi"]["agents"]["worker"]["system"]
    assert "試験・lint は実行して" in text


@pytest.mark.parametrize(("name", "key", "text"), [s for s in _systems() if s[0] != "worker"])
def test_public_repository_sentence_matches_the_canonical_strength(name, key, text):
    assert "私物の環境以外の具体" in text, (name, key)
    assert "勤務先・組織・契約・環境の具体は" not in text, (name, key)


@pytest.mark.parametrize(("name", "key", "text"), _systems())
def test_refusal_rule_forbids_workarounds(name, key, text):
    if name == "worker":
        assert "言い換え" in text
        assert "guarded_read" in text


@pytest.mark.parametrize("name", ["review", "plan"])
def test_review_and_plan_mention_public_repository(name):
    assert "公開" in load_common()["pi"]["agents"][name]["system"]


@pytest.mark.parametrize("name", ["explore", "review"])
def test_search_first_rule_for_unknown_external_bugs(name):
    for key in ("system", "plain_system"):
        text = load_common()["pi"]["agents"][name].get(key)
        if text:
            assert "検索" in text and "未知の不具合" in text, (name, key)


def test_plain_and_full_system_share_common_sentences():
    raw = load_common()["pi"]["agents"]
    for name in ("explore", "review"):
        full, plain = raw[name]["system"], raw[name]["plain_system"]
        for marker in ("返答は日本語で書く", "このリポジトリは公開"):
            assert (marker in full) == (marker in plain), (name, marker)
