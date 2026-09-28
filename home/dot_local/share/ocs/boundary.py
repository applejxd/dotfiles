"""境界の組み立てと、追加の許可の承認。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from . import backup
from .common import HOME, _now, die

RULES = HOME / ".config/opencode/guide-plugin/rules.json"
REQUEST_REL = ".opencode/sandbox.toml"
TRUST = HOME / ".local/state/opencode-sandbox/trusted.json"
REQUEST_KEYS = ("read", "write", "network_allow")


def load_boundary() -> dict:
    if not RULES.is_file():
        die(f"{RULES} が無い", "chezmoi apply で生成する")
    try:
        sandbox = json.loads(RULES.read_text(encoding="utf-8")).get("sandbox")
    except json.JSONDecodeError as e:
        die(f"{RULES} を読めない: {e}")
    if not sandbox:
        die(
            "境界の設定が出力されていない",
            "srt が入っていないか enabled=false。このマシンは非対応",
        )
    for key in ("runtime_path", "base", "config_dir"):
        if not sandbox.get(key):
            die(f"境界の設定に {key} が無い")
    return sandbox


def project_extras(request: dict | None) -> dict:
    """この起動ディレクトリに足す追加の許可を返す。

    **宣言が無ければ追加はゼロ**（共通の許可だけで動く）。宣言は「機密でない
    パスを開けたい」ときにだけ要る。

    宣言は ``<起動ディレクトリ>/.opencode/sandbox.toml`` に置く。複数 PC で
    使えるようリポジトリと一緒に移動させるため。

    ★リポジトリは「要求」できるが「付与」はできない。ここは要求を読むだけで、
      実際に許可するかは :func:`ensure_trusted` の承認を通す。敵対的な
      リポジトリが自分で ``~/.ssh`` を開けられる構造にしないこと
      (OpenCode 自身の permission が実際にその穴を持っている。
      docs/research/opencode/permission/gaps.md 第 5 節)。
    ★``request`` は**呼び出し側が一度だけ読んだもの**を受け取る。ここで
      読み直すと、承認した内容と適用する内容が別物になりうる (間に書き換え
      られると、承認していない許可が境界へ入る)。
    """
    if request is None:
        return {"read": [], "write": [], "network_allow": []}
    return request["extras"]


def git_common_dir(workspace: Path) -> Path | None:
    """linked worktree のとき、共有 ``.git`` の実体を返す。

    worktree の ``.git`` は「外のディレクトリを指すファイル」なので、
    起動ディレクトリ以下しか開いていないと **``git status`` すら通らない**
    (``fatal: not a git repository``。実測)。

    ★ここは境界の外で走る。``/usr/bin/git`` を絶対パスで呼び、利用者の ``GIT_*`` を落とす
      (``GIT_DIR`` を通すと、別のリポジトリが書けるようになる)。
    """
    done = subprocess.run(
        ["/usr/bin/git", "-C", str(workspace), "rev-parse", "--path-format=absolute",
         "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
        env=backup.git_env(),
    )
    if done.returncode != 0:
        return None
    common = Path(done.stdout.strip())
    if not common.is_dir():
        return None
    # 通常のリポジトリ (共有 .git が起動ディレクトリの中) なら足すものは無い
    if common == workspace or workspace in common.parents:
        return None
    return common


def reject_unsafe_workspace(sandbox: dict, workspace: Path) -> None:
    """``denyRead`` を打ち消してしまう起動ディレクトリを拒否する。

    ★R3: ``allowRead`` は ``denyRead`` に勝つ。起動ディレクトリは無条件に
    ``allowRead`` へ入るので、``denyRead`` の項目**そのもの**か、その**祖先**で
    起動すると、その deny が丸ごと無効になる。``cd ~ && ocs`` でホーム全体が
    読み書き可能になり、``~/.ssh`` まで見えるのがこれ (実測で再現)。

    子孫での起動は安全なので許す (``/tmp/x`` は ``/tmp`` の deny を壊さない)。
    """
    denied = [Path(p) for p in sandbox["base"].get("deny_read", [])]
    for target in denied:
        if workspace == target or target.is_relative_to(workspace):
            die(
                f"保護対象を打ち消す場所で起動しようとした: {workspace}",
                f"ここで起動すると {target} の denyRead が無効になる。"
                "作業対象のディレクトリへ cd してから起動する。",
            )


def build_boundary(sandbox: dict, workspace: Path, request: dict | None = None) -> dict:
    """起動ディレクトリを書き込み可能領域として境界を組み立てる。

    **起動ディレクトリ以下は無条件に許可する。** どこで起動するかは利用者の
    責務。Claude Code の sandbox と同じ考え方。
    """
    base = sandbox["base"]
    extras = project_extras(request)
    read = [*base.get("read", []), *extras.get("read", [])]
    write = [*base.get("write", []), *extras.get("write", [])]
    protected = [str(workspace / rel) for rel in base.get("protected", [])]
    network = dict(base["network"])
    if extras.get("network_allow"):
        network["allowedDomains"] = [
            *network.get("allowedDomains", []),
            *extras["network_allow"],
        ]
    common = git_common_dir(workspace)
    if common:
        # commit / branch 操作に共有 .git への書き込みが要る。
        # ★hooks と config は除く。ここへ書けると**ホストで実行される
        #   コード**を仕込めてしまう (Claude Code も同じ 2 つを denyWrite にする)。
        write = [*write, str(common)]
        protected = [*protected, str(common / "hooks"), str(common / "config")]
    return {
        "network": network,
        "filesystem": {
            "denyRead": base.get("deny_read", []),
            # ★R1: ワークスペースは allowRead と allowWrite の両方へ完全一致で
            #   入れる。祖先を allowRead に載せると書き込みが無効化される。
            "allowRead": _uniq([str(workspace), *read]),
            "allowWrite": _uniq([str(workspace), *write]),
            "denyWrite": protected,
        },
    }


def _uniq(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


def _resolve_requested(value: str, workspace: Path) -> str:
    """要求されたパスを実際に開く形へ直す。

    ``~`` を展開し、相対パスは起動ディレクトリ基準にする。展開後の形を
    承認画面に出すこと。人が承認するのは「何が開くか」であって、
    書かれた文字列ではない。
    """
    expanded = Path(value).expanduser()
    if not expanded.is_absolute():
        expanded = workspace / expanded
    return str(expanded)


def read_request(workspace: Path) -> dict | None:
    """``.opencode/sandbox.toml`` の要求を読む。無ければ ``None``。

    **ここは読むだけ。許可はしない。**
    """
    path = workspace / REQUEST_REL
    if not path.is_file():
        return None
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - 3.11 未満
        die(f"{path} を読めない (tomllib が無い)", "Python 3.11 以降が要る")
    raw = path.read_bytes()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        die(f"{path} を解釈できない: {exc}")
    unknown = sorted(set(data) - set(REQUEST_KEYS))
    if unknown:
        die(f"{path} に知らない項目がある: {', '.join(unknown)}")
    extras: dict[str, list[str]] = {}
    for key in REQUEST_KEYS:
        values = data.get(key) or []
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            die(f"{path} の {key} は文字列の配列でなければならない")
        extras[key] = [
            v if key == "network_allow" else _resolve_requested(v, workspace)
            for v in values
        ]
    if not any(extras.values()):
        return None
    return {
        "path": path,
        # ★要求そのもののハッシュ。1 文字でも変われば承認をやり直す。
        "digest": hashlib.sha256(raw).hexdigest(),
        "extras": extras,
    }


def load_trust() -> dict:
    if not TRUST.is_file():
        return {}
    try:
        data = json.loads(TRUST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 壊れていたら承認なしとして扱う (安全側)
        return {}
    return data if isinstance(data, dict) else {}


def save_trust(workspace: Path, digest: str) -> None:
    TRUST.parent.mkdir(parents=True, exist_ok=True)
    record = load_trust()
    record[str(workspace)] = {"digest": digest, "approved": _now()}
    TRUST.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    TRUST.chmod(0o600)


def describe_request(workspace: Path, request: dict) -> str:
    lines = [
        "このリポジトリは境界の外への追加の許可を要求しています。",
        f"  {request['path']}",
        "",
    ]
    labels = {"read": "読める", "write": "書ける", "network_allow": "通信"}
    for key, label in labels.items():
        values = request["extras"][key]
        lines.append(f"  {label:4}: {', '.join(values) if values else '(なし)'}")
    lines += [
        "",
        f"  起動ディレクトリ ({workspace}) 以下は元から読み書きできます。",
        "  ここに挙がっているのは、それ以外に開くものです。",
    ]
    return "\n".join(lines)


def ensure_trusted(workspace: Path, assume_yes: bool, request: dict | None) -> None:
    """要求を承認済みにする。承認できなければ**起動しない**。

    ★承認の記録は境界の外 (``~/.local/state``) に置く。内側から書けると
      自分で自分を承認できてしまう。
    ★マシンごとの記録なので、別 PC では改めて承認が要る。宣言だけが
      リポジトリと一緒に移動する。
    ★``request`` は**呼び出し側が一度だけ読んだもの**を受け取る。承認する
      内容と境界へ入る内容が同一であることを、同じ辞書を使うことで保証する。
    """
    if request is None:
        return
    known = load_trust().get(str(workspace))
    if isinstance(known, dict) and known.get("digest") == request["digest"]:
        return

    print(describe_request(workspace, request), file=sys.stderr)
    if isinstance(known, dict):
        print("\n  ★ 前回の承認から内容が変わっています。", file=sys.stderr)
    if assume_yes:
        save_trust(workspace, request["digest"])
        print("  --trust が指定されたので承認しました。", file=sys.stderr)
        return
    if not sys.stdin.isatty():
        die(
            "追加の許可が承認されていない",
            "対話できないので承認を求められない。--trust を付けるか端末から起動する",
        )
    try:
        answer = input("\n許可しますか? [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        die("追加の許可を承認しなかった", f"要求を見直すなら {request['path']}")
    save_trust(workspace, request["digest"])


def workspace_paths(sandbox: dict, workspace: Path) -> dict[str, str]:
    """安全網と DB の置き場。起動ディレクトリごとに分かれる。"""
    return {
        key: str(workspace / rel) for key, rel in (sandbox.get("paths") or {}).items()
    }
