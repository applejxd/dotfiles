#!/bin/bash

set -euo pipefail

# OpenCode を隔離環境で実行する。
#
# 実環境のセッション DB (~/.local/share/opencode/opencode.db) を汚さずに
# permission や plugin の挙動を試すための入口。
#
# ★XDG_CONFIG_HOME / XDG_DATA_HOME / HOME は差し替えてはいけない。
#   OpenCode は config dir の決定に XDG_CONFIG_HOME を使わず、認証情報は
#   セッション DB の credential テーブルにあるため、どれを差し替えても
#   「Model unavailable」か認証失敗になる。
# see docs/research/opencode-test-isolation.md
#
# Usage:
#   mise run opencode:probe -- '<prompt>'
#   OPENCODE_PROBE_CONFIG=<dir> mise run opencode:probe -- '<prompt>'
#
# OPENCODE_PROBE_CONFIG を渡すと global config も隔離する。
#
# ★渡さない場合は OPENCODE_CONFIG_DIR を **明示的に外す**。環境に値が残って
#   いると黙って継承してしまい、試験結果が呼び出し元の状態に左右される
#   (Orca 経由のセッションは opencode.json を持たない overlay を指している)。

REAL_DB="${HOME}/.local/share/opencode/opencode.db"
WORKDIR="${OPENCODE_PROBE_DIR:-/tmp/opencode/probe}"
SEED_DB="${WORKDIR}/seed.db"
MODEL="${OPENCODE_PROBE_MODEL:-github-copilot/claude-opus-5}"

if [ "$#" -eq 0 ]; then
  echo "usage: mise run opencode:probe -- '<prompt>'" >&2
  exit 2
fi

if [ ! -f "${REAL_DB}" ]; then
  echo "実 DB が無い: ${REAL_DB}" >&2
  echo "OpenCode を一度起動して認証を通してから再実行する。" >&2
  exit 1
fi

mkdir -p "${WORKDIR}"

# 認証 (credential) だけ引き継いで履歴を空にした DB を作る。
# 種が古いと認証に失敗するので毎回作り直す。
python3 - "${REAL_DB}" "${SEED_DB}" <<'PY'
import sqlite3
import sys

real, seed = sys.argv[1], sys.argv[2]
src = sqlite3.connect(f"file:{real}?mode=ro", uri=True)
dst = sqlite3.connect(seed)
src.backup(dst)
# セッション由来のものだけ消す。credential / account は残す。
for table in ("session_message", "session_v2", "session_inbox", "session_pending", "event"):
    dst.execute(f"delete from {table}")  # noqa: S608 - 固定の識別子のみ
dst.commit()
dst.execute("vacuum")
if dst.execute("select count(*) from credential").fetchone()[0] == 0:
    sys.exit("credential が空になった。認証が引き継げていない")
dst.close()
PY

export OPENCODE_DB="${SEED_DB}"
if [ -n "${OPENCODE_PROBE_CONFIG:-}" ]; then
  export OPENCODE_CONFIG_DIR="${OPENCODE_PROBE_CONFIG}"
else
  unset OPENCODE_CONFIG_DIR
fi

echo "OPENCODE_DB=${OPENCODE_DB}" >&2
echo "OPENCODE_CONFIG_DIR=${OPENCODE_CONFIG_DIR:-(既定: ~/.config/opencode)}" >&2

exec opencode run --standalone --log-level error --model "${MODEL}" "$@"
