"""pi を Fence で囲って起動する (``pis`` の標準)。

境界の組み立て・危険な起動場所の拒否・起動前の退避は OpenCode と共通 (``boundary`` / ``backup``)。
ここは pi だけの部分: 境界用の agent 置き場の作成、起動コマンド、内側へ渡さない環境変数。

pi は設定と認証を読むときにも隣へ ``.lock`` を作るので、agent 置き場は書ける必要がある。
一方、本物の ``~/.pi/agent`` を境界に入れると、内側で作られた拡張を外の通常の pi が読む。
そこで**起動ごとに境界用の agent 置き場を作り**、認証・モデルの一覧・設定を写す。
see docs/spec/pi-guard.md#サンドボックス
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
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from . import backup, boundary, check, cli, relay
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
# 入力は PIS_COPILOT_BROKER (未設定なら何も変わらない)。
BROKER_ENV = "PIS_COPILOT_BROKER"
BROKER_PROVIDER = "github-copilot"
BROKER_DUMMY_TOKEN = "dummy-not-a-real-token"
BROKER_IDENTITY_PATH = "/__pis_broker"
BROKER_IDENTITY_PREFIX = "pis-broker-copilot"
BROKER_TIMEOUT_SECONDS = 3
BROKER_HINT = (
    f"{BROKER_ENV} は http://127.0.0.1:<1024-65535> の形で指定する (例 http://127.0.0.1:18080)"
)


def parse_broker(value: str | None) -> tuple[str, int] | None:
    """``PIS_COPILOT_BROKER`` を厳密に検証し、(末尾スラッシュなしの URL, ポート) を返す。

    未設定 (None / 空文字) なら None。http・127.0.0.1・1024〜65535・パス無し・
    ユーザー情報 / クエリ / フラグメント無し以外は起動を拒否する。
    """
    if value is None or value == "":
        return None
    if value != value.strip() or "?" in value or "#" in value:
        die(f"{BROKER_ENV} が不正: {value!r} (空白・クエリ・フラグメントは使えない)", BROKER_HINT)
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        die(f"{BROKER_ENV} が URL として読めない: {value!r}", BROKER_HINT)
    if parts.scheme != "http":
        die(f"{BROKER_ENV} のスキームは http のみ: {value!r}", BROKER_HINT)
    if "@" in parts.netloc:
        die(f"{BROKER_ENV} にユーザー情報は書けない: {value!r}", BROKER_HINT)
    if parts.hostname != "127.0.0.1":
        die(f"{BROKER_ENV} のホストは 127.0.0.1 のみ: {value!r}", BROKER_HINT)
    if port is None or not 1024 <= port <= 65535:
        die(f"{BROKER_ENV} のポートは 1024〜65535 (必須): {value!r}", BROKER_HINT)
    if parts.path not in ("", "/"):
        die(f"{BROKER_ENV} にパスは書けない: {value!r}", BROKER_HINT)
    return f"http://127.0.0.1:{port}", port


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None  # リダイレクトは辿らない (HTTPError になる)


def verify_broker(url: str) -> None:
    """境界を組む前に、ブローカーが本物か確かめる。違えば起動を拒否する。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    target = url + BROKER_IDENTITY_PATH
    hint = "Envoy (scripts/agents/broker-spike/envoy-copilot.yaml) を起動してから pis を使う"
    try:
        with opener.open(target, timeout=BROKER_TIMEOUT_SECONDS) as response:
            status = response.status
            body = response.read(256).decode("utf-8", errors="replace")
    except OSError as e:  # URLError / HTTPError / タイムアウトはすべて OSError の仲間
        die(f"Copilot ブローカーが動いていない、または別のサービス: {target} ({e})", hint)
    if status != 200 or not body.startswith(BROKER_IDENTITY_PREFIX):
        die(
            f"Copilot ブローカーが動いていない、または別のサービス: {target} (status={status})",
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


def apply_broker_network(config_: dict, port: int) -> None:
    """ブローカーモードのときだけ、ホストのブローカーのポート 1 つへ localhost の送信を許す。

    ``allowLocalBinding`` は触らない (``ocs`` と共通の ``build_boundary`` の出力は変えない)。
    """
    network = config_["network"]
    network["allowLocalOutbound"] = True
    network["allowLocalOutboundPorts"] = [port]


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


def prepare_agent_dir(
    real: Path | None = None, home: Path | None = None, broker_url: str | None = None
) -> Path:
    """境界用の agent 置き場を作り、本物から必要なものだけを写す。

    既定の置き場は呼び出しのときに引く (定義時に固定すると、差し替えが効かない)。
    ``broker_url`` があれば (ブローカーモード) ``auth.json`` から ``github-copilot`` を除き、
    ``models.json`` に ``baseUrl`` を入れる。
    """
    real = real if real is not None else REAL_AGENT
    home = home if home is not None else AGENT_HOME
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    _prune_agents(home)
    agent = Path(tempfile.mkdtemp(prefix="agent-", dir=str(home)))
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
    return agent


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


def inner_env(agent: Path, config_: dict, broker: bool = False) -> dict[str, str]:
    """境界の内側へ渡す環境変数。役割と bypass は ``pis`` が環境変数で渡す。

    ``PI_HARNESS_BOUNDARY`` は「内側のはず」という期待にすぎない。内側のフルガードが、次のカナリアで
    実測し (読めてはいけないファイル・書けてはいけない場所)、効いていなければ起動を止める。
    許可の一覧 (``PI_HARNESS_ALLOWED``) は、実際に開けた場所で、作業ツリーの外の判定に使う。
    see docs/spec/pi-guard.md#緩和のゲート
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
    see docs/spec/pi-guard.md#起動
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


def _launch(args: argparse.Namespace, passthrough: list[str]) -> int:
    """pi を Fence で囲って起動する。OpenCode と違い、DB も設定の書き出しも要らない。

    境界用の agent 置き場を起動ごとに作り (:mod:`pi`)、セッションの置き場だけを本物へ開ける。
    see docs/spec/pi-guard.md#サンドボックス
    """
    check_installed()
    # ブローカーモード (未設定なら None で、以降は現行と同じ)。境界を組む前に検証と身元確認をする
    broker = parse_broker(os.environ.get(BROKER_ENV))
    if broker is not None:
        verify_broker(broker[0])
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

    agent = prepare_agent_dir(broker_url=broker[0] if broker else None)
    sessions = sessions_dir(workspace)
    config_ = boundary.build_boundary(sandbox, workspace, request, agent)
    if broker is not None:
        apply_broker_network(config_, broker[1])
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
    env = inner_env(agent, config_, broker is not None)

    # 社内プロキシ越しでないと外へ出られない機械では、許可リストの照合を中継へ移す (relay)
    with relay.session(config_) as fence_config:
        project["relay"] = fence_config is not config_
        if args.check:
            boundary_file = cli.write_boundary(fence_config)
            try:
                return check.run_check(runtime, boundary_file, project, env, cli.FENCE_TMP)
            finally:
                Path(boundary_file).unlink(missing_ok=True)
                cleanup(agent, broker is not None)

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
            cleanup(agent, broker is not None)
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
            return run(argv, check.host_env(env, cli.FENCE_TMP), agent, broker is not None)
        finally:
            Path(boundary_file).unlink(missing_ok=True)


def run_sandboxed(argv: list[str]) -> int:
    """``pis`` の標準の起動 (サンドボックスの中)。

    ``--no-backup`` と ``--check`` だけを解釈し、残りは pi へ渡す。
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
    args, passthrough = parser.parse_known_args(argv)
    return _launch(args, passthrough)
