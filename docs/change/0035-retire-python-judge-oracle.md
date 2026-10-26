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
| `docs/spec/guard/pi-decide.md` | 「移植は途中」の古い記述 → 現状に合わせる | 後段と食い違う | 未適用 |

## 実装・検証

未着手。判定器に触るので、`review`・正解データの全件一致・全件検証を経る（既存の運用）。

## 重要な更新

- **2026-10-24**: 起票。[CHG-0033](0033-sandbox-build-value-assessment.md) の暫定の判定（部分的に置き換え＝縮小）の第 1 の項目として。依存の棚卸し（段 R0）を `explore` の子で行った。実行時に Python 版が走る経路は見つからなかった。

## 判定器の TS 移植の記録（旧 pi-decide.md から移設）

`docs/spec/guard/pi-decide.md#ts-版への移植` から移した記録。移設時点で再測定していない。冒頭の「移植は途中」「フルガードはまだ Python 版を呼んでいる」は移植中の記述で、後段の「切り替え」のとおり現在は切り替え済み（現行の仕様は pi-decide.md に残した）。件数・実測日は書かれた時点のもの（観測日: 2026-10-13 ほか）。

pi だけを使う前提で、判定器を TypeScript に移し、フルガードのプロセスの中で動かす計画（`docs/change/0020-pi-migration.md`）。
外部プロセスの起動をやめ、Windows の `python3` の壁と、判定のたびのプロセス起動の費用をなくす。
**移植は途中**で、フルガードはまだ Python 版（`decide.py`）を呼んでいる。

| 層 | 中身 | 状態 |
| --- | --- | --- |
| C | `decide.py` の入口・役割・ファイルの判定・bypass | 移植済み（`home/dot_config/pi/harness/judge/decide.ts`） |
| A（glob） | `command_policy.py` の設定の読み出しと glob 照合 | 移植済み（`judge/policy.ts`） |
| A（正規化） | `command_policy.py` の `normalize` / `find_match`（`shlex` 相当を含む。約 900 行） | 移植済み（`judge/normalize.ts`、Python 互換の部品は `judge/pystr.ts`）。部品ごとの正解データと 9,199 件が全件一致 |
| B | `bashrules/` の各検査（約 3,900 行）と `tables.toml` | 未着手 |
| 生成 | `common.toml` を JSON にして配る（TS は TOML を読まない） | 試験用の `golden/common.json` だけ。配布の生成は未着手 |

### 差分試験（正解データ）

Python 版の判定結果を正解として、TS 版との全件一致で進捗を測る。

- `scripts/agents/export_decide_golden.py`: `test_check_bash_*.py` のコマンド × 役割 × bypass、ファイルツール × パス、そのほかのツール、不正な入力の 6,311 件を `decide()` に流し、
  `test/agents/golden/decide_golden.jsonl`（応答）と `common.json`（描画した `common.toml` の JSON）に書く。パスは `${ROOT}` / `${HOME}` の記号で保存する。
  規則や判定器を変えたら引数なしで書き出し直す。`--check` は全件を作り直して比べる（約 1 分）
- `test/agents/test_decide_golden.py`: 正解データが Python 版と一致していること（一定間隔の標本）
- `test/agents/pi/judge_golden.mjs`: TS 版との差分。`node` の型除去で動く（22.18 以上）。`--bash` で bash も必須にする（移植の完了条件）
- `test/agents/test_pi_judge_ts.py`: 上を pytest から呼ぶ。いまは bash 以外が全件一致であることを必須にしている
- 部品ごとの正解データ: `scripts/agents/export_policy_golden.py` が、`shlex`・分割・正規化・置換と関数の抽出・`find_match`（deny / ask / allow の各一覧）の Python 版の出力を
  `golden/policy_golden.jsonl`（9,199 件）に書く。`test/agents/pi/policy_golden.mjs` が TS 版と突き合わせる（食い違ったときに部品を特定できる）。
  `test_pi_judge_ts.py` が全件一致を必須にし、`test_decide_golden.py` が正解データの鮮度を標本で見る

実測（2026-10-13）: 正規化の層（`shlex`・分割・正規化・照合）は、初回から部品ごとの正解データの 9,199 件が全件一致した
（複数セグメントへの展開 323 件、`shlex` のエラー 11 件、deny / ask / allow に当たる 373 件を含む）。
bash 以外（ファイル 1,081 件・そのほかのツール 16 件・不正な入力 6 件）は TS 版が初回から全件一致。bash は未移植（5,205 件が食い違い）。

### 判定が前の呼び出しに依存していた（修正済み）

正解データを作る過程で、**同じ入力でも、同じプロセスで前に何を判定したかで結果が変わる**ことが分かった。
`bashrules/_shared.py` の `_LITERAL_HEREDOC_BODIES`（引用付き heredoc の本文の記録）はモジュールのグローバルなリストで、
`split_heredoc_body` が積み、`check_pipe_to_shell` が「記録と同じ本文のセグメントを見送る」ために読む。どこでも消さないので、
`python3 - <<'PY'` の後に引用なしの `python3 - <<PY`（本文の `$(curl …)` が実行時に展開される）を判定すると、後者の検査が見送られた。

- hook（1 コマンド 1 プロセス）と、フルガードが呼ぶ `decide.py`（呼び出しごとに新しいプロセス）では起きない
- 起きるのは、同じプロセスで続けて判定したとき（試験、将来の常駐化・TS 版）。**TS へ移すときにこのグローバルな記録を写してはいけない**（判定ごとの状態にする）
- 対処: `decide()` が bash を判定する前にこの記録を空にする。試験 `test_decision_does_not_depend_on_earlier_calls` を足した。
  `test_decide` の hook との等価試験のドライバも、コマンドごとに空にした（以前は hook 側も同じ汚染を受けていて、両方が同じ誤りで一致していた）
- 正解データは、新しいプロセスで流した結果と一致することを標本（120 件）で確かめた

### 状態

層 B（`bashrules`）まで、**TS 版が Python 版の正解データと全件一致**している（`node test/agents/pi/judge_golden.mjs --bash`。
bash 5,208・file 1,081・invalid 6・other 16）。検査関数 32 種は `checks_golden.mjs` でも個別に一致する。

- 土台: `judge/pathutil.ts`・`context.ts`（`Ctx`）・`shellparse.ts`・`shared.ts`・`pystr.ts`・`normalize.ts`
- 検査: `sensitive.ts`・`http.ts`・`rules_exec.ts`・`rm.ts`・`bashpolicy.ts`（policy）・`rules_files.ts`・`rules_guard.ts`・`ghapi.ts`・`docker.ts`
- 登録簿と順序: `judge/checks.ts`（`CHECKS` と `DENY_NAMES` / `PATH_NAMES` / `ASK_NAMES`。順序は `bashrules/__init__.py` と同じ）
- bash の組み立て: `judge/bash.ts`（`makeBashDecider(tables)`。誘導・役割の shell_deny / shell_allow・skill_scripts）。`decide.ts` の `setBashDecider` へ差し込む
- 差分試験の約束:
  - 正解データは `None` を書かないので、**記録の無いコマンドは `None` のはず**という照合もしている（TS が誤って理由を返す＝誤検知を拾う）
  - 当たりが薄い検査は、手書きの入力（`export_checks_golden.py` の `EXTRA_*`）で厚くした。検査を足したら同じ流儀で入力を足す
  - `urlsplit` / `ipaddress` は CPython 3.13.11 の実装に合わせた（ブラケット前後の文字を拒否する検査を含む）。Python を上げたら `local_url` の正解データで確かめる
- 既知の差: `expandUser` は `~` と `~/` だけを展開する（Python は `~user` も解く）。正解データの範囲では差が出ていない

### 切り替え（済み）

フルガード（`harness/index.ts`）は、`python3 decide.py` を呼ぶ代わりに、同じプロセスで `judge/decide.ts` の `decide()` を呼ぶ。
bash は `setBashDecider(makeBashDecider(tables))` で差し込む。判定のたびに 0.1 秒ほどかかっていたプロセス起動が無くなった。

- 設定の渡し方: `generate.py` の `build_pi_harness` が、`rules.json` の `judge` に
  `common`（`common.toml` の `[bash]` / `[file]` / `[pi]`）と `tables`（`home/dot_config/pi/harness/judge/tables.toml`）を JSON で入れる。
  `chezmoi apply` のたびに作り直されるので、`common.toml` を編集して apply すれば TS の判定に届く
- 失敗は deny: `judge` が無い・壊れていれば、起動時に失敗する（ツールが無くなる）か、判定が `source: error` の deny になる
- 試験: `test_pi_harness.py` は実際の pi を TS の判定器で動かす（`judge/` を一緒に置く）。
  壊れた設定の試験は `rules["judge"]["common"] = {}`

### 次

- 撤去: Python 版（`decide.py`・`bashrules` の検査・`command_policy.py` の判定部分）を外す。Claude / Copilot の hook 設定は ADR-0017 の段で消す。
  それまでは、Python 版が正解データの出力元（`scripts/agents/export_*_golden.py`）なので残す。
  撤去のときは正解データを固定の入力として残し、`--check` の鮮度検査を外す
- `tables.toml` の置き場（移設済み）: `home/dot_config/pi/harness/judge/tables.toml`。TS 版が `rules.json` 経由で読む。
  Python 版の `tables.py` は、同じディレクトリ → リポジトリのソース → 配備先 `~/.config/pi/harness/judge/` の順に探す（Python 版を撤去するまでの橋渡し。
  Windows は `harness/` を配らないので、Windows の Python の hook は表を読めず fail-closed で止まる）
- 構文解析の堅牢化（`shellparse` を正式な構文解析に替える）は別の変更。差分試験を残したまま進める
