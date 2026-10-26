# 開発ガイドの実測メモ

`docs/spec/development.md` から移した記録（gitleaks のプレビルド、検証の所要時間、hook の stage、Windows Sandbox の実測）。
移設時点で再測定していない。

> **現行の仕様**: [開発ガイド](../../spec/development.md)。検証コマンドの正本は [AGENTS.md の検証表](../../../AGENTS.md#検証)。

## 記録 E1 — 全件検証の所要時間（2026-10-22）

- **観測日**: 2026-10-22（元の文の日付）

### 問い

全件の pytest にどのくらいかかるか。

### 結果（元の文）

> 全件の pytest は約 3,700 件で約 9 分かかる（2026-10-22 実測 556 秒）。

## 記録 E2 — hook の所要時間と stage の判断（2026-10-23）

- **観測日**: 2026-10-23（元の文の日付）

### 問い

どの hook を commit に置き、どれを push に置くか。

### 結果（元の文）

| stage | hook | 所要時間 (2026-10-23 実測) |
| --- | --- | --- |
| commit | gitleaks・YAML・ruff・frontmatter・`common-toml-local`・docs の索引・`verify-stamp`・空白など | 各 0.5 秒以下 |
| commit | Markdown lint | 1.7 秒 |
| push | `lint-templates-local` (テンプレートの描画 lint) | 9.9 秒 |
| push | `raspi-regression-local` (Raspberry Pi の回帰テスト) | 3.0 秒 |
| push | `verify-stamp-push` (印の警告) | 0.5 秒以下 |

> 理由: commit のたびに 10 秒以上待たせると `--no-verify` を誘う。push は回数が少なく、
> まとめて検査する場所に向く。利用者の判断 (2026-10-23)

## 記録 E3 — gitleaks のプレビルドの失敗（2026-09-26）

- **観測日**: 2026-09-26（元の文の日付）。詳細は [Raspberry Pi の OOM と SSH 停止](raspi-oom-ssh-freeze.md)

### 結果（元の文）

> Raspberry Pi 4（RAM 3.7GB、swap 0）ではこのビルドでメモリが尽き、SSH も応答しなくなって電源の抜き差しが要った（2026-09-26）。

## 記録 E4 — Windows Sandbox の実行ポリシーの実測

- **観測日**: 日付は元の文に無い

### 結果（元の文）

> `launch.ps1` が `-ExecutionPolicy Bypass` で `guest.ps1` を起動すると、子の `chezmoi` にも `PSExecutionPolicyPreference=Bypass` が引き継がれる（実測）。
> README の `Set-ExecutionPolicy` の行は、`Restricted` のままだと `chezmoi` が `.ps1` の run スクリプトを実行できないために必要（実測）だが、この検証はその行が無くても通る。
