# 子エージェントが受け取る文脈（AGENTS.md）の実測

- **目的**: CHG-0059（親と子で文脈を分ける）の S0。受け渡しの分かれ道（(P) pi の文脈の一覧を hook で変換する / (N) `-nc` で止めて選別結果を `--append-system-prompt` に入れる）を、実測で決められるようにする
- **対象**: pi 1.4.0、2026-11-02。偽のモデル（`test/agents/pi/faux.ts` の `FAUX_DUMP_PROMPT=1`）が受け取った最終の system prompt を、全文で見た。Linux（WSL）。Windows 実機は未実施
- **読めなかったもの**: pi 本体の docs とソース（作業ツリーの外。読み取りが承認されない）。結果はすべて挙動の実験による。内部の実装の理由は推測しない

## 結論

- **(P) は可能**: `before_agent_start` の `event.systemPromptOptions.contextFiles`（`{path, content}` の配列）を、ハンドラが**その場で書き換える**と、最終の prompt に反映された（本文の差し替え・要素を減らす・空にする、の 3 通り）。`-nc` は要らず、出典（path）と順序が保たれる
- **(N) も可能**: `-nc` は AGENTS.md / CLAUDE.md を**全部**止める（作業先・祖先・agent 置き場）。`--append-system-prompt` は `-nc` でも効く。ただし作業先の規約も消えるので、祖先の探索と順序を自前で再現する必要がある
- 推奨は (P)。文脈ファイルが path つきで一覧になって届くので、出典ごとに全文継承か抜粋かを決められる

## 手順（再現できる形）

- 作業用ディレクトリ: `up/work`（cwd）・`up`（親）・`agent`（`PI_CODING_AGENT_DIR`）。各場所に目印入りの `AGENTS.md` と `CLAUDE.md`
- 起動: `pi --no-session --model faux/spike -nbt -ne -e faux.ts -e dump_options.ts -p go`（`FAUX_DUMP_PROMPT=1`）。`-nc`・`--append-system-prompt`・`--approve`・`DUMP_OPTIONS_MUTATE=<キー>:<操作>[:<目印>]` を足して比較
- `dump_options.ts`（試験専用の拡張）は、`DUMP_OPTIONS_FILE` へキー一覧と各値の形（型・長さ。本文は書かない）を書き、`DUMP_OPTIONS_MUTATE` で書き換える
- 子の prompt の全文は、`FAUX_CHILD_DUMP_FILE=<パス>`（`PI_HARNESS_CHILD=1` のときだけ）でファイルへ書く
- 注意: 作業用ディレクトリが、このリポジトリの `.tmp/` の下だと、リポジトリの `AGENTS.md` が祖先として混ざる（それ自体が「祖先も入る」の証拠）

## P1 — `-nc` の範囲

| 目印を置いた場所 | 既定 | `-nc` |
| --- | --- | --- |
| 作業先の `AGENTS.md`（`CLAUDE.md` も同居） | 入る | **入らない** |
| 親ディレクトリの `AGENTS.md` | 入る | **入らない** |
| agent 置き場（`PI_CODING_AGENT_DIR`）の `AGENTS.md` | 入る | **入らない** |
| `CLAUDE.md` だけの作業先・agent 置き場 | 入る | **入らない** |
| 同じ場所に `AGENTS.md` と `CLAUDE.md` の両方 | `AGENTS.md` だけ入る | 入らない |
| agent 置き場の `SYSTEM.md` | 効く（既定の prompt の本体を**置き換える**） | **効く**（`-nc` は止めない） |
| 作業先の `.pi/SYSTEM.md` | **入らない**（`--no-approve` でも同じ） | — |
| 作業先の `.pi/SYSTEM.md`（`--approve` 付き） | 効く | 未測定 |

- 子の起動引数（`spawnChild`）は `--no-approve`。したがって子は作業先の `.pi/SYSTEM.md` を読まない（この実験の範囲では）
- 順序（P3 と同じ実験）: 既定の本体 → `--append-system-prompt` → 文脈ファイル（agent 置き場 → 祖先の外側から内側 → 作業先）→ スキル一覧

## P2 — `systemPromptOptions` の形と書き換え

- `event` のキー: `images`・`messageType`・`prompt`・`systemPrompt`・`systemPromptOptions`・`type`
- `systemPromptOptions` のキー: `appendSystemPrompt`（文字列）・`contextFiles`・`customPrompt`・`cwd`・`forceSystemPrompt`・`hiddenTools`・`promptGuidelines`・`sections`・`selectedTools`・`skills`・`toolGuidelines`・`toolSnippets`
- `contextFiles` の要素: `{path: string, content: string}`。上の実験では 4 件（agent 置き場・祖先 2・作業先の順）
- 書き換え（ハンドラが `options.contextFiles` を代入）の結果:

| 操作 | 最終の prompt |
| --- | --- |
| 全件の `content` を目印に差し替え | 4 件とも目印になり、元の目印は消える |
| 先頭の 1 件だけ残す | agent 置き場の分だけが残る |
| 空配列 | 文脈ファイルが 1 件も入らない |

- 既存の前例（`home/dot_config/pi/harness/index.ts` の `skills` 周り）と同じく、ハンドラは**返り値でなく、渡されたオブジェクトの書き換え**で効いた

## P3 — `--append-system-prompt` と文脈の並び

- `--append-system-prompt MARK` の位置は、文脈ファイルの**前**（行 26 → 文脈は 33 以降）。`-nc` を付けても append は残る
- 子の prompt の中の位置（下の P4）も同じ: 前置き + 役割の system は、agent 置き場の `AGENTS.md` より前

## P4 — 今の子（`spawnChild`）の特性化

- 作業先の `AGENTS.md` と agent 置き場の `AGENTS.md` の**両方**が、全文で入る（4 役とも。`test/agents/test_pi_child_prompt.py`）
- 前置き（`CHILD_PREAMBLE`）は役割の system の直前（空行 1 つ）。2 つで 1 つのかたまりが `--append-system-prompt` に入り、位置は文脈ファイルより前
- 役割ごとの prompt の長さ（この試験の環境。目印だけの AGENTS.md 2 つ + 祖先のリポジトリの AGENTS.md を含む。バイト）:

| 役割 | 全長 | 前置きの先頭位置 | agent 置き場の AGENTS.md | 作業先の AGENTS.md |
| --- | --- | --- | --- | --- |
| explore | 20808 | 3467 | 5871 | 17268 |
| review | 21583 | 3467 | 6646 | 18043 |
| plan | 20265 | 2635 | 5328 | 16725 |
| worker | 22248 | 4328 | 7311 | 18708 |

- 前置きの位置の違いは、役割ごとのツール一覧の長さの違い（既定の本体の長さ）による

## X-2 — pre-commit の hook ごとの対象

未追跡の `*.py`・`*.md`（使い捨て。測定後に削除）に `uv run pre-commit run --files ...`:

| hook | 結果 |
| --- | --- |
| Detect hardcoded secrets（gitleaks） | 実行（Passed）。ただし **`--files` と無関係**（`pass_filenames: false`・`--staged`） |
| Python Lint | 実行（Passed） |
| Markdown Lint | 実行（Passed） |
| Warn when staged content lacks a verify:all stamp | 実行（Passed） |
| Fix end of files・Trim trailing whitespace | 実行（Passed） |
| YAML Lint・Skill frontmatter・Rendered common.toml・Lint docs index・Check YAML・Check TOML | 対象の拡張子でなく、skip（no files） |

- gitleaks が何を見るか:

| 状態 | 結果 |
| --- | --- |
| 未追跡・未ステージ（偽の GitHub トークン形式の文字列入り） | `--staged` で `0 commits scanned / no leaks found`。**漏れを見ない**（`gitleaks dir` では 1 件検出） |
| ステージ済み | **未測定**（この役割では `git add` ができない）。`--staged` はインデックスを読むので見るはずだが、実測していない |

- つまり、`--files` に新規ファイルを渡しても、**秘密検出の保証にはならない**（lint 系だけが実際にファイルを検査する）。ステージしてから回すか、`gitleaks dir <パス>` を併用する

## 複数ターン・複数拡張・優先関係（S4 の前提）

子の文脈をハンドラが書き換える方式（S4）で、書き換えが**どこまで保たれるか**を測った。試験は `test/agents/test_pi_child_persist.py`（固定した事実はここの表の「試験」列）。

- **結論**: 子の起動時に 1 回だけ書き換える方式では**足りない**。`before_agent_start` は**ユーザーメッセージごと**に呼ばれ、`contextFiles` は**毎回元の内容で新しく**渡される（前回の書き換えは残らない）。したがって、ハンドラは**毎回**書き換える（同じ変換を毎回かける）必要がある。一方、同じメッセージ内のツールの往復では書き換えは残り、`/reload` の後も、拡張が作り直されて次のターンから同じハンドラが効く
- 手順: `pi --no-session --model faux/spike -nbt -ne -e builtin:mcp -e <harness> -e dump_options.ts -e faux.ts --mode json -p <メッセージ...>`。`DUMP_OPTIONS_CALLS_FILE` にハンドラの呼び出しごとの記録を書く。最終の prompt は `FAUX_DUMP_PROMPT=1` で assistant の本文として json の出力から取る。2 つ目の拡張は `dump_options.ts` を別名（`dump_options_b.ts`）へコピーして `-e` で足し、`DUMP_OPTIONS_MUTATE__<名前>` で別々に指定する
- `dump_options.ts` の追加: `add` 操作（要素を足す）、`DUMP_OPTIONS_RETURN_PROMPT`（`{systemPrompt}` を返す）、`DUMP_OPTIONS_CALLS_FILE`（呼び出しごとの観測。本文は書かず path・長さ・先頭 24 字）

| 番号 | 問い | 結果 | 試験 |
| --- | --- | --- | --- |
| Q1 | 複数メッセージ（3 回）で毎回呼ばれるか。前回の書き換えは残るか | 毎回呼ばれる（seq 1,2,3）。渡される `contextFiles` は**毎回元の内容**。書き換えは**毎回の最終 prompt に反映**（毎回かけた場合） | あり |
| Q2 | ツールの往復で 2 回目以降の LLM 呼び出しに残るか | `before_agent_start` は 1 回だけ。LLM 呼び出し（turn）は 2 回で、どちらの `ctx.getSystemPrompt()` にも書き換えが残る。**2 回目の最終 prompt そのもの**は faux から見えない（FAUX_DUMP_PROMPT は最初の呼び出しだけ）ので、`ctx.getSystemPrompt()` での確認 | あり（この範囲） |
| Q3 | 2 つの拡張が両方 `contextFiles` を書き換える | (a) 実行の順は `-e` の順 (b) 後の拡張は**前の書き換えを見る**（`before` が前の拡張の結果）(c) 最終の prompt は**後の拡張の結果**。順序を逆にすると勝つ側も逆になる | あり |
| Q4 | `{systemPrompt}` を返したときの優先 | **返り値が勝つ**（最終の prompt は返した文字列そのもの。文脈も既定の本体も出ない）。同じハンドラで書き換えても、先の拡張が返して後の拡張が書き換えても、返り値のまま。後の拡張が返せば、その値 | あり |
| Q5 | `/reload` の後の次のターン | `ctx.reload()` を呼ぶコマンド（`faux.ts` の `spike-reload`）を print/json モードのメッセージ `/spike-reload` で呼べた。拡張は作り直され（`seq` が 1 に戻る）、次のターンにも書き換えが効いた | あり |
| Q6 | 空の `contextFiles`（`-nc`）に足すと出るか | **出る**。`-nc` のとき `before` は空で、足した `{path, content}` だけが prompt の `<project_context>` に出る。`-nc` なしでは既存の文脈の**末尾**に足される | あり |

- 補足（試験にしていない観測）: `event.systemPrompt` は、同じイベントの中では**書き換え前**の prompt（最初のハンドラが見る長さ 16861）。書き換えの後に呼ばれる 2 つ目のハンドラの `event.systemPrompt` は、1 つ目の書き換えを反映した長さ（10619）だった。つまり pi は contextFiles の書き換えのたびに prompt を作り直して次へ渡す。ただし返り値 `{systemPrompt}` の後は作り直されない（上の Q4）
- 補足: 祖先ディレクトリの `AGENTS.md` も `contextFiles` に入る（試験の作業先が本リポジトリの内側にあるときに実際に入った）。試験は path の末尾（`/proj/AGENTS.md`）で選び、件数に依存しない
- 反例先行: 期待を逆にした試験（2 回目は元に戻る / 往復で 2 回呼ばれる / 先の拡張が勝つ / 書き換えが勝つ / `-nc` で足した要素が出ない）が、実際に落ちることを確かめてから正しい期待にした

## 分からないこと

- 往復の 2 回目の LLM 呼び出しの**最終 prompt 本文**での反映（`ctx.getSystemPrompt()` でしか確認していない。`before_provider_request` の `payload` は faux では取れなかった）
- 対話モード（TUI）・RPC での `/reload`（print/json モードだけ測った）、`/reload` 中の拡張の読み直しでハンドラの状態が失われること以外の副作用
- 3 つ以上の拡張、`{systemPrompt}` と contextFiles を両方使う拡張が混ざるときの順序の組み合わせ（2 つだけ測った）
- 作業先の `.pi/SYSTEM.md`（`--approve`）と `-nc` の組み合わせ
- ステージ済みのときの gitleaks の実測
- Windows の素の `pi`（別の `subagents` 拡張が子を起動する経路）での同じ挙動
