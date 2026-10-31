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

## 記録 E5 — 全件検証の内訳と段階化の前提（2026-11-01）

### 問い

`verify:all` が重い。どこが重く、安い検査はどれだけ軽いか。段階化の設計（[CHG-0051](../../change/0051-verification-tiers.md)）の根拠にする。

### 結果

全件の `pytest test/ -n auto`（6187 件、11 件は Windows 固有で skip）: 壁時計 3 分 30 秒、user 2494 秒、sys 448 秒、CPU 約 1400%（約 14 コア）。
直前の `verify:all` 全体も、壁時計 3 分 30 秒前後だった。

- 試験ごとの経過時間の和（並列下で競合により膨らむので、相対比較にだけ使う）では、`pi` を実際に起動する 3 ファイルが半分を占める
  - `test_pi_harness` 35.8%（185 件）、`test_pi_actions_harness` 9.5%（57 件）、`test_pi_harness_extensions` 6.4%（28 件）。合計 51.8%
  - 上位 10 ファイルで 69.8%。件数が多い `test_check_bash_*` は 1 件が約 0.17 秒で、合計は 10% 前後
- 1 件で遅いもの: `test_decide` の hook 試験集との照合 34 秒、`test_model_eval` の自己試験 33 秒、`test_lint_templates` 22 秒
- 段階化で先に回す安い検査（単独実行）: ruff 0.13 秒、pre-commit 全件（commit 段）6.9 秒、同（pre-push 段）13.7 秒、
  `lint_docs.py` 0.15 秒、`test/test_verify.py` 1.7 秒、shellcheck（全 `*.sh`）2.6 秒。合計約 25 秒で、全件の約 12%
- 故意に長い行（E501）を足して全件を回すと、T0 の pre-commit が落ち、T2 を始めずに **23 秒**で止まった（段階化の前は約 3 分 30 秒後）

出典: 実行記録は `.tmp/keep/verify-redesign/`（非公開の作業置き場）。並列度ごとの壁時計は未測定。
