"""kcage コマンド（cli.py）の試験。sudo・incus は呼ばず、FakeRunner で argv を確かめる。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from kcage import cli, gitmeta, model

HELPER = f"{model.ROOT_HELPER_DIR}/kcage-root"
POLICY = """
[defaults]
network = "nat"

[repo.demo]
path = "/work/demo"
network = "proxy-only"
proxy_upstream = "192.0.2.10:3128"
"""


class FakeFs(cli.Fs):
    def __init__(self, files: dict[str, str]):
        self.files = files

    def read_text(self, path: str) -> str:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def exists(self, path: str) -> bool:
        return path in self.files

    def realpath(self, path: str) -> str:
        return path


class FakeRunner:
    """呼ばれた argv を記録し、あらかじめ決めた応答を返す。"""

    def __init__(
        self, answers: dict[tuple[str, ...], cli.Result] | None = None, *, top: str = "/work/demo"
    ):
        self.calls: list[list[str]] = []
        self.answers = answers or {}
        self.top = top

    def __call__(self, argv, *, capture: bool = False):
        argv = list(argv)
        self.calls.append(argv)
        if argv[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return cli.Result(0, self.top + "\n")
        for key, res in self.answers.items():
            if tuple(argv[: len(key)]) == key:
                return res
        return cli.Result(0)


def fs_with(policy: str = POLICY, extra: dict[str, str] | None = None) -> FakeFs:
    return FakeFs({model.POLICY_PATH: policy, **(extra or {})})


@pytest.mark.parametrize(
    ("verb", "expected"),
    [
        ("up", ["sudo", "-n", HELPER, "up", "demo"]),
        ("stop", ["sudo", "-n", HELPER, "stop", "demo"]),
        ("rm", ["sudo", HELPER, "rm", "demo"]),
        ("snap", ["sudo", HELPER, "snap", "demo"]),
    ],
)
def test_動詞はbox_rootのargvへ対応しpasswordlessだけsudo_nになる(verb, expected):
    runner = FakeRunner()
    assert cli.main([verb], runner=runner, fs=fs_with()) == 0
    assert runner.calls[-1] == expected


def test_lsはリポジトリidなしでsudo_nを使う():
    runner = FakeRunner()
    cli.main(["ls"], runner=runner, fs=fs_with())
    assert runner.calls[-1] == ["sudo", "-n", HELPER, "ls"]


def test_piはexecの後ろにダッシュ2つとpiと引数を置く():
    runner = FakeRunner()
    cli.main(["pi", "--", "-p", "hello"], runner=runner, fs=fs_with())
    assert runner.calls[-1] == [
        "sudo",
        "-n",
        HELPER,
        "exec",
        "demo",
        "--",
        "/opt/kcage-dist/bin/kcage-pi",
        "-p",
        "hello",
    ]


def test_snapは名前を渡せる():
    runner = FakeRunner()
    cli.main(["snap", "before"], runner=runner, fs=fs_with())
    assert runner.calls[-1] == ["sudo", HELPER, "snap", "demo", "before"]


def test_registerは許可表になくても動きパスワードを尋ねる():
    runner = FakeRunner(top="/work/new-repo")
    cli.main(["register"], runner=runner, fs=fs_with())
    assert runner.calls[-1] == ["sudo", HELPER, "register", "new-repo", "--path", "/work/new-repo"]


def test_明示のrepoは許可表を引かずに使う():
    runner = FakeRunner(top="/elsewhere")
    cli.main(["up", "--repo", "other"], runner=runner, fs=fs_with())
    assert runner.calls[-1] == ["sudo", "-n", HELPER, "up", "other"]


def test_未登録のリポジトリは呼び出さずに終わる(capsys):
    runner = FakeRunner(top="/work/unknown")
    assert cli.main(["up"], runner=runner, fs=fs_with()) == 2
    assert all(c[0] != "sudo" for c in runner.calls)
    assert "kcage register" in capsys.readouterr().out


def test_許可表が読めなければ呼び出さない():
    runner = FakeRunner()
    assert cli.main(["up"], runner=runner, fs=FakeFs({})) == 2


def test_passwordlessの失敗は理由を表示し終了コードを返す(capsys):
    runner = FakeRunner({("sudo", "-n"): cli.Result(1)})
    assert cli.main(["up"], runner=runner, fs=fs_with()) == 1
    assert "kcage doctor" in capsys.readouterr().out


def test_shellを使わずリスト形式のargvだけを渡す():
    runner = FakeRunner()
    cli.main(["pi", "--", "a b; rm -rf /"], runner=runner, fs=fs_with())
    assert "a b; rm -rf /" in runner.calls[-1]  # 1 つの引数のまま（分割されない）


def test_setupはsudoでsetup_pyを実行する():
    runner = FakeRunner()
    cli.main(["setup", "--dry-run"], runner=runner, fs=fs_with())
    argv = runner.calls[-1]
    assert argv[:2] == ["sudo", "python3"]
    assert argv[2].endswith("scripts/kcage/setup.py")
    assert argv[-1] == "--dry-run"


# ---- doctor ----

SUDO_OK = f"    (root) NOPASSWD: {HELPER} up *, {HELPER} stop *\n"


def doctor(runner: FakeRunner, fs: FakeFs, capsys) -> tuple[int, str]:
    rc = cli.main(["doctor"], runner=runner, fs=fs)
    return rc, capsys.readouterr().out


def test_doctorは正常なら0(capsys):
    runner = FakeRunner({("sudo", "-n", "-l"): cli.Result(0, SUDO_OK)})
    rc, out = doctor(runner, fs_with(), capsys)
    assert rc == 0
    assert "登録済み: demo" in out
    assert "[OK  ] sudoers" in out


def test_doctorはsudoersの雛形がなければ失敗(capsys):
    runner = FakeRunner({("sudo", "-n", "-l"): cli.Result(1)})
    rc, out = doctor(runner, fs_with(), capsys)
    assert rc == 1
    assert "[FAIL] sudoers" in out


def test_doctorは許可表が読めなければ失敗(capsys):
    runner = FakeRunner({("sudo", "-n", "-l"): cli.Result(0, SUDO_OK)})
    rc, out = doctor(runner, FakeFs({}), capsys)
    assert rc == 1
    assert "[FAIL] 許可表" in out


def test_doctorは未登録を警告する(capsys):
    runner = FakeRunner({("sudo", "-n", "-l"): cli.Result(0, SUDO_OK)}, top="/work/other")
    rc, out = doctor(runner, fs_with(), capsys)
    assert rc == 0
    assert "[WARN] 許可表" in out


def test_doctorはhooksPathとworktreeConfigを警告する(capsys):
    runner = FakeRunner(
        {
            ("sudo", "-n", "-l"): cli.Result(0, SUDO_OK),
            ("git", "config", "--get", "core.hooksPath"): cli.Result(0, ".githooks\n"),
            ("git", "config", "--get", "extensions.worktreeConfig"): cli.Result(0, "true\n"),
        }
    )
    rc, out = doctor(runner, fs_with(), capsys)
    assert rc == 0  # 警告だけ（C14）
    assert "[WARN] core.hooksPath" in out
    assert "[WARN] extensions.worktreeConfig" in out


def test_doctorはbox_tomlが無ければ警告_壊れていれば失敗(capsys):
    ok = {("sudo", "-n", "-l"): cli.Result(0, SUDO_OK)}
    _, out = doctor(FakeRunner(ok), fs_with(), capsys)
    assert "[WARN] kcage.toml" in out
    rc, out = doctor(FakeRunner(ok), fs_with(extra={"/work/demo/kcage.toml": "gpu = ["}), capsys)
    assert rc == 1
    assert "[FAIL] kcage.toml" in out


# ---- selftest の判定（純粋） ----


def test_ホームの秘密が見えたら失敗():
    assert cli.judge_home_secrets("").status == "ok"
    assert cli.judge_home_secrets("/home/ubuntu/.ssh\n").status == "fail"


def test_環境変数の秘密は名前だけを出し値は出さない():
    dummy = "ghp_" + "A" * 30
    res = cli.judge_env(f"PATH=/usr/bin\nGH_TOKEN={dummy}\n")
    assert res.status == "fail"
    assert "GH_TOKEN" in res.detail
    assert dummy not in res.detail
    assert cli.judge_env("PATH=/usr/bin\nHOME=/home/ubuntu\nTOKEN_URL=\n").status == "ok"


def test_gitの読み取り専用の判定():
    ro = ".git/hooks=ro\n.git/config=ro\n.git/commondir=ro\n"
    assert cli.judge_git_ro(ro).status == "ok"
    assert cli.judge_git_ro(".git/hooks=rw\n.git/config=ro\n.git/commondir=ro\n").status == "fail"
    # commondir が書ける（古い箱）
    assert cli.judge_git_ro(".git/hooks=ro\n.git/config=ro\n.git/commondir=rw\n").status == "fail"
    assert cli.judge_git_ro(".git/hooks=ro\n.git/config=ro\n").status == "fail"
    assert cli.judge_git_ro("").status == "fail"


GIT = "/work/demo/.git"


def test_git_metadata_の判定():
    ins = gitmeta.inspect_metadata
    assert ins(None, GIT, frozenset()) == [("ok", "追加の参照先なし")]
    assert ins(b".\n", GIT, frozenset()) == [("ok", "追加の参照先なし")]
    assert ins(GIT.encode(), GIT, frozenset())[0][0] == "ok"
    assert ins(b"/tmp/x", GIT, frozenset())[0][0] == "fail"
    names = [n for n, _ in gitmeta.WARN_ENTRIES]
    for n in names:
        assert ins(None, GIT, frozenset({n}))[0][0] == "warn"
    assert len(ins(None, GIT, frozenset(names))) == len(names)


class GitFs(FakeFs):
    def __init__(self, files: dict[str, str], dirs: set[str]):
        super().__init__(files)
        self.dirs = dirs

    def isdir(self, path: str) -> bool:
        return path in self.dirs

    def exists(self, path: str) -> bool:
        return path in self.files or path in self.dirs

    def read_bytes(self, path: str):
        return self.files[path].encode() if path in self.files else None


def _git_doctor(files: dict[str, str], dirs: set[str], capsys):
    runner = FakeRunner({("sudo", "-n", "-l"): cli.Result(0, SUDO_OK)})
    base = fs_with()
    fs = GitFs({**base.files, **files}, {GIT, *dirs})
    rc = cli.main(["doctor"], runner=runner, fs=fs)
    return rc, capsys.readouterr().out


def test_doctorはcommondirが別の場所なら失敗(capsys):
    rc, out = _git_doctor({GIT + "/commondir": "/tmp/x\n"}, set(), capsys)
    assert rc == 1
    assert "[FAIL] git の metadata" in out


def test_doctorはgitのmetadataに追加の参照先が無ければok(capsys):
    rc, out = _git_doctor({GIT + "/commondir": ".\n"}, set(), capsys)
    assert rc == 0
    assert "[OK  ] git の metadata: 追加の参照先なし" in out


def test_doctorはmodulesなどを警告する(capsys):
    rc, out = _git_doctor({GIT + "/config.worktree": ""}, {GIT + "/modules"}, capsys)
    assert rc == 0
    assert out.count("[WARN] git の metadata") == 2


def test_直通はproxy_onlyのときだけ検査する():
    assert cli.judge_direct("rc=0", "nat").status == "ok"
    assert cli.judge_direct("rc=0", "proxy-only").status == "fail"
    assert cli.judge_direct("rc=6", "proxy-only").status == "ok"
    assert cli.judge_direct("", "proxy-only").status == "fail"


def test_selftestは箱の中のexecだけをsudo_nで呼ぶ(capsys):
    answers = {
        ("sudo", "-n", HELPER, "exec", "demo", "--", "env"): cli.Result(0, "PATH=/usr/bin\n"),
        ("sudo", "-n", HELPER, "exec", "demo", "--", "sh", "-c", "curl"): cli.Result(0),
    }
    runner = FakeRunner(answers)

    def run(argv, *, capture=False):
        res = runner(argv, capture=capture)
        joined = " ".join(argv)
        if "curl" in joined:
            return cli.Result(0, "rc=7\n")
        if ".git/hooks" in joined:
            return cli.Result(0, ".git/hooks=ro\n.git/config=ro\n.git/commondir=ro\n")
        return res

    assert cli.main(["selftest"], runner=run, fs=fs_with()) == 0
    out = capsys.readouterr().out
    assert "直通は失敗" in out  # demo は proxy-only
    execs = [c for c in runner.calls if c[0] == "sudo"]
    assert execs
    assert all(c[:4] == ["sudo", "-n", HELPER, "exec"] for c in execs)


# ---- 構造 ----


def test_本体はadaptersをimportしない():
    root = Path(__file__).resolve().parents[2] / "scripts" / "kcage"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "")] + [a.name for a in node.names]
            assert not any("adapters" in n for n in names), f"{path.name}: {names}"


# ---- template ----

PI_PKG_JSON = '{"name": "@earendil-works/pi-coding-agent", "version": "1.5.0"}'
PI_EXE = "/opt/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"


def test_templateは配布物を作りsudoでbox_root_templateを呼ぶ(tmp_path):
    runner = FakeRunner()
    built: list[Path] = []
    rc = cli.cmd_template(runner, fs_with(), built.append, lambda: "1.5.0", home=str(tmp_path))
    dest = tmp_path / ".cache" / "kcage" / "dist"
    assert rc == 0 and built == [dest]
    assert runner.calls == [
        ["sudo", HELPER, "template", "--dist", str(dest), "--pi-version", "1.5.0"]
    ]
    assert "-n" not in runner.calls[0]  # パスワードを尋ねる（passwordless ではない）
    assert (tmp_path / ".cache" / "kcage").stat().st_mode & 0o777 == 0o700
    assert dest.stat().st_mode & 0o777 == 0o700 if dest.exists() else True


def test_templateはサブコマンドとして呼べる(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = FakeRunner()
    assert cli.main(["template"], runner=runner, fs=fs_with(), dist_builder=lambda d: None,
                    pi_version_reader=lambda: None) == 0  # fmt: skip
    assert runner.calls[-1][:3] == ["sudo", HELPER, "template"]


def test_templateは版が読めなければ警告して版なしで呼ぶ(tmp_path, capsys):
    runner = FakeRunner()
    rc = cli.cmd_template(runner, fs_with(), lambda d: None, lambda: None, home=str(tmp_path))
    assert rc == 0
    assert "--pi-version" not in runner.calls[0]
    assert "警告" in capsys.readouterr().out


def test_templateは配布物の作成に失敗したらsudoを呼ばない(tmp_path, capsys):
    def boom(dest):
        raise RuntimeError("配布物に秘密らしいものがある")

    runner = FakeRunner()
    assert cli.cmd_template(runner, fs_with(), boom, lambda: "1.5.0", home=str(tmp_path)) == 1
    assert runner.calls == []


def test_templateは配布物の作成関数が無ければ止まる(tmp_path):
    runner = FakeRunner()
    assert cli.cmd_template(runner, fs_with(), None, home=str(tmp_path)) == 2
    assert runner.calls == []


def test_配布物のディレクトリがsymlinkなら拒否する(tmp_path):
    (tmp_path / ".cache").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / ".cache" / "kcage").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OSError):
        cli.prepare_dist_dir(str(tmp_path))


def test_piの版はパッケージのpackage_jsonから読む():
    fs = FakeFs({"/opt/node_modules/@earendil-works/pi-coding-agent/package.json": PI_PKG_JSON})
    assert cli.find_pi_version(PI_EXE, fs) == "1.5.0"


def test_piの版が読めないか不正なら_None():
    pkg = "/opt/node_modules/@earendil-works/pi-coding-agent/package.json"
    assert cli.find_pi_version(PI_EXE, FakeFs({})) is None
    assert cli.find_pi_version(PI_EXE, FakeFs({pkg: "not json"})) is None
    bad = '{"name": "@earendil-works/pi-coding-agent", "version": "latest"}'
    assert cli.find_pi_version(PI_EXE, FakeFs({pkg: bad})) is None
    other = '{"name": "other", "version": "1.2.3"}'
    assert cli.find_pi_version(PI_EXE, FakeFs({pkg: other})) is None


# ---- ガードの案内文が許可動詞として挙げている kcage exec（箱の中でコマンドを実行する）


def test_exec_は箱の中のコマンドを_passwordless_で実行する():
    runner = FakeRunner()
    assert cli.main(["exec", "--", "ls", "-l"], runner=runner, fs=fs_with()) == 0
    assert runner.calls[-1] == ["sudo", "-n", HELPER, "exec", "demo", "--", "ls", "-l"]


def test_exec_はコマンドが無ければ実行せず_2_を返す():
    runner = FakeRunner()
    assert cli.main(["exec"], runner=runner, fs=fs_with()) == 2
    assert not any("exec" in c for c in runner.calls if c[:2] == ["sudo", "-n"])


# ---- e2e で見つけた: ブローカーがダミーの認証を環境変数に入れるので selftest が誤検出していた


def test_selftest_の環境変数の判定はブローカーのダミーを許し本物らしい値は拒否する():
    from kcage.broker import copilot, gh

    assert gh.DUMMY_TOKEN.startswith(cli.DUMMY_PREFIX)
    assert copilot.DUMMY_TOKEN.startswith(cli.DUMMY_PREFIX)
    ok = f"GH_TOKEN={gh.DUMMY_TOKEN}\nCOPILOT_GITHUB_TOKEN={copilot.DUMMY_TOKEN}\n"
    assert cli.judge_env(ok).status == "ok"
    real = "GH_TOKEN=ghp_" + "A" * 36 + "\n"
    assert cli.judge_env(real).status == "fail"
