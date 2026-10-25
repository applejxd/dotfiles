"""pi を Fence で囲って起動する (``pis`` の標準)。

境界の組み立て・危険な起動場所の拒否・起動前の退避は OpenCode と共通 (``boundary`` / ``backup``)。
ここは pi だけの部分: 境界用の agent 置き場の作成、起動コマンド、内側へ渡さない環境変数。

pi は設定と認証を読むときにも隣へ ``.lock`` を作るので、agent 置き場は書ける必要がある。
一方、本物の ``~/.pi/agent`` を境界に入れると、内側で作られた拡張を外の通常の pi が読む。
そこで**起動ごとに境界用の agent 置き場を作り**、認証・モデルの一覧・設定を写す。
see docs/spec/guard/pi-guard.md#サンドボックス
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

from . import backup, boundary, broker, check, cli, relay
from .common import HOME, STATE, die

RULES = HOME / ".config/pi/harness/rules.json"
HARNESS = HOME / ".config/pi/harness"
PI = HOME / "bin/pi"
REAL_AGENT = HOME / ".pi/agent"
# 境界用の agent 置き場の親。境界の内側から読み書きできる場所 (ocs の状態領域は見えない)。
# ★ここ全体ではなく、起動ごとの 1 つだけを書き込み可能にする。
AGENT_HOME = HOME / ".local/share/pi-sandbox"
AGENT_MAX_AGE_SECONDS = 3 * 24 * 60 * 60
# 本物から写すファイル。認証の写しは更新されても本物へ戻らない
# AGENTS.md (共通の指示)・keybindings.json・prompts/ (/fleet) も写す。
# 無いと、サンドボックスの中だけ指示やプロンプトが消える
COPY_FILES = ("auth.json", "models-store.json", "settings.json", "AGENTS.md", "keybindings.json")
COPY_DIRS = ("prompts",)
# 内側から書き換えられたくないもの (pi が読むだけ)。無いと denyWrite が効かないので作っておく
FROZEN_FILES = ("settings.json", "trust.json", "mcp.json", "AGENTS.md", "keybindings.json")
FROZEN_DIRS = ("extensions", "prompts")
# pis の通常の起動とサンドボックスの内側で、同じ形にそろえる pi の起動フラグ
# (作業先の .pi/ を読まない・組み込みのツールと拡張の自動発見を止める・MCP だけ戻す)
BASE_FLAGS = ("--no-approve", "-nbt", "-ne", "-e", "builtin:mcp")
# 境界の内側へ渡さない環境変数。子エージェントの印は自分で付け直す
DROP_ENV = (
    "PI_CODING_AGENT_DIR",
    "PI_HARNESS_CHILD",
    "PI_HARNESS_TEST_CHILD_EXT",
    "PI_HARNESS_BOUNDARY",
    "PI_HARNESS_NO_SANDBOX",
    "PI_HARNESS_ALLOWED",
    "PI_HARNESS_CANARY_READ",
    "PI_HARNESS_CANARY_WRITE",
)


# 名前から資格情報と分かる環境変数は、固定の一覧 (cli.DROP_ENV) に無くても内側へ渡さない。
# Orca が起動時に入れるもの (ORCA_AGENT_HOOK_TOKEN など) も、これで落ちる。
SECRET_ENV = re.compile(r"TOKEN|SECRET|PASSWORD|PASSPHRASE|ORCA_PANE_KEY", re.IGNORECASE)


def is_secret_env(name: str) -> bool:
    return SECRET_ENV.search(name) is not None


# ─── Copilot ブローカーモード ────────────────────────────────────────
# ホスト側の Envoy が本物の認証情報を持ち、内側の pi にはダミーだけを渡す。
# 入力は rules.json の broker.copilot (正本は common.toml の [pis.broker] copilot)。
# see docs/spec/sandbox/broker.md#copilot-ブローカー
BROKER_KEY = "broker.copilot"
NO_BROKER_NOTICE = "pis: ブローカー無し: 内側に Copilot の認証情報が入る"
NO_BROKER_GITHUB_NOTICE = "。GitHub ブローカーも使わない (gh にはダミーも本物も渡さない)"
NO_BROKER_SEARCH_NOTICE = "。検索ブローカーも使わない (内側から websearch の検索は使えない)"
NO_BROKER_HINT = "一時的に外すなら pis --no-broker (内側に本物の Copilot の認証が入る)"
BROKER_PROVIDER = "github-copilot"
BROKER_DUMMY_TOKEN = "dummy-not-a-real-token"
# GitHub ブローカー (gh)。内側の gh にはダミーの GH_TOKEN と Unix ソケットの設定だけを渡す。
# see docs/spec/sandbox/broker.md#github-ブローカー
GITHUB_DUMMY_TOKEN = "dummy-not-a-real-token"
GITHUB_HINT = (
    "broker.github は off / auto、broker.github_token_file (文字列) と "
    "broker.github_token_command (文字列の配列) はどちらか一方"
)
BROKER_IDENTITY_PATH = "/__pis_broker"
BROKER_IDENTITY_PREFIX = "pis-broker-copilot"
# 検索ブローカー (websearch.py)。内側へはこの環境変数で URL だけを渡す (鍵は渡さない)。
# see .tmp/handoff-search/README.md
SEARCH_ENV = "WEBSEARCH_BROKER_URL"
SEARCH_HINT = 'broker.search は "off" / "auto" のどちらか'
BROKER_TIMEOUT_SECONDS = 3
BROKER_HINT = f"{BROKER_KEY} は off / auto / http://127.0.0.1:<1024-65535> のどれか (例 http://127.0.0.1:18080)"


_ABSENT = object()


def is_auto_broker(value: str | None) -> bool:
    """``broker.copilot`` が ``auto`` (大文字小文字は区別しない)。前後の空白は認めない。"""
    return value is not None and value.lower() == "auto"


def _broker_section(path: Path) -> dict | None:
    """``rules.json`` の ``broker`` 節。無ければ None。表でない (破損) なら起動を拒否する。"""
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        die(f"{path} を読めない: {e}", "chezmoi apply で生成する")
    section = rules.get("broker", _ABSENT) if isinstance(rules, dict) else _ABSENT
    if section is _ABSENT:
        return None
    # 設定の破損を off 扱いにしない (fail-closed)
    if not isinstance(section, dict):
        die(f"{path} の broker が表でない: {section!r}", BROKER_HINT)
    return section


def read_broker_setting(rules_path: Path | None = None) -> str | None:
    """``rules.json`` の ``broker.copilot`` を返す。``off``・未設定・``broker`` 節が無いなら None。
    ``broker`` が表でない・``copilot`` が文字列でない (``null`` を含む) ときは起動を拒否する。

    ``auto`` や URL の検証は :func:`parse_broker` と :func:`is_auto_broker` に任せる。
    """
    path = rules_path if rules_path is not None else RULES
    section = _broker_section(path)
    if section is None or "copilot" not in section:
        return None
    value = section["copilot"]
    if value == "off":
        return None
    if not isinstance(value, str):
        die(f"{path} の {BROKER_KEY} は文字列でないといけない: {value!r}", BROKER_HINT)
    return value


class GithubSetting(NamedTuple):
    """``broker.github = "auto"`` のときの PAT の出どころ (両方 None なら「設定無し」)。"""

    token_file: str | None
    token_command: tuple[str, ...] | None


def read_github_setting(rules_path: Path | None = None) -> GithubSetting | None:
    """``rules.json`` の ``broker.github`` を読む。``off``・未設定なら None。

    ``off`` / ``auto`` 以外、出どころの型違い、ファイルとコマンドの両方は起動を拒否する (fail-closed)。
    """
    path = rules_path if rules_path is not None else RULES
    section = _broker_section(path)
    if section is None or "github" not in section or section["github"] == "off":
        return None
    if section["github"] != "auto":
        die(f"{path} の broker.github が不正: {section['github']!r}", GITHUB_HINT)
    token_file = section.get("github_token_file")
    command = section.get("github_token_command")
    if token_file is not None and command is not None:
        die(f"{path} の github_token_file と github_token_command が両方ある", GITHUB_HINT)
    if token_file is not None and (not isinstance(token_file, str) or not token_file.strip()):
        die(f"{path} の github_token_file が空でない文字列でない", GITHUB_HINT)
    if command is not None and (
        not isinstance(command, list)
        or not command
        or not all(isinstance(a, str) and "\0" not in a for a in command)
        or not command[0].strip()
    ):
        die(f"{path} の github_token_command が空でない文字列の配列でない", GITHUB_HINT)
    return GithubSetting(token_file, tuple(command) if command is not None else None)


def github_enabled_in_rules(rules_path: Path | None = None) -> bool:
    """``--no-broker`` の注意の文面用: ``broker.github`` が ``auto`` か。読めない・破損は False (起動は拒否しない)。"""
    path = rules_path if rules_path is not None else RULES
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    section = rules.get("broker") if isinstance(rules, dict) else None
    return isinstance(section, dict) and section.get("github") == "auto"


def read_search_setting(rules_path: Path | None = None) -> bool:
    """``rules.json`` の ``broker.search`` を読む。``auto`` なら True。``off``・未設定・``broker`` 節無しなら False。

    ``off`` / ``auto`` 以外 (型違いを含む) は起動を拒否する (fail-closed)。
    """
    path = rules_path if rules_path is not None else RULES
    section = _broker_section(path)
    if section is None or "search" not in section:
        return False
    value = section["search"]
    if value == "off":
        return False
    if value != "auto":
        die(f"{path} の broker.search が不正: {value!r}", SEARCH_HINT)
    return True


def search_enabled_in_rules(rules_path: Path | None = None) -> bool:
    """``--no-broker`` の注意の文面用: ``broker.search`` が ``auto`` か。読めない・破損は False。"""
    path = rules_path if rules_path is not None else RULES
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    section = rules.get("broker") if isinstance(rules, dict) else None
    return isinstance(section, dict) and section.get("search") == "auto"


def parse_broker(value: str | None) -> tuple[str, int] | None:
    """``broker.copilot`` の URL を厳密に検証し、(末尾スラッシュなしの URL, ポート) を返す。

    未設定 (None / 空文字) なら None。http・127.0.0.1・1024〜65535・パス無し・
    ユーザー情報 / クエリ / フラグメント無し以外は起動を拒否する。
    """
    if value is None or value == "":
        return None
    if value != value.strip() or "?" in value or "#" in value:
        die(f"{BROKER_KEY} が不正: {value!r} (空白・クエリ・フラグメントは使えない)", BROKER_HINT)
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        die(f"{BROKER_KEY} が URL として読めない: {value!r}", BROKER_HINT)
    if parts.scheme != "http":
        die(f"{BROKER_KEY} のスキームは http のみ: {value!r}", BROKER_HINT)
    if "@" in parts.netloc:
        die(f"{BROKER_KEY} にユーザー情報は書けない: {value!r}", BROKER_HINT)
    if parts.hostname != "127.0.0.1":
        die(f"{BROKER_KEY} のホストは 127.0.0.1 のみ: {value!r}", BROKER_HINT)
    if port is None or not 1024 <= port <= 65535:
        die(f"{BROKER_KEY} のポートは 1024〜65535 (必須): {value!r}", BROKER_HINT)
    if parts.path not in ("", "/"):
        die(f"{BROKER_KEY} にパスは書けない: {value!r}", BROKER_HINT)
    return f"http://127.0.0.1:{port}", port


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None  # リダイレクトは辿らない (HTTPError になる)


def verify_broker(url: str, prefix: str = BROKER_IDENTITY_PREFIX, label: str = "Copilot") -> None:
    """境界を組む前に、ブローカーが本物か確かめる。違えば起動を拒否する。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    target = url + BROKER_IDENTITY_PATH
    hint = (
        f"{BROKER_KEY}=auto なら pis が Envoy を自動で起動する。手動なら Envoy を起動してから pis を使う。"
        f"{NO_BROKER_HINT}"
    )
    try:
        with opener.open(target, timeout=BROKER_TIMEOUT_SECONDS) as response:
            status = response.status
            body = response.read(256).decode("utf-8", errors="replace")
    except OSError as e:  # URLError / HTTPError / タイムアウトはすべて OSError の仲間
        die(f"{label} ブローカーが動いていない、または別のサービス: {target} ({e})", hint)
    if status != 200 or not body.startswith(prefix):
        die(
            f"{label} ブローカーが動いていない、または別のサービス: {target} (status={status})",
            hint,
        )


def _copy_auth_without_broker_provider(source: Path, dest: Path) -> None:
    """``auth.json`` を、``github-copilot`` のエントリだけ除いて写す (権限は元のまま)。"""
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        die(
            f"{source} を読めない ({e})",
            "ブローカーモードでは auth.json を JSON として読む必要がある",
        )
    if not isinstance(data, dict):
        die(f"{source} がオブジェクトでない", "auth.json を直す")
    data.pop(BROKER_PROVIDER, None)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    shutil.copystat(source, dest)


def _write_broker_models(agent: Path, broker_url: str) -> None:
    """``models.json`` に Copilot の ``baseUrl`` を入れる (あれば既存へマージ、無ければ新規)。"""
    path = agent / "models.json"
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            die(f"{path} を JSON として読めない ({e})")
        if not isinstance(data, dict):
            die(f"{path} がオブジェクトでない")
    providers = data.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    entry = providers.get(BROKER_PROVIDER)
    entry = dict(entry) if isinstance(entry, dict) else {}
    entry["baseUrl"] = broker_url.rstrip("/")
    providers[BROKER_PROVIDER] = entry
    data["providers"] = providers
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def apply_broker_network(config_: dict, *ports: int) -> None:
    """ブローカーモードのときだけ、ホストのブローカーのポート (Copilot・検索) だけへ localhost の送信を許す。

    ``allowLocalBinding`` は触らない (``ocs`` と共通の ``build_boundary`` の出力は変えない)。
    """
    network = config_["network"]
    network["allowLocalOutbound"] = True
    network["allowLocalOutboundPorts"] = list(ports)


def pi_binary() -> Path:
    """pi の実体。インストーラーが作る場所は PATH で変わるので、順に探す。"""
    for path in (PI, HOME / ".local/bin/pi", REAL_AGENT / "bin/pi"):
        if path.is_file():
            return path
    found = shutil.which("pi")
    return Path(found) if found else PI


def check_installed() -> None:
    for path, hint in (
        (pi_binary(), "pi を入れる (公式インストーラー。~/bin か ~/.local/bin に pi が要る)"),
        (HARNESS / "index.ts", "chezmoi apply でフルガードを配る"),
        (RULES, "chezmoi apply でフルガードを配る"),
    ):
        if not path.is_file():
            die(f"{path} が無い", hint)


def _prune_agents(home: Path) -> None:
    """古い境界用の agent 置き場を捨てる。並行して動いているものを消さないよう、古いものだけ。"""
    if not home.is_dir():
        return
    cutoff = time.time() - AGENT_MAX_AGE_SECONDS
    for path in home.glob("agent-*"):
        try:
            if path.stat().st_mtime < cutoff:
                shutil.rmtree(path)
        except OSError:
            pass  # 消せなくても起動は妨げない


def make_agent_dir(home: Path | None = None) -> Path:
    """境界用の agent 置き場を**空のまま**確保する (0700)。古いものの掃除もここで。

    GitHub ブローカーのソケット (``<agent>/gh.sock``) をブローカーの起動前に決めるため、
    確保と中身の配置 (:func:`populate_agent_dir`) を分けている。消すのは呼び出し側の責任。
    """
    home = home if home is not None else AGENT_HOME
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    _prune_agents(home)
    return Path(tempfile.mkdtemp(prefix="agent-", dir=str(home)))


def populate_agent_dir(
    agent: Path, real: Path | None = None, broker_url: str | None = None
) -> None:
    """確保済みの agent 置き場へ、本物から必要なものだけを写す。

    既定の置き場は呼び出しのときに引く (定義時に固定すると、差し替えが効かない)。
    ``broker_url`` があれば (Copilot ブローカーモード) ``auth.json`` から ``github-copilot`` を除き、
    ``models.json`` に ``baseUrl`` を入れる。
    """
    real = real if real is not None else REAL_AGENT
    for name in COPY_FILES:
        source = real / name
        if source.is_file():
            if broker_url and name == "auth.json":
                _copy_auth_without_broker_provider(source, agent / name)
            else:
                shutil.copy2(source, agent / name)
    for name in COPY_DIRS:
        source = real / name
        if source.is_dir():
            shutil.copytree(source, agent / name, symlinks=True)
    _copy_provider_compat(real, agent)
    # pi は <agent 置き場>/bin の fd・rg を探し、無ければダウンロードする。
    # 起動ごとの置き場では毎回見つからないので、本物の bin (読み取りだけ許可済み) を指すリンクにする
    if (real / "bin").is_dir():
        (agent / "bin").symlink_to(real / "bin")
    for name in FROZEN_FILES:
        if not (agent / name).exists():
            (agent / name).write_text("" if name.endswith(".md") else "{}\n", encoding="utf-8")
    for name in FROZEN_DIRS:
        (agent / name).mkdir(exist_ok=True)
    if broker_url:
        _write_broker_models(agent, broker_url)


def _copy_provider_compat(real: Path, agent: Path) -> None:
    """本物の ``models.json`` から、プロバイダーごとの ``compat`` だけを内側へ写す。

    ``apiKey``・``baseUrl``・``headers``・``models`` などは写さない (秘密を境界の内側へ出さない許可リスト)。
    読めない・形が違うときは何もしない。
    see docs/spec/guard/pi-guard.md#ツール引数の-json-を壊さない設定
    """
    try:
        data = json.loads((real / "models.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, dict):
        return
    kept = {
        name: {"compat": entry["compat"]}
        for name, entry in providers.items()
        if isinstance(entry, dict) and isinstance(entry.get("compat"), dict)
    }
    if kept:
        (agent / "models.json").write_text(
            json.dumps({"providers": kept}, indent=2) + "\n", encoding="utf-8"
        )


def prepare_agent_dir(
    real: Path | None = None, home: Path | None = None, broker_url: str | None = None
) -> Path:
    """境界用の agent 置き場を確保して中身を写す (:func:`make_agent_dir` + :func:`populate_agent_dir`)。"""
    agent = make_agent_dir(home)
    try:
        populate_agent_dir(agent, real, broker_url)
    except BaseException:
        shutil.rmtree(agent, ignore_errors=True)
        raise
    return agent


def write_gh_config(agent: Path, socket_path: Path) -> Path:
    """``<agent>/gh/config.yml`` (``http_unix_socket`` の 1 行だけ、0600) を作り、``gh/`` を返す。

    内側の ``gh`` は ``GH_CONFIG_DIR`` でここを読み、``https://api.github.com/...`` を TLS なしで
    このソケットへ送る。終了時に本物へは戻さない (agent 置き場ごと消える)。
    """
    gh = agent / "gh"
    gh.mkdir(exist_ok=True)
    os.chmod(gh, 0o700)
    value = str(socket_path)
    if re.fullmatch(r"[A-Za-z0-9_./+-]+", value) is None:
        value = json.dumps(value)  # YAML の二重引用符でもある
    fd = os.open(gh / "config.yml", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"http_unix_socket: {value}\n")
    return gh


def frozen_paths(agent: Path) -> list[str]:
    """境界で書き込みを塞ぐ、境界用 agent 置き場の中の設定・拡張。"""
    return [str(agent / n) for n in (*FROZEN_FILES, *FROZEN_DIRS)]


def sessions_dir(workspace: Path, real: Path | None = None) -> Path:
    """この作業ディレクトリのセッションの置き場。外の ``pi -c`` と同じ場所にする (再開できる)。

    pi は ``sessions/--<作業ディレクトリ>--`` に置く (``dist/core/session-manager.js`` の
    ``getDefaultSessionDirPath``。先頭の区切りを外し、``/`` ``\\`` ``:`` を ``-`` にする)。
    ``--session-dir`` は渡した場所へそのまま置くので、この 1 つだけを開ける。
    """
    safe = re.sub(r"[/\\:]", "-", str(workspace).lstrip("/\\"))
    path = (real if real is not None else REAL_AGENT) / "sessions" / f"--{safe}--"
    path.mkdir(parents=True, exist_ok=True)
    return path


def inner_env(
    agent: Path,
    config_: dict,
    broker: bool = False,
    github: bool = False,
    search_url: str | None = None,
) -> dict[str, str]:
    """境界の内側へ渡す環境変数。役割と bypass は ``pis`` が環境変数で渡す。

    ``PI_HARNESS_BOUNDARY`` は「内側のはず」という期待にすぎない。内側のフルガードが、次のカナリアで
    実測し (読めてはいけないファイル・書けてはいけない場所)、効いていなければ起動を止める。
    許可の一覧 (``PI_HARNESS_ALLOWED``) は、実際に開けた場所で、作業ツリーの外の判定に使う。
    see docs/spec/guard/pi-guard.md#緩和のゲート
    """
    from .cli import DROP_ENV as COMMON_DROP

    check.ensure_canary()
    fs = config_["filesystem"]
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in (*COMMON_DROP, *DROP_ENV) and not is_secret_env(k)
    }
    if broker:
        # TOKEN を含む名前のフィルターの後に足す (ホストの同名変数は上で落ちている)
        env["COPILOT_GITHUB_TOKEN"] = BROKER_DUMMY_TOKEN
    if github:
        # こちらもフィルターの後。ホストの GH_TOKEN / GITHUB_TOKEN / GH_ENTERPRISE_TOKEN は上で落ちている
        env["GH_TOKEN"] = GITHUB_DUMMY_TOKEN
        env["GH_CONFIG_DIR"] = str(agent / "gh")
        env["GH_NO_UPDATE_NOTIFIER"] = "1"
        env["GH_TELEMETRY"] = "false"
        env["GH_PROMPT_DISABLED"] = "1"
    # ホストの同名変数は落とし、検索ブローカーが有効のときだけ自分の URL を入れる (鍵は入れない)
    env.pop(SEARCH_ENV, None)
    if search_url is not None:
        env[SEARCH_ENV] = search_url
    # 内側では DISPLAY / WAYLAND_DISPLAY が見えてもソケットと powershell.exe が塊がれていて、pi のコピーが
    # 「Clipboard unavailable」で失敗する。OSC 52 (端末への書き込み専用) を強制する
    # see docs/spec/troubleshooting-agents.md#pis-の内側でクリップボードへコピーできない
    env["PI_CLIPBOARD_OSC52"] = "1"
    # 内側は DNS が引けないが、プロキシ (HTTPS_PROXY) が許可ドメインを強制する。web-search の fetch に、
    # 事前の DNS 検査を省いてプロキシ越しに取らせる印。ホスト側の同名の値は信用しない
    # see docs/spec/web-search.md#pis-の内側のプロキシ越しの取得
    env.pop("PIS_FETCH_VIA_PROXY", None)
    env["PIS_FETCH_VIA_PROXY"] = "1"
    env["PI_CODING_AGENT_DIR"] = str(agent)
    env["PI_HARNESS_BOUNDARY"] = "1"
    env["PI_HARNESS_ALLOWED"] = json.dumps(
        {"read": list(fs.get("allowRead") or []), "write": list(fs.get("allowWrite") or [])}
    )
    env["PI_HARNESS_CANARY_READ"] = str(HOME / check.CANARY_REL)
    # 存在しないパス。内側から書けてしまったらサンドボックスが効いていない
    env["PI_HARNESS_CANARY_WRITE"] = str(STATE / f"canary-write-{uuid.uuid4().hex}")
    return env


def own_extensions(rules: Path | None = None) -> list[str]:
    """``rules.json`` の ``extensions`` (``[pi] own_extensions`` から生成。``pis`` と同じ一覧)。"""
    path = rules if rules is not None else RULES
    try:
        names = json.loads(path.read_text(encoding="utf-8"))["extensions"]
    except (OSError, ValueError, KeyError):
        die(f"{path} から拡張の一覧を読めない", "chezmoi apply で rules.json を配り直す")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        die(f"{path} の extensions が文字列の配列でない", "chezmoi apply で rules.json を配り直す")
    return names


def extension_args(real: Path | None = None, names: list[str] | None = None) -> list[str]:
    """``pis`` が足す自作の拡張の ``-e``。配られていないものは足さない。"""
    real = real if real is not None else REAL_AGENT
    names = names if names is not None else own_extensions()
    args: list[str] = []
    for name in names:
        ext = real / "extensions" / name / "index.ts"
        if ext.is_file():
            args += ["-e", str(ext)]
    return args


def _git_root(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        if (directory / ".git").exists():
            return directory
    return None


def skill_args(workspace: Path | None = None) -> list[str]:
    """作業先のスキル (``.agents/skills``) を足す ``--skill``。

    ``--no-approve`` は project trust を拒否するので、pi の自動発見では読まれない。
    作業先から git ルートまでの ``.agents/skills`` だけを、明示の ``--skill`` で足す
    (pi の発見の範囲と同じ。git ルートが無ければ何も足さない)。
    ``--skill`` はグローバルのスキルより後に載るので、同名ならグローバルが勝つ。
    スキルは指示を読む許可で、実行の許可ではない (実行は判定器とサンドボックスが決める)。
    see docs/spec/guard/pi-guard.md#起動
    """
    try:
        start = (workspace if workspace is not None else Path.cwd()).resolve()
        root = _git_root(start)
        if root is None:
            return []
        user_skills = (HOME / ".agents/skills").resolve()  # ユーザーのスキルは pi が元から読む
        args: list[str] = []
        for directory in (start, *start.parents):
            skills = directory / ".agents" / "skills"
            if skills.is_dir() and skills.resolve() != user_skills:
                args += ["--skill", str(skills)]
            if directory == root:
                break
    except OSError:
        return []
    return args


def inner_command(passthrough: list[str], path: str, sessions: Path) -> list[str]:
    """境界の内側で走らせるコマンド。``pis`` と同じ形の引数に、セッションの置き場を足す。"""
    from .cli import INNER_STATE

    return [
        "/usr/bin/env",
        f"PATH={path}",
        "TMPDIR=/tmp",
        f"XDG_STATE_HOME={INNER_STATE}",
        str(pi_binary()),
        *BASE_FLAGS,
        *extension_args(),
        *skill_args(),
        "-e",
        str(HARNESS),
        "--session-dir",
        str(sessions),
        *passthrough,
    ]


def _expires(entry: object) -> float:
    value = entry.get("expires") if isinstance(entry, dict) else None
    return float(value) if isinstance(value, (int, float)) else 0.0


def sync_auth_back(agent: Path, real: Path | None = None, skip: tuple[str, ...] = ()) -> bool:
    """境界の内側で更新された認証を本物の ``auth.json`` へ戻す。

    OAuth のリフレッシュトークンは更新のたびに入れ替わりうる。写しの中だけで更新されると、
    本物のトークンが失効する。**有効期限が本物より新しいプロバイダの分だけ**戻し、ほかは触らない。
    本物は pi と同じ ``auth.json.lock`` を取って書く。取れなければ戻さない (False)。
    ``skip`` のプロバイダは戻さない (ブローカーモードの ``github-copilot``)。
    """
    real = real if real is not None else REAL_AGENT
    copy_path, real_path = agent / "auth.json", real / "auth.json"
    try:
        theirs = json.loads(copy_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(theirs, dict):
        return False
    lock = real / "auth.json.lock"
    for _ in range(50):
        try:
            lock.mkdir()
            break
        except FileExistsError:
            time.sleep(0.1)
        except OSError:
            return False
    else:
        return False
    try:
        try:
            ours = json.loads(real_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(ours, dict):
            return False
        changed = False
        for name, entry in theirs.items():
            if name in skip:
                continue
            if entry != ours.get(name) and _expires(entry) > _expires(ours.get(name)):
                ours[name] = entry
                changed = True
        if not changed:
            return False
        tmp = real_path.with_name(real_path.name + ".ocs-tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ours, f, indent=2)
        os.replace(tmp, real_path)
        return True
    finally:
        with contextlib.suppress(OSError):
            lock.rmdir()


def run(argv: list[str], env: dict[str, str], agent: Path, broker: bool = False) -> int:
    """境界の内側の pi を子プロセスとして動かし、終わったら認証を本物へ戻して置き場を消す。

    ``execve`` で置き換えると終了後の処理ができない。Ctrl-C は端末が子へも届けるので、
    親は無視して終了を待つ。親が SIGTERM / SIGHUP (端末を閉じた) を受けたら子へ渡し、
    終わるのを待ってから後始末する。
    """
    proc = subprocess.Popen(argv, env=env)
    saved = {
        signal.SIGINT: signal.signal(signal.SIGINT, signal.SIG_IGN),
        signal.SIGTERM: signal.signal(signal.SIGTERM, lambda *_: proc.terminate()),
        signal.SIGHUP: signal.signal(signal.SIGHUP, lambda *_: proc.terminate()),
    }
    try:
        return proc.wait()
    finally:
        for number, handler in saved.items():
            signal.signal(number, handler)
        cleanup(agent, broker)


def cleanup(agent: Path, broker: bool = False) -> None:
    """認証を戻して、写しを置いた境界用の agent 置き場を消す。"""
    sync_auth_back(agent, skip=(BROKER_PROVIDER,) if broker else ())
    shutil.rmtree(agent, ignore_errors=True)


def _github_token(setting: GithubSetting | None) -> str | None:
    """GitHub ブローカー用の PAT を得る。無効・出どころの設定無し・出どころ無しは None。

    ``auto`` で出どころ無し (ファイル無し・コマンド失敗) なら起動を止めず、値を出さない 1 行を標準エラーへ出す。
    権限・形式の違反・設定の破損は起動を拒否する。
    """
    if setting is None:
        return None
    origin = broker.github_origin(setting.token_file, setting.token_command)
    if origin is None:
        return None
    token: str | None = None
    try:
        token = broker.resolve_github_token(setting.token_file, setting.token_command)
    except broker.BrokerError as e:
        die(str(e), e.hint)
    if token is None:
        print(
            f"pis: GitHub 認証なし: gh は無認証になる (PAT の出どころ: {origin})",
            file=sys.stderr,
        )
    return token


def _launch(args: argparse.Namespace, passthrough: list[str]) -> int:
    """pi を Fence で囲って起動する。OpenCode と違い、DB も設定の書き出しも要らない。

    境界用の agent 置き場を起動ごとに作り (:mod:`pi`)、セッションの置き場だけを本物へ開ける。
    see docs/spec/guard/pi-guard.md#サンドボックス
    """
    check_installed()
    github: GithubSetting | None = None
    search_on = False
    if args.no_broker:
        notice = NO_BROKER_NOTICE + (NO_BROKER_GITHUB_NOTICE if github_enabled_in_rules() else "")
        notice += NO_BROKER_SEARCH_NOTICE if search_enabled_in_rules() else ""
        print(notice, file=sys.stderr)
        value = None
    else:
        value = read_broker_setting()
        github = read_github_setting()
        search_on = read_search_setting()
    # 空の agent 置き場を先に確保し (GitHub のソケット <agent>/gh.sock の置き場所)、ブローカーを起動し、
    # URL (Copilot) 確定後に中身を配置する。auto は pis と同じ寿命の Envoy を 1 つ立てる。
    # 例外・SystemExit・--check でも ExitStack がブローカーを止め、agent 置き場を消す
    with contextlib.ExitStack() as stack:
        agent = make_agent_dir()
        stack.callback(shutil.rmtree, agent, ignore_errors=True)
        token = _github_token(github)
        github_socket = agent / broker.GH_SOCKET_NAME if token is not None else None
        copilot_auto = is_auto_broker(value)
        state: Path | None = None
        search_url: str | None = None
        search_kwargs: dict = {}
        if search_on:
            # 鍵はホスト側でだけ読む (環境変数は見ない)。読めないものは鍵なし (理由は出すが鍵は出さない)
            search_keys, notes = broker.read_search_keys()
            for note in notes:
                print(f"pis: {note}", file=sys.stderr)
            missing = [
                p.name for p in broker.SEARCH_PROVIDERS if p.header and p.name not in search_keys
            ]
            if missing:
                print(
                    f"pis: 検索の鍵なし: {', '.join(missing)} (このプロバイダーは使えない)",
                    file=sys.stderr,
                )
            search_kwargs = {"search": True, "search_keys": search_keys}
        if copilot_auto or token is not None or search_on:
            try:
                started = stack.enter_context(
                    broker.session(
                        REAL_AGENT,
                        copilot=copilot_auto,
                        github_token=token,
                        github_socket=github_socket,
                        **search_kwargs,
                    )
                )
            except broker.BrokerError as e:
                die(str(e), f"{e.hint}。{NO_BROKER_HINT}")
            token = None  # PAT の値をこれ以上持ち回らない
            search_kwargs = {}  # 鍵も同じ
            state = started.state
            if copilot_auto:
                value = started.url
            search_url = started.search_url
        # 検索が有効のときだけ search_url を渡す (無効なときの呼び出しを変えない)
        extra = {"search_url": search_url} if search_url is not None else {}
        return _launch_with(
            args,
            passthrough,
            value,
            state,
            agent=agent,
            github_socket=github_socket,
            **extra,
        )


def _reject_state_overlap(state: Path, workspace: Path) -> None:
    """ブローカーの状態ディレクトリが、境界の内側から読める作業場所と重なるなら起動を拒否する。"""
    base = state.resolve().parent
    if state.resolve().is_relative_to(workspace) or workspace.is_relative_to(base):
        die(
            f"ブローカーの状態の置き場と作業場所が重なる: {base} と {workspace}",
            "別のディレクトリで起動する (状態は $XDG_RUNTIME_DIR か ~/.local/state/pis の下)",
        )


def _launch_with(
    args: argparse.Namespace,
    passthrough: list[str],
    broker_value: str | None,
    broker_state: Path | None = None,
    *,
    agent: Path,
    github_socket: Path | None = None,
    search_url: str | None = None,
) -> int:
    """``_launch`` の本体。``broker_value`` は ``broker.copilot`` の URL (無ければ None)。

    ``broker_state`` はブローカーの状態ディレクトリ (作業場所と重なれば拒否する)。
    ``agent`` は確保済みの空の agent 置き場 (最終的な削除は呼び出し側の ExitStack)、
    ``github_socket`` は GitHub ブローカーが有効のときの Unix ソケット、
    ``search_url`` は検索ブローカーが有効のときの URL (内側へ ``WEBSEARCH_BROKER_URL`` として渡す)。
    """
    # ブローカーモード (未設定なら None で、以降は現行と同じ)。境界を組む前に検証と身元確認をする
    endpoint = parse_broker(broker_value)
    if endpoint is not None:
        verify_broker(endpoint[0])
    search_endpoint = parse_broker(search_url)
    if search_endpoint is not None:
        verify_broker(search_endpoint[0], broker.SEARCH_IDENTITY_PREFIX, "検索")
    sandbox = boundary.load_boundary(RULES, required=())
    runtime = Path(sandbox["runtime_path"])
    if not runtime.is_file():
        die(f"Fence が無い: {runtime}", "mise install で入れる")

    workspace = Path.cwd().resolve()
    boundary.reject_unsafe_workspace(sandbox, workspace)
    request = boundary.read_request(workspace)
    boundary.reject_control_dirs(sandbox, workspace, request)
    boundary.reject_protected_workspace(sandbox, workspace, request)
    boundary.announce_request(request)
    if broker_state is not None:
        _reject_state_overlap(broker_state, workspace)

    try:
        populate_agent_dir(agent, broker_url=endpoint[0] if endpoint else None)
        if github_socket is not None:
            write_gh_config(agent, github_socket)
        sessions = sessions_dir(workspace)
        config_ = boundary.build_boundary(sandbox, workspace, request, agent)
        if endpoint is not None or search_endpoint is not None:
            apply_broker_network(
                config_, *[e[1] for e in (endpoint, search_endpoint) if e is not None]
            )
        # セッションの置き場だけを本物へ開け、境界用 agent 置き場の設定と拡張は書けなくする
        config_["filesystem"]["allowWrite"].append(str(sessions))
        config_["filesystem"]["allowRead"].append(str(sessions))
        config_["filesystem"]["denyWrite"] += boundary.prepare_protected(frozen_paths(agent))
        project = {
            "workspace": str(workspace),
            "data_dir": str(agent),
            "db": "",
            "config": config_,
        }
        env = inner_env(
            agent,
            config_,
            endpoint is not None,
            github_socket is not None,
            search_endpoint[0] if search_endpoint else None,
        )
    except BaseException:
        cleanup(agent, endpoint is not None)
        raise

    # プロキシ越しでないと外へ出られない機械では、許可リストの照合を中継へ移す (relay)
    with relay.session(config_) as fence_config:
        project["relay"] = fence_config is not config_
        if args.check:
            boundary_file = cli.write_boundary(fence_config)
            try:
                return check.run_check(runtime, boundary_file, project, env, cli.FENCE_TMP)
            finally:
                Path(boundary_file).unlink(missing_ok=True)
                cleanup(agent, endpoint is not None)

        try:
            boundary_file = cli.write_boundary(fence_config)
            try:
                # 事前検査 (同じ設定で合格した記憶があれば省く)。落ちたら起動しない
                code = check.preflight(
                    runtime, boundary_file, project, env, cli.FENCE_TMP, volatile=[str(agent)]
                )
                if code != 0:
                    die(
                        "サンドボックスの事前検査に落ちた",
                        "pis --check で詳細を見る。サンドボックス無しで使うなら pis --no-sandbox",
                    )
                backup.backup_worktree(workspace, args.no_backup)
            except BaseException:
                Path(boundary_file).unlink(missing_ok=True)
                raise
        except BaseException:
            cleanup(agent, endpoint is not None)
            raise
        argv = [
            str(runtime),
            "--settings",
            boundary_file,
            "--",
            *inner_command(passthrough, env.get("PATH", check.HOST_PATH), sessions),
        ]
        try:
            # execve で置き換えない: 終了後に認証を本物へ戻し、写しを消すため (:func:`pi.run`)
            return run(argv, check.host_env(env, cli.FENCE_TMP), agent, endpoint is not None)
        finally:
            Path(boundary_file).unlink(missing_ok=True)


def run_sandboxed(argv: list[str]) -> int:
    """``pis`` の標準の起動 (サンドボックスの中)。

    ``--no-backup``・``--check``・``--no-broker`` だけを解釈し、残りは pi へ渡す。
    """
    parser = argparse.ArgumentParser(prog="pis")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="起動前の退避をしない (壊した未コミットの変更は戻せなくなる)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="起動せず、この起動ディレクトリのサンドボックスを内側から検査する",
    )
    parser.add_argument(
        "--no-broker",
        action="store_true",
        help="Copilot / GitHub ブローカーを使わない (設定が auto でも。内側に本物の Copilot の認証が入る)",
    )
    args, passthrough = parser.parse_known_args(argv)
    return _launch(args, passthrough)
