"""pending-adapters.ts (git_integrate の配線と、承認側の再判定) の試験。

integrateWiring は両キルスイッチが true のときだけ有効にする。authorizeRecord は迷ったら断る。
see docs/change/0055
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_integrate_plan import _commit, _git
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "integrate_wiring_driver.mjs"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="git の実リポジトリを使う")


def _run(payload: dict, timeout: int = 120) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=timeout,
    )
    return json.loads(out.stdout)


def _rules(pending: object = True, integrate: object = True, **integ: object) -> dict:
    pi: dict = {}
    if pending is not None:
        pi["pending"] = {"enabled": pending}
    if integrate is not None:
        pi["integrate"] = {"enabled": integrate, **integ}
    return {"judge": {"common": {"pi": pi}}}


def _wiring(rules: dict) -> dict:
    return _run({"op": "wiring", "rules": rules})


# --- integrateWiring: キルスイッチ ---


@pytest.mark.parametrize(
    "rules",
    [
        {},
        {"judge": {"common": {"pi": {}}}},
        _rules(False, False),
        _rules(True, False),
        _rules(False, True),
        _rules("true", True),
        _rules(True, 1),
        _rules(None, True),
        _rules(True, None),
    ],
)
def test_wiring_disabled_unless_both_true(rules: dict) -> None:
    w = _wiring(rules)
    assert w["enabled"] is False
    assert w["specs"] == [] and w["request"] == [] and w["approval"] == []


def test_wiring_enabled_when_both_true() -> None:
    w = _wiring(_rules())
    assert w["enabled"] is True
    assert w["specs"] == ["git_integrate"]
    assert w["request"] == ["git_integrate"] and w["approval"] == ["git_integrate"]
    assert w["exclusive"] is True and w["runsHere"] == "function"


# --- 設定の読み方 ---


def _cfg(**integ: object) -> dict:
    return _run({"op": "cfg", "rules": _rules(**integ)})["cfg"]


def test_cfg_target() -> None:
    assert _cfg()["target"] == "develop"
    assert _cfg(target="release/1.0")["target"] == "release/1.0"
    for bad in ("", "-x", "a b", "a;b", "../x", 5, None, ["develop"], "x\ny"):
        assert _cfg(target=bad)["target"] == "develop", bad


def test_cfg_protected_refs() -> None:
    assert _cfg()["protectedRefs"] == ["main", "master", "develop", "release/*", "hotfix/*"]
    assert _cfg(protected_refs=["main", "x/*"])["protectedRefs"] == ["main", "x/*"]
    for bad in ([], [1], "main", ["main", 2]):
        assert _cfg(protected_refs=bad)["protectedRefs"] == [
            "main",
            "master",
            "develop",
            "release/*",
            "hotfix/*",
        ], bad


def test_cfg_risk_paths() -> None:
    assert _cfg()["riskPaths"] == []
    assert _cfg(risk_paths="scripts/**")["riskPaths"] == []
    assert _cfg(risk_paths=["a/**", 1, None, {"x": 1}, ["b"], "c"])["riskPaths"] == ["a/**", "c"]
    assert _cfg(risk_paths=["x" * 300])["riskPaths"] == ["x" * 200]
    many = _cfg(risk_paths=[f"p{i}" for i in range(500)])["riskPaths"]
    assert len(many) == 200 and many[0] == "p0"


# --- 登録表は空のまま (C1) ---


def test_registries_stay_empty() -> None:
    r = _run({"op": "registries"})
    assert r == {"pending": [], "approval": []}


# --- request.capture と、実行中のキルスイッチ ---


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "main"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    _commit(r, "a.txt", "1\n2\n3\n", "init")
    _git(r, "checkout", "-q", "-b", "feature/x")
    _commit(r, "b.txt", "new\n")
    _git(r, "checkout", "-q", "develop")
    return r


def test_capture_honours_kill_switches_at_call_time(repo: Path) -> None:
    res = _run(
        {
            "op": "capture",
            "rules": _rules(),
            "cwd": str(repo),
            "values": {"source": "feature/x", "message": "feat: x"},
        }
    )
    assert res["before"]["ok"] is True, res["before"]
    assert res["afterIntegrateOff"]["ok"] is False and "無効" in res["afterIntegrateOff"]["reason"]
    assert res["restored"]["ok"] is True
    # pending を切ると、アダプタ自体は (作り済みなので) 残るが、enabled() で拒否される
    assert res["afterPendingOff"]["ok"] is False and "無効" in res["afterPendingOff"]["reason"]


# --- authorizeRecord ---

OK_PARAMS = {"source": "feature/x", "message": "feat: x\n\nbody"}


def _auth(
    params: object = None,
    action: str = "git_integrate",
    specs: str = "integrate",
    tools: list[str] | None = None,
    child: bool = False,
) -> dict:
    rec = {"action": action, "params": OK_PARAMS if params is None else params}
    ctx = {"specs": specs, "roleTools": ["action"] if tools is None else tools, "child": child}
    return _run({"op": "authorize", "rec": rec, "ctx": ctx})["result"]


def test_authorize_ok() -> None:
    assert _auth() == {"ok": True}
    assert _auth({**OK_PARAMS, "cleanup": "branch"}) == {"ok": True}


def test_authorize_child_refused() -> None:
    r = _auth(child=True)
    assert r["ok"] is False and "子" in r["reason"]


def test_authorize_role_without_action_tool() -> None:
    for tools in ([], ["bash", "read"]):
        r = _auth(tools=tools)
        assert r["ok"] is False and "action" in r["reason"]


def test_authorize_unregistered_action() -> None:
    r = _auth(specs="none")
    assert r["ok"] is False and "登録" in r["reason"]
    r = _auth(action="other_op")
    assert r["ok"] is False and "登録" in r["reason"]


@pytest.mark.parametrize(
    "params",
    [
        {**OK_PARAMS, "extra": "x"},
        {"source": "feature/x", "message": "m" * 1201},
        {"source": "feature/x", "message": ""},
        {"source": "feature/x"},
        {"source": "feat\nx", "message": "m"},
        {"source": "feat\x00x", "message": "m"},
        {"source": "s" * 201, "message": "m"},
        {"source": 5, "message": "m"},
        {"source": "feature/x", "message": ["m"]},
        {**OK_PARAMS, "cleanup": 3},
        None,
        [],
        "x",
    ],
)
def test_authorize_invalid_params(params: object) -> None:
    rec = {"action": "git_integrate", "params": params}
    ctx = {"specs": "integrate", "roleTools": ["action"], "child": False}
    r = _run({"op": "authorize", "rec": rec, "ctx": ctx})["result"]
    assert r["ok"] is False and r["reason"], params
    assert "\n" not in r["reason"], r


def test_authorize_reason_does_not_echo_free_text() -> None:
    secret = "SECRET-FREE-TEXT"
    r = _auth({"source": "feature/x", "message": "m", secret: "v"})
    assert r["ok"] is False and secret not in r["reason"]
    r = _auth(action=secret)
    assert r["ok"] is False and secret not in r["reason"]


def test_authorize_order() -> None:
    # 子 > 役割 > 登録 > params
    r = _auth(child=True, tools=[], specs="none", params={"x": 1})
    assert "子" in r["reason"]
    r = _auth(tools=[], specs="none", params={"x": 1})
    assert "action" in r["reason"]
    r = _auth(specs="none", params={"x": 1})
    assert "登録" in r["reason"]
    r = _auth(params={"x": 1})
    assert (
        "登録" not in r["reason"] and "action ツール" not in r["reason"] and "子" not in r["reason"]
    )


def test_authorize_reason_is_capped_even_with_many_bad_params() -> None:
    # 未知のキーが多いと、検査のエラー文は 200 字を超える。理由は 1 行・200 字までに切る (接頭辞を除く)
    many = {f"k{i}": "v" for i in range(30)}
    r = _auth({**OK_PARAMS, **many})
    prefix = "引数が操作の定義に合わない: "
    assert r["ok"] is False and r["reason"].startswith(prefix)
    assert len(r["reason"]) - len(prefix) <= 200 and "\n" not in r["reason"]


# --- cwd ごとの設定 (HEAD の .agents/config/pi.json。保護は全体のまま) ---


def _pi_json(repo: Path, obj: object | str) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj)
    _commit(repo, ".agents/config/pi.json", text, "pi.json")
    return _git(repo, "rev-parse", "HEAD:.agents/config/pi.json").strip()


def test_cfg_without_cwd_or_pi_json_is_unchanged(tmp_path: Path) -> None:
    c = _cfg()
    assert c["target"] == "develop" and c["sourcePrefixes"] == ["feature/", "bugfix/"]
    assert "profile" not in c
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    _commit(r, "a.txt", "1\n", "init")
    c = _run({"op": "cfg", "rules": _rules(), "cwd": str(r)})["cfg"]
    assert c["target"] == "develop" and c["sourcePrefixes"] == ["feature/", "bugfix/"]
    assert c["profile"] == {"blob": None, "overridden": False, "diagnostics": []}


def test_cfg_uses_pi_json_at_head(tmp_path: Path) -> None:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    blob = _pi_json(r, {"integrate": {"target": "production", "source_prefixes": ["feat/"]}})
    rules = _rules(protected_refs=["main", "develop", "production"])
    c = _run({"op": "cfg", "rules": rules, "cwd": str(r)})["cfg"]
    assert c["target"] == "production" and c["sourcePrefixes"] == ["feat/"]
    assert c["profile"] == {"blob": blob, "overridden": True, "diagnostics": []}
    # 保護は全体のまま
    assert c["protectedRefs"] == ["main", "develop", "production"]


def test_cfg_protected_refs_never_come_from_pi_json(tmp_path: Path) -> None:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    _pi_json(r, {"integrate": {"protected_refs": ["x"], "extra_protected_refs": ["y"]}})
    c = _run({"op": "cfg", "rules": _rules(), "cwd": str(r)})["cfg"]
    assert c["protectedRefs"] == ["main", "master", "develop", "release/*", "hotfix/*"]
    assert c["target"] == "develop"
    codes = [d["code"] for d in c["profile"]["diagnostics"]]
    assert codes and set(codes) == {"protected_refs_not_allowed"}, c["profile"]


def test_cfg_target_not_protected_is_invalid(tmp_path: Path) -> None:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    _pi_json(r, {"integrate": {"target": "production"}})
    c = _run({"op": "cfg", "rules": _rules(), "cwd": str(r)})["cfg"]
    assert c["target"] == "develop" and c["profile"]["overridden"] is False
    assert [d["code"] for d in c["profile"]["diagnostics"]] == ["bad_target"]


def test_cfg_ignores_uncommitted_pi_json(tmp_path: Path) -> None:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    _commit(r, "a.txt", "1\n", "init")
    (r / ".agents" / "config").mkdir(parents=True)
    (r / ".agents" / "config" / "pi.json").write_text(
        '{"integrate": {"source_prefixes": ["x/"]}}', encoding="utf-8"
    )
    c = _run({"op": "cfg", "rules": _rules(), "cwd": str(r)})["cfg"]
    assert c["sourcePrefixes"] == ["feature/", "bugfix/"]
    assert c["profile"] == {"blob": None, "overridden": False, "diagnostics": []}
