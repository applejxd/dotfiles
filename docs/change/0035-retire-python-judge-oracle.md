# CHG-0035: 判定器の Python 版（オラクル）を撤去して、二重保守を解消する

- **状態**: Exploring
- **更新日**: 2026-10-24
- **基準**: [ADR-0017](../adr/0017-pi-only-and-ts-judge.md) 決定 1・2（Python 版は、TS 版との全件一致が確認できたら外す）。コミット `d0f9358`

## 目的と非目的

**目的**: 判定器の **Python 版**（約 4,975 行。TS 版の移植の正解＝オラクルとして残している）を撤去し、**同じ規則を 2 つの言語で保守する**費用をなくす。[CHG-0033](0033-sandbox-build-value-assessment.md) の調査で、2026-10-10 以降の Python 版に触れる 8 コミットのうち 6 件が、TS 版と同時の修正だった。

**非目的**:

- TS 版の判定の挙動を変えない（撤去前後で、判定結果が全件同じ）
- Claude Code・Copilot CLI・Codex・OpenCode を、再び判定器の対象にする（ADR-0017 の「見直す条件」。別の案件）
- 今回は、撤去の設計と起票まで。実装は、設計を `review` に見せた後

## 受入条件（実装前の期待動作）

1. TS 版の判定結果が、撤去の前後で**同じ**（正解データ 3 種のすべての行。現在は `decide` 6,516 行、`policy` 9,844 行、`checks` 14,640 行）
2. Python 版が実行時に走る経路が**無い**ことを確かめてから外す（判定の hook は登録を撤去済み。ただし、配布済みのファイルが `~/.claude/hooks/` に残る）
3. 正解データは、固定の入力として残す。TS 版に新しい規則・ケースを足す手順を、Python 版なしで行える（正解データの書き出し元が TS 版になる、または手書きの期待値）
4. Python 版にしか無い試験のうち、TS 版の挙動を固定する価値があるものは、TS 側へ移す。移さないものは、理由を記録する
5. `scripts/verify.py` の選択規則、CI の `paths`、文書（ADR・仕様）が、撤去後の構成と一致する
6. 撤去後も `mise run verify:all` が通る。所要時間の変化を記録する

## 実施計画

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 段 R0 | 何が Python 版に依存しているか分からない | 依存の棚卸し（`explore` の子） | 完了（「現在地」） |
| 段 R1 | ADR-0017 の撤去条件「実機での観察の後」の定義が無い | 「実機での観察」を、測れる条件に決める（例: `pis` を一定期間使って、判定の退行の報告が無い）。**利用者の判断** | 未着手 |
| 段 R2 | 正解データを、Python 版なしでどう保つか | (a) 凍結（現在の正解データを固定の入力にし、鮮度検査を外す。TS を直したら、TS が書き出す）、(b) TS 版から書き出す新しい仕組み、のどちらか。設計を `review` に見せる | 未着手 |
| 段 R3 | 失われる試験の扱い | Python 版にしか無い試験の一覧から、移す・捨てるを決める | 未着手 |
| 段 R4 | 撤去の実装 | 順に、(1) 配布の停止（`~/.claude/hooks` の判定 hook）、(2) 書き出しスクリプトと鮮度検査の整理、(3) 試験の移行、(4) Python 版の削除、(5) `verify.py`・CI・文書 | 未着手 |
| 段 R5 | 方針と文書が食い違う | ADR-0017 を部分改定し、`pi-decide.md` の古い記述を直す | 未着手 |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

`explore` の子が棚卸しした結果（2026-10-24）。確かめた行は「確認済み」、それ以外は子の抜き書き。

**実行時に Python 版が走る経路は、見つからなかった**:

- `pi` のハーネスは Python の判定器を呼ばない（`harness/*.ts` の `python3` は `landlock_exec.py` 用だけ）。判定は TS
- Claude・Copilot の判定 hook は `[retired_hooks]` へ移し、登録していない（確認済み: `common.toml.tmpl:2138`）。生成する hook は `markdownlint.sh` と `format-file.sh` だけ
- **ただし、判定 hook のファイル自体は、chezmoi の source として今も配布される**（`home/dot_claude/hooks/` の `executable_check_bash.py`、`executable_check_file_read.py`、`executable_decide.py`、`executable_redirect-tmp.py`、`lib/` 配下。確認済み: `git ls-files`）。Codex・OpenCode から呼ぶ記述は見つからなかった。生成器が他の CLI の設定を今も出すかは、未確認

**依存するもの**:

| 種類 | 内容 |
| --- | --- |
| 本体（Python） | hook 3 本（`check_bash`・`check_file_read`・`decide`）、`redirect-tmp.py`、`lib/decide.py`、`lib/policy_loader.py`、`lib/bashrules/`（12 ファイル） |
| 書き出し | `scripts/agents/export_{decide,policy,checks}_golden.py`。3 本とも Python 版を呼ぶ。入力は、`export_checks_golden.py` の手書きの配列（`EXTRA_*`）と、`test_check_bash_*.py` の `parametrize` から集めたコマンド。**TS 側に書き出し相当は無い**（`test/agents/pi/*.mjs` は読む側のみ） |
| 試験 | Python 版を直接動かす試験が 10 ファイル（子の数え。確認済み: 名前のパターン一致で 13 ファイルが `git ls-files` にあり、正解データの鮮度を見る `test_decide_golden.py` などを含むかで数え方が違う）。`test_check_bash_{shell,sensitive,file_ops,http_github,config}.py`（`def test_` の行数 50・31・33・22・40）、`test_command_policy.py`（約 40）、`test_decide.py`（約 32）、`test_check_file_read.py`（27）、`test_preflight.py`（15）、`test_redirect_tmp.py`（14）、`test_shellparse.py`（7）、`test_bashrules_tables.py`（5） |
| TS との一致を見る試験 | `test_pi_judge_ts.py`（TS が正解データと一致するか。3 本）。`test_decide_golden.py`（正解データの鮮度を Python 版で見る側） |
| 設定 | `scripts/verify.py` の `_HOOK_TESTS`（62〜73 行付近）と規則 3 箇所、`.github/workflows/windows.yml` の `paths` |
| 文書 | ADR 0002・0004・0005・0006・0007・0013・0017、`pi-decide.md`、`agent-command-policy.md`、`agent-config-generation.md`、`web-search.md`、`pi-guard.md`、`.agents/skills/pi-extension-dev/` |

**撤去の条件の記述**: ADR-0017 決定 2「移植が全件一致するまで正解として残し、**一致したら外す**」。決定 1 は「Python 版の判定器本体の撤去は、**実機での観察の後**」。**「実機での観察」の定義は、ADR に無い**。`pi-decide.md` の「次」は、撤去時に正解データを固定の入力として残し、`--check` の鮮度検査を外す、としている。

**文書の食い違い（確かめた事実）**: `pi-decide.md` の「TS 版への移植」の冒頭は「移植は途中」「フルガードはまだ Python 版を呼ぶ」と読めるが、後段の「状態」「切り替え（済み）」は完了している。撤去の際に直す。

**未確認**: parametrize 展開後の実際のケース数、`.pre-commit-config.yaml` と mise タスクの中身、`scripts/preflight.py` の `--judge claude`（既定）の使われ方、生成器が他の CLI の設定を出すか、`test_pi_boundary.py` と `test_pi_harness.py` が TS の判定器に触れる範囲。

## 未解決点

1. **「実機での観察」の定義**（段 R1）。撤去を急ぐ理由と、退行を見逃す危険のバランス。**利用者の判断が要る**
2. **正解データの保ち方**（段 R2）。凍結なら、TS の挙動を意図して変えるとき、正解データを手で直すか、TS から書き出す仕組みを足すかの設計が要る。書き出しの入力（`EXTRA_*` の手書きの配列と、`test_check_bash_*` の `parametrize`）の置き場も、Python 試験を消すと失われる
3. **`test_check_bash_*`（約 176 本）の扱い**。hook を実行する形の試験で、1,000 件余りのコマンドを通す。入力は正解データに入っているが、TS 版が同じ入力を直接検証する試験は `test_pi_judge_ts.py` のみ。**再開条件**: 段 R3
4. **他の CLI の設定の生成**（`generate.py`）が Python 版の hook に依存するか。依存するなら、撤去と生成器の整理を同時に扱う
5. **正解データの書き出しスクリプトの Windows の扱い**（`windows.yml` の `paths`）

## 次の調査・実験

1. 段 R1 の定義を利用者に尋ねる
2. `scripts/preflight.py`、`.pre-commit-config.yaml`、`generate.py` の hook 生成を読んで、未確認を埋める（`explore` の子）
3. 段 R2 の 2 案を、`review` に見せる

## 評価基準

**必須**: 受入条件 1〜6。**判断の原則**: サンクコストを使わない。撤去の費用と、二重保守を続ける費用（直近 2 週間で 6 コミット）を比べる（[CHG-0033](0033-sandbox-build-value-assessment.md)）。結果を見て基準を変えたら、「重要な更新」に残す。

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| A: 正解データを凍結して Python 版を撤去 | 二重保守が消える。ADR-0017 の計画どおり。実行時の経路が見つからない | TS の挙動を意図して変えるとき、正解データの更新手順が要る。Python 単体の試験が失われる | 段 R2・R3 | **有望（暫定）** | 設計を `review` へ |
| B: TS 版から正解データを書き出す仕組みを作って撤去 | 正解データの更新が自動 | 書き出しの新規実装。TS が正解データを作ると、自己参照になり、退行を検出する力が弱まる | — | 保留（A の更新手順が重いと分かったとき） | — |
| C: 現状維持（Python 版を残す） | 撤去の作業が無い。退行を二重に検出する | 二重保守が続く（2 週間で 6 コミット）。実行時に使われない | — | 見送り（再開条件: 他の CLI を再び判定器の対象にするとき） | — |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| [ADR-0017](../adr/0017-pi-only-and-ts-judge.md) 決定 1・2 | 撤去は実機での観察の後 → 観察の定義と撤去の時期を明記し、部分改定 | 定義が無い | 未適用 |
| `docs/spec/pi-decide.md` | 「移植は途中」の古い記述 → 現状に合わせる | 後段と食い違う | 未適用 |

## 実装・検証

未着手。判定器に触るので、`review`・正解データの全件一致・全件検証を経る（既存の運用）。

## 重要な更新

- **2026-10-24**: 起票。[CHG-0033](0033-sandbox-build-value-assessment.md) の暫定の判定（部分的に置き換え＝縮小）の第 1 の項目として。依存の棚卸し（段 R0）を `explore` の子で行った。実行時に Python 版が走る経路は見つからなかった。
