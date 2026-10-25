"""env-check の診断スクリプト (env_check.py) の試験。値を漏らさないことを固定する。"""

import importlib.util
import os
import subprocess
import sys

from agents_common import ROOT

SCRIPT = ROOT / "home/dot_claude/skills/env-check/scripts/env_check.py"
BASHRULES = ROOT / "home/dot_claude/hooks/lib"


def _load():
    spec = importlib.util.spec_from_file_location("env_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args, **env):
    full = {k: v for k, v in os.environ.items() if k.isupper()} | env
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=full,
    )


def test_sensitive_pattern_matches_the_hook():
    sys.path.insert(0, str(BASHRULES))
    try:
        from bashrules._shared import _SENSITIVE_ENV_RE
    finally:
        sys.path.remove(str(BASHRULES))
    assert _SENSITIVE_ENV_RE.pattern == _load().SENSITIVE_ENV_PATTERN


def test_url_credentials_are_masked():
    proc = _run("get", "HTTPS_PROXY", HTTPS_PROXY="http://user:pw@proxy.example:8080")
    assert proc.returncode == 0
    assert "pw" not in proc.stdout and "user" not in proc.stdout
    assert "HTTPS_PROXY=http://***@proxy.example:8080" in proc.stdout


def test_secret_names_never_show_values():
    for name in ("GITHUB_TOKEN", "MY_API_KEY", "PROXY_PASSWORD"):
        for args in (("get", name), ("show",)):
            proc = _run(*args, **{name: "s3cr3t-value"})
            assert "s3cr3t-value" not in proc.stdout, (name, args)
    assert "秘密の名前" in _run("get", "GITHUB_TOKEN", GITHUB_TOKEN="x").stdout


def test_names_lists_names_only():
    proc = _run("names", SOME_VAR="visible-value-xyz")
    assert "SOME_VAR" in proc.stdout.split()
    assert "visible-value-xyz" not in proc.stdout


def test_other_variables_show_only_the_length():
    proc = _run("get", "SOME_VAR", SOME_VAR="visible-value-xyz")
    assert "visible-value-xyz" not in proc.stdout
    assert "17 文字" in proc.stdout


def test_whitelisted_values_are_shown():
    proc = _run("get", "WEBSEARCH_BROKER_URL", WEBSEARCH_BROKER_URL="http://127.0.0.1:9")
    assert "WEBSEARCH_BROKER_URL=http://127.0.0.1:9" in proc.stdout


def test_bad_arguments_exit_2():
    assert _run().returncode == 2
    assert _run("get", "A B").returncode == 2
    assert _run("set", "X").returncode == 2
