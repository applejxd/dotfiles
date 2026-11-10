# 設定のスキーマ（`.agents/config/experiments.json`）

リポジトリの根からの相対パスで置く。`exp init` が雛形を書く。誤りは理由つきで終了コード 2 になる。

```json
{
  "version": 1,
  "primary": "score",
  "metrics": {"score": {"direction": "max", "unit": ""}},
  "run": {"cmd": "python3 bench.py --seed {seed} --split {split}", "cwd": ".", "timeout_s": 3600, "env": {}},
  "parse": {"mode": "json-last-line"},
  "seeds": [0, 1, 2, 3, 4],
  "splits": {"tune": {}, "val": {"max_runs": 10}},
  "resources": {"lock": ".exp/lock"},
  "ledger": ".exp/ledger.jsonl"
}
```

| キー | 必須 | 内容 |
| --- | --- | --- |
| `version` | はい | `1` |
| `primary` | はい | 主指標の名前。`metrics` にあること。`compare` の既定の指標 |
| `metrics` | はい | 指標名 → `direction`（`max` か `min`。良い向き）と `unit`（任意） |
| `run.cmd` | はい | 1 回の実行のコマンド。**シェルを通さない**（`shlex.split` で語に分け、その後に置換）。`{seed}`・`{split}`・`{label}` と、`--set key=val` の `{key}` を置換する。値に空白や `;`・`$()` があっても 1 語のまま渡る（シェルの機能〈パイプ・リダイレクト〉は使えない。要るなら、それを行うスクリプトを呼ぶ） |
| `run.cwd` | | 実行する場所（リポジトリの根から。既定 `.`） |
| `run.timeout_s` | | 1 回の上限秒（既定 3600）。超えると失敗として記録 |
| `run.env` | | 追加の環境変数（文字列→文字列） |
| `parse.mode` | はい | `json-last-line`: 標準出力の最後の JSON オブジェクトの行から、指標名→数値を読む。`regex`: 指標ごとの正規表現の最初の捕捉群を数値にする |
| `parse.regex` | regex のとき | 指標名 → 正規表現（捕捉群が 1 つ以上）。`primary` を含むこと |
| `seeds` | | `--seeds` を省いたときの seed（既定 `[0]`） |
| `splits` | | 分割名 → `{"max_runs": N}`（任意）。定義があるとき、未定義の名前は拒否。`max_runs` は、その分割の ledger の既存の件数（失敗も数える）と今回の件数の合計の上限。超えると実行を拒否し、`--allow-overrun` で解除（その行に `overrun: true`） |
| `resources.lock` | | ロックファイル。実行中は排他（`O_EXCL`。pid と時刻を書く）。pid が死んでいるか 24 時間より古い残骸は回収する。ほかの実行が持っていたら終了コード 2 |
| `ledger` | | 記録先の JSONL（既定 `.exp/ledger.jsonl`） |

## ledger の 1 行

`id`（連番）・`ts`・`label`・`split`・`seed`・`params`（`--set`）・`metrics`・`wall_s`・`exit_code`・`ok`・
`git`（`commit`・`dirty`・`diff_hash`。git が無ければ `null`。`.exp` 配下の変更は diff に含めない）・`note`・
`cmd`（置換後の argv）・`stdout_tail`（最後の 20 行）。加えて、失敗時は `error`・`stderr_tail`、予算超過のときは `overrun`。

失敗（終了コード非 0・timeout・主指標が取れない）も `ok: false` で記録し、比較・順位からは除外する（件数を表示）。
壊れた行は、読むときに警告を出して読み飛ばす。`id` は同時に複数のプロセスで書くと重なりうる（ロックで 1 本にする前提）。
