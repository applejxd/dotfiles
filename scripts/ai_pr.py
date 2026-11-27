#!/usr/bin/env python3
"""専用 GitHub App（applejxd-dotfiles-ai）で ai/* PR の push・作成・Auto-Merge・片付けを行う入口。

生の `git push` や `gh pr merge` を解禁せず、以下の不変条件を入口側で強制する:
- 対象リポジトリは applejxd/dotfiles、PR ベースは develop、作業枝は ai/<slug> のみに固定する。
- App トークン（contents: write + pull_requests: write、workflows 権限なし）を都度発行し、
  トークン・秘密鍵・JWT を標準出力やログへ一切出さない。
- push は --force なし、push 前に gitleaks で履歴の秘密を検査する。
- マージ完了または close 後のローカル worktree・ローカル ai/* 枝・develop の ff-only 更新を安全に片付ける。

see docs/adr/0044-github-app-auto-merge-and-3os-ci.md
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ci_policy  # noqa: E402

REPO_OWNER = "applejxd"
REPO_NAME = "dotfiles"
REPO_FULL = f"{REPO_OWNER}/{REPO_NAME}"
BASE_BRANCH = "develop"
AI_BRANCH_RE = re.compile(r"^ai/[a-z0-9][a-z0-9._-]{0,63}$")
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "dotfiles-ai"


class AiPrError(RuntimeError):
    """ai_pr 実行時のユーザー向けエラー。"""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def validate_ai_branch(branch: str) -> str:
    name = branch.strip()
    if not AI_BRANCH_RE.match(name) or ".." in name or name.endswith("."):
        raise AiPrError(
            f"ブランチ名は ai/<英小文字・数字・._-> の形式にしてください: {branch!r}"
        )
    return name


def load_app_config(config_dir: Path | None = None) -> tuple[int, int, Path]:
    base = (config_dir or Path(os.environ.get("DOTFILES_AI_APP_DIR", str(DEFAULT_CONFIG_DIR)))).expanduser()
    meta_path = base / "app.json"
    if not meta_path.is_file():
        raise AiPrError(f"GitHub App 設定が見つかりません: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    app_id = int(meta["app_id"])
    installation_id = int(meta["installation_id"])
    pem_path = Path(meta.get("pem_path") or (base / "app.pem")).expanduser()
    if not pem_path.is_file():
        raise AiPrError(f"GitHub App 秘密鍵が見つかりません: {pem_path}")
    return app_id, installation_id, pem_path


def _find_openssl() -> str:
    found = shutil.which("openssl")
    if found:
        return found
    if os.name == "nt":
        for cand in (
            r"C:\Program Files\Git\mingw64\bin\openssl.exe",
            r"C:\Program Files\Git\usr\bin\openssl.exe",
        ):
            if Path(cand).is_file():
                return cand
    raise AiPrError("openssl が見つかりません（JWT 署名に必要）")


def _sign_rs256(signing_input: bytes, pem_path: Path) -> bytes:
    """RS256 署名を生成する。openssl が無ければ cryptography を試す。"""
    try:
        openssl = _find_openssl()
    except AiPrError:
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as exc:
            raise AiPrError("openssl も cryptography も利用できません") from exc
        key = serialization.load_pem_private_key(pem_path.read_bytes(), password=None)
        return key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())  # type: ignore[union-attr]

    proc = subprocess.run(
        [openssl, "dgst", "-sha256", "-sign", str(pem_path)],
        input=signing_input,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AiPrError(f"openssl での JWT 署名に失敗しました（exit {proc.returncode}）")
    return proc.stdout


def build_app_jwt(app_id: int, pem_path: Path, *, now: int | None = None) -> str:
    ts = int(time.time()) if now is None else now
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64url(
        json.dumps({"iat": ts - 60, "exp": ts + 540, "iss": str(app_id)}, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    sig = _b64url(_sign_rs256(signing_input, pem_path))
    return f"{header}.{payload}.{sig}"


def _github_json(
    method: str,
    url: str,
    token: str,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "applejxd-dotfiles-ai-pr",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        # 秘密が混入しないよう応答本文を短く切り、トークン文字列を絶対に露出させない
        raise AiPrError(f"GitHub API {method} {url} が失敗しました (HTTP {exc.code}): {detail[:400]}") from exc


def mint_installation_token(app_id: int, installation_id: int, pem_path: Path) -> str:
    jwt = build_app_jwt(app_id, pem_path)
    resp = _github_json(
        "POST",
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        jwt,
        {"repositories": [REPO_NAME]},
    )
    token = resp.get("token")
    if not isinstance(token, str) or not token:
        raise AiPrError("Installation Access Token の取得に失敗しました")
    return token


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and proc.returncode != 0:
        raise AiPrError(f"git {' '.join(args)} が失敗しました: {proc.stderr.strip()}")
    return proc


def _repo_root(cwd: Path) -> Path:
    return Path(_git(cwd, "rev-parse", "--show-toplevel").stdout.strip()).resolve()


def _main_worktree_root(cwd: Path) -> Path:
    common = Path(_git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    return common.parent.resolve()


def _ensure_clean_worktree(root: Path) -> None:
    status = _git(root, "status", "--porcelain").stdout.strip()
    if status:
        raise AiPrError("未コミットの変更が残っています。コミットしてから push してください。")


def _run_gitleaks_check(root: Path, base_ref: str) -> None:
    """push する範囲（base_ref..HEAD）の全コミットを gitleaks で検査する。"""
    gitleaks_bin = shutil.which("gitleaks")
    cmd = (
        [gitleaks_bin, "git", "--log-opts", f"{base_ref}..HEAD", "--redact", "--verbose"]
        if gitleaks_bin
        else ["mise", "exec", "--", "gitleaks", "git", "--log-opts", f"{base_ref}..HEAD", "--redact", "--verbose"]
    )
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if proc.returncode != 0:
        raise AiPrError(f"gitleaks 検査に失敗しました（秘密の疑いまたは起動失敗）:\n{proc.stderr or proc.stdout}")


def _push_with_app_token(root: Path, branch: str, token: str) -> None:
    """App トークンを一時 askpass で渡して refs/heads/<branch> だけを非強制 push する。"""
    remote_url = f"https://github.com/{REPO_FULL}.git"
    # repo ローカルの url.*.pushInsteadOf による宛先すり替えを拒否する（P1-2 対策）
    resolved = _git(root, "ls-remote", "--get-url", remote_url).stdout.strip()
    if resolved != remote_url:
        raise AiPrError(f"git の URL 書き換えが検出されたため push を中止しました: {resolved}")

    # トークンは URL・コマンド引数・環境変数へ載せず、権限を絞った一時ファイル経由で askpass のみへ渡す。
    # さらに --no-verify と空の core.hooksPath により、リポジトリ内の hook にトークンへ触れさせない。
    with tempfile.TemporaryDirectory(prefix="ai-pr-askpass-") as tmp:
        tmp_dir = Path(tmp)
        empty_hooks = tmp_dir / "empty-hooks"
        empty_hooks.mkdir()
        token_file = tmp_dir / "token.txt"
        token_file.write_text(token, encoding="ascii")
        if os.name != "nt":
            os.chmod(token_file, 0o600)

        askpass = tmp_dir / ("askpass.cmd" if os.name == "nt" else "askpass.sh")
        if os.name == "nt":
            askpass.write_text(
                "@echo off\r\n"
                "setlocal\r\n"
                "echo %~1 | findstr /I \"Username\" >nul\r\n"
                "if %ERRORLEVEL%==0 (\r\n"
                "  echo x-access-token\r\n"
                ") else (\r\n"
                f"  set /p TOK=<\"{token_file}\"\r\n"
                "  setlocal enabledelayedexpansion\r\n"
                "  echo !TOK!\r\n"
                ")\r\n",
                encoding="ascii",
            )
        else:
            askpass.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  *Username*) printf '%s\\n' x-access-token ;;\n"
                f"  *) cat '{token_file}' ; printf '\\n' ;;\n"
                "esac\n",
                encoding="ascii",
            )
            os.chmod(askpass, 0o700)

        env = dict(os.environ)
        env["GIT_ASKPASS"] = str(askpass)
        env["GIT_TERMINAL_PROMPT"] = "0"
        refspec = f"refs/heads/{branch}:refs/heads/{branch}"
        proc = subprocess.run(
            [
                "git",
                "-c",
                "credential.helper=",
                "-c",
                f"core.hooksPath={empty_hooks}",
                "push",
                "--no-verify",
                remote_url,
                refspec,
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            safe_err = proc.stderr.replace(token, "***")
            raise AiPrError(f"git push ({branch}) に失敗しました:\n{safe_err.strip()}")


def _find_open_pr(branch: str, token: str) -> dict[str, object] | None:
    q = urllib.parse.urlencode({"state": "open", "head": f"{REPO_OWNER}:{branch}", "base": BASE_BRANCH})
    url = f"https://api.github.com/repos/{REPO_FULL}/pulls?{q}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "applejxd-dotfiles-ai-pr",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        items = json.loads(resp.read().decode("utf-8"))
    return items[0] if items else None


def _create_or_update_pr(
    branch: str,
    title: str,
    body: str,
    token: str,
) -> dict[str, object]:
    existing = _find_open_pr(branch, token)
    if existing:
        number = existing["number"]
        return _github_json(
            "PATCH",
            f"https://api.github.com/repos/{REPO_FULL}/pulls/{number}",
            token,
            {"title": title, "body": body},
        )
    return _github_json(
        "POST",
        f"https://api.github.com/repos/{REPO_FULL}/pulls",
        token,
        {
            "title": title,
            "body": body,
            "head": branch,
            "base": BASE_BRANCH,
            "maintainer_can_modify": True,
        },
    )


def _enable_auto_merge(pr_node_id: str, title: str, summary: str, token: str) -> tuple[bool, str]:
    query = """
    mutation($prId: ID!, $headline: String!, $body: String!) {
      enablePullRequestAutoMerge(input: {
        pullRequestId: $prId,
        mergeMethod: SQUASH,
        commitHeadline: $headline,
        commitBody: $body
      }) {
        pullRequest {
          number
          autoMergeRequest { enabledAt mergeMethod }
        }
      }
    }
    """
    resp = _github_json(
        "POST",
        "https://api.github.com/graphql",
        token,
        {
            "query": query,
            "variables": {
                "prId": pr_node_id,
                "headline": title,
                "body": summary,
            },
        },
    )
    errors = resp.get("errors")
    if isinstance(errors, list) and errors:
        msg = "; ".join(str(e.get("message", e)) for e in errors if isinstance(e, dict))
        return False, msg
    return True, "enabled"


def _cmd_check_auth(args: argparse.Namespace) -> int:
    app_id, installation_id, pem_path = load_app_config(args.config_dir)
    token = mint_installation_token(app_id, installation_id, pem_path)
    repo = _github_json("GET", f"https://api.github.com/repos/{REPO_FULL}", token)
    print(
        json.dumps(
            {
                "ok": True,
                "app_id": app_id,
                "installation_id": installation_id,
                "repo": repo.get("full_name"),
                "allow_auto_merge": repo.get("allow_auto_merge"),
                "delete_branch_on_merge": repo.get("delete_branch_on_merge"),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_start(args: argparse.Namespace) -> int:
    branch = validate_ai_branch(f"ai/{args.slug}" if not args.slug.startswith("ai/") else args.slug)
    slug = branch.removeprefix("ai/")
    main_root = _main_worktree_root(Path.cwd())
    wt_path = main_root / ".tmp" / "worktrees" / slug
    if wt_path.exists():
        raise AiPrError(f"worktree が既に存在します: {wt_path}")
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    base = args.base or BASE_BRANCH
    _git(main_root, "worktree", "add", "-b", branch, str(wt_path), base)
    print(json.dumps({"branch": branch, "worktree": str(wt_path), "base": base}, ensure_ascii=False))
    return 0


def _cmd_submit(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    root = _repo_root(cwd)
    branch = validate_ai_branch(_git(root, "branch", "--show-current").stdout.strip())
    title_err = ci_policy.validate_pr_title(args.title)
    if title_err:
        raise AiPrError(title_err)
    _ensure_clean_worktree(root)

    # まず origin/develop の最新を取り込み、改ざんできない merge-base 範囲で差分と秘密を検査する
    if not args.dry_run:
        _git(root, "fetch", "origin", BASE_BRANCH, check=False)
    has_origin_base = (
        _git(root, "rev-parse", "--verify", "--quiet", f"origin/{BASE_BRANCH}", check=False).returncode
        == 0
    )
    base_ref = f"origin/{BASE_BRANCH}" if has_origin_base else BASE_BRANCH
    merge_base = _git(root, "merge-base", base_ref, "HEAD").stdout.strip()
    changed = ci_policy.changed_files_between(merge_base, "HEAD", cwd=root)
    if not changed:
        raise AiPrError(f"{base_ref} からの差分が 0 件です。")
    if any(p.startswith(".github/workflows/") for p in changed):
        raise AiPrError(".github/workflows/ の変更は専用 App 経由では push できません（人間操作が必要です）。")
    protected = ci_policy.find_protected_paths(changed)

    _run_gitleaks_check(root, merge_base)

    summary = args.summary.strip() if args.summary else ""
    body_lines = [summary] if summary else [args.title.strip()]
    if protected:
        body_lines.append("")
        body_lines.append("保護パスを含むため `protected-path-approval` の承認待ちに入ります:")
        body_lines.extend(f"- `{p}`" for p in protected)
    pr_body = "\n".join(body_lines).strip()

    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "branch": branch,
                    "base": BASE_BRANCH,
                    "title": args.title.strip(),
                    "changed_count": len(changed),
                    "protected": bool(protected),
                    "protected_paths": protected,
                },
                ensure_ascii=False,
            )
        )
        return 0

    app_id, installation_id, pem_path = load_app_config(args.config_dir)
    token = mint_installation_token(app_id, installation_id, pem_path)
    _push_with_app_token(root, branch, token)
    # cleanup が「push 済み後にリモートから消えた [gone] 枝」だけを安全に判別できるよう upstream を記録する
    _git(root, "fetch", "origin", branch, check=False)
    _git(root, "branch", f"--set-upstream-to=origin/{branch}", branch, check=False)
    pr = _create_or_update_pr(branch, args.title.strip(), pr_body, token)

    auto_enabled = False
    auto_note = "disabled (--no-auto-merge)"
    if not args.no_auto_merge:
        node_id = str(pr.get("node_id") or "")
        if node_id:
            auto_enabled, auto_note = _enable_auto_merge(node_id, args.title.strip(), summary, token)

    print(
        json.dumps(
            {
                "branch": branch,
                "pr_number": pr.get("number"),
                "pr_url": pr.get("html_url"),
                "protected": bool(protected),
                "protected_paths": protected,
                "auto_merge_enabled": auto_enabled,
                "auto_merge_note": auto_note,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_cleanup(args: argparse.Namespace) -> int:
    main_root = _main_worktree_root(Path.cwd())
    _git(main_root, "fetch", "origin", "--prune")

    # 本体が develop かつ作業ツリーが綺麗なら ff-only で最新化する（dry-run では変更しない）
    cur_branch = _git(main_root, "branch", "--show-current").stdout.strip()
    cur_dirty = bool(_git(main_root, "status", "--porcelain").stdout.strip())
    updated_develop = False
    if (
        not args.dry_run
        and cur_branch == BASE_BRANCH
        and not cur_dirty
        and _git(main_root, "merge", "--ff-only", f"origin/{BASE_BRANCH}", check=False).returncode == 0
    ):
        updated_develop = True

    if args.allow_squashed and not args.branch:
        raise AiPrError("--allow-squashed は誤削除防止のため --branch と併用してください。")

    removed_worktrees: list[str] = []
    deleted_branches: list[str] = []
    skipped: list[str] = []

    wt_root = (main_root / ".tmp" / "worktrees").resolve()
    upstream_track: dict[str, str] = {}
    ref_out = _git(
        main_root,
        "for-each-ref",
        "--format=%(refname:short)\t%(upstream:track)",
        "refs/heads/ai/",
    ).stdout
    for line in ref_out.splitlines():
        if not line.strip():
            continue
        name, _, track = line.partition("\t")
        upstream_track[name.strip()] = track.strip()

    if args.branch:
        targets = [validate_ai_branch(args.branch)]
    else:
        targets = list(upstream_track.keys())

    # worktree 一覧を branch -> path で引く
    wt_map: dict[str, Path] = {}
    wt_out = _git(main_root, "worktree", "list", "--porcelain").stdout
    cur_wt: Path | None = None
    for line in wt_out.splitlines():
        if line.startswith("worktree "):
            cur_wt = Path(line[len("worktree ") :]).resolve()
        elif line.startswith("branch refs/heads/") and cur_wt is not None:
            wt_map[line[len("branch refs/heads/") :]] = cur_wt

    for branch in targets:
        # リモートにまだ ai/* が残っている進行中ブランチは触らない
        remote_exists = (
            _git(main_root, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}", check=False).returncode
            == 0
        )
        if remote_exists:
            skipped.append(f"{branch} (リモートに残存)")
            continue
        # 引数なしの自動掃除も --allow-squashed も、一度 push されてリモートから消えた [gone] 枝だけを対象にする。
        # start 直後や未 push の仕掛り枝・並列 worker の worktree を巻き込まない（P1-1 対策）。
        track = upstream_track.get(branch, "")
        if (not args.branch or args.allow_squashed) and track != "[gone]":
            skipped.append(f"{branch} (未 push または追跡対象外: track={track or 'none'})")
            continue

        # 削除可否（マージ済み判定）を worktree 削除より先に行う
        merged = (
            _git(main_root, "merge-base", "--is-ancestor", branch, f"origin/{BASE_BRANCH}", check=False).returncode
            == 0
        )
        if not merged and not args.allow_squashed:
            skipped.append(f"{branch} (未マージ。Squash 済みなら --branch {branch} --allow-squashed を指定)")
            continue

        wt = wt_map.get(branch)
        if wt is not None:
            try:
                wt.relative_to(wt_root)
            except ValueError:
                skipped.append(f"{branch} (.tmp/worktrees 外のため保護)")
                continue
            if _git(wt, "status", "--porcelain").stdout.strip():
                skipped.append(f"{branch} (worktree に未コミット変更あり)")
                continue
            if not args.dry_run:
                _git(main_root, "worktree", "remove", str(wt))
            removed_worktrees.append(str(wt))

        if not args.dry_run:
            flag = "-d" if merged else "-D"
            _git(main_root, "branch", flag, branch)
        deleted_branches.append(branch)

    print(
        json.dumps(
            {
                "dry_run": args.dry_run,
                "updated_develop": updated_develop,
                "removed_worktrees": removed_worktrees,
                "deleted_branches": deleted_branches,
                "skipped": skipped,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="専用 GitHub App で ai/* PR を安全に扱う入口")
    parser.add_argument("--config-dir", type=Path, default=None, help="app.json / app.pem の置き場")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_auth = sub.add_parser("check-auth", help="App トークン発行と対象リポ権限の疎通を確認する")
    p_auth.set_defaults(func=_cmd_check_auth)

    p_start = sub.add_parser("start", help="ai/<slug> 枝と .tmp/worktrees/<slug> を作成する")
    p_start.add_argument("slug", help="作業名（ai/ 接頭辞は自動付与）")
    p_start.add_argument("--base", default=BASE_BRANCH, help="分岐元（既定 develop）")
    p_start.set_defaults(func=_cmd_start)

    p_submit = sub.add_parser("submit", help="現在の ai/* 枝を App 認証で push し PR 作成＋Auto-Merge 有効化する")
    p_submit.add_argument("--title", required=True, help="PR タイトル（Conventional Commits）")
    p_submit.add_argument("--summary", default="", help="Squash コミット本文および PR 要約（1〜3 行）")
    p_submit.add_argument("--cwd", default=None, help="対象の worktree パス")
    p_submit.add_argument("--no-auto-merge", action="store_true", help="Auto-Merge を有効化しない")
    p_submit.add_argument("--dry-run", action="store_true", help="push・PR 作成せず事前検査だけ実行する")
    p_submit.set_defaults(func=_cmd_submit)

    p_clean = sub.add_parser("cleanup", help="完了済み ai/* の worktree とローカル枝を片付け develop を更新する")
    p_clean.add_argument("--branch", default=None, help="特定の ai/* 枝だけ片付ける")
    p_clean.add_argument("--allow-squashed", action="store_true", help="リモートから消えた Squash 済み ai/* 枝の削除を許可する")
    p_clean.add_argument("--dry-run", action="store_true", help="削除せず対象を表示するだけ")
    p_clean.set_defaults(func=_cmd_cleanup)

    parsed = parser.parse_args(argv)
    try:
        return int(parsed.func(parsed))
    except AiPrError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
