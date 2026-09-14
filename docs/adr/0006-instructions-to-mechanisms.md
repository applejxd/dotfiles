# エージェントへの指示を減らし、強制は機構へ寄せる

- **ステータス**: Accepted
- **日付**: 2026-09-14
- **決定者**: applejxd

## コンテキスト

エージェントへの指示は 2 系統ある。

| 系統 | ファイル | 適用範囲 |
| --- | --- | --- |
| 個人用カスタム指示 | `home/dot_claude/CLAUDE.md`、`home/dot_codex/AGENTS.md`、`home/dot_copilot/copilot-instructions.md` | 全リポジトリ |
| リポジトリ規約 | リポジトリ直下の `AGENTS.md` | このリポジトリ |

どちらも全ターンのコンテキストに載る。棚卸ししたところ、`AGENTS.md` の
7 節 62 行のうち大半が次のどれかだった。

- **モデルが自力で分かる**: Tech Stack、ディレクトリ構成、
  「既存ファイルの流儀を優先し、不要な形式変更は避ける」
- **CLI の既定動作と重複**: 「サブディレクトリに別の `AGENTS.md` がある場合は、
  より近いものを優先する」
- **機構が既に強制している**: 「秘密情報をログや出力に含めない」
  （`check_secret_env_echo` が deny）、「作業範囲はリポジトリ内に限定する」
  （sandbox が deny-by-default で強制）
- **内容が無い**: 「ブランチ運用はこのリポジトリの実運用に合わせる」

指示が増えるほど、本当に必要な行（検証コマンド、`chezmoi re-add`、
PowerShell の BOM）が埋もれる。

Python ツールの指定にはもう 1 つ問題があった。個人用カスタム指示の
「Python で依存管理ツールが決まっていないリポジトリでは `uv` / `uvx` を使う」は
**指示でしかない**。読み飛ばされれば `pip install` が実行される。
一方、同じ内容は既に機構側にもある。

- Claude Code / Copilot CLI: `check_bash.py` の `check_pip_redirect` が
  `pip3` / `python3 -m pip` / `uvx pip` / `cd foo && pip` まで正規化して deny し、
  `_pip_suggestion()` が `uv add` などの代替案を返す
- Gemini CLI: `home/dot_gemini/policies/python.toml` が `pip` / `pip3` を deny
- Codex CLI: **何も無い**

## 検討した選択肢

### 選択肢 1: 現状維持

- **利点**: 変更のリスクがない
- **欠点**: 冗長な指示が残り続け、Codex の穴も塞がらない

### 選択肢 2: 指示をすべて消してモデルの判断に委ねる

- **利点**: コンテキストが最小になる
- **欠点**: 検証コマンド（`uv run --with pywinpty --no-project pytest ...`）や
  PowerShell の BOM のように、**探索しても分からない/高くつく**情報まで失う。
  実際 BOM が無いと日本語コメントが次行を無警告で飲み込むという症状は、
  テストを回すまで表面化しない

### 選択肢 3: 「機構で強制できるか」で指示を仕分け、残りだけ書く

各行を次の 3 つに分類する。

1. 機構（hook / rules / policies / sandbox）で強制できる → 機構へ移して指示から消す
2. モデルが自力で到達できる → 消す
3. どちらでもない（発見コストが高い事実、ユーザーの好み、行動の約束）→ 残す

- **利点**: 残った行がすべて「消すと壊れる行」になる。
  強制したいものは読み飛ばされなくなる
- **欠点**: CLI ごとに機構が違うため、移す先を CLI ごとに用意する必要がある

## 決定事項

**選択肢 3 を採用する。**

### 1. Python ツールの強制は機構へ一本化する

個人用カスタム指示から「環境の前提」節を削除し、全 CLI に deny を用意する。

| CLI | 機構 | 実体 |
| --- | --- | --- |
| Claude Code | hook | `check_bash.py` の `check_pip_redirect`（`common.toml` の deny にも `pip` / `pip3`） |
| Copilot CLI | hook | 同上（`~/.copilot/hooks/from-claude.json` 経由） |
| Gemini CLI | policies | `home/dot_gemini/policies/python.toml` |
| Codex CLI | rules | `home/dot_codex/rules/python.rules`（本 ADR で新設） |

deny のメッセージに代替案（`uv add` / `uvx` / `uv pip ...`）を含めるので、
止めるだけでなく指示と同じ誘導ができる。指示より強く、かつ
「pip を打とうとした瞬間」にだけコンテキストを消費する。

判定軸は「周囲の Python 環境を書き換えるか」。`uv pip ...` は uv の
サブコマンドなので通し、`python script.py` や `python -c` は依存管理では
ないので **deny にしない**（`common.toml` の方針どおり未掲載にして
LLM 判定へ委ねる）。

### 2. 指示に残すのは 3 種類だけにする

- **発見コストが高い事実**: 検証コマンド、`chezmoi add` / `re-add`、
  `run_once_` の番号体系、`.ps1` の UTF-8 BOM、`SKILL.md` frontmatter の引用符、
  `common.toml` が単一ソースであること
- **ユーザーの好み**: 日本語で説明する、Conventional Commits、
  `git commit` の前に承認を取る
- **機構で表現できない行動の約束**: 拒否されたときに迂回せず停止する、
  完了報告の前に検証してその出力を示す

「迂回せず停止する」は hook では表現できない。hook は個々のコマンドを
止められるが、**等価だが表層の違う形で再試行する**という振る舞いは
止められないため（ADR-0004 参照）。

## 完了条件

- [x] 直下の `AGENTS.md` を 62 行 7 節から 42 行 2 節へ削減し、
      Tech Stack / ディレクトリ構成 / 一般論を落とす
- [x] 個人用カスタム指示 3 本から「環境の前提」節を削除する
- [x] `home/dot_codex/rules/python.rules` を新設し、Codex の穴を塞ぐ
- [x] この ADR と `docs/adr/index.md` を更新する

## 結果

### ポジティブな結果

- 直下の `AGENTS.md` から一般論が消え、残った行がすべて
  「知らないと壊れる」内容になった
- Python ツールの指定が 4 CLI すべてで機構による deny になり、
  読み飛ばしで `pip install` が通る経路が無くなった
- 指示の重複（同じ内容を `AGENTS.md` と個人用カスタム指示の両方に書く）が
  解消した

### ネガティブな結果

- 機構が CLI ごとに違うため、同じ意図を 3 箇所
  （`common.toml` + `policies/python.toml` + `rules/python.rules`）に書く必要が
  残る。新しい deny を足すときは 3 箇所とも更新する
- `AGENTS.md` から構成の説明が消えたので、初見のエージェントは
  `docs/index.md` を 1 回余分に読む

### 中立的な結果

- 「モデルは賢いから指示は要らない」は半分正しい。
  一般論は不要だが、**この環境でしか成り立たない事実**（BOM、番号体系、
  検証コマンド）は書かないと分からない。仕分けの基準はモデルの賢さではなく
  「探索で到達できるか」と「機構で強制できるか」だった

## 関連 ADR

- [ADR-0004](0004-hook-check-semantic-axis.md): hook の判定軸。
  本 ADR の「強制は機構へ寄せる」は、その機構が誤検知しないことを前提にしている
- [ADR-0001](0001-external-tool-config-coexistence.md): 外部ツールが書き込む
  設定領域との共存。生成物を直接編集しない方針は `AGENTS.md` にも残した
