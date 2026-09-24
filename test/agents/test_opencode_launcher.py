"""ランチャーの設定書き出しに関するテスト。

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.

★守りたいのは「緩和に関わるキーは毎回差し替わる」ことと
  「それ以外のキーは残る」ことの両立。
  丸ごと上書きすると、TUI で選んだモデルが毎回消える (実際に出したバグ)。
see docs/change/0004-opencode-sandbox.md
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

LAUNCHER = ROOT / "home" / "dot_local" / "bin" / "executable_ocs"
COMMON = load_common()


def _launcher() -> dict:
    """ランチャーの関数だけ取り出す (main は動かさない)。"""
    namespace: dict = {"__name__": "probe"}
    exec(compile(LAUNCHER.read_text(encoding="utf-8"), "launcher", "exec"), namespace)
    return namespace


def _sandbox(tmp_path: Path, **overrides) -> dict:
    """境界の設定に、書き出し先だけ差し替えたものを返す。"""
    base = gen.opencode_sandbox(COMMON) or {}
    fallback = [{"action": "shell", "resource": "*", "effect": "allow"}]
    return {
        "config_dir": str(tmp_path / "config"),
        "permissions": base.get("permissions", fallback),
        "policies": base.get("policies", []),
        "plugins": base.get("plugins", []),
        "system_prompt": base.get("system_prompt", "境界の説明"),
        "model_preference": base.get("model_preference", []),
        **overrides,
    }


def _project(tmp_path: Path) -> dict:
    """cwd で選ばれるプロジェクト 1 つ分。"""
    return {
        "workspace": str(tmp_path / "ws"),
        "data_home": str(tmp_path / "ws" / ".opencode-sandbox" / "data"),
        "db": str(tmp_path / "opencode.db"),
        "config": {"network": {"allowedDomains": []}, "filesystem": {"denyWrite": []}},
    }


def _seed_db(path: Path, integration: str = "github-copilot") -> None:
    con = sqlite3.connect(str(path))
    con.execute("create table credential (id text, integration_id text)")
    con.execute("insert into credential values ('cred_x', ?)", (integration,))
    con.commit()
    con.close()


def test_managed_keys_are_replaced_every_time(tmp_path):
    """緩和に関わるキーは、内側で書き換えられても毎回戻ること。"""
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    launcher["write_isolated_config"](sandbox, project)

    target = Path(sandbox["config_dir"]) / "opencode.json"
    tampered = json.loads(target.read_text(encoding="utf-8"))
    tampered["permissions"] = []  # 緩めた想定
    tampered["snapshots"] = False
    target.write_text(json.dumps(tampered), encoding="utf-8")

    launcher["write_isolated_config"](sandbox, project)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after["permissions"] == sandbox["permissions"], "permissions が戻っていない"
    assert after["snapshots"] is True, "snapshots が戻っていない"


def test_unmanaged_keys_survive(tmp_path):
    """★こちらが管理しないキーは残すこと。

    丸ごと上書きすると、TUI で選んだモデルが起動のたびに消える。
    """
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    launcher["write_isolated_config"](sandbox, project)

    target = Path(sandbox["config_dir"]) / "opencode.json"
    config = json.loads(target.read_text(encoding="utf-8"))
    config["model"] = "github-copilot/claude-sonnet-5"
    config["username"] = "alice"
    target.write_text(json.dumps(config), encoding="utf-8")

    launcher["write_isolated_config"](sandbox, project)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after.get("model") == "github-copilot/claude-sonnet-5", "model が消えた"
    assert after.get("username") == "alice", "宣言外のキーが消えた"


def test_broken_config_is_rebuilt(tmp_path):
    """壊れた JSON は作り直す。読めないまま残すと起動できない。"""
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    config_dir = Path(sandbox["config_dir"])
    config_dir.mkdir(parents=True)
    (config_dir / "opencode.json").write_text("{これは JSON ではない", encoding="utf-8")

    launcher["write_isolated_config"](sandbox, project)
    after = json.loads((config_dir / "opencode.json").read_text(encoding="utf-8"))
    assert after["permissions"] == sandbox["permissions"]


def test_default_model_only_on_first_write(tmp_path):
    """既定モデルは初回だけ置き、以降は利用者の選択を尊重する。"""
    launcher = _launcher()
    sandbox = _sandbox(
        tmp_path,
        model_preference=[{"provider": "github-copilot", "model": "claude-opus-5"}],
    )
    project = _project(tmp_path)
    _seed_db(Path(project["db"]))
    target = Path(sandbox["config_dir"]) / "opencode.json"

    def current_model() -> str:
        return json.loads(target.read_text(encoding="utf-8"))["model"]

    launcher["write_isolated_config"](sandbox, project)
    assert current_model() == "github-copilot/claude-opus-5"

    config = json.loads(target.read_text(encoding="utf-8"))
    config["model"] = "github-copilot/claude-sonnet-5"
    target.write_text(json.dumps(config), encoding="utf-8")
    launcher["write_isolated_config"](sandbox, project)
    assert current_model() == "github-copilot/claude-sonnet-5"


def test_model_preference_order_wins(tmp_path):
    """★資格情報がある provider を、宣言した順で選ぶこと。

    無い provider を既定にすると、起動しても応答が来ない。
    """
    launcher = _launcher()
    sandbox = _sandbox(
        tmp_path,
        model_preference=[
            {"provider": "amazon-bedrock", "model": "sonnet-5"},
            {"provider": "github-copilot", "model": "claude-opus-5"},
        ],
    )
    project = _project(tmp_path)
    # bedrock の資格情報は無く、copilot だけある状況
    _seed_db(Path(project["db"]), integration="github-copilot")
    assert launcher["pick_model"](sandbox, project) == "github-copilot/claude-opus-5"


def test_model_is_absent_without_credentials(tmp_path):
    """資格情報が無ければ既定を置かない (誤った provider を固定しない)。"""
    launcher = _launcher()
    sandbox = _sandbox(
        tmp_path,
        model_preference=[{"provider": "amazon-bedrock", "model": "sonnet-5"}],
    )
    project = _project(tmp_path)
    _seed_db(Path(project["db"]), integration="github-copilot")
    assert launcher["pick_model"](sandbox, project) is None


def _base_sandbox() -> dict:
    return {
        "base": {
            "read": ["/opt/shared"],
            "write": [],
            "deny_read": ["/home/u", "/mnt", "/tmp"],
            "protected": [".opencode"],
            "network": {
                "allowedDomains": ["github.com"],
                "deniedDomains": [],
                "allowLocalBinding": False,
            },
        },
        "paths": {
            "data_home": ".opencode-sandbox/data",
            "db": ".opencode-sandbox/opencode.db",
        },
    }


def _request(workspace: Path, body: str) -> Path:
    path = workspace / ".opencode" / "sandbox.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_launch_directory_is_always_writable(tmp_path):
    """★起動ディレクトリ以下は無条件に許可する。

    どこで起動するかは利用者の責務。要求は追加の許可が要るときだけ。
    """
    launcher = _launcher()
    where = tmp_path / "undeclared" / "deep"
    where.mkdir(parents=True)
    filesystem = launcher["build_boundary"](_base_sandbox(), where)["filesystem"]
    assert str(where) in filesystem["allowWrite"]
    # R1: ワークスペースは allowRead にも完全一致で入れる
    assert str(where) in filesystem["allowRead"]


@pytest.mark.parametrize(
    "where",
    ["/home/u", "/home", "/", "/tmp", "/mnt"],
    ids=["deny_read そのもの", "その祖先", "ルート", "/tmp", "/mnt"],
)
def test_workspace_that_cancels_deny_read_is_rejected(where):
    """★deny_read を打ち消す場所では起動しない。

    R3 で allowRead が denyRead に勝つため、deny_read の項目そのものか
    その祖先で起動すると、その deny が丸ごと無効になる。
    """
    launcher = _launcher()
    with pytest.raises(SystemExit):
        launcher["reject_unsafe_workspace"](_base_sandbox(), Path(where))


@pytest.mark.parametrize(
    "where",
    ["/home/u/work/repo", "/tmp/scratch", "/opt/shared/x"],
    ids=["ホーム配下", "/tmp 配下", "deny_read の外"],
)
def test_workspace_below_deny_read_is_allowed(where):
    """子孫での起動は安全なので通す。/tmp/x は /tmp の deny を壊さない。"""
    launcher = _launcher()
    launcher["reject_unsafe_workspace"](_base_sandbox(), Path(where))


def test_unsafe_workspace_is_rejected_before_boundary_is_built(tmp_path, monkeypatch):
    """★拒否は境界を組み立てる前に起きること。

    順序が逆だと、打ち消された境界を一度作ってから捨てることになる。
    """
    launcher = _launcher()
    built = []
    monkeypatch.setitem(launcher, "build_boundary", lambda *a: built.append(a))
    with pytest.raises(SystemExit):
        launcher["reject_unsafe_workspace"](_base_sandbox(), Path("/home/u"))
    assert built == []


def test_no_request_means_no_extras(tmp_path):
    """要求が無ければ追加はゼロ。共通分だけで動く。"""
    launcher = _launcher()
    (tmp_path / "gamma").mkdir()
    boundary = launcher["build_boundary"](_base_sandbox(), tmp_path / "gamma")
    assert boundary["filesystem"]["allowRead"] == [
        str(tmp_path / "gamma"),
        "/opt/shared",
    ]
    assert boundary["network"]["allowedDomains"] == ["github.com"]


def test_request_adds_only_to_its_own_workspace(tmp_path):
    """★要求は、それを置いたワークスペースにしか効かない。"""
    launcher = _launcher()
    alpha, beta = tmp_path / "alpha", tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    _request(
        alpha,
        'read = ["/mnt/d/alpha"]\nnetwork_allow = ["api.alpha.test"]\n',
    )

    got = launcher["build_boundary"](_base_sandbox(), alpha, launcher["read_request"](alpha))
    assert "/mnt/d/alpha" in got["filesystem"]["allowRead"]
    assert "api.alpha.test" in got["network"]["allowedDomains"]

    other = launcher["build_boundary"](_base_sandbox(), beta, launcher["read_request"](beta))
    assert "/mnt/d/alpha" not in other["filesystem"]["allowRead"]
    assert "api.alpha.test" not in other["network"]["allowedDomains"]


def test_request_is_not_inherited_by_subdirectories(tmp_path):
    """★親の要求で子を動かさない。

    起動ディレクトリが境界なので、要求もその場のものだけを見る。
    """
    launcher = _launcher()
    outer = tmp_path / "repo"
    inner = outer / "pkg"
    inner.mkdir(parents=True)
    _request(outer, 'read = ["/outer"]\n')
    allow_read = launcher["build_boundary"](_base_sandbox(), inner)["filesystem"][
        "allowRead"
    ]
    assert "/outer" not in allow_read


def test_request_paths_are_resolved(tmp_path):
    """``~`` と相対パスは展開してから境界へ渡す。

    人が承認するのは「何が開くか」なので、書かれた文字列のままにしない。
    """
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["~/datasets", "sub/dir"]\n')
    allow_read = launcher["build_boundary"](
        _base_sandbox(), ws, launcher["read_request"](ws)
    )["filesystem"]["allowRead"]
    assert str(Path.home() / "datasets") in allow_read
    assert str(ws / "sub/dir") in allow_read
    assert "~/datasets" not in allow_read


def test_protected_paths_are_workspace_relative(tmp_path):
    """保護対象は起動ディレクトリと組み合わせる。"""
    launcher = _launcher()
    where = tmp_path / "gamma"
    where.mkdir()
    deny_write = launcher["build_boundary"](_base_sandbox(), where)["filesystem"][
        "denyWrite"
    ]
    assert str(where / ".opencode") in deny_write


def test_unapproved_request_refuses_to_start(tmp_path, monkeypatch):
    """★承認していない要求では起動しない。

    リポジトリは「要求」できるが「付与」はできない。
    """
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\n')
    monkeypatch.setitem(launcher, "TRUST", tmp_path / "trusted.json")
    monkeypatch.setattr(launcher["sys"].stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        launcher["ensure_trusted"](ws, False, launcher["read_request"](ws))


def test_approval_is_recorded_outside_the_workspace(tmp_path, monkeypatch):
    """承認の記録は境界の外に置く。内側から書けると自分で承認できる。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\n')
    trust = tmp_path / "state" / "trusted.json"
    monkeypatch.setitem(launcher, "TRUST", trust)

    launcher["ensure_trusted"](ws, True, launcher["read_request"](ws))  # --trust
    assert ws not in trust.parents, "承認の記録がワークスペースの中にある"
    # 2 回目は尋ねずに通る (端末が無くても落ちない)
    monkeypatch.setattr(launcher["sys"].stdin, "isatty", lambda: False)
    launcher["ensure_trusted"](ws, False, launcher["read_request"](ws))


def test_changed_request_needs_reapproval(tmp_path, monkeypatch):
    """★要求が変わったら承認をやり直す。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\n')
    monkeypatch.setitem(launcher, "TRUST", tmp_path / "trusted.json")
    launcher["ensure_trusted"](ws, True, launcher["read_request"](ws))

    _request(ws, 'read = ["/mnt/d/alpha", "/home/u/.ssh"]\n')
    monkeypatch.setattr(launcher["sys"].stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        launcher["ensure_trusted"](ws, False, launcher["read_request"](ws))


def test_unknown_keys_in_request_refuse_to_start(tmp_path):
    """知らない項目は黙って無視しない。読み違えたまま承認させない。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\nallow_all = true\n')
    with pytest.raises(SystemExit):
        launcher["read_request"](ws)


def test_approval_prompt_shows_what_opens(tmp_path):
    """承認画面に、実際に開くものが出ること。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\nnetwork_allow = ["api.alpha.test"]\n')
    text = launcher["describe_request"](ws, launcher["read_request"](ws))
    assert "/mnt/d/alpha" in text
    assert "api.alpha.test" in text
    assert str(ws / ".opencode" / "sandbox.toml") in text



def test_system_prompt_is_written(tmp_path):
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    launcher["write_isolated_config"](sandbox, project)
    agents = Path(sandbox["config_dir"]) / "AGENTS.md"
    assert agents.is_file(), "AGENTS.md が書かれていない"
    assert agents.read_text(encoding="utf-8").strip(), "AGENTS.md が空"


# --- 渡した引数が opencode まで届くこと -------------------------------------


def test_passthrough_reaches_opencode():
    """★srt の -c はコマンド文字列を 1 個しか取らない。

    後ろへ並べた引数は srt の位置引数になり **エラーも出さずに捨てられる**。
    `ocs --continue` が素の起動になっていた回帰。
    """
    launcher = _launcher()
    got = launcher["inner_command"](["--continue"])
    assert got.endswith("--standalone --continue"), got
    assert "--session ses_x" in launcher["inner_command"](["--session", "ses_x"])


def test_passthrough_is_quoted():
    """コマンド文字列へ入れる以上、引用符はこちらで付ける。"""
    launcher = _launcher()
    got = launcher["inner_command"](["--prompt", "a; rm -rf /"])
    assert "'a; rm -rf /'" in got, got


# --- git worktree ------------------------------------------------------------


def _worktree(tmp_path: Path) -> tuple[Path, Path]:
    """linked worktree を 1 つ作り、(共有 .git, worktree) を返す。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(repo), *a], check=True, capture_output=True
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (repo / "a.txt").write_text("hi", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "init")
    run("worktree", "add", "-q", str(tmp_path / "wt"), "-b", "feat")
    return repo / ".git", tmp_path / "wt"


def test_worktree_shares_the_main_git_dir(tmp_path):
    """★linked worktree の .git は起動ディレクトリの外を指す。

    足さないと `git status` すら `not a git repository` で落ちる (実測)。
    """
    launcher = _launcher()
    common, wt = _worktree(tmp_path)
    filesystem = launcher["build_boundary"](_base_sandbox(), wt)["filesystem"]
    assert str(common) in filesystem["allowWrite"], "共有 .git が書けない"


def test_worktree_git_hooks_and_config_stay_protected(tmp_path):
    """★共有 .git を開けても hooks と config は閉じたままにする。

    ここへ書けると **ホストで実行されるコード** を仕込める。
    """
    launcher = _launcher()
    common, wt = _worktree(tmp_path)
    deny_write = launcher["build_boundary"](_base_sandbox(), wt)["filesystem"]["denyWrite"]
    assert str(common / "hooks") in deny_write
    assert str(common / "config") in deny_write


def test_plain_repository_adds_nothing(tmp_path):
    """通常のリポジトリでは足すものが無い (起動ディレクトリの中にある)。"""
    launcher = _launcher()
    repo = tmp_path / "plain"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    assert launcher["git_common_dir"](repo) is None


# --- 境界チェックの再利用 ----------------------------------------------------


def test_check_digest_changes_with_the_boundary(tmp_path, monkeypatch):
    """★境界が変われば再検査になること。

    ここに混ぜ忘れた入力は「変わっても古い合格が使われる」ことになる。
    """
    launcher = _launcher()
    sandbox = {"runtime_path": str(tmp_path / "srt.js")}
    one = launcher["check_digest"](sandbox, {"filesystem": {"allowWrite": ["/a"]}})
    two = launcher["check_digest"](sandbox, {"filesystem": {"allowWrite": ["/a", "/b"]}})
    assert one != two, "境界を広げても digest が変わっていない"


def test_seed_db_never_copies_host_conversations(tmp_path, monkeypatch):
    """★ホストの会話をワークスペースへ**一度も書かない**こと。

    以前は ``src.backup(dst)`` で丸ごと写してから要らないテーブルを
    削除していた。削除前の全会話がワークスペース内に存在する時間帯があり、
    同じワークスペースで別セッションが動いていれば読めた。
    """
    launcher = _launcher()
    home = tmp_path / "home"
    source = home / ".local/share/opencode/opencode.db"
    source.parent.mkdir(parents=True)
    con = sqlite3.connect(str(source))
    con.execute("create table credential (id text, integration_id text)")
    con.execute("create table migration (id integer)")
    con.execute("create table session_v2 (id text, title text)")
    con.execute("create table session_message (id text, body text)")
    con.execute("insert into credential values ('c1', 'github-copilot')")
    con.execute("insert into migration values (1)")
    con.execute("insert into session_v2 values ('s1', 'ホストの会話')")
    con.execute("insert into session_message values ('m1', '秘密の本文')")
    con.commit()
    con.close()

    monkeypatch.setitem(launcher, "HOME", home)
    out = tmp_path / "ws" / ".opencode-sandbox" / "opencode.db"
    launcher["seed_db"](out)

    got = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    counts = {
        name: got.execute(f'select count(*) from "{name}"').fetchone()[0]
        for (name,) in got.execute(
            "select name from sqlite_master where type='table'"
            " and name not like 'sqlite_%'"
        )
    }
    got.close()

    assert counts["credential"] == 1, "資格情報が引き継がれていない"
    assert counts["migration"] == 1, "migration が無いと OpenCode が壊れる"
    assert counts["session_v2"] == 0, "ホストの会話が入っている"
    assert counts["session_message"] == 0, "ホストのメッセージが入っている"
    # ★スキーマは残す。テーブルごと消すと OpenCode が作り直せない。
    assert "session_v2" in counts, "スキーマまで落としている"
    # 削除済みデータが空きページに残っていないこと (本文が生で出ないこと)
    assert b"\xe7\xa7\x98\xe5\xaf\x86" not in out.read_bytes(), "本文がファイルに残っている"


def test_seed_db_does_not_leave_a_half_built_db(tmp_path, monkeypatch):
    """★書き途中を ``db.exists()`` に拾わせないこと。

    途中で落ちたものが残ると、次回は初期化を飛ばして**不完全な DB を
    恒久的に再利用**する。別名で作ってから rename する。
    """
    launcher = _launcher()
    home = tmp_path / "home"
    source = home / ".local/share/opencode/opencode.db"
    source.parent.mkdir(parents=True)
    con = sqlite3.connect(str(source))
    con.execute("create table credential (id text)")
    con.commit()
    con.close()

    monkeypatch.setitem(launcher, "HOME", home)
    out = tmp_path / "ws" / "opencode.db"
    launcher["seed_db"](out)

    leftovers = list(out.parent.glob("*.building"))
    assert not leftovers, f"作業用ファイルが残っている: {leftovers}"


def test_boundary_check_is_fail_closed():
    """★検査スクリプトが無ければ起動しないこと。

    以前は ``if not args.skip_check and CHECK.is_file():`` で、配備の失敗や
    ファイル消失が「検査を飛ばして起動」に化けていた。保護が消えても
    誰も気づかない形なので、**存在しないときは die** にする。
    """
    body = LAUNCHER.read_text(encoding="utf-8")
    assert "if not args.skip_check and CHECK.is_file():" not in body, (
        "fail-open の条件が残っている"
    )
    assert "if not CHECK.is_file():" in body, "検査スクリプトの不在を弾いていない"


def test_boundary_file_lives_outside_the_workspace():
    """★境界の定義をワークスペース内に置かないこと。

    tempfile の既定は TMPDIR に従い、このリポジトリでは TMPDIR が
    ワークスペース内を指す。そこは allowWrite 領域なので、srt が読む前に
    **内側から書き換えられる**（同一 UID では 0600 でも別セッションを
    隔離できない）。
    """
    launcher = _launcher()
    boundaries = launcher["BOUNDARIES"]
    assert ".local/state/opencode-sandbox" in str(boundaries), (
        f"境界の置き場が状態領域の外: {boundaries}"
    )
    assert "/.tmp" not in str(boundaries), "TMPDIR 配下に置いている"


def test_prune_boundaries_drops_only_stale_files(tmp_path, monkeypatch):
    """★残骸だけ捨て、稼働中のものは残すこと。

    execve で finally が走らないため自分では消せない。次の起動が前回の分を
    捨てるが、並行して動いているセッションの分を消してはいけない。
    """
    launcher = _launcher()
    monkeypatch.setitem(launcher, "BOUNDARIES", tmp_path)
    monkeypatch.setitem(launcher, "BOUNDARY_MAX_AGE_SECONDS", 3600)

    stale = tmp_path / "opencode-boundary-old.json"
    fresh = tmp_path / "opencode-boundary-new.json"
    other = tmp_path / "checked.json"
    for p in (stale, fresh, other):
        p.write_text("{}", encoding="utf-8")
    os.utime(stale, (0, time.time() - 7200))

    launcher["prune_boundaries"]()

    assert not stale.exists(), "古い残骸が残っている"
    assert fresh.exists(), "稼働中のものを消した"
    assert other.exists(), "対象外のファイルを消した"


def test_check_is_reused_only_while_fresh(tmp_path, monkeypatch):
    """同じ入力の合格は使い回すが、期限を過ぎたら再検査する。"""
    launcher = _launcher()
    monkeypatch.setitem(launcher, "CHECKED", tmp_path / "checked.json")
    assert launcher["check_is_fresh"]("d1") is False, "記録が無いのに合格にした"

    launcher["save_check"]("d1")
    assert launcher["check_is_fresh"]("d1") is True
    assert launcher["check_is_fresh"]("d2") is False, "別の入力で合格にした"

    monkeypatch.setitem(launcher, "CHECK_TTL_SECONDS", 0)
    assert launcher["check_is_fresh"]("d1") is False, "期限を過ぎても合格にした"


# --- 通常版から引き継ぐ設定 --------------------------------------------------


def test_ui_keys_are_inherited_but_never_overwritten(tmp_path, monkeypatch):
    """見た目・操作感は引き継ぎ、隔離版で選んだ値は残す。"""
    launcher = _launcher()
    host = tmp_path / "host.json"
    host.write_text(
        json.dumps({"theme": "dark", "model": "p/host"}), encoding="utf-8"
    )
    monkeypatch.setitem(launcher, "HOST_CONFIG", host)
    got = launcher["inherit_ui"]({"model": "p/chosen"})
    assert got["theme"] == "dark", "テーマが引き継がれていない"
    assert got["model"] == "p/chosen", "隔離版の選択が上書きされた"


def test_security_keys_are_never_inherited(tmp_path, monkeypatch):
    """★緩和に関わるキーを通常版から持ち込まないこと。

    持ち込めると、境界の外の設定で境界の内側の permission を決められる。
    """
    launcher = _launcher()
    host = tmp_path / "host.json"
    host.write_text(
        json.dumps(
            {
                "permissions": [],
                "plugins": ["evil"],
                "mcp": {"x": {}},
                "agent": {"a": {}},
                "experimental": {"policies": []},
                "tools": {"bash": True},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(launcher, "HOST_CONFIG", host)
    got = launcher["inherit_ui"]({})
    assert got == {}, f"引き継いではいけないキーが入った: {sorted(got)}"


def test_skill_roots_are_readable_inside_the_boundary():
    """★skill 置き場が read に載っていること。

    deny_read の ~ に埋もれると skill が 1 つも読めなくなる (実測)。
    """
    read = (gen.opencode_sandbox(COMMON) or {}).get("base", {}).get("read", [])
    joined = " ".join(read)
    assert ".claude/skills" in joined, "~/.claude/skills が読めない"
    assert ".agents/skills" in joined, "~/.agents/skills が読めない"


# --- 起動前の退避 ------------------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(
            ["git", "-C", str(repo), "config", key, value], check=True, capture_output=True
        )
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "init"], check=True, capture_output=True
    )
    return repo


def _backups(launcher: dict) -> list[Path]:
    return sorted(launcher["BACKUPS"].rglob("*.tgz"))


def test_backup_never_touches_the_worktree(tmp_path, monkeypatch):
    """★`git stash` とは別物。作業ツリーを巻き戻さないこと。

    再開のたびに変更が消えるなら、退避ではなく破壊になる。
    """
    launcher = _launcher()
    monkeypatch.setitem(launcher, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    (repo / "b.txt").write_text("untracked\n", encoding="utf-8")

    launcher["backup_worktree"](repo, False)

    assert (repo / "a.txt").read_text(encoding="utf-8") == "changed\n", "変更が巻き戻った"
    assert (repo / "b.txt").is_file(), "未追跡ファイルが消えた"


def test_backup_is_skipped_when_nothing_is_uncommitted(tmp_path, monkeypatch):
    """未コミットの変更が無ければ退避しない。"""
    launcher = _launcher()
    monkeypatch.setitem(launcher, "BACKUPS", tmp_path / "store")
    launcher["backup_worktree"](_repo(tmp_path), False)
    assert _backups(launcher) == []


def test_identical_content_is_not_backed_up_twice(tmp_path, monkeypatch):
    """★中断と再開を繰り返しても溜まらないこと。

    同じ内容なら同じ tree SHA になるので作り直さない。
    """
    launcher = _launcher()
    monkeypatch.setitem(launcher, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")

    launcher["backup_worktree"](repo, False)
    launcher["backup_worktree"](repo, False)
    assert len(_backups(launcher)) == 1, "同じ内容で 2 つ作られた"

    (repo / "a.txt").write_text("changed again\n", encoding="utf-8")
    launcher["backup_worktree"](repo, False)
    assert len(_backups(launcher)) == 2, "内容が変わったのに退避されていない"


def test_backup_excludes_ignored_files(tmp_path, monkeypatch):
    """.gitignore が効くこと (隔離用 DB などを巻き込まない)。"""
    import tarfile

    launcher = _launcher()
    monkeypatch.setitem(launcher, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("heavy/\n", encoding="utf-8")
    (repo / "heavy").mkdir()
    (repo / "heavy" / "db.bin").write_text("x" * 1000, encoding="utf-8")

    launcher["backup_worktree"](repo, False)
    with tarfile.open(_backups(launcher)[0]) as archive:
        names = archive.getnames()
    assert "heavy/db.bin" not in names, f"無視されるはずのものが入った: {names}"
    assert ".gitignore" in names


def test_backup_is_restorable(tmp_path, monkeypatch):
    """★退避から中身が戻せること。ファイルが在ることを合格にしない。"""
    import tarfile

    launcher = _launcher()
    monkeypatch.setitem(launcher, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("precious\n", encoding="utf-8")

    launcher["backup_worktree"](repo, False)
    out = tmp_path / "restored"
    with tarfile.open(_backups(launcher)[0]) as archive:
        archive.extractall(out, filter="data")
    assert (out / "a.txt").read_text(encoding="utf-8") == "precious\n"


def test_old_backups_are_pruned(tmp_path, monkeypatch):
    """世代数で頭を押さえること。"""
    launcher = _launcher()
    monkeypatch.setitem(launcher, "BACKUPS", tmp_path / "store")
    monkeypatch.setitem(launcher, "BACKUP_KEEP", 3)
    repo = _repo(tmp_path)
    for i in range(6):
        (repo / "a.txt").write_text(f"rev {i}\n", encoding="utf-8")
        launcher["backup_worktree"](repo, False)
    assert len(_backups(launcher)) == 3


def test_oversized_worktree_is_measured_before_hashing(tmp_path, monkeypatch):
    """★大きすぎる作業ツリーは、**ハッシュする前に**断ること。

    作ってから間引くと、巨大なリポジトリで .git を肥大させたうえに
    時間を使う（実測で追跡対象だけ 84 GB のリポジトリがあった）。
    """
    launcher = _launcher()
    monkeypatch.setitem(launcher, "BACKUPS", tmp_path / "store")
    monkeypatch.setitem(launcher, "BACKUP_MAX_SOURCE_BYTES", 1024)
    repo = _repo(tmp_path)
    (repo / "big.bin").write_text("x" * 4096, encoding="utf-8")

    before = _git_object_count(repo)
    with pytest.raises(SystemExit):
        launcher["backup_worktree"](repo, False)
    assert _backups(launcher) == [], "断ったのに退避が残っている"
    assert _git_object_count(repo) == before, "断る前に .git へ書き込んでいる"


def _git_object_count(repo: Path) -> int:
    done = subprocess.run(
        ["git", "-C", str(repo), "count-objects", "-v"],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in done.stdout.splitlines():
        if line.startswith("count:"):
            return int(line.split()[1])
    return 0


def test_total_size_is_capped_across_projects(tmp_path, monkeypatch):
    """★起動ディレクトリごとの上限だけでは全体が青天井になる。

    プロジェクトが増えても合計で頭を押さえること。
    """
    launcher = _launcher()
    store = tmp_path / "store"
    monkeypatch.setitem(launcher, "BACKUPS", store)
    monkeypatch.setitem(launcher, "BACKUP_TOTAL_MAX_BYTES", 1)  # 実質 1 件だけ残る
    for name in ("one", "two", "three"):
        repo = _repo(tmp_path / name)
        (repo / "a.txt").write_text(f"{name}\n", encoding="utf-8")
        launcher["backup_worktree"](repo, False)
    assert len(_backups(launcher)) <= 1, "全体の上限が効いていない"


def test_expired_backups_are_dropped(tmp_path, monkeypatch):
    """触らなくなったプロジェクトの分を期限で捨てること。"""
    launcher = _launcher()
    store = tmp_path / "store"
    monkeypatch.setitem(launcher, "BACKUPS", store)
    stale = store / "abandoned-000000000000"
    stale.mkdir(parents=True)
    old = stale / "20200101T000000+0000-deadbeefcafe.tgz"
    old.write_bytes(b"old")
    ancient = time.time() - (launcher["BACKUP_MAX_AGE_DAYS"] + 1) * 86400
    os.utime(old, (ancient, ancient))

    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("fresh\n", encoding="utf-8")
    launcher["backup_worktree"](repo, False)

    assert not old.exists(), "期限切れの退避が残っている"
    assert not stale.exists(), "空になった置き場が残っている"


def test_launch_is_refused_when_the_backup_fails(tmp_path, monkeypatch):
    """★退避できなければ**起動しない**。

    「退避したつもり」で作業を始めるのが一番危ない。
    """
    launcher = _launcher()
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    monkeypatch.setitem(launcher, "BACKUPS", blocked)
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    try:
        with pytest.raises(SystemExit):
            launcher["backup_worktree"](repo, False)
    finally:
        blocked.chmod(0o700)


def test_backup_location_is_outside_the_workspace(tmp_path, monkeypatch):
    """★退避先が境界の内側にあってはいけない。

    内側から消せるなら復旧元にならない。
    """
    launcher = _launcher()
    repo = _repo(tmp_path)
    assert repo not in launcher["BACKUPS"].parents, "退避先がワークスペースの中にある"
    assert str(launcher["BACKUPS"]).startswith(str(Path.home() / ".local/state"))


def test_backup_is_scoped_to_the_launch_directory(tmp_path, monkeypatch):
    """★git は親を遡る。サブディレクトリで起動しても親全体を掴まないこと。

    境界が書き込みを許すのは起動ディレクトリ以下なので、退避も揃える。
    """
    import tarfile

    launcher = _launcher()
    monkeypatch.setitem(launcher, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "inner.txt").write_text("work\n", encoding="utf-8")

    launcher["backup_worktree"](pkg, False)

    with tarfile.open(_backups(launcher)[0]) as archive:
        names = archive.getnames()
    assert "inner.txt" in names, f"起動ディレクトリの中身が入っていない: {names}"
    assert "a.txt" not in names, f"親リポジトリまで退避した: {names}"


def test_untracked_only_directory_does_not_block_launch(tmp_path, monkeypatch):
    """退避するものが無くても起動を止めないこと。

    Git リポジトリでない場所や、中身が全て .gitignore の場所が当たる。
    """
    launcher = _launcher()
    monkeypatch.setitem(launcher, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("skip/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "ignore"], check=True, capture_output=True
    )
    skipped = repo / "skip"
    skipped.mkdir()
    (skipped / "junk.txt").write_text("junk\n", encoding="utf-8")

    launcher["backup_worktree"](skipped, False)  # 例外を出さないこと
    assert _backups(launcher) == []
