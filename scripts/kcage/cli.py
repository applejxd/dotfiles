"""kcage コマンド。root 所有の補助 kcage-root を sudo で呼ぶだけの薄い入口。

- passwordless の動詞（up・stop・exec・ls）は sudo -n（パスワードを尋ねない）。それ以外は sudo（端末で尋ねる）。
- doctor・selftest の判定は純粋関数に分けてある（試験は FakeRunner で行う）。
- 秘密は読まない・表示しない（環境変数の検査も、名前だけを出す）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from kcage import model, trust
from kcage.template import PI_PACKAGE, PI_VERSION_RE

HELPER = f"{model.ROOT_HELPER_DIR}/kcage-root"
PASSWORDLESS = frozenset({"up", "stop", "exec", "ls"})
# ブローカーが箱に入れるダミーの認証の共通の接頭辞（scripts/kcage/broker/*.py の DUMMY_TOKEN）
DUMMY_PREFIX = "kcage-dummy-"
SECRET_NAME = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_?KEY)", re.I)
SECRET_VALUE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|hf_[A-Za-z0-9]{20,}"
    r"|sk-[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
HOME_SECRET_DIRS = ("~/.ssh", "~/.aws", "~/.gnupg", "~/.config/gh", "~/.config/kcage")


@dataclass
class Result:
    """runner の戻り値。subprocess.CompletedProcess と同じ属性だけを使う。"""

    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[..., Result]


def default_runner(argv: Sequence[str], *, capture: bool = False) -> Result:
    """shell=False で実行する。capture=False は端末を引き継ぐ（pi・パスワード入力のため）。"""
    if not capture:
        return Result(subprocess.run(list(argv), check=False).returncode)
    proc = subprocess.run(list(argv), capture_output=True, text=True, encoding="utf-8", check=False)
    return Result(proc.returncode, proc.stdout, proc.stderr)


class Fs:
    """ファイル参照の薄い層（試験で差し替える）。"""

    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def realpath(self, path: str) -> str:
        return os.path.realpath(path)


# ---- 動詞 → kcage-root の argv（純粋） ----


def helper_argv(verb: str, *args: str) -> list[str]:
    """sudo 経由の kcage-root の argv。passwordless の動詞だけ sudo -n。"""
    sudo = ["sudo", "-n"] if verb in PASSWORDLESS else ["sudo"]
    return [*sudo, HELPER, verb, *args]


def exec_argv(repo_id: str, cmd: Sequence[str]) -> list[str]:
    return helper_argv("exec", repo_id, "--", *cmd)


def build_argv(
    verb: str, repo_id: str, rest: Sequence[str], toplevel: str | None = None
) -> list[str]:
    if verb == "pi":
        return exec_argv(repo_id, ["pi", *rest])
    if verb == "exec":
        return exec_argv(repo_id, list(rest))
    if verb == "register":
        # kcage-root の register は --path を要求する（e2e 前の実装では位置引数で渡していて拒否された）
        return helper_argv("register", repo_id, "--path", toplevel or "", *rest)
    if verb == "snap":
        return helper_argv("snap", repo_id, *rest)
    if verb == "ls":
        return helper_argv("ls")
    return helper_argv(verb, repo_id)


# ---- 許可表・リポジトリ id ----


def parse_policy(text: str) -> dict[str, dict]:
    """許可表から [repo.<id>] を読む。壊れていれば ValueError。"""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"許可表が不正: {exc}") from exc
    repos = data.get("repo", {})
    if not isinstance(repos, dict):
        raise ValueError("許可表の repo がテーブルではない")
    return {k: v for k, v in repos.items() if isinstance(v, dict)}


def find_repo_id(
    repos: dict[str, dict], toplevel: str, realpath: Callable[[str], str] = os.path.realpath
) -> str | None:
    top = realpath(toplevel)
    for rid, ent in repos.items():
        path = ent.get("path")
        if isinstance(path, str) and realpath(path) == top:
            return rid
    return None


def default_repo_id(toplevel: str) -> str:
    """register 用の既定の id: ディレクトリ名（英数字・ハイフンに寄せる）。"""
    name = re.sub(r"[^a-z0-9-]+", "-", Path(toplevel).name.lower()).strip("-")
    return name or "repo"


# ---- doctor（純粋な判定） ----


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # ok / warn / fail
    detail: str = ""


def check_policy(
    text: str | None, toplevel: str, realpath: Callable[[str], str] = os.path.realpath
) -> Check:
    if text is None:
        return Check(
            "許可表", "fail", f"{model.POLICY_PATH} が読めない（kcage setup が未実施の可能性）"
        )
    try:
        repos = parse_policy(text)
    except ValueError as exc:
        return Check("許可表", "fail", str(exc))
    rid = find_repo_id(repos, toplevel, realpath)
    if rid is None:
        return Check("許可表", "warn", "このリポジトリは未登録（kcage register）")
    return Check("許可表", "ok", f"登録済み: {rid}")


def check_passwordless_sudo(sudo_l_output: str | None) -> Check:
    """パスワードなしで何でも実行できる sudo があると、ホストの pi が root になれる（箱の制御面の分離が成立しない）。

    e2e で見つけた: WSL のディストロの既定のユーザーには `NOPASSWD: ALL` が入っていることがある。
    """
    if sudo_l_output is None:
        return Check("sudo の範囲", "warn", "sudo -n -l が使えない（確認できない）")
    for line in sudo_l_output.splitlines():
        if re.search(r"NOPASSWD:\s*ALL\b", line):
            return Check(
                "sudo の範囲",
                "fail",
                "NOPASSWD: ALL の規則がある。ホストの pi が root になれるので、"
                "箱の制御面の分離が成立しない（/etc/sudoers.d/ の該当の規則を外す）",
            )
    return Check("sudo の範囲", "ok", "NOPASSWD: ALL なし")


def check_sudoers(sudo_l_output: str | None) -> Check:
    if sudo_l_output is None:
        return Check("sudoers", "fail", "sudo -n -l が失敗（雛形が無い、または認証が要る）")
    for line in sudo_l_output.splitlines():
        if "NOPASSWD" in line and HELPER in line:
            return Check("sudoers", "ok", "kcage-root の雛形あり")
    return Check("sudoers", "fail", "kcage-root の NOPASSWD の雛形が見つからない（kcage setup）")


def check_box_toml(repo_path: str, fs: Fs) -> Check:
    path = f"{repo_path}/kcage.toml"
    if not fs.exists(path):
        return Check("kcage.toml", "warn", "無い（既定の要求で動く）")
    try:
        text = fs.read_text(path)
    except OSError as exc:
        return Check("kcage.toml", "fail", f"読めない: {exc}")
    try:
        _spec_loader()(text)
    except Exception as exc:
        return Check("kcage.toml", "fail", f"不正: {exc}")
    return Check("kcage.toml", "ok", "妥当")


def _spec_loader() -> Callable[[str], object]:
    """W1a の config.parse_spec(text)（kcage.toml を厳格に検証する）。無い環境では TOML の構文だけ見る。"""
    try:
        from kcage import config

        return config.parse_spec
    except (ImportError, AttributeError):
        return tomllib.loads


def check_git_config(hooks_path: str, worktree_config: str) -> list[Check]:
    """契約 C14: .git/hooks の読み取り専用は、ホストの git の実行経路の一部しか守らない。"""
    out: list[Check] = []
    if hooks_path.strip():
        out.append(
            Check(
                "core.hooksPath",
                "warn",
                "設定あり。箱が書いたコードがホストの git で実行されうる（C14）",
            )
        )
    if worktree_config.strip().lower() in ("true", "1", "yes", "on"):
        out.append(
            Check(
                "extensions.worktreeConfig",
                "warn",
                "有効。.git/config の保護が及ばない設定がありうる（C14）",
            )
        )
    if not out:
        out.append(Check("git の実行経路", "ok", "core.hooksPath・worktreeConfig なし"))
    return out


def format_checks(checks: Sequence[Check]) -> str:
    mark = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}
    return "\n".join(f"[{mark[c.status]}] {c.name}: {c.detail}" for c in checks)


# ---- selftest（純粋な判定） ----


def judge_home_secrets(out: str) -> Check:
    names = [ln for ln in out.splitlines() if ln.strip()]
    if names:
        return Check("ホームの秘密", "fail", f"{len(names)} 件が箱の中から見える")
    return Check("ホームの秘密", "ok", "~/.ssh 等は無い")


def judge_env(out: str) -> Check:
    """環境変数に秘密らしい値が無いこと。値は表示せず名前だけを出す。"""
    hits: list[str] = []
    for line in out.splitlines():
        name, _, value = line.partition("=")
        if value.startswith(DUMMY_PREFIX):
            continue  # ブローカーが箱に入れるダミーの認証。本物は Envoy が注入する（e2e で、誤検出した）
        if SECRET_VALUE.search(value) or (SECRET_NAME.search(name) and len(value) >= 16):
            hits.append(name)
    if hits:
        return Check("環境変数", "fail", "秘密らしい値: " + ", ".join(sorted(set(hits))))
    return Check("環境変数", "ok", "秘密らしい値なし")


def judge_git_ro(out: str) -> Check:
    state = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
    bad = [k for k in (".git/hooks", ".git/config") if state.get(k) != "ro"]
    if bad:
        return Check("git の読み取り専用", "fail", "書き込める、または判定不能: " + ", ".join(bad))
    return Check("git の読み取り専用", "ok", ".git/hooks と .git/config は書き込み不可")


def judge_direct(out: str, mode: str) -> Check:
    if mode != "proxy-only":
        return Check("直通の遮断", "ok", f"{mode} のため対象外")
    m = re.search(r"rc=(\d+)", out)
    if m is None:
        return Check("直通の遮断", "fail", "判定不能")
    if m.group(1) == "0":
        return Check("直通の遮断", "fail", "proxy-only なのに直通できた")
    return Check("直通の遮断", "ok", f"直通は失敗（curl rc={m.group(1)}）")


def selftest_commands(repo_path: str) -> dict[str, list[str]]:
    dirs = " ".join(HOME_SECRET_DIRS)
    quoted = shlex.quote(repo_path)
    git = (
        f"cd {quoted} && for p in .git/hooks .git/config; do "
        'if [ -w "$p" ]; then echo "$p=rw"; else echo "$p=ro"; fi; done'
    )
    return {
        "home": ["sh", "-c", f"ls -A {dirs} 2>/dev/null | head -5; true"],
        "env": ["env"],
        "git": ["sh", "-c", git],
        "direct": [
            "sh",
            "-c",
            "curl -sS --noproxy '*' -m 5 -o /dev/null https://example.com >/dev/null 2>&1; echo rc=$?",
        ],
    }


# ---- 実行層 ----


def _out(text: str) -> None:
    print(text, flush=True)


def _toplevel(runner: Runner) -> str | None:
    res = runner(["git", "rev-parse", "--show-toplevel"], capture=True)
    return res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else None


def _git_value(runner: Runner, key: str) -> str:
    res = runner(["git", "config", "--get", key], capture=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def _read_policy(fs: Fs) -> str | None:
    try:
        return fs.read_text(model.POLICY_PATH)
    except OSError:
        return None


def resolve_repo(
    args: argparse.Namespace, runner: Runner, fs: Fs, *, registering: bool = False
) -> tuple[str | None, str | None]:
    """(repo_id, toplevel)。決まらなければ (None, toplevel)。"""
    top = _toplevel(runner)
    if args.repo:
        return args.repo, top
    if top is None:
        return None, None
    if registering:
        return default_repo_id(top), top
    text = _read_policy(fs)
    if text is None:
        return None, top
    try:
        return find_repo_id(parse_policy(text), top, fs.realpath), top
    except ValueError:
        return None, top


def cmd_doctor(args: argparse.Namespace, runner: Runner, fs: Fs) -> int:
    top = _toplevel(runner)
    if top is None:
        _out("git のリポジトリの中で実行する")
        return 2
    checks = [
        check_policy(_read_policy(fs), top, fs.realpath),
    ]
    res = runner(["sudo", "-n", "-l"], capture=True)
    checks.append(check_sudoers(res.stdout if res.returncode == 0 else None))
    checks.append(check_passwordless_sudo(res.stdout if res.returncode == 0 else None))
    checks.append(check_box_toml(top, fs))
    checks.extend(
        check_git_config(
            _git_value(runner, "core.hooksPath"), _git_value(runner, "extensions.worktreeConfig")
        )
    )
    checks.extend(net_hook())
    _out(format_checks(checks))
    return 1 if any(c.status == "fail" for c in checks) else 0


def net_hook() -> list[Check]:
    """incusbr0 の経路の点検は W2（net.py）の担当。あれば呼ぶ（遅延 import）。"""
    try:
        from kcage import net
    except ImportError:
        return []
    fn = getattr(net, "doctor_checks", None)
    if fn is None:
        return []
    return [Check(n, s, d) for n, s, d in fn()]


def cmd_selftest(args: argparse.Namespace, runner: Runner, fs: Fs) -> int:
    repo_id, top = resolve_repo(args, runner, fs)
    if repo_id is None or top is None:
        _out("リポジトリが許可表に無い（kcage register）")
        return 2
    mode = _policy_network(fs, repo_id)
    cmds = selftest_commands(top)
    outs: dict[str, str] = {}
    for key, cmd in cmds.items():
        res = runner(exec_argv(repo_id, cmd), capture=True)
        if res.returncode != 0 and key in ("home", "env", "git"):
            _out(
                f"箱の中で実行できない（kcage up が先、または sudo -n が失敗）: {key}\n{res.stderr.strip()}"
            )
            return 1
        outs[key] = res.stdout
    checks = [
        judge_home_secrets(outs["home"]),
        judge_env(outs["env"]),
        judge_git_ro(outs["git"]),
        judge_direct(outs["direct"], mode),
    ]
    _out(format_checks(checks))
    return 1 if any(c.status == "fail" for c in checks) else 0


def _policy_network(fs: Fs, repo_id: str) -> str:
    text = _read_policy(fs)
    if text is None:
        return "nat"
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return "nat"
    ent = data.get("repo", {}).get(repo_id, {})
    return ent.get("network") or data.get("defaults", {}).get("network", "nat")


DistBuilder = Callable[[Path], object]
PiVersionReader = Callable[[], str | None]


def find_pi_version(start: str, fs: Fs) -> str | None:
    """pi の実体のパスから上へ package.json を探し、pi の版を返す。読めなければ None。"""
    cur = fs.realpath(start)
    for _ in range(8):
        cur = os.path.dirname(cur)
        cand = f"{cur}/package.json"
        if fs.exists(cand):
            try:
                data = json.loads(fs.read_text(cand))
            except (OSError, ValueError):
                return None
            if isinstance(data, dict) and data.get("name") == PI_PACKAGE:
                v = data.get("version")
                return v if isinstance(v, str) and PI_VERSION_RE.match(v) else None
        if cur in ("/", ""):
            break
    return None


def default_pi_version(fs: Fs | None = None) -> str | None:
    exe = shutil.which("pi")
    return find_pi_version(exe, fs or Fs()) if exe else None


def prepare_dist_dir(home: str) -> Path:
    """~/.cache/kcage/dist（呼び出し元だけが書ける 0700。symlink は拒否）を返す。中身は作り直す側で消す。"""
    base = Path(home) / ".cache" / "kcage"
    base.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for d in (base, base / "dist"):
        if d.is_symlink():
            raise OSError(f"symlink は使わない: {d}")
    base.mkdir(mode=0o700, exist_ok=True)
    base.chmod(0o700)
    return base / "dist"


def cmd_template(
    runner: Runner,
    fs: Fs,
    dist_builder: DistBuilder | None,
    pi_version_reader: PiVersionReader | None = None,
    home: str | None = None,
) -> int:
    """配布物をユーザー権限で作り、sudo kcage-root template --dist <パス> を呼ぶ（パスワードが要る）。"""
    if dist_builder is None:
        _out("配布物を作る関数が結線されていない（kcage の入口から呼ぶ）")
        return 2
    dest = prepare_dist_dir(home or os.path.expanduser("~"))
    try:
        dist_builder(dest)
    except Exception as exc:  # DistError など。内容は出さない
        _out(f"配布物を作れない（{type(exc).__name__}）: {exc}")
        return 1
    if dest.exists():
        dest.chmod(0o700)
    version = (pi_version_reader or default_pi_version)()
    extra: list[str] = []
    if version:
        extra = ["--pi-version", version]
    else:
        _out("警告: ホストの pi の版を読めない。版を固定せずに最新を入れる")
    return runner(helper_argv("template", "--dist", str(dest), *extra)).returncode


def cmd_setup(args: argparse.Namespace, runner: Runner) -> int:
    """root で setup.py を実行する（人が起動し、sudo がパスワードを尋ねる）。"""
    script = Path(__file__).resolve().parent / "setup.py"
    argv = ["sudo", "python3", str(script)]
    if args.dry_run:
        argv.append("--dry-run")
    if args.update:
        argv.append("--update")
    return runner(argv).returncode


def cmd_init(args: argparse.Namespace, runner: Runner, template: Callable[[], int]) -> int:
    """setup → template を続けて行う。setup が失敗したら template は実行しない。dry-run は setup の表示だけ。"""
    ns = argparse.Namespace(dry_run=args.dry_run, update=False)
    rc = cmd_setup(ns, runner)
    if rc != 0 or args.dry_run:
        return rc
    return template()


UNINSTALL_UNTRUSTED = (
    "kcage uninstall: root 所有の配備コピーが無い、または信頼できない。"
    "導入されていないか、配備コピーが古い・欠けている。"
    "`kcage setup --update` で配備し直してから実行する（導入されていないなら何もしなくてよい）"
)


def uninstall_script(
    deployed_dir: str = model.ROOT_HELPER_DIR, *, anchor: str = "/", root_uid: int = 0
) -> Path | None:
    """root で実行する uninstall.py。root 所有で信頼できる配備コピーだけを返す。

    無い・信頼できないときは None（このリポジトリのコードへは戻さない。利用者が書けるコードを root で実行しないため）。
    anchor・root_uid は試験用（検査の起点・root とみなす uid）。
    """
    pkg = os.path.join(deployed_dir, "kcage")
    script = os.path.join(pkg, "uninstall.py")
    try:
        # uninstall.py が import 経路に足す配備の根（kcage-root の入口を含む）全体を検査する
        trust.check_tree(deployed_dir, start=anchor, root_uid=root_uid)
        trust.check_trusted(script, start=anchor, root_uid=root_uid)
    except (trust.TrustError, OSError):
        return None
    if trust.missing_modules(pkg):
        return None
    return Path(script)


def cmd_uninstall(args: argparse.Namespace, runner: Runner) -> int:
    """root で uninstall.py を実行する（人が起動し、sudo がパスワードを尋ねる）。"""
    # -I: 環境変数（PYTHONPATH など）と利用者の site を読まない
    script = uninstall_script()
    if script is None:
        print(UNINSTALL_UNTRUSTED, file=sys.stderr)
        return 2
    # -B: root が __pycache__ を書かない
    argv = ["sudo", "python3", "-I", "-B", str(script)]
    for flag, on in (
        ("--dry-run", args.dry_run),
        ("--keep-policy", args.keep_policy),
        ("--drop-subid", getattr(args, "drop_subid", False)),
        ("--yes", args.yes),
    ):
        if on:
            argv.append(flag)
    return runner(argv).returncode


def register_flags(args: argparse.Namespace) -> list[str]:
    """kcage register の引数を kcage-root register のフラグへ。"""
    out: list[str] = []
    for root in args.data_root:
        out += ["--data-root", root]
    for port in args.port:
        out += ["--port", port]
    for broker in args.broker:
        out += ["--broker", broker]
    if args.gpu:
        out.append("--gpu")
    for flag, value in (
        ("--network", args.network),
        ("--proxy-upstream", args.proxy_upstream),
        ("--idmap", args.idmap),
        ("--subnet", args.subnet),
    ):
        if value:
            out += [flag, value]
    return out


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="リポジトリ id（省略時はカレントの git から許可表で決める）")
    p = argparse.ArgumentParser(prog="kcage", description="リポジトリごとの Incus の箱")
    sub = p.add_subparsers(dest="verb", required=True)
    for verb, helptext in (
        ("up", "箱を作って起動する"),
        ("stop", "箱を止める"),
        ("rm", "箱を消す（パスワードを尋ねる）"),
        ("snap", "スナップショットを取る"),
        ("doctor", "設定の点検"),
        ("selftest", "箱の中から否定試験をする"),
        ("register", "このリポジトリを許可表へ登録する"),
    ):
        sp = sub.add_parser(verb, parents=[common], help=helptext)
        if verb == "snap":
            sp.add_argument("name", nargs="?", help="スナップショット名")
        if verb == "register":
            # 許可表へ追加する内容。実際の追記は kcage-root（root）が差分を表示して y/N を確認してから行う
            sp.add_argument(
                "--data-root", action="append", default=[], help="読み取り専用で渡してよい根"
            )
            sp.add_argument(
                "--port", action="append", default=[], help="公開してよいポート（N または LO-HI）"
            )
            sp.add_argument(
                "--broker", action="append", default=[], help="gh / copilot / aws / hf-cache"
            )
            sp.add_argument("--gpu", action="store_true", help="GPU を渡す")
            sp.add_argument(
                "--network", choices=("nat", "proxy-only", "offline"), help="外向き通信のモード"
            )
            sp.add_argument("--proxy-upstream", help="proxy-only の上流（IP:ポート）")
            sp.add_argument("--idmap", choices=("user", "root"), help="uid の対応")
            sp.add_argument("--subnet", help="incusbr0 のサブネット")
    sub.add_parser("ls", parents=[common], help="箱の一覧")
    pi = sub.add_parser("pi", parents=[common], help="箱の中で pi を起動する")
    pi.add_argument("pi_args", nargs=argparse.REMAINDER, help="pi へ渡す引数（-- の後ろ）")
    ex = sub.add_parser("exec", parents=[common], help="箱の中でコマンドを実行する（-- の後ろ）")
    ex.add_argument("exec_cmd", nargs=argparse.REMAINDER, help="実行するコマンド")
    su = sub.add_parser("setup", help="ホストの初期設定（root。パスワードを尋ねる）")
    su.add_argument("--dry-run", action="store_true", help="何もせず、やることを表示する")
    su.add_argument("--update", action="store_true", help="root 所有の配備コピーだけを更新する")
    sub.add_parser("template", help="テンプレート（箱の元のイメージ）を作る（パスワードを尋ねる）")
    ini = sub.add_parser("init", help="初期化: setup → template を続けて行う（パスワードを尋ねる）")
    ini.add_argument("--dry-run", action="store_true", help="setup のやることを表示するだけ")
    un = sub.add_parser("uninstall", help="導入物を戻す（root。Incus 本体は残す）")
    un.add_argument("--dry-run", action="store_true", help="何もせず、やることを表示する")
    un.add_argument("--keep-policy", action="store_true", help="許可表（/etc/kcage）を残す")
    un.add_argument(
        "--drop-subid",
        action="store_true",
        help="subuid/subgid の kcage 用の行も消す（既定は残す）",
    )
    un.add_argument("--yes", action="store_true", help="箱を消す確認を省く")
    return p


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
    fs: Fs | None = None,
    dist_builder: DistBuilder | None = None,
    pi_version_reader: PiVersionReader | None = None,
) -> int:
    runner = runner or default_runner
    fs = fs or Fs()
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.verb == "setup":
        return cmd_setup(args, runner)
    if args.verb == "template":
        return cmd_template(runner, fs, dist_builder, pi_version_reader)
    if args.verb == "init":
        return cmd_init(
            args, runner, lambda: cmd_template(runner, fs, dist_builder, pi_version_reader)
        )
    if args.verb == "uninstall":
        return cmd_uninstall(args, runner)
    if args.verb == "doctor":
        return cmd_doctor(args, runner, fs)
    if args.verb == "selftest":
        return cmd_selftest(args, runner, fs)
    if args.verb == "ls":
        return runner(helper_argv("ls")).returncode
    repo_id, top = resolve_repo(args, runner, fs, registering=args.verb == "register")
    if repo_id is None:
        _out("リポジトリが許可表に無い。登録は: kcage register（git のリポジトリの中で）")
        return 2
    rest: list[str] = []
    if args.verb == "pi":
        rest = [a for a in args.pi_args if True]
        if rest[:1] == ["--"]:
            rest = rest[1:]
    elif args.verb == "exec":
        rest = list(args.exec_cmd)
        if rest[:1] == ["--"]:
            rest = rest[1:]
        if not rest:
            _out("実行するコマンドが無い（例: kcage exec -- ls -l）")
            return 2
    elif args.verb == "snap" and args.name:
        rest = [args.name]
    elif args.verb == "register":
        rest = register_flags(args)
    res = runner(build_argv(args.verb, repo_id, rest, top))
    if res.returncode != 0 and args.verb in PASSWORDLESS:
        _out(
            f"失敗（kcage-root が拒否した、または sudoers の雛形が無い）: kcage doctor で点検する（rc={res.returncode}）"
        )
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())
