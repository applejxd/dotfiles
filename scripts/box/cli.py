"""box コマンド。root 所有の補助 box-root を sudo で呼ぶだけの薄い入口。

- passwordless の動詞（up・stop・exec・ls）は sudo -n（パスワードを尋ねない）。それ以外は sudo（端末で尋ねる）。
- doctor・selftest の判定は純粋関数に分けてある（試験は FakeRunner で行う）。
- 秘密は読まない・表示しない（環境変数の検査も、名前だけを出す）。
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from box import model

HELPER = f"{model.ROOT_HELPER_DIR}/box-root"
PASSWORDLESS = frozenset({"up", "stop", "exec", "ls"})
SECRET_NAME = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_?KEY)", re.I)
SECRET_VALUE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|hf_[A-Za-z0-9]{20,}"
    r"|sk-[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
HOME_SECRET_DIRS = ("~/.ssh", "~/.aws", "~/.gnupg", "~/.config/gh", "~/.config/box")


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


# ---- 動詞 → box-root の argv（純粋） ----


def helper_argv(verb: str, *args: str) -> list[str]:
    """sudo 経由の box-root の argv。passwordless の動詞だけ sudo -n。"""
    sudo = ["sudo", "-n"] if verb in PASSWORDLESS else ["sudo"]
    return [*sudo, HELPER, verb, *args]


def exec_argv(repo_id: str, cmd: Sequence[str]) -> list[str]:
    return helper_argv("exec", repo_id, "--", *cmd)


def build_argv(
    verb: str, repo_id: str, rest: Sequence[str], toplevel: str | None = None
) -> list[str]:
    if verb == "pi":
        return exec_argv(repo_id, ["pi", *rest])
    if verb == "register":
        return helper_argv("register", repo_id, toplevel or "")
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
            "許可表", "fail", f"{model.POLICY_PATH} が読めない（box setup が未実施の可能性）"
        )
    try:
        repos = parse_policy(text)
    except ValueError as exc:
        return Check("許可表", "fail", str(exc))
    rid = find_repo_id(repos, toplevel, realpath)
    if rid is None:
        return Check("許可表", "warn", "このリポジトリは未登録（box register）")
    return Check("許可表", "ok", f"登録済み: {rid}")


def check_sudoers(sudo_l_output: str | None) -> Check:
    if sudo_l_output is None:
        return Check("sudoers", "fail", "sudo -n -l が失敗（雛形が無い、または認証が要る）")
    for line in sudo_l_output.splitlines():
        if "NOPASSWD" in line and HELPER in line:
            return Check("sudoers", "ok", "box-root の雛形あり")
    return Check("sudoers", "fail", "box-root の NOPASSWD の雛形が見つからない（box setup）")


def check_box_toml(repo_path: str, fs: Fs) -> Check:
    path = f"{repo_path}/box.toml"
    if not fs.exists(path):
        return Check("box.toml", "warn", "無い（既定の要求で動く）")
    try:
        text = fs.read_text(path)
    except OSError as exc:
        return Check("box.toml", "fail", f"読めない: {exc}")
    try:
        _spec_loader()(text)
    except Exception as exc:
        return Check("box.toml", "fail", f"不正: {exc}")
    return Check("box.toml", "ok", "妥当")


def _spec_loader() -> Callable[[str], object]:
    """W1a の config.load_spec(text)。まだ無い環境では TOML の構文だけ見る。"""
    try:
        from box import config

        return config.load_spec
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
        from box import net
    except ImportError:
        return []
    fn = getattr(net, "doctor_checks", None)
    if fn is None:
        return []
    return [Check(n, s, d) for n, s, d in fn()]


def cmd_selftest(args: argparse.Namespace, runner: Runner, fs: Fs) -> int:
    repo_id, top = resolve_repo(args, runner, fs)
    if repo_id is None or top is None:
        _out("リポジトリが許可表に無い（box register）")
        return 2
    mode = _policy_network(fs, repo_id)
    cmds = selftest_commands(top)
    outs: dict[str, str] = {}
    for key, cmd in cmds.items():
        res = runner(exec_argv(repo_id, cmd), capture=True)
        if res.returncode != 0 and key in ("home", "env", "git"):
            _out(
                f"箱の中で実行できない（box up が先、または sudo -n が失敗）: {key}\n{res.stderr.strip()}"
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


def cmd_setup(args: argparse.Namespace, runner: Runner) -> int:
    """root で setup.py を実行する（人が起動し、sudo がパスワードを尋ねる）。"""
    script = Path(__file__).resolve().parent / "setup.py"
    argv = ["sudo", "python3", str(script)]
    if args.dry_run:
        argv.append("--dry-run")
    if args.update:
        argv.append("--update")
    return runner(argv).returncode


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="リポジトリ id（省略時はカレントの git から許可表で決める）")
    p = argparse.ArgumentParser(prog="box", description="リポジトリごとの Incus の箱")
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
    sub.add_parser("ls", parents=[common], help="箱の一覧")
    pi = sub.add_parser("pi", parents=[common], help="箱の中で pi を起動する")
    pi.add_argument("pi_args", nargs=argparse.REMAINDER, help="pi へ渡す引数（-- の後ろ）")
    su = sub.add_parser("setup", help="ホストの初期設定（root。パスワードを尋ねる）")
    su.add_argument("--dry-run", action="store_true", help="何もせず、やることを表示する")
    su.add_argument("--update", action="store_true", help="root 所有の配備コピーだけを更新する")
    return p


def main(
    argv: Sequence[str] | None = None, *, runner: Runner | None = None, fs: Fs | None = None
) -> int:
    runner = runner or default_runner
    fs = fs or Fs()
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.verb == "setup":
        return cmd_setup(args, runner)
    if args.verb == "doctor":
        return cmd_doctor(args, runner, fs)
    if args.verb == "selftest":
        return cmd_selftest(args, runner, fs)
    if args.verb == "ls":
        return runner(helper_argv("ls")).returncode
    repo_id, top = resolve_repo(args, runner, fs, registering=args.verb == "register")
    if repo_id is None:
        _out("リポジトリが許可表に無い。登録は: box register（git のリポジトリの中で）")
        return 2
    rest: list[str] = []
    if args.verb == "pi":
        rest = [a for a in args.pi_args if True]
        if rest[:1] == ["--"]:
            rest = rest[1:]
    elif args.verb == "snap" and args.name:
        rest = [args.name]
    res = runner(build_argv(args.verb, repo_id, rest, top))
    if res.returncode != 0 and args.verb in PASSWORDLESS:
        _out(
            f"失敗（box-root が拒否した、または sudoers の雛形が無い）: box doctor で点検する（rc={res.returncode}）"
        )
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())
