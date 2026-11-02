"""プロジェクト内の pi.json の解析・検査 (harness/judge/integrateprofile.ts) の表試験 (純関数)。

保護は全体設定のまま: 接頭辞・統合先が保護と交差する設定は拒否し、拒否したら全体の既定に倒す。
診断には入力の本文・値を入れない。fixture には架空の名前だけを使う。
see docs/change/0057-per-project-integrate.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "integrate_profile_driver.mjs"
SECRET = "SECRET-TOKEN-XYZ"
PROTECTED = ["main", "develop", "production", "release/*", "hotfix/*"]


def _defaults(protected=None, target="production") -> dict:
    return {
        "protectedRefs": PROTECTED if protected is None else protected,
        "target": target,
        "sourcePrefixes": ["feature/", "bugfix/"],
        "freeZonePrefixes": ["feature/"],
    }


def _eff(text, defaults=None) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    payload = {"fn": "effective", "defaults": defaults or _defaults(), "text": text}
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(out.stdout)


def _cfg(**integrate) -> str:
    return json.dumps({"integrate": integrate})


def _assert_default(r: dict, code: str | None = None):
    assert r["profile"]["source"] == "default", r
    assert r["profile"]["target"] == "production"
    assert r["profile"]["sourcePrefixes"] == ["feature/", "bugfix/"]
    assert r["profile"]["freeZonePrefixes"] == ["feature/"]
    assert r["overridden"] is False
    if code is not None:
        assert code in [d["code"] for d in r["diagnostics"]], r


# --- C5: 接頭辞は保護と交差しない ---------------------------------------------------------


@pytest.mark.parametrize(
    ("prefix", "protected"),
    [
        ("feature/", ["feature/base"]),
        ("Feature/", ["feature/base"]),
        ("feature/", ["Feature/Base"]),
        ("x/", ["x/*"]),
        ("x/y/", ["x/*"]),
        ("x/", ["x/y/*"]),
        ("release/", ["release/*"]),
        ("hotfix/", ["hotfix/*"]),
        ("release/", ["refs/heads/release/*"]),
    ],
)
@pytest.mark.parametrize("key", ["source_prefixes", "free_zone_prefixes"])
def test_prefix_overlapping_protected_is_rejected(prefix, protected, key):
    r = _eff(_cfg(**{key: [prefix]}), _defaults(protected=protected))
    _assert_default(r, "prefix_overlaps_protected")


def test_prefix_not_overlapping_is_accepted():
    r = _eff(_cfg(free_zone_prefixes=["feat/"], source_prefixes=["feat/", "fix/"]))
    assert r["diagnostics"] == []
    assert r["profile"]["source"] == "project"
    assert r["profile"]["freeZonePrefixes"] == ["feat/"]
    assert r["profile"]["sourcePrefixes"] == ["feat/", "fix/"]
    assert r["overridden"] is True


def test_prefix_checked_against_the_given_protected_list_only():
    # 下限に当たる release/ は、全体の保護の一覧に release/* が無ければ交差しない (一覧は呼び出し側が下限を含めて渡す)
    r = _eff(_cfg(source_prefixes=["release/"]), _defaults(protected=["main"], target="main"))
    assert r["profile"]["source"] == "project"


# --- C4: target は保護の完全一致の要素 ---------------------------------------------------


def test_target_equal_to_protected_element_is_accepted():
    r = _eff(_cfg(target="develop"))
    assert r["diagnostics"] == []
    assert r["profile"]["target"] == "develop"
    assert r["overridden"] is True


@pytest.mark.parametrize(
    ("target", "protected"),
    [
        ("release/a", ["release/*"]),
        ("release/*", ["release/*"]),
        ("Develop", PROTECTED),
        ("staging", PROTECTED),
        ("", PROTECTED),
        ("ma?n", PROTECTED),
        ("ma[i]n", PROTECTED),
    ],
)
def test_bad_target_is_rejected(target, protected):
    r = _eff(_cfg(target=target), _defaults(protected=protected))
    _assert_default(r, "bad_target")


# --- 保護は減らせない / 空・消す ----------------------------------------------------------


@pytest.mark.parametrize("key", ["extra_protected_refs", "protected_refs"])
@pytest.mark.parametrize("where", ["top", "integrate"])
def test_protected_refs_keys_are_not_allowed(key, where):
    body = {key: ["main"]} if where == "top" else {"integrate": {key: ["main"]}}
    r = _eff(json.dumps(body))
    _assert_default(r, "protected_refs_not_allowed")


@pytest.mark.parametrize("text", [None, "", "  \n"])
def test_empty_or_missing_is_default_without_diagnostics(text):
    r = _eff(text)
    _assert_default(r)
    assert r["diagnostics"] == []


@pytest.mark.parametrize("text", ["{}", '{"integrate": {}}'])
def test_empty_object_keeps_default_values(text):
    r = _eff(text)
    assert r["diagnostics"] == []
    assert r["overridden"] is False
    assert r["profile"]["target"] == "production"
    assert r["profile"]["sourcePrefixes"] == ["feature/", "bugfix/"]


def test_a_utf8_bom_is_accepted():
    """Windows のエディタが付ける BOM で、正しい設定が invalid_json にならない。"""
    r = _eff("\ufeff" + _cfg(target="develop"))
    assert r["profile"]["source"] == "project" and r["profile"]["target"] == "develop", r


def test_omitted_keys_keep_defaults():
    r = _eff(_cfg(target="develop"))
    assert r["profile"]["sourcePrefixes"] == ["feature/", "bugfix/"]
    assert r["profile"]["freeZonePrefixes"] == ["feature/"]


def test_duplicates_are_merged():
    r = _eff(_cfg(source_prefixes=["feat/", "feat/", "fix/"]))
    assert r["profile"]["sourcePrefixes"] == ["feat/", "fix/"]


def test_same_values_as_default_are_not_overridden():
    r = _eff(
        _cfg(
            target="production",
            source_prefixes=["feature/", "bugfix/"],
            free_zone_prefixes=["feature/"],
        )
    )
    assert r["profile"]["source"] == "project"
    assert r["overridden"] is False


def test_empty_prefix_list_is_allowed():
    r = _eff(_cfg(free_zone_prefixes=[]))
    assert r["profile"]["freeZonePrefixes"] == []
    assert r["overridden"] is True


# --- 形の検査 -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("{not json", "invalid_json"),
        ("[]", "not_object"),
        ("null", "not_object"),
        ('"str"', "not_object"),
        (json.dumps({"integrate": []}), "bad_type"),
        (json.dumps({"integrate": "x"}), "bad_type"),
        (_cfg(target=1), "bad_type"),
        (_cfg(source_prefixes="feat/"), "bad_type"),
        (_cfg(source_prefixes=[1]), "bad_type"),
        (_cfg(free_zone_prefixes={"a": 1}), "bad_type"),
        (_cfg(source_prefixes=["a/"] * 9), "too_many"),
        (_cfg(source_prefixes=["a" * 64 + "/"]), "too_large"),
        (_cfg(target="x" * 129), "too_large"),
        (" " * 4097 + "{}", "too_large"),
        (json.dumps({"integrate": {"unknown": 1}}), "unknown_key"),
        (json.dumps({"other": {}}), "unknown_key"),
    ],
)
def test_invalid_shapes_fall_back_to_default(text, code):
    r = _eff(text)
    _assert_default(r, code)


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "feat",
        "/feat/",
        "fe*/",
        "fe?/",
        "fe[a]/",
        "a b/",
        "a\tb/",
        "a\x01/",
        "a..b/",
        "a//b/",
        "refs/heads/",
        "Refs/x/",
        "a@{b/",
        "a~b/",
        "a^b/",
        "a:b/",
        "a\\b/",
    ],
)
def test_bad_prefix_shapes(prefix):
    r = _eff(_cfg(source_prefixes=[prefix]))
    _assert_default(r, "bad_prefix")


def test_nine_prefixes_boundary_eight_is_ok():
    r = _eff(_cfg(source_prefixes=[f"p{i}/" for i in range(8)]))
    assert r["profile"]["source"] == "project"
    assert len(r["profile"]["sourcePrefixes"]) == 8


def test_one_bad_key_rejects_the_whole_config():
    r = _eff(_cfg(target="develop", source_prefixes=["release/"]))
    _assert_default(r, "prefix_overlaps_protected")


def test_a_bad_free_zone_does_not_apply_a_good_target():
    r = _eff(_cfg(target="develop", free_zone_prefixes=["feature"]))
    assert r["profile"]["target"] == "production"


# --- 診断に入力の本文・値を入れない -------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "{" + SECRET,  # 壊れた JSON
        json.dumps({SECRET + " k": 1}),
        json.dumps({"integrate": {SECRET + "!": 1}}),
        json.dumps({SECRET: 1}),
        _cfg(target=SECRET),
        _cfg(source_prefixes=[SECRET]),
        _cfg(source_prefixes=[SECRET + "/*"]),
        _cfg(free_zone_prefixes=[SECRET] * 9),
        json.dumps({"integrate": SECRET}),
        json.dumps([SECRET]),
        json.dumps({"protected_refs": [SECRET]}),
    ],
)
def test_diagnostics_never_echo_values(text):
    r = _eff(text)
    assert r["profile"]["source"] == "default"
    assert r["diagnostics"], r
    dumped = json.dumps(r["diagnostics"])
    # 値・本文は出ない。キー名は許す形のときだけ (固定の文字種・32 字まで)
    assert SECRET + "/" not in dumped
    assert SECRET + "!" not in dumped
    assert SECRET + " k" not in dumped
    for d in r["diagnostics"]:
        assert set(d) <= {"code", "key"}
        assert len(d.get("key", "")) <= 32


def test_unknown_key_name_is_sanitized():
    long_key = "k" * 100
    r = _eff(json.dumps({"integrate": {long_key: 1, "bad key!": 2, "日本語": 3}}))
    keys = sorted(d["key"] for d in r["diagnostics"])
    assert keys == sorted(["k" * 32, "?", "?"])
    assert all(d["code"] == "unknown_key" for d in r["diagnostics"])


@pytest.mark.parametrize("key", ["Ghp_ABC123", "token-abc", "k1", "A", "a.b", "a/b"])
def test_key_names_that_look_like_tokens_are_not_echoed(key):
    """大文字・数字・ハイフン・ドットを含むキー名は、秘密に見えるので出さない。小文字とアンダースコアだけ出す（綴り違いを直す手がかり）。"""
    r = _eff(json.dumps({"integrate": {key: 1}}))
    assert r["diagnostics"] == [{"code": "unknown_key", "key": "?"}], r


def test_a_misspelled_known_key_is_shown():
    r = _eff(json.dumps({"integrate": {"free_zone_prefix": ["x/"]}}))
    assert r["diagnostics"] == [{"code": "unknown_key", "key": "free_zone_prefix"}], r


def test_parse_exception_message_not_used():
    r = _eff("{" + SECRET)
    assert r["diagnostics"] == [{"code": "invalid_json"}]
