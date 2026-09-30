"""隔離実行用の DB の用意と、集計用の書き出し。

seed:   実 DB を読み取り専用で複製し、セッション由来の表を空にする。資格情報 (credential) は残る
export: 複製した DB から session_v2 と session_message だけを JSON に書き出す (資格情報は含めない)
see scripts/model-eval/README.md
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SESSION_TABLES = ("session_message", "session_v2", "session_inbox", "session_pending", "event")


def seed(src: Path, dst: Path, allow_no_credential: bool = False) -> None:
    if not src.is_file():
        sys.exit(f"実 DB が無い: {src}")
    dst.unlink(missing_ok=True)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    s.backup(d)
    s.close()
    for table in SESSION_TABLES:
        d.execute(f"delete from {table}")
    d.commit()
    if not allow_no_credential and d.execute("select count(*) from credential").fetchone()[0] == 0:
        d.close()
        dst.unlink()
        sys.exit("credential が空。OpenCode で認証してから実行する")
    d.close()


def export(db: Path, out: Path) -> None:
    d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    d.row_factory = sqlite3.Row
    data = {
        "session_v2": [dict(r) for r in d.execute("select * from session_v2")],
        "session_message": [
            {**dict(r), "data": json.loads(r["data"])}
            for r in d.execute("select session_id, type, seq, data from session_message "
                               "order by session_id, seq")
        ],
    }
    d.close()
    out.write_text(json.dumps(data, ensure_ascii=False))


def main() -> None:
    p = argparse.ArgumentParser(description="隔離実行用の DB の用意と書き出し")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="実 DB を読み取り専用で複製し、資格情報だけ残す")
    s.add_argument("src", type=Path)
    s.add_argument("dst", type=Path)
    s.add_argument("--allow-no-credential", action="store_true",
                   help="credential が空でも止めない (資格情報を DB の外から取るプロバイダ向け)")
    e = sub.add_parser("export", help="session_v2 と session_message を JSON へ書き出す")
    e.add_argument("db", type=Path)
    e.add_argument("out", type=Path)
    a = p.parse_args()
    if a.cmd == "seed":
        seed(a.src, a.dst, a.allow_no_credential)
    else:
        export(a.db, a.out)


if __name__ == "__main__":
    main()
