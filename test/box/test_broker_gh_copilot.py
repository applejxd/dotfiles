"""gh・copilot ブローカーの計画と Envoy 設定の試験。実際の Envoy・ネットワークは使わない。"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from box import model
from box.broker import copilot, gh
from box.broker import plan as broker_plan
from test_broker_common import DUMMY_COPILOT, DUMMY_PAT, REPO, cfg, flat, policy

SOCK = f"{model.BROKER_HOST_DIR}/{REPO}/gh.sock"
SDS = f"{model.BROKER_HOST_DIR}/{REPO}/.gh"


def walk(obj: Any):  # type: ignore[no-untyped-def]
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def vhosts(config: dict) -> list[dict]:
    return [
        v
        for x in walk(config)
        if isinstance(x, dict) and "virtual_hosts" in x
        for v in x["virtual_hosts"]
    ]


# ---- gh の Envoy 設定 ----


def test_gh_config_routes_only_api_github_com_and_denies_others() -> None:
    config = json.loads(gh.envoy_config(SOCK, SDS))
    hosts = {v["name"]: v for v in vhosts(config)}
    assert hosts["github"]["domains"] == ["api.github.com"]
    assert "route" in hosts["github"]["routes"][0]
    deny = hosts["deny"]
    assert deny["domains"] == ["*"]
    assert deny["routes"][-1]["direct_response"]["status"] == 403
    assert all("route" not in r for r in deny["routes"])  # 上流へ出さない


def test_gh_config_replaces_authorization_with_bearer_overwrite() -> None:
    config = json.loads(gh.envoy_config(SOCK, SDS))
    generic = next(
        x for x in walk(config) if isinstance(x, dict) and x.get("header") == "Authorization"
    )
    assert generic["header_value_prefix"] == "Bearer "
    injector = next(x for x in walk(config) if isinstance(x, dict) and "overwrite" in x)
    assert injector["overwrite"] is True


def test_gh_config_verifies_upstream_tls_with_exact_san() -> None:
    config = json.loads(gh.envoy_config(SOCK, SDS))
    ctx = next(x for x in walk(config) if isinstance(x, dict) and "validation_context" in x)
    vc = ctx["validation_context"]
    assert vc["trusted_ca"]["filename"]
    assert vc["match_typed_subject_alt_names"] == [
        {"san_type": "DNS", "matcher": {"exact": "api.github.com"}}
    ]


def test_gh_listener_is_a_0600_unix_socket_under_the_broker_dir() -> None:
    config = json.loads(gh.envoy_config(SOCK, SDS))
    (listener,) = config["static_resources"]["listeners"]
    assert listener["address"]["pipe"] == {"path": SOCK, "mode": 0o600}


def test_gh_pat_is_never_in_config_or_plan() -> None:
    text = gh.envoy_config(SOCK, SDS)
    assert DUMMY_PAT not in text
    assert DUMMY_PAT not in flat(broker_plan("gh", cfg(), policy()))


# ---- gh の計画 ----


def test_gh_plan_shape() -> None:
    p = broker_plan("gh", cfg(), policy())
    (dev,) = p.devices
    assert dev.type == "proxy"
    assert dict(dev.config) == {
        "listen": f"unix:{model.BOX_SOCK_DIR}/gh.sock",
        "connect": f"unix:{SOCK}",
        "bind": "instance",
        "uid": "1000",
        "gid": "1000",
        "mode": "0600",
    }
    assert p.routes[0].modes == ("nat", "proxy-only")
    assert "offline" not in p.routes[0].modes
    assert p.readiness is not None and p.stop_ops


def test_gh_box_gets_dummy_token_and_socket_config_only() -> None:
    p = broker_plan("gh", cfg(), policy())
    assert p.env["GH_TOKEN"] != DUMMY_PAT and "dummy" in p.env["GH_TOKEN"]
    assert (
        p.env["GH_NO_UPDATE_NOTIFIER"]
        and p.env["GH_TELEMETRY"] == "false"
        and p.env["GH_PROMPT_DISABLED"]
    )
    (f,) = p.files
    assert f.where == "box" and f.path == f"{p.env['GH_CONFIG_DIR']}/config.yml"
    assert f.content == f"http_unix_socket: {model.BOX_SOCK_DIR}/gh.sock\n"
    assert f.secret is None


def test_gh_pat_goes_only_through_stdin_secret_and_not_argv() -> None:
    p = broker_plan("gh", cfg(), policy())
    ops = [op for op in p.host_ops if op.stdin_secret is not None]
    assert len(ops) == 1 and ops[0].stdin_secret is not None and ops[0].stdin_secret.name == "gh"
    assert "envoy" in " ".join(next(op for op in p.host_ops if "--config-yaml" in op.argv).argv)


def test_gh_missing_envoy_fails_clearly_in_a_host_op() -> None:
    p = broker_plan("gh", cfg(), policy())
    first = p.host_ops[0]
    assert "command -v envoy" in first.argv[-1] and "envoy が無い" in first.argv[-1]


# ---- copilot ----


def test_copilot_config_allows_exact_post_paths_only() -> None:
    config = json.loads(copilot.envoy_config(f"{model.BROKER_HOST_DIR}/{REPO}/copilot.sock", SDS))
    (vh,) = vhosts(config)
    allowed = [r for r in vh["routes"] if "route" in r]
    assert sorted(r["match"]["path"] for r in allowed) == sorted(copilot.PATHS)
    assert all(r["match"]["headers"][0]["string_match"]["exact"] == "POST" for r in allowed)
    assert vh["routes"][-1]["direct_response"]["status"] == 403
    ctx = next(x for x in walk(config) if isinstance(x, dict) and "validation_context" in x)
    assert ctx["validation_context"]["match_typed_subject_alt_names"][0]["matcher"] == {
        "suffix": "githubcopilot.com"
    }


def test_copilot_plan_gives_the_box_only_a_dummy_and_base_url() -> None:
    p = broker_plan("copilot", cfg(), policy())
    assert p.env == {"COPILOT_GITHUB_TOKEN": copilot.DUMMY_TOKEN}
    (f,) = p.files
    body = json.loads(f.content or "")
    assert body == {"providers": {"github-copilot": {"baseUrl": "http://127.0.0.1:7112"}}}
    (dev,) = p.devices
    assert dev.config["listen"] == "tcp:127.0.0.1:7112"
    assert dev.config["connect"] == f"unix:{model.BROKER_HOST_DIR}/{REPO}/copilot.sock"
    assert dev.config["bind"] == "instance"
    assert p.routes[0].modes == ("nat", "proxy-only")
    assert DUMMY_COPILOT not in flat(p)


# ---- copilot の更新 ----


def test_refresh_once_writes_sds_with_short_lived_token(tmp_path: Path) -> None:
    (tmp_path / "token").write_text(DUMMY_COPILOT + "\n", encoding="utf-8")
    seen: list[str] = []

    def fake(long: str) -> tuple[str, int]:
        seen.append(long)
        return "short-lived", 9999999999

    assert copilot.refresh_loop(tmp_path, once=True, exchange_fn=fake) == 0
    assert seen == [DUMMY_COPILOT]  # 改行は除かれる
    sds = json.loads((tmp_path / gh.SDS_NAME).read_text(encoding="utf-8"))
    assert sds["resources"][0]["generic_secret"]["secret"]["inline_string"] == "short-lived"
    assert (tmp_path / gh.SDS_NAME).stat().st_mode & 0o777 == 0o600


def test_refresh_failure_does_not_leak_token(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "token").write_text(DUMMY_COPILOT, encoding="utf-8")

    def boom(long: str) -> tuple[str, int]:
        raise copilot.ExchangeError("Copilot のトークンを取れない (HTTP 401)")

    assert copilot.refresh_loop(tmp_path, once=True, exchange_fn=boom) == 1
    seen = capsys.readouterr()
    assert DUMMY_COPILOT not in seen.out + seen.err


def test_refresh_retries_after_failure_then_sleeps_until_before_expiry(tmp_path: Path) -> None:
    (tmp_path / "token").write_text(DUMMY_COPILOT, encoding="utf-8")
    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky(long: str) -> tuple[str, int]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise copilot.ExchangeError("x")
        return "t", 10_000

    class Stop(Exception):
        pass

    def sleep(sec: float) -> None:
        sleeps.append(sec)
        if len(sleeps) == 2:
            raise Stop

    with pytest.raises(Stop):
        copilot.refresh_loop(tmp_path, exchange_fn=flaky, sleep=sleep, clock=lambda: 1_000.0)
    assert sleeps == [copilot.RETRY_SECONDS, 10_000 - 1_000 - copilot.REFRESH_MARGIN_SECONDS]


# ---- 構造 ----


def test_broker_package_imports_nothing_dotfiles_specific() -> None:
    root = Path(__file__).resolve().parents[2] / "scripts" / "box" / "broker"
    allowed = {
        "box",
        "json",
        "os",
        "re",
        "sys",
        "time",
        "socket",
        "socketserver",
        "subprocess",
        "threading",
        "tempfile",
        "argparse",
        "urllib",
        "http",
        "datetime",
        "pathlib",
        "typing",
        "collections",
        "__future__",
        "dataclasses",
    }
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] in allowed, (path.name, name)
                if name.startswith("box"):
                    assert name in {"box", "box.model", "box.broker"} or name.startswith(
                        "box.broker"
                    ), (path.name, name)


def test_all_broker_routes_drop_offline() -> None:
    for kind in ("gh", "aws", "copilot", "hf-cache"):
        for route in broker_plan(kind, cfg(), policy()).routes:
            assert "offline" not in route.modes
