# Docker の cold start 検証で直した障害

- **観測日**: 2026-09-26 〜 2026-09-27
- **対象**: `test/test.sh` の Docker ハーネス（`ubuntu2204` ほか）と GitHub Actions の
  e2e（`arm2404`）
- **一次情報**: このリポジトリの実行ログ（`.tmp/e2e/`）と各修正コミット。
  各節の日付は、その修正を `test/README.md` に記録したコミットの日付

ハーネスのモード・判定の契約と、未解決のものは
[テストと検証の仕組み](../../spec/testing.md) が正本。
ここには、`ubuntu2204` の `apply` と `update`（2 回の apply と残差分 0 件）が
通るまでに直したものの経緯だけを残す。

## 1. tmpfs の `noexec`（2026-09-26）

`$HOME` の tmpfs に既定で `noexec` が付き、**そこへ入れた実行ファイルが一切
起動できなかった**。uv / mise / AI CLI はすべて `$HOME` 配下に入るので、
cold start は必ず失敗する。しかも症状が紛らわしい。

```text
installing to /home/tester/.local/bin
everything's installed!
⚠️  uv を導入できませんでした          ← ファイルは -rwxr-xr-x で存在する
```

`test -x` は `access(2)` を使うため、`noexec` の上では権限ビットがあっても
false を返す。`compose.yaml` の `tmpfs: - /home/tester:exec,...` で解消した。
**これはハーネスの欠陥であってリポジトリの不具合ではなかった。**

## 2. `modify_` スクリプトが `python3` を解決できない（2026-09-26）

素の Ubuntu で apply すると `modify_` が全滅していた（残差分 16 件）。

```text
chezmoi: .claude/settings.json: exec: "python3": executable file not found in $PATH
```

順序の問題だった。`chezmoi init` が `[interpreters.py]` を焼く時点では
3.11 以上どころか `python3` すら無く、後から `run_before_005_python.sh.tmpl` が
uv で入れる Python は PATH に出ない。

固定パスの shim（`~/.local/bin/chezmoi-python3`）を挟んで解決した。
init 時に PATH 上で 3.11 以上が見つからなければ設定はこの shim を指し、
005 が毎 apply その実体へ張り直す（`run_before_` なので modify より先に走る）。
`python3` が 3.10 の Ubuntu 22.04 も同じ経路で救われる。

**実測で残差分 16 件 → 1 件**（残りはスクリプト 6 件で、これは diff に出るのが正常）。

## 3. `121_ubuntu.sh` が素の Ubuntu で exit 127（2026-09-26）

`xdg-user-dirs-update` は Desktop 版にしか無く、`set -eu` でスクリプトが止まり
以降の apt 導入が全て走らなかった。コマンドが無ければ整理を飛ばすようにした。

## 4. `.codex/config.toml` が 2 回目の apply まで安定しない（2026-09-27）

`modify_config.toml` は、既存ファイルに管理ブロックが無いと（新規・ユーザが先に
書いた設定）、その中身を `# chezmoi-managed:end` の直後へ改行なしで連結していた。
ユーザ設定の 1 行目がコメントに吸収され、2 回目の apply で元に戻る。
終端マーカーの後に常に改行を出し、ユーザ設定は空行を挟んでつなぐようにした。

## 5. `410_claude_mcp.sh` が `claude is not a mise bin` で失敗する（2026-09-27）

AI CLI を公式インストーラーでの導入へ切り替えた後も、410（Windows は 346）だけが
`mise which claude` で探していた。公式の導入先（`~/.local/bin/claude`）、
次に PATH の順に探すようにした。Windows 側は静的テストのみで、実機では未確認。

## 6. 2 回目の apply でも `.claude/settings.json` の差分が消えない（2026-09-27）

`generate.py` が `~/.claude/hooks/` 配下を起動する hook をすべて自分の物とみなし、
herdr が同じディレクトリに置く `herdr-agent-state.sh` の hook を apply のたびに消していた
（直後の `140` が足し直す）。所有権をスクリプト名（現役 + 撤去済み）で決めるようにした。
see [外部ツールとの共存](../../spec/agent-config-generation.md#外部ツールとの共存-orca--herdr)

## 7. init を通すモードで Pi 扱いの注入が消えていた（2026-09-27）

`IS_RASPI=1` の注入（`[data]` への `is_raspi = true` の追記）を init の**前**に
行っていたので、`place` / `apply` では `chezmoi init --force` が設定を作り直して
消していた。注入の確認も init の前だったため、`inject-is-raspi: SUCCESS` のまま
Pi 以外の経路を検証していた（i3 が入り zram-tools が入らないことで発覚）。
init を省く `update` 以外（`dryrun` / `place` / `apply`）はすべて影響を受けていた。
注入と確認を init の後へ移し、順序を `test/test_raspi_detection.py` で検査する。

## 8. 素の Linux で `111_microsoft.sh` が `Unable to locate package` で止まる（2026-09-27）

GitHub Actions の `arm2404` で発覚。111 は `apt-get update` をせずに前提パッケージ
（wget / gpg）を入れていたので、パッケージ一覧が空の機械では失敗していた。
一覧を更新する 121 より先に走る。`110_native/` は WSL と Pi では除外されるので、
手元の Docker では見えなかった。先に `apt-get update` するようにした。

## 9. Codex のトップレベルのキーが直前のテーブルに入る（2026-09-27）

ユーザ部分を管理ブロック（最後が `[windows]` や `[mcp_servers.*]`）の後ろへまとめて
足していたので、ユーザ部分のトップレベルのキー（`model = ...` など）が TOML 上
そのテーブルに属していた（`windows.model` になる）。

管理側をトップレベルのキー（`chezmoi-managed:start` 〜 `end`）とテーブル
（`chezmoi-managed:tables:start` 〜 `end`）の 2 ブロックに分け、ユーザ部分も
最初のテーブル見出し（行頭の `[`）の前後で分けて、キー同士・テーブル同士を
並べるようにした。旧形式（ブロック 1 つ）やファイル途中のブロックも除去できる。

残っている制約（未検証）は
[テストと検証の仕組み](../../spec/testing.md#未検証のまま残っているもの) に移した。

[調査記録一覧へ戻る](../index.md)
