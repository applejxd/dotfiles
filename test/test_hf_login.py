"""Bitwarden の Login 項目 huggingface-token から `uvx hf auth login` を実行する chezmoi スクリプトの試験。

Unix 版は、描画して実際に bash で動かす (bw と uvx は偽物。jq は本物)。Windows 版は PowerShell を動かせないので静的に見る。
実際のトークン・Bitwarden・Hugging Face には触れない (トークンは架空の文字列)。

see docs/spec/security.md#hugging-face-のトークンの-login
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNIX = ROOT / "home/.chezmoiscripts/400_unix/run_after_442_hf_login.sh.tmpl"
WINDOWS = ROOT / "home/.chezmoiscripts/300_windows/run_after_352_hf_login.ps1.tmpl"
BACKSLASH = chr(92)
# テンプレートの Go 文字列では、正規表現のバックスラッシュ 1 文字を 4 文字で書く
APPLEJXD_GATE = 'regexMatch "(?i)(^|' + BACKSLASH * 4 + ')applejxd$" .chezmoi.username'

TOKEN = "hf_FakeTokenForTestOnly0123456789"


def _chezmoi() -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    return chezmoi


def _render(username: str) -> str:
    """`.chezmoi.username` だけを差し替えて、スクリプトを描画する。"""
    context = json.dumps({"chezmoi": {"username": username}})
    template = (
        "{{ with "
        + json.dumps(context)
        + " | fromJson }}\n"
        + UNIX.read_text(encoding="utf-8")
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


BW_STUB = """#!/bin/bash
echo "$*" >> "$STUB_DIR/bw.log"
[[ -z "${BW_STDERR:-}" ]] || echo "(node) DeprecationWarning: stub" >&2
case "$1" in
  sync) exit 0 ;;
  list)
    [[ -z "${BW_LIST_FAIL:-}" ]] || exit 1
    cat "$STUB_DIR/items.json" ;;
  *) exit 2 ;;
esac
"""

# 受け取った引数を 1 行で記録する。UVX_FAIL のときは、引数のトークンを含む失敗メッセージを出す
UVX_STUB = """#!/bin/bash
echo "$*" >> "$STUB_DIR/uvx.log"
if [[ -n "${UVX_FAIL:-}" ]]; then
    echo "Error: Invalid user token: ${@: -1}" >&2
    exit 1
fi
echo "Login successful."
"""


def login(name="huggingface-token", password=TOKEN, type_=1):
    return {"type": type_, "name": name, "login": {"username": "someone", "password": password}}


class Env:
    def __init__(self, tmp_path: Path):
        jq = shutil.which("jq")
        if jq is None:
            pytest.skip("jq is not installed")
        self.stub = tmp_path / "stub"
        self.stub.mkdir()
        self.home = tmp_path / "home"
        self.home.mkdir()
        for name, body in (("bw", BW_STUB), ("uvx", UVX_STUB)):
            path = self.stub / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        script = tmp_path / "hf.sh"
        script.write_text(_render("applejxd"), encoding="utf-8")
        self.script = script
        self.items([login()])
        # 本物の bw・uvx (mise の shims など) を見ないように、PATH は偽物の置き場と jq・基本のコマンドだけにする
        self.path = os.pathsep.join([str(self.stub), str(Path(jq).parent), "/usr/bin", "/bin"])
        self.env = {
            "PATH": self.path,
            "HOME": str(self.home),
            "STUB_DIR": str(self.stub),
            "BW_SESSION": "stub-session",
        }

    def items(self, items):
        (self.stub / "items.json").write_text(json.dumps(items), encoding="utf-8")

    def run(self, **extra):
        env = dict(self.env)
        for key, value in extra.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(
            ["bash", str(self.script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            env=env,
            cwd=self.home,
        )

    def log(self, name: str) -> list[str]:
        path = self.stub / f"{name}.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    @property
    def token_file(self) -> Path:
        return self.home / ".cache" / "huggingface" / "token"


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def combined(proc) -> str:
    return proc.stdout + proc.stderr


# ─── Unix 版: 動かして確かめる ────────────────────────────────────────


def test_unix_script_renders_nothing_for_other_users():
    assert _render("someone-else").strip() == ""
    assert _render("applejxd").startswith("#!/bin/bash")


def test_logs_in_with_the_login_item_password(env):
    proc = env.run()

    assert proc.returncode == 0, combined(proc)
    assert env.log("uvx") == [f"hf auth login --token {TOKEN}"]
    assert "ログインした" in proc.stdout
    assert TOKEN not in combined(proc)  # トークンは出力に出さない
    # 同期してから、名前で絞って 1 回だけ引く。認証 (unlock) は求めない
    assert env.log("bw") == [
        "sync --nointeraction",
        "list items --search huggingface-token --nointeraction",
    ]


def test_warnings_on_bw_stderr_do_not_break_the_json_or_the_login(env):
    # bw (Node) は DeprecationWarning を標準エラーに出すことがある。JSON (標準出力) に混ざらず、ログインも止まらない
    proc = env.run(BW_STDERR="1")

    assert proc.returncode == 0 and env.log("uvx") == [f"hf auth login --token {TOKEN}"]
    assert "DeprecationWarning" not in combined(proc)


def test_never_stores_into_the_git_credential_helper(env):
    env.run()

    assert all("--add-to-git-credential" not in line for line in env.log("uvx"))


def test_already_logged_in_does_nothing_and_does_not_touch_bitwarden(env):
    env.token_file.parent.mkdir(parents=True)
    env.token_file.write_text("hf_existing", encoding="utf-8")

    proc = env.run()

    assert proc.returncode == 0 and "ログイン済み" in proc.stdout
    assert env.log("uvx") == [] and env.log("bw") == []


def test_empty_token_file_does_not_count_as_logged_in(env):
    env.token_file.parent.mkdir(parents=True)
    env.token_file.write_text("", encoding="utf-8")

    env.run()

    assert env.log("uvx") == [f"hf auth login --token {TOKEN}"]


def test_resync_logs_in_again_even_when_already_logged_in(env):
    env.token_file.parent.mkdir(parents=True)
    env.token_file.write_text("hf_old", encoding="utf-8")

    env.run(DOTFILES_RESYNC_HF_TOKEN="1")

    assert env.log("uvx") == [f"hf auth login --token {TOKEN}"]


@pytest.mark.parametrize(
    ("variable", "value", "token"),
    [
        ("HF_HOME", "hfhome", "hfhome/token"),
        ("XDG_CACHE_HOME", "xdg", "xdg/huggingface/token"),
        ("HF_TOKEN_PATH", "elsewhere/tok", "elsewhere/tok"),
    ],
)
def test_logged_in_check_follows_the_hf_storage_location(env, variable, value, token):
    # hf の保存先の優先順位 (HF_TOKEN_PATH > HF_HOME > XDG_CACHE_HOME > ~/.cache)。ここにあるトークンを見てログイン済みと判断する
    path = env.home / token
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("hf_existing", encoding="utf-8")

    proc = env.run(**{variable: str(env.home / value)})

    assert "ログイン済み" in proc.stdout and env.log("uvx") == []


def test_hf_token_path_wins_over_hf_home(env):
    # HF_HOME 側にだけトークンがあっても、HF_TOKEN_PATH が別の場所を指していれば未ログインとして扱う
    (env.home / "hfhome").mkdir()
    (env.home / "hfhome" / "token").write_text("hf_existing", encoding="utf-8")

    env.run(HF_HOME=str(env.home / "hfhome"), HF_TOKEN_PATH=str(env.home / "elsewhere"))

    assert env.log("uvx") == [f"hf auth login --token {TOKEN}"]


def test_without_a_bitwarden_session_it_skips_and_never_unlocks(env):
    proc = env.run(BW_SESSION=None)

    assert proc.returncode == 0 and "BW_SESSION が無い" in proc.stdout
    assert env.log("uvx") == [] and env.log("bw") == []


def test_skips_when_bitwarden_cannot_be_read(env):
    proc = env.run(BW_LIST_FAIL="1")

    assert proc.returncode == 0 and "bw から取得できない" in proc.stdout
    assert env.log("uvx") == []


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([], "0 件"),
        ([login(), login()], "2 件"),
        # Login 以外 (Secure Note = 2) は数えない。名前の部分一致 (huggingface-token-old) も数えない
        ([login(type_=2)], "0 件"),
        ([login(name="huggingface-token-old")], "0 件"),
        # 通常ログインの項目 (名前 huggingface、Password はアカウントのパスワード) だけでは使わない
        ([login(name="huggingface", password="account-password-1")], "0 件"),
        ([login(name="huggingface", password=TOKEN)], "0 件"),
    ],
)
def test_uses_only_exactly_one_login_item_with_the_exact_name(env, items, message):
    env.items(items)

    proc = env.run()

    assert proc.returncode == 0 and message in proc.stdout
    assert env.log("uvx") == []


def test_ignores_lookalike_items_when_one_exact_item_exists(env):
    env.items(
        [
            login(name="huggingface-token-old", password="hf_other"),
            login(name="huggingface", password="account-password-1"),  # 通常ログインの項目
            login(type_=2),
            login(name="HuggingFace-Token"),
        ]
    )

    proc = env.run()

    assert env.log("uvx") == [
        f"hf auth login --token {TOKEN}"
    ]  # 名前は大文字小文字を無視して一致させる
    assert "account-password-1" not in combined(proc)


@pytest.mark.parametrize("password", ["", "api_org_abc123", "not-a-token", "hf_has space", "hf_"])
def test_rejects_values_that_are_not_a_user_token(env, password):
    env.items([login(password=password)])

    proc = env.run()

    assert proc.returncode == 0 and "トークンの形" in proc.stdout
    assert env.log("uvx") == []
    if password not in ("", "hf_"):  # "hf_" は案内文の一部と重なる
        assert password not in combined(proc)


def test_surrounding_whitespace_in_the_password_is_dropped(env):
    env.items([login(password=f"  {TOKEN}\r\n")])

    env.run()

    assert env.log("uvx") == [f"hf auth login --token {TOKEN}"]


def test_login_failure_never_stops_apply_and_masks_the_token(env):
    proc = env.run(UVX_FAIL="1")

    assert proc.returncode == 0 and "失敗した" in proc.stdout
    assert TOKEN not in combined(proc)  # 失敗メッセージに引数のトークンが入っていても伏せる
    assert "***" in proc.stderr


def test_skips_when_a_tool_is_missing(env, tmp_path):
    for tool in ("uvx", "bw"):
        (env.stub / tool).rename(tmp_path / f"{tool}.off")
        proc = env.run()
        assert proc.returncode == 0 and f"{tool} が無い" in proc.stdout, tool
        (tmp_path / f"{tool}.off").rename(env.stub / tool)


# ─── 静的な検査 (両方の版) ────────────────────────────────────────────


@pytest.mark.parametrize("path", [UNIX, WINDOWS])
def test_scripts_are_personal_and_never_ask_for_authentication(path):
    text = path.read_text(encoding="utf-8-sig")

    assert APPLEJXD_GATE in text  # applejxd の機械だけ
    assert "BW_SESSION" in text and "DOTFILES_RESYNC_HF_TOKEN" in text
    assert "hf auth login --token" in text or "'hf', 'auth', 'login', '--token'" in text
    assert "huggingface-token" in text
    assert "--add-to-git-credential" not in text  # 平文の ~/.git-credentials を作らせない
    # コメントの手順以外に bw unlock を実行しない (apply を入力待ちにしない)
    assert not [
        line
        for line in text.splitlines()
        if re.match(r"\s*(bw unlock|& \$?bw\S* unlock|\$env:BW_SESSION\s*=)", line)
    ]
    # トークンを自分でファイルへ書かない (保存は hf に任せる)
    assert "Set-Content" not in text and "Out-File" not in text and "> " + '"$token' not in text
    # 形の検査と、Login (type 1) の完全一致 1 件だけを使う条件
    assert "hf_[A-Za-z0-9]+" in text
    assert "HF_TOKEN_PATH" in text and "HF_HOME" in text and "XDG_CACHE_HOME" in text


def test_scripts_share_the_selection_rule():
    unix = UNIX.read_text(encoding="utf-8")
    windows = WINDOWS.read_text(encoding="utf-8-sig")

    assert ".type == 1" in unix and '"$count" != "1"' in unix
    assert "$_.type -eq 1" in windows and "$items.Count -ne 1" in windows
    assert "-ieq $itemName" in windows
    # ログイン済みでも DOTFILES_RESYNC_HF_TOKEN=1 のときは取り直す (コメントや案内文だけでなく、判定に使う)
    assert "$loggedIn -and $env:DOTFILES_RESYNC_HF_TOKEN -ne '1'" in windows
    assert '"${DOTFILES_RESYNC_HF_TOKEN:-}" != "1"' in unix


def test_windows_script_is_saved_with_a_bom_and_keeps_stderr_from_stopping_it():
    raw = WINDOWS.read_bytes()

    assert raw.startswith(b"\xef\xbb\xbf")  # PowerShell 5.1 が CP932 として読まないように
    text = raw.decode("utf-8-sig")
    # 外部コマンドは Invoke-Native 経由。Stop のままだと、標準エラーの 1 行 (Node の警告など) で PowerShell 5.1 が例外にして apply を止める
    assert "function Invoke-Native" in text and "$ErrorActionPreference = 'Continue'" in text
    assert "$ErrorActionPreference = $previous" in text
    assert not re.search(r"^\s*&\s*\$(bw|uvx)\.Path", text, re.MULTILINE)  # 直接は呼ばない
    # 失敗の出力は行の文字列で受け (ErrorRecord の体裁はトークンを途中省略して漏らす)、トークンを伏せてから出す
    assert "-MergeStderr" in text and "$_.Replace($token, '***')" in text
    assert "Out-String" not in text.split("$uvx.Path")[-1]
