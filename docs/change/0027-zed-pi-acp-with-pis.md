# CHG-0027: Zed の pi-acp から `pis`（フルガード）を使えるようにする

- **状態**: Exploring
- **更新日**: 2026-10-20
- **基準**: pi 1.3.0、`~/.local/share/ocs/pis.py`、pi-acp（svkozak/pi-acp の main、2026-10-20 時点）

## 目的と非目的

- 目的: Zed が ACP で呼ぶ pi を、素の `pi` ではなく `pis`（フルガード付き）にできるか確かめる。標準のサンドボックスは使わず `pis --no-sandbox` を前提にする
- 非目的: サンドボックス（Fence）の中での ACP。`pi-acp` の改造・公開。Orca の扱いは、段 6 の調査にとどめる（実装は [CHG-0020](0020-pi-migration.md) の段 5e・[CHG-0023](0023-guard-terminology.md) の続き）

用語: **pi-acp** は、Zed と ACP（Agent Client Protocol、stdio の JSON-RPC）で話し、`pi --mode rpc --no-themes` を子プロセスとして起動する橋渡し役の公開 npm パッケージ。**フルガード**は `pis` で効く判定器・伏字化など（[pi のガード](../spec/pi-guard.md)）。

## 実施計画

| 段 | 内容 | 状態 |
| --- | --- | --- |
| 1 | 下調べ: pi-acp の仕組みと、`pis --no-sandbox` の RPC 経路を調べる | 完了 |
| 2 | pi-acp のソースを読み、`extension_ui_request`（`setStatus`・`confirm`）の扱いと、起動コマンドの差し替え口を確かめる | 完了（2026-10-20） |
| 3 | 本物の pi-acp（`npx`）に ACP の `initialize`・`session/new`・`session/prompt` を手で送り、ラッパー経由で通るか確かめる（外部パッケージの取得と実行なので、実施前に利用者へ確認する） | 未着手 |
| 4 | 確認が要る操作の拒否と 5 分の期限が、pi-acp 経由でどう見えるか確かめる | 未着手 |
| 5 | Zed の実機で `agent_servers` を設定して通す。設定の置き場（chezmoi の管理）を決める | 未着手 |
| 6 | Orca の起動ボタンから `pis` を使えるかを調べる（Orca の設定の公開情報の調査。実機は未確認） | 調査済み（2026-10-20）。実機は未着手 |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

段 1 で分かったこと（2026-10-20、調べた範囲）:

- pi-acp は PATH 上の `pi` を `pi --mode rpc --no-themes` で起動する。README の環境変数は `PI_ACP_ENABLE_EMBEDDED_CONTEXT` だけで、起動コマンドを替える設定は無い。ソースの `spawn` は `piCommand` を受け取れる形だが、利用者の設定から渡せるかは未確認（[process.ts](https://raw.githubusercontent.com/svkozak/pi-acp/main/src/pi-rpc/process.ts)、[README](https://raw.githubusercontent.com/svkozak/pi-acp/main/README.md)）
- 別実装の [victor-software-house/pi-acp](https://github.com/victor-software-house/pi-acp) は pi を SDK で組み込み、子プロセスを起動しないので `pis` と合わない
- `pis --no-sandbox` は、フラグを足して `os.execvpe` で `pi` に置き換わる。残りの引数は末尾へそのまま渡るので `--mode rpc` も通る。stderr に 1 行出すが stdout は汚さない
- 実測: `pis --no-sandbox --mode rpc` に `get_state` を送ると RPC の応答が返った
- 実測: `/tmp/wrap/pi`（`PATH` から自分のディレクトリを外して `exec pis --no-sandbox "$@"` を呼ぶラッパー）を PATH の先頭に置き、`pi --mode rpc --no-themes` で呼んでも応答が返り、無限ループにならなかった。**起動に約 4 秒以上かかる**（4 秒で stdin を閉じると応答前に終了）
- 実測: フルガードの拡張が stdout に `extension_ui_request`（`setStatus` を 5 件ほど）を出す
- pi-acp は stdout の JSON でない行を、起動時の案内文として表示する（ソースの読みで、実機は未確認）

段 2 で分かったこと（2026-10-20、pi-acp の `src/acp/agent.ts`・`session.ts`・`src/pi-rpc/process.ts` の main を読んだ。実行はしていない）:

- **起動コマンドの差し替え口がある**: 環境変数 `PI_ACP_PI_COMMAND`（`agent.ts`）。README には載っていない。値は実行ファイル 1 つで、引数は pi-acp が `--mode rpc --no-themes` を付ける（`spawn(cmd, args)`）。`pis --no-sandbox` のような引数つきの文字列は渡せないので、`exec pis --no-sandbox "$@"` だけのラッパースクリプトを置いて、そのパスを渡す。Zed の `agent_servers.<名前>.env` に書ける
- **`extension_ui_request` の扱い**（`session.ts` の `handleExtensionUiRequest`）: `confirm`・`select` は ACP の許可ダイアログ（Yes / No）になる。`input`・`editor` は「未対応」と表示して取り消す。`notify` は会話にメッセージとして出る。`setStatus` などそれ以外は、取り消しの応答を返して無視する
- フルガードの拡張（`~/.config/pi/harness/index.ts`）が使う UI は `confirm`（確認）・`notify`（警告）・`setStatus`（状態表示）だけ。いずれも pi-acp が扱える。確認は Zed のダイアログに出るので、[5 分の期限](../spec/pi-guard.md#orcazed)に頼らず利用者が答えられる見込み（実機は未確認）

## 未解決点

- **Orca（段 6 の調査、2026-10-20）**: 公開情報の読みで、実機は未確認
  - Orca（stablyai/orca）は、Settings → Agents に、エージェントごとの起動コマンド・引数・環境変数の上書き（`agentCmdOverrides`・`agentDefaultArgs`・`agentDefaultEnv`）を持つ（[Issue #20552](https://github.com/stablyai/orca/issues/20552)）。pi の起動コマンドを `pis` に替えられる見込み。pi の派生（`omo`）を `agentCmdOverrides.pi = "omo"` で使い、状態表示・再開・プロンプトの事前入力が動いた報告がある（[Issue #28273](https://github.com/stablyai/orca/issues/28273)。ただし同じ報告で、`worker-start --agent pi` の起動待ち（`agent_readiness`）は、派生がターミナルのタイトルを変えると 60 秒で時間切れになる）
  - 独自のエージェントの定義（ラッパー・社内 CLI など）は [PR #2521](https://github.com/stablyai/orca/pull/2521)、`expectedProcess`（実行中のプロセス名で状態追跡する）は [Issue #18249](https://github.com/stablyai/orca/issues/18249) で提案中。取り込まれた版は未確認
  - Orca は pi の起動のたびに、状態表示の拡張 `~/.pi/agent/extensions/orca-agent-status.ts` を書き出す（[PR #17243](https://github.com/stablyai/orca/pull/17243) の記述）。起動した印（`ORCA_AGENT_LAUNCH_TOKEN` など）を状態の送信に付ける。`pis --no-sandbox` は、この拡張を `-e` で足す（`pis.py` の `orca_args`）ので、サンドボックス無しなら状態表示は動く見込み。**サンドボックスの中では、拡張を読まず、`TOKEN` を含む環境変数も落とす**ので、状態表示は出ない（[CHG-0023](0023-guard-terminology.md) に既知）
  - 未確認: 起動コマンドの上書きに引数（`--no-sandbox`）を足せるか。`pis` は `exec` で `pi` に置き換わるので、Orca が見るプロセス名・タイトルが変わらないか。ローカルの `~/.orca` には `agent-hooks` しか無く、設定は読めなかった（Orca が動くホストが別の可能性）

- `PI_ACP_PI_COMMAND` に渡したラッパーを、Zed の `env` 経由で実際に pi-acp が起動できるか。ラッパーを PATH に置く場合は、`pis` の中の `pi` を再帰で呼ばないよう PATH から自分を外す必要がある（上の実測のとおり。`PI_ACP_PI_COMMAND` に絶対パスを渡せば PATH を触らないので、その必要は無い見込み）
- Zed の許可ダイアログが、確認の本文（フルガードの `body`）をどう表示するか。実機でしか分からない
- 起動の遅さ（約 4 秒以上）が、pi-acp の起動処理（`get_state` の待ち）や Zed の接続で時間切れにならないか。未確認
- `-nbt -ne` が付くので、Zed の pi は素の `pi` とツール・拡張が変わる。`~/.pi/agent/mcp.json` にサーバがあると `pis` が起動を断る。pi-acp の `session-map.json` との相性は未確認
- 保留にしたものは無い

## 次の調査・実験

1. 段 3: 利用者の許可を得たうえで、一時ディレクトリへ pi-acp を取得して ACP を手で送る
2. 段 5: Zed の設定ファイルの置き場と、配る方法（chezmoi）を決める

## 評価基準

- 必須: Zed から会話でき、ツールの実行が `pis` のフルガードの判定を通る。確認が要る操作が、拒否または確認のどちらかで確実に終わる（永久に待たない）
- 望ましい: 起動が数秒で終わる。素の `pi` へ戻す手順が簡単。`pi-acp` を改造しない

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| A. PATH の先頭にラッパー `pi`（`pis --no-sandbox` を呼ぶ）を置く | 手元の RPC の試験で応答が返り、再帰も起きなかった | PATH の細工になる。ツールと拡張が素の `pi` と変わる | Zed の `env` で足せるか。起動の遅さ | 保留（B が使えれば要らない） | |
| B. `PI_ACP_PI_COMMAND` に、`exec pis --no-sandbox "$@"` のラッパーを渡す | 改造が要らない。PATH を触らない。確認は Zed のダイアログに出る（ソースの読み） | 環境変数は README に載っておらず、将来の版で変わりうる | Zed の `env` から渡して実際に起動できるか。起動の遅さ | 有望 | 段 3 |
| C. pi-acp を自前で直して起動コマンドを差し替える | 確実に差し替えられる | 保守が増える | | 未評価 | A・B が駄目なとき |
| D. SDK 組み込み版（victor-software-house/pi-acp） | 子プロセスの起動が無い | フルガードを通す方法が無い。公開元の信頼を審査していない | | 見送り（`pis` の包み方と合わない） | |
| E. 現状のまま素の `pi`（フルガード無し） | 今の運用で、利用者の判断済み（[pi のガード](../spec/pi-guard.md#起動)） | 守りが無い | | 現状 | |
| F. Orca の pi の起動コマンドを `pis`（`--no-sandbox` 付き）に上書きする | Orca の設定にある公開の機能。派生の起動の報告がある。拡張の読み込み処理は `pis` に済み | 起動コマンドに引数を足せるか未確認。`--no-sandbox` なので守りはフルガードだけ | 状態表示・プロセス名の判定が `pis` で壊れないか | 未評価 | 段 6 の実機 |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `docs/spec/pi-guard.md` の「Orca・Zed」 | Zed は素の `pi` → 通ったら Zed の設定と注意点を足す | 検証後に決める | 未適用 |

## 実装・検証

2026-10-20、実測（WSL、サンドボックス外のシェルでの試験）:

```sh
echo '{"id":"1","type":"get_state"}' | pis --no-sandbox --mode rpc
# → get_state の response（success:true）。先に extension_ui_request（setStatus）が出る
(printf '{"id":"1","type":"get_state"}\n'; sleep 9) | PATH=/tmp/wrap:$PATH pi --mode rpc --no-themes
# → response が 1 件。sleep 4 では 0 件（起動が間に合わない）
```

pi-acp 本体の実行、Zed の実機は未実施。

## 重要な更新

- 2026-10-20: 段 6（Orca）を調べた。公開情報では、Orca は起動コマンドの上書きを持ち、`pis --no-sandbox` なら状態表示の拡張も読まれる見込み。実機は未確認
- 2026-10-20: 段 2 を終えた。`PI_ACP_PI_COMMAND` で起動コマンドを差し替えられ、`confirm`・`notify`・`setStatus` も扱えると分かった。候補 B を有望、A を保留にした
- 2026-10-20: 起案。段 1（下調べと手元の RPC の試験）まで済み。pi-acp の実行は未実施
