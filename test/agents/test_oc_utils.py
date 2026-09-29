"""OpenCode の運用の小道具 ``oc-utils`` のテスト。

偽の ``opencode`` を PATH の先頭に置き、``opencode api`` の呼び出しを記録して確かめる。

see docs/spec/agent-permissions.md#保存した承認の確認とリセット
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "home" / "dot_local" / "bin" / "executable_oc-utils"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="oc-utils は Linux 専用")

# 状態ファイル (state.json) を読み書きし、呼び出しを calls.jsonl へ残す偽の opencode。
# mode で失敗の仕方を切り替える。
FAKE_OPENCODE = r"""
import json, sys
from pathlib import Path

here = Path(__file__).resolve().parent
state_file = here / "state.json"
state = json.loads(state_file.read_text())
args = sys.argv[1:]
with (here / "calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
mode = state.get("mode")
if args[:1] != ["api"]:
    sys.exit("api 以外は知らない")
rest = [a for a in args[1:] if a != "--standalone"]
if "--server" in rest:
    i = rest.index("--server")
    del rest[i : i + 2]
params = dict(rest[i + 1].split("=", 1) for i, a in enumerate(rest) if a == "--param")
operation = rest[0]
if mode == "unreachable":
    print("Error: Could not reach server at http://127.0.0.1:4096", file=sys.stderr)
    sys.exit(1)
if mode == "broken_json":
    print("{not json")
    sys.exit(0)
if operation == "project.list":
    print(json.dumps(state["projects"]))
elif operation == "permission.saved.list":
    project = params.get("projectID")
    items = state["saved"].get(project, []) if project else []
    print(json.dumps({"data": items}))
elif operation == "permission.saved.remove":
    if mode == "sticky":
        sys.exit(0)
    if mode == "delete_fails":
        print("HTTP 500 Internal Server Error", file=sys.stderr)
        sys.exit(1)
    for items in state["saved"].values():
        items[:] = [a for a in items if a["id"] != params["id"]]
    state_file.write_text(json.dumps(state))
else:
    print(f"HTTP 404 Not Found: {operation}", file=sys.stderr)
    sys.exit(1)
"""


def _approval(approval_id: str, project: str, action: str, resource: str) -> dict:
    return {
        "id": approval_id,
        "projectID": project,
        "action": action,
        "resource": resource,
        "time": {"created": 0, "updated": 0},
    }


class Fake:
    def __init__(self, directory: Path, repo: Path):
        self.dir = directory
        self.state = {
            "projects": [
                {"id": "global", "canonical": "/tmp/opencode/live/proj", "sandboxes": []},
                {"id": "p-repo", "canonical": str(repo), "vcs": "git", "sandboxes": []},
                {"id": "p-empty", "canonical": "/srv/empty", "sandboxes": []},
            ],
            "saved": {
                "p-repo": [
                    _approval("psv_2", "p-repo", "shell", "bash *"),
                    _approval("psv_1", "p-repo", "external_directory", "/*"),
                    _approval("psv_3", "p-repo", "shell", "/usr/bin/git *"),
                ],
                "global": [_approval("psv_9", "global", "read", "*.env")],
            },
        }
        self.save()
        fake = directory / "opencode"
        fake.write_text(f"#!{sys.executable}\n{FAKE_OPENCODE}", encoding="utf-8")
        fake.chmod(0o755)

    def save(self) -> None:
        (self.dir / "state.json").write_text(json.dumps(self.state), encoding="utf-8")

    def set_mode(self, mode: str) -> None:
        self.state["mode"] = mode
        self.save()

    def calls(self) -> list[list[str]]:
        log = self.dir / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def remaining(self) -> int:
        state = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        return sum(len(items) for items in state["saved"].values())


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / "sub").mkdir(parents=True)
    return path


@pytest.fixture
def fake(tmp_path: Path, repo: Path) -> Fake:
    directory = tmp_path / "bin"
    directory.mkdir()
    return Fake(directory, repo)


def run(fake: Fake | None, *args: str, path: str | None = None, cwd: Path | None = None):
    env = dict(os.environ)
    env["PATH"] = path if path is not None else f"{fake.dir}{os.pathsep}{env['PATH']}"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
        check=False,
    )


def _operations(fake: Fake) -> list[tuple[str, ...]]:
    return [tuple(call[1:]) for call in fake.calls()]


def test_list_walks_every_project_with_its_id(fake: Fake, repo: Path):
    """projectID を付けないと空が返るので、プロジェクトごとに問い合わせる。"""
    result = run(fake, "approvals")
    assert result.returncode == 0, result.stderr
    listed = [c for c in _operations(fake) if c[0] == "permission.saved.list"]
    assert sorted(listed) == sorted(
        ("permission.saved.list", "--param", f"projectID={p}")
        for p in ("global", "p-repo", "p-empty")
    )


def test_list_shows_count_path_and_sorted_entries(fake: Fake, repo: Path):
    out = run(fake, "approvals", "list").stdout.splitlines()
    assert f"p-repo {repo}: 3 件" in out
    assert "p-empty /srv/empty: 0 件" in out
    start = out.index(f"p-repo {repo}: 3 件")
    entries = [line.split() for line in out[start + 1 : start + 4]]
    assert entries == [
        ["external_directory", "/*"],
        ["shell", "/usr/bin/git", "*"],
        ["shell", "bash", "*"],
    ]
    assert out[-1] == "合計 4 件 (3 プロジェクト)"


def test_list_json(fake: Fake, repo: Path):
    result = run(fake, "approvals", "--json")
    data = json.loads(result.stdout)
    by_id = {p["id"]: p for p in data["projects"]}
    assert by_id["p-repo"]["count"] == 3
    assert by_id["p-repo"]["path"] == str(repo)
    assert {"id": "psv_1", "action": "external_directory", "resource": "/*"} in by_id["p-repo"][
        "approvals"
    ]


@pytest.mark.parametrize("how", ["id", "path", "subdir", "cwd"])
def test_project_filter(fake: Fake, repo: Path, how: str):
    value = {"id": "p-repo", "path": str(repo), "subdir": str(repo / "sub"), "cwd": "."}[how]
    result = run(fake, "approvals", "--project", value, "--json", cwd=repo / "sub")
    assert result.returncode == 0, result.stderr
    assert [p["id"] for p in json.loads(result.stdout)["projects"]] == ["p-repo"]


def test_path_inside_non_git_project_is_not_guessed(fake: Fake, tmp_path: Path):
    """git でないプロジェクトの下位は同じプロジェクトとは限らない。"""
    result = run(fake, "approvals", "--project", "/srv/empty/child")
    assert result.returncode == 1
    assert "プロジェクトが見つからない" in result.stderr


def test_reset_without_yes_deletes_nothing(fake: Fake, repo: Path):
    result = run(fake, "approvals", "reset")
    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout
    assert f"p-repo {repo}: 3 件" in result.stdout
    assert not [c for c in _operations(fake) if c[0] == "permission.saved.remove"]
    assert fake.remaining() == 4


def test_reset_yes_deletes_every_approval_then_recounts(fake: Fake):
    result = run(fake, "approvals", "reset", "--yes")
    assert result.returncode == 0, result.stderr
    operations = _operations(fake)
    removed = [c[-1] for c in operations if c[0] == "permission.saved.remove"]
    assert sorted(removed) == ["id=psv_1", "id=psv_2", "id=psv_3", "id=psv_9"]
    # 消したあとに全プロジェクトを数え直している
    last_remove = max(i for i, c in enumerate(operations) if c[0] == "permission.saved.remove")
    recount = [c for c in operations[last_remove + 1 :] if c[0] == "permission.saved.list"]
    assert len(recount) == 3
    assert fake.remaining() == 0
    assert "4/4 件を消した。取り直した残りは 0 件" in result.stdout


def test_reset_yes_limited_to_project(fake: Fake):
    result = run(fake, "approvals", "reset", "--yes", "--project", "p-repo")
    assert result.returncode == 0, result.stderr
    assert fake.remaining() == 1


def test_reset_fails_when_approvals_remain(fake: Fake):
    fake.set_mode("sticky")
    result = run(fake, "approvals", "reset", "--yes", "--json")
    assert result.returncode == 1
    assert "消し残りがある (4 件)" in result.stderr
    assert json.loads(result.stdout)["remaining"] == 4


def test_reset_reports_failed_deletes(fake: Fake):
    fake.set_mode("delete_fails")
    result = run(fake, "approvals", "reset", "--yes")
    assert result.returncode == 1
    assert "HTTP 500" in result.stderr
    # 1 件の失敗で止めず、全件を試す
    assert len([c for c in _operations(fake) if c[0] == "permission.saved.remove"]) == 4


@pytest.mark.parametrize(
    "args",
    [
        ("--standalone", "approvals"),
        ("approvals", "reset", "--standalone"),
        ("--server", "http://127.0.0.1:9", "approvals"),
    ],
)
def test_connection_options_reach_every_call(fake: Fake, args: tuple[str, ...]):
    run(fake, *args)
    expected = [a for a in args if a not in ("approvals", "reset")]
    calls = fake.calls()
    assert calls
    assert all(call[1 : 1 + len(expected)] == expected for call in calls)


def test_standalone_and_server_are_exclusive(fake: Fake):
    result = run(fake, "--standalone", "--server", "http://x", "approvals")
    assert result.returncode == 2
    assert not fake.calls()


def test_missing_opencode(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run(None, "approvals", path=str(empty))
    assert result.returncode == 1
    assert "opencode が PATH に無い" in result.stderr


@pytest.mark.parametrize(
    ("mode", "message"),
    [("unreachable", "Could not reach server"), ("broken_json", "JSON として読めない")],
)
@pytest.mark.parametrize("command", [("approvals",), ("approvals", "reset", "--yes")])
def test_api_errors_exit_nonzero(fake: Fake, mode: str, message: str, command: tuple[str, ...]):
    fake.set_mode(mode)
    result = run(fake, *command)
    assert result.returncode == 1
    assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_unexpected_shape_is_an_error(fake: Fake):
    fake.state["projects"] = {"not": "a list"}
    fake.save()
    result = run(fake, "approvals")
    assert result.returncode == 1
    assert "想定の形" in result.stderr


def test_subcommand_is_required(fake: Fake):
    assert run(fake).returncode == 2
