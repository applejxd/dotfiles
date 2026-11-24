"""T3 Code (Windows と WSL) を Tailscale Serve で出すための chezmoi スクリプトの試験。

WSL 側の `service.env` を書くスクリプトは、描画して実際に bash で動かす (`t3` は偽物。呼ばれないことを見る)。
Windows 側の PowerShell は動かせないので静的に見る (実機の実行結果は docs に記録)。

see docs/spec/t3code-remote-access.md
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ENV = ROOT / "home/.chezmoiscripts/100_linux/run_after_127_t3code_service_env.sh.tmpl"
WIN_PORT = ROOT / "home/.chezmoiscripts/300_windows/run_after_353_t3code_port.ps1.tmpl"
WIN_SERVE = ROOT / "home/.chezmoiscripts/300_windows/run_after_354_t3code_wsl_serve.ps1.tmpl"
BACKSLASH = chr(92)
WSL_KERNEL = "5.15.167.4-microsoft-standard-WSL2"


def _chezmoi() -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    return chezmoi


def _bash() -> str:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not installed")
    return bash


def _render(username: str, osrelease: str, work: bool | None = None) -> str:
    """ユーザー名・カーネル・work (is-work の上書き) だけを差し替えて、WSL のスクリプトを描画する。"""
    data: dict = {"chezmoi": {"username": username, "kernel": {"osrelease": osrelease}}}
    if work is not None:
        data["work"] = work
    return _render_template(SERVICE_ENV, data)


class Home:
    """偽の HOME と、呼ばれた回数を記録する偽の `t3`。"""

    def __init__(self, tmp_path: Path):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.log = tmp_path / "t3.log"
        stub = self.bin / "t3"
        stub.write_text('#!/bin/bash\necho "$*" >> "$T3_LOG"\n', encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.script = tmp_path / "script.sh"

    @property
    def env_file(self) -> Path:
        return self.home / ".t3" / "service.env"

    def run(self, script: str) -> subprocess.CompletedProcess[str]:
        self.script.write_text(script, encoding="utf-8", newline="\n")
        env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "T3_LOG": str(self.log),
        }
        return subprocess.run(
            [_bash(), str(self.script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )

    def t3_calls(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""


@pytest.fixture
def home(tmp_path) -> Home:
    return Home(tmp_path)


def _script() -> str:
    return _render("applejxd", WSL_KERNEL)


@pytest.mark.parametrize(
    ("username", "osrelease", "work", "deployed"),
    [
        ("applejxd", WSL_KERNEL, None, True),  # 家の機 (個人のユーザー名)
        ("HOST" + BACKSLASH + "applejxd", WSL_KERNEL, None, True),  # Windows 形式のドメイン付き
        ("applejxd", WSL_KERNEL, True, False),  # 個人のユーザー名でも、会社 PC と明示した機
        ("other-user", WSL_KERNEL, None, False),  # 会社 PC とみなす
        ("other-user", WSL_KERNEL, False, True),  # 家の機と明示した機
        ("applejxd", "6.8.0-45-generic", None, False),  # WSL ではない
    ],
)
def test_service_env_script_is_only_for_home_machines_on_wsl(username, osrelease, work, deployed):
    # 判定は is-work (会社 PC の判定の単一ソース)。WSL かどうかはカーネルの名前で見る
    assert bool(_render(username, osrelease, work).strip()) is deployed


def test_service_env_is_left_alone_when_t3_home_is_missing(home):
    result = home.run(_script())
    assert result.returncode == 0, result.stderr
    assert not (home.home / ".t3").exists()


def test_service_env_is_created_private_with_the_two_keys(home):
    (home.home / ".t3").mkdir()
    result = home.run(_script())
    assert result.returncode == 0, result.stderr
    assert home.env_file.read_text(encoding="utf-8") == "T3CODE_PORT=3776\nT3CODE_HOST=127.0.0.1\n"
    if os.name == "posix":
        assert stat.S_IMODE(home.env_file.stat().st_mode) == 0o600


def test_service_env_replaces_only_the_managed_keys_and_keeps_the_rest(home):
    (home.home / ".t3").mkdir()
    home.env_file.write_text(
        "# メモ\n"
        "T3CODE_PORT=45899\n"
        "OTHER_KEY=keep me\n"
        "T3CODE_LAN=true\n"
        "T3CODE_PORT=1111\n"  # 重複は 1 つにまとめる
        "  T3CODE_HOST = 0.0.0.0\n",
        encoding="utf-8",
        newline="\n",
    )
    result = home.run(_script())
    assert result.returncode == 0, result.stderr
    assert home.env_file.read_text(encoding="utf-8") == (
        "# メモ\nT3CODE_PORT=3776\nOTHER_KEY=keep me\nT3CODE_LAN=true\nT3CODE_HOST=127.0.0.1\n"
    )


def test_service_env_second_run_changes_nothing(home):
    (home.home / ".t3").mkdir()
    assert home.run(_script()).returncode == 0
    first = home.env_file.read_bytes()
    second = home.run(_script())
    assert second.returncode == 0, second.stderr
    assert home.env_file.read_bytes() == first
    assert "設定済み" in second.stdout


def test_service_env_script_never_restarts_the_service(home):
    # 再起動は実行中のエージェントの処理を止める。案内するだけで、自動では呼ばない
    (home.home / ".t3").mkdir()
    result = home.run(_script())
    assert home.t3_calls() == ""
    assert "t3 service restart" in result.stdout
    code = "\n".join(
        line for line in SERVICE_ENV.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith(("#", "echo"))
    )
    assert "t3 service" not in code
    assert "systemctl" not in code


def test_service_env_script_does_not_touch_other_files(home):
    (home.home / ".t3").mkdir()
    other = home.home / ".t3" / "keep.txt"
    other.write_text("x", encoding="utf-8")
    home.run(_script())
    assert other.read_text(encoding="utf-8") == "x"
    assert sorted(p.name for p in (home.home / ".t3").iterdir()) == ["keep.txt", "service.env"]




def test_service_env_keeps_the_mode_of_an_existing_file(home):
    if os.name != "posix":
        pytest.skip("権限ビットは POSIX だけ")
    (home.home / ".t3").mkdir()
    home.env_file.write_text("OTHER=1\n", encoding="utf-8")
    home.env_file.chmod(0o640)
    assert home.run(_script()).returncode == 0
    assert stat.S_IMODE(home.env_file.stat().st_mode) == 0o640
    assert "OTHER=1\n" in home.env_file.read_text(encoding="utf-8")


def test_service_env_follows_a_symlink_instead_of_replacing_it(home):
    if os.name != "posix":
        pytest.skip("symlink は POSIX だけ")
    (home.home / ".t3").mkdir()
    real = home.home / "real.cfg"
    real.write_text("OTHER=1\n", encoding="utf-8")
    home.env_file.symlink_to(real)
    assert home.run(_script()).returncode == 0
    assert home.env_file.is_symlink()
    assert real.read_text(encoding="utf-8") == "OTHER=1\nT3CODE_PORT=3776\nT3CODE_HOST=127.0.0.1\n"


def test_service_env_is_not_touched_when_it_is_not_a_regular_file(home):
    (home.home / ".t3" / "service.env").mkdir(parents=True)
    result = home.run(_script())
    assert result.returncode == 0, result.stderr
    assert "通常のファイルではない" in result.stderr


def test_service_env_is_not_overwritten_when_it_changes_during_processing(home):
    # t3 up などが、読んでから置き換えるまでの間に書き足したら、その追加を消さない
    if os.name != "posix":
        pytest.skip("偽の awk は POSIX だけ")
    real_awk = shutil.which("awk")
    if real_awk is None:
        pytest.skip("awk is not installed")
    (home.home / ".t3").mkdir()
    home.env_file.write_text("OTHER=1\n", encoding="utf-8")
    fake = home.bin / "awk"
    fake.write_text(
        f'#!/bin/bash\n"{real_awk}" "$@"\nstatus=$?\necho "ADDED_BY_T3_UP=1" >> "$HOME/.t3/service.env"\nexit $status\n',
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    result = home.run(_script())
    assert result.returncode == 0, result.stderr
    text = home.env_file.read_text(encoding="utf-8")
    assert "ADDED_BY_T3_UP=1" in text
    assert "T3CODE_PORT=3776" not in text
    assert "処理中に変わった" in result.stderr


# ---- Windows ----


def _windows(path: Path) -> str:
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM が必要"
    return raw.decode("utf-8-sig")


def _render_template(path: Path, data: dict) -> str:
    """`.` を指定のデータに差し替えて描画する (`is-work` も同じ `.` を見る)。"""
    template = (
        "{{ with " + json.dumps(json.dumps(data)) + " | fromJson }}\n"
        + path.read_text(encoding="utf-8-sig")
        + "\n{{ end }}"
    )
    result = subprocess.run(
        [_chezmoi(), "--source", str(ROOT), "execute-template"],
        input=template,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize(
    ("data", "deployed"),
    [
        ({"chezmoi": {"username": "applejxd"}}, True),  # 家の機 (個人のユーザー名)
        ({"chezmoi": {"username": "applejxd"}, "work": True}, False),  # 個人のユーザー名でも、会社 PC と明示した機
        ({"chezmoi": {"username": "other-user"}}, False),  # 会社 PC とみなす
        ({"chezmoi": {"username": "other-user"}, "work": False}, True),  # 家の機と明示した機
    ],
)
@pytest.mark.parametrize(("path", "word"), [(WIN_PORT, "T3CODE_PORT"), (WIN_SERVE, "tailscale")])
def test_windows_scripts_are_only_for_home_machines(path, word, data, deployed):
    # T3 Code の設定は、家の機だけ。判定は is-work (会社 PC の判定の単一ソース) に揃える
    rendered = _render_template(path, data).replace("\ufeff", "").strip()
    assert bool(rendered) is deployed
    if deployed:
        assert word in rendered


def test_windows_port_script_pins_the_user_variable_only_when_it_differs():
    script = _windows(WIN_PORT)
    assert "$port = '3773'" in script
    assert "GetEnvironmentVariable('T3CODE_PORT', 'User') -ne $port" in script
    assert "SetEnvironmentVariable('T3CODE_PORT', $port, 'User')" in script


def test_windows_serve_script_never_resets_funnels_or_turns_things_off():
    code = "\n".join(
        line for line in _windows(WIN_SERVE).splitlines() if not line.lstrip().startswith("#")
    )
    assert "$httpsPort = '8443'" in code
    assert "$target = 'http://127.0.0.1:3776'" in code
    assert "serve reset" not in code
    assert "funnel --bg" not in code
    assert "'funnel'" not in code  # funnel のサブコマンドは呼ばない (状態を見るだけ)
    assert " off" not in code


# 偽の tailscale.exe。FAKE_MODE で serve の現状を、FAKE_DIR に呼び出しの記録と設定済みの印を置く
FAKE_TAILSCALE = r"""
using System;
using System.IO;
using System.Threading;

public static class Fake {
  const string Same = "{\"TCP\":{\"8443\":{\"HTTPS\":true}},\"Web\":{\"host.ts.net:8443\":{\"Handlers\":{\"/\":{\"Proxy\":\"http://127.0.0.1:3776\"}}}}}";

  public static int Main(string[] args) {
    string dir = Environment.GetEnvironmentVariable("FAKE_DIR");
    string mode = Environment.GetEnvironmentVariable("FAKE_MODE") ?? "free";
    string backend = Environment.GetEnvironmentVariable("FAKE_BACKEND") ?? "Running";
    string call = string.Join(" ", args);
    File.AppendAllText(Path.Combine(dir, "calls.log"), call + "\n");
    string marker = Path.Combine(dir, "set.done");

    if (call == "status --json") {
      Console.Out.Write("{\"BackendState\":\"" + backend + "\"}");
      return 0;
    }
    if (call == "serve status --json") {
      switch (mode) {
        case "fail": Console.Error.Write("boom"); return 1;
        case "badjson": Console.Out.Write("not json"); return 0;
        case "same": Console.Out.Write(Same); return 0;
        case "used": Console.Out.Write(Same.Replace("3776", "3080")); return 0;
        case "tcp": Console.Out.Write("{\"TCP\":{\"8443\":{\"TCPForward\":\"localhost:1\"}}}"); return 0;
        case "funnel":
          Console.Out.Write(Same.Substring(0, Same.Length - 1) + ",\"AllowFunnel\":{\"host.ts.net:8443\":true}}");
          return 0;
        case "empty-output": return 0;
        default: Console.Out.Write(File.Exists(marker) ? Same : "{}"); return 0;
      }
    }
    if (call == "serve --bg --https=8443 http://127.0.0.1:3776") {
      if (mode == "setfail") { Console.Error.Write("denied"); return 1; }
      File.WriteAllText(marker, "1");
      Console.Out.Write("ok");
      return 0;
    }
    return 2;
  }
}
"""


def _powershells() -> list[str]:
    found = [shutil.which(name) for name in ("powershell", "pwsh")]
    return [path for path in found if path]


@pytest.fixture(scope="module")
def fake_tailscale(tmp_path_factory) -> Path:
    if os.name != "nt" or not shutil.which("powershell"):
        pytest.skip("偽の tailscale.exe は Windows PowerShell (Add-Type) で作る")
    work = tmp_path_factory.mktemp("fake-tailscale")
    source = work / "fake.cs"
    source.write_text(FAKE_TAILSCALE, encoding="utf-8")
    exe = work / "Tailscale" / "tailscale.exe"
    exe.parent.mkdir()
    build = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Add-Type -TypeDefinition (Get-Content -Raw -Encoding UTF8 '{source}') "
            f"-OutputAssembly '{exe}' -OutputType ConsoleApplication",
        ],
        capture_output=True,
        check=False,
    )
    assert exe.exists(), build.stderr.decode("utf-8", errors="replace")
    return work


def _render_windows_serve(tmp_path: Path) -> Path:
    rendered = _render_template(WIN_SERVE, {"chezmoi": {"username": "applejxd"}})
    script = tmp_path / "serve.ps1"
    script.write_bytes(b"\xef\xbb\xbf" + rendered.lstrip("\ufeff").encode("utf-8"))
    return script


def _run_serve(shell: str, script: Path, fake: Path, calls_dir: Path, mode: str, backend: str = "Running"):
    env = dict(os.environ)
    env["DOTFILES_TAILSCALE_EXE"] = str(fake / "Tailscale" / "tailscale.exe")
    env.update({"FAKE_DIR": str(calls_dir), "FAKE_MODE": mode, "FAKE_BACKEND": backend})
    result = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        env=env,
        check=False,
        timeout=120,
    )
    calls_log = calls_dir / "calls.log"
    calls = calls_log.read_text(encoding="utf-8").splitlines() if calls_log.exists() else []
    # 日本語の文言は端末の文字コードに依るので、ASCII の目印だけで確かめる
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    return result.returncode, calls, output


SET_CALL = "serve --bg --https=8443 http://127.0.0.1:3776"


@pytest.mark.parametrize("shell", _powershells() or ["powershell"])
@pytest.mark.parametrize(
    ("mode", "backend", "sets", "marker"),
    [
        ("free", "Running", True, "http://127.0.0.1:3776"),  # 空き: 設定して、読み戻して確かめる
        ("empty-output", "Running", True, "ok"),  # 出力が空 (終了コード 0) は空き。読み戻せないので、設定の出力を添えて警告する
        ("same", "Running", False, "http://127.0.0.1:3776"),  # 設定済み
        ("used", "Running", False, "3080"),  # 別の転送先は上書きしない
        ("tcp", "Running", False, "TCP"),  # TCP の公開も上書きしない
        ("funnel", "Running", False, "(funnel)"),  # インターネットへ公開されていたら、成功扱いにしない
        ("fail", "Running", False, ""),  # 現状を確認できない (終了コード非 0) ときは、空きと見なさない
        ("badjson", "Running", False, ""),  # 壊れた JSON でも apply を止めない
        ("setfail", "Running", True, "denied"),  # 設定の失敗は警告だけ
        ("free", "NeedsLogin", False, "NeedsLogin"),  # 未ログイン
    ],
)
def test_windows_serve_script_behaviors_with_a_fake_tailscale(
    tmp_path, fake_tailscale, shell, mode, backend, sets, marker
):
    script = _render_windows_serve(tmp_path)
    calls_dir = tmp_path / "calls"
    calls_dir.mkdir()
    code, calls, output = _run_serve(shell, script, fake_tailscale, calls_dir, mode, backend)
    assert code == 0, output  # どの場合も apply を止めない
    assert (SET_CALL in calls) is sets, calls
    assert marker in output, output
    if mode == "free" and backend == "Running":
        assert calls[-1] == "serve status --json"  # 設定のあとに読み戻している


def test_ports_agree_between_the_wsl_and_windows_scripts_and_the_doc():
    doc = (ROOT / "docs/spec/t3code-remote-access.md").read_text(encoding="utf-8")
    linux = SERVICE_ENV.read_text(encoding="utf-8")
    assert "PORT=3776" in linux and "HOST=127.0.0.1" in linux
    assert "http://127.0.0.1:3776" in _windows(WIN_SERVE)
    for text in ("3773", "3776", "4433", "8443", "T3CODE_PORT=3776", "T3CODE_HOST=127.0.0.1"):
        assert text in doc, text
