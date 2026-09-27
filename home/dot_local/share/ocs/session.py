"""隔離用 DB の用意と、隔離セッションの操作。"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from .common import HOME, OPENCODE, die, fail

# 隔離用 DB へ引き継ぐもの。migration を消すとスキーマ管理が壊れる。
DB_KEEP = ("credential", "account", "account_state", "control_account", "migration")


def seed_db(db: Path) -> None:
    """隔離用 DB を作る。資格情報と migration だけ引き継ぐ。

    ホストの DB を共有すると他プロジェクトの会話が境界内へ入る。

    ★**ホストの DB をワークスペースへ複製しない。** 以前は
      ``src.backup(dst)`` で丸ごと写してから要らないテーブルを削除して
      いたが、削除前の全会話がワークスペース内に存在する時間帯があった。
      さらに途中で落ちると ``db.exists()`` が真になり、**未削除の DB を
      恒久的に再利用**してしまう。
      いまはスキーマだけ写し、``DB_KEEP`` の行だけを入れる。落ちた場合も
      ワークスペースに残るのはホストのデータを含まない不完全な DB になる。
    ★書き途中を ``db.exists()`` に拾わせないため、**別名で作ってから
      rename** する。rename は同一ファイルシステム上で原子的。
    """
    if db.exists():
        return
    source = HOME / ".local/share/opencode/opencode.db"
    if not source.is_file():
        die(f"元の DB が無い: {source}", "一度 opencode を起動して認証する")
    db.parent.mkdir(parents=True, exist_ok=True)
    staging = db.with_name(db.name + ".building")
    staging.unlink(missing_ok=True)

    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        schema = [
            (name, sql)
            for name, sql in src.execute(
                "select name, sql from sqlite_master"
                " where sql is not null and name not like 'sqlite_%'"
            )
        ]
        dst = sqlite3.connect(str(staging))
        try:
            for _, sql in schema:
                dst.execute(sql)
            for table in DB_KEEP:
                if not any(name == table for name, _ in schema):
                    continue
                rows = list(src.execute(f'select * from "{table}"'))
                if not rows:
                    continue
                marks = ",".join("?" * len(rows[0]))
                dst.executemany(f'insert into "{table}" values ({marks})', rows)
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()

    staging.replace(db)
    print(f"隔離用 DB を作った: {db}", file=sys.stderr)


def handoff_session(workspace: Path, session_id: str) -> int:
    """隔離セッションをホストの DB へ移す。

    移したあとは、OpenCode が終了時に表示する ``opencode -s <ID>`` が
    **そのまま動く**。``session import`` は ID を保つ（実測）。

    ★DB を共有せずに済ませる。隔離用 DB をホストから覗く仕組みは無く、
      共有すると他プロジェクトの会話が境界内へ入る。必要なものだけ移送する。
    ★書き出す JSON は**ワークスペースの外**へ置く。境界内から書ける場所に
      置くと、取り込む前に内容を差し替えられる。
    """
    db = workspace / ".opencode-sandbox" / "opencode.db"
    if not db.is_file():
        fail(
            "セッションを移送できない",
            f"隔離用 DB が無い: {db}",
            "このディレクトリで ocs を起動したことがない。",
        )
    staging = HOME / ".local/state/opencode-sandbox"
    staging.mkdir(parents=True, exist_ok=True)
    os.chmod(staging, 0o700)

    with tempfile.TemporaryDirectory(dir=str(staging)) as work:
        dump = Path(work) / "session.json"
        export_env = dict(os.environ)
        export_env["OPENCODE_DB"] = str(db)
        with dump.open("wb") as out:
            exported = subprocess.run(
                [str(OPENCODE), "session", "export", session_id, "--standalone"],
                stdout=out,
                env=export_env,
                check=False,
            )
        if exported.returncode != 0 or dump.stat().st_size == 0:
            fail(
                "セッションを移送できない",
                f"隔離セッションを書き出せない: {session_id}",
                "ID を確かめる: ocs --list-sessions",
            )

        # ★取り込み先はホストの DB。OPENCODE_DB を落とし、--standalone も
        #   付けない (付けないと常駐サービス = ホスト DB が応答する)。
        import_env = dict(os.environ)
        import_env.pop("OPENCODE_DB", None)
        imported = subprocess.run(
            [
                str(OPENCODE),
                "session",
                "import",
                str(dump),
                "--directory",
                str(workspace),
            ],
            env=import_env,
            check=False,
        )
    if imported.returncode != 0:
        fail("セッションを移送できない", f"ホストの DB へ取り込めない: {session_id}")
    print(f"\n  境界の外から再開できます:  opencode -s {session_id}", file=sys.stderr)
    return 0


def list_isolated_sessions(workspace: Path) -> int:
    """隔離用 DB のセッションを並べる。``--handoff`` に渡す ID を選ぶため。"""
    db = workspace / ".opencode-sandbox" / "opencode.db"
    if not db.is_file():
        fail(
            "セッションを並べられない",
            f"隔離用 DB が無い: {db}",
            "このディレクトリで ocs を起動したことがない。",
        )
    env = dict(os.environ)
    env["OPENCODE_DB"] = str(db)
    return subprocess.run(
        [str(OPENCODE), "session", "list", "--standalone"], env=env, check=False
    ).returncode
