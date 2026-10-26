# Windows の task と guarded_task を統合しない理由

> `docs/spec/guard/pi-guard.md#二つの-task-を別物にしている理由` から移した記録。移設時点で再測定していない。

## 記録 — 観測日は各文に記載（移設 2026-10-26）

- **対象バージョン**: 各文に記載（pi 1.3.0 前後）
- **環境**: 各文に記載

### 問い

Windows の `task`（`subagents` 拡張）とフルガードの `guarded_task` を、なぜ統合しなかったか。

### 根拠

[調査 P3](pi-public-extensions-survey.md)（採点の訂正）。元の文のとおり。コードの行数は移設時点で再計測していない。

### 結果（元の文）

Windows の `task`（`subagents` 拡張。120 行）とフルガードの `guarded_task`（`registerTask` と `children.ts`。約 1,200 行）は、統合せず別物のままにしている（調査と判断は [調査 P3](../../research/agents/pi-public-extensions-survey.md)、採点の訂正）。

- **重なるのは約 50 行**（答えの取り出し・プロセスの起動と停止・役割一覧の整形・`promptSnippet`）。子の一覧 `globalThis.__piChildren` を `activity` が読む点だけが共有
- **子の実行方式が違う**: `subagents` は 1 回だけ実行する `--mode json -p`、`guarded_task` は常駐できる `--mode rpc`（`Job`。並列・背景・`keep`・`steer`・`abort`）。後者の子はハーネスを `-e` で読み、`PI_HARNESS_*` を前提にする
- **`Job` は Windows で使えない**（Unix のプロセスグループと `pi.cmd` に依る）。Windows の `task` の子はフルガード付きで出すが、`Job` を流用して shell を持つ役割まで出すと、Windows 実機で未検証の経路に判定なしの実行を載せることになる。だから `subagents` は読み取り役に限る
- **共通モジュールにしない**: ハーネスは `~/.config/pi/harness`、拡張は `~/.pi/agent/extensions` にあり、別の場所からの import は配置とサンドボックスの許可の点で脆い
- **ずれは試験で止める**: 宣言は同じ `[pi.agents]` から出る。名前・モデル・読み取り専用の役割の説明と指示が食い違わないことを `test_pi_subagents.py::test_declarations_stay_in_step_with_the_full_guard_agents` が確かめる（`plain_description` を宣言した役割だけ、意図して違う）

### 考察

現在の仕様は ../../spec/guard/pi-guard.md の該当節。ここの数値・日付は観測時点のもので、再測定していない。
