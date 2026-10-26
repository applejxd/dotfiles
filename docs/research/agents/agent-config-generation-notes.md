# AI CLI 設定の生成に関する経緯・実測の記録

`docs/spec/agent-config-generation.md` から移した記録。移設時点で再測定していない。
元の文を、書かれた時点のままここへ置く（日付・版・件数は当時のもの）。現行の仕様は
[AI CLI 設定の生成と所有権](../../spec/agent-config-generation.md)にある。

- **観測日**: 各節の元の文に書かれた日付（2026-08〜2026-10）。日付が無いものは不明
- **対象**: Claude Code / Copilot CLI / OpenCode V2（v2.0.12〜2.0.14）/ pi
- **根拠**: 元の文にある記録へのリンク・コマンド（各節に再掲）

## 記録 N1 — MCP の生成先（`docs/spec/agent-config-generation.md#mcp-サーバ`）

### 問い

pi の MCP は Windows でどこへ登録するか。

### 結果（元の文）

- 表の旧「pi（Windows）」行: `~/.config/pi/harness/rules.json` の `mcp`。Unix と同じ（2026-10-26。Windows にもフルガードを載せたので、`mcp.json` へ書く経路は廃止した）
- **`deepwiki` は 2026-09-25 に外した。** `agentcore-websearch` は全機に配る（2026-10-26。使うかは実行時に決まる。下の「AgentCore Web Search」）。
- AgentCore の表の「対象」行: **全機に配る**（2026-10-26。会社 PC で Copilot を使うようになったので、`llm-provider` では切らない）。

## 記録 N2 — 作業ツリーの外の読み取り・スキルのスクリプト（`#作業ツリーの外の読み取り` / `#スキルのスクリプト`）

### 結果（元の文）

- 作業ツリーの中のパスは resource が相対パスになるので、`~/.local/share/chezmoi/*` の `edit` の `ask` は、このリポジトリで作業するときの編集には当たらない（絶対パスで渡しても相対に直る。実測）
- `external_directory` の確認は出ない（shell は引数に書いた外のパスから外部ディレクトリを推定しなかった。`ls <外のパス>` でも同じ。実測）
- **runner に `uv run --no-project python` を使わない。** 作業ツリーの `.python-version` に実行ファイルのパスが書いてあると、それを起動する（実測）。`python3` は uv の設定探索を通らないが、`PATH` の解決（mise の shim・venv）で作業ツリーに従う余地はある（OpenCode の shell での解決先は未確認）。`--no-config` や Python の明示で避けられた実測もあり、uv 一般が危険という意味ではない
- `--save <パス>` を `ask` で外そうとしても、`'--'save`・`$X`・argparse の省略形（`--sa`）で当たらなくなる（実測）
- `git ls-files` や `git check-ignore` は `.git/config` の `core.fsmonitor` を起動する（実測。`git status` / `git diff` を shell の allow に載せない理由と同じ）
- コマンド置換（`$(…)` / `` `…` ``）は scanner が中のコマンドを別の resource として取り出し、それぞれ照合する。中身が allow でなければ全体が確認になる（実測）
- away-shift: `snapshot` は…**隔離ではない**（[CHG-0030](../../change/0030-away-shift-on-pi.md) の 2026-10-26）。許可の期待値は `test_decide.py` の `test_away_shift_scripts_allow_only_the_listed_subcommands` が固定している（2026-10-22 に全件通過）。実際の pis（TS 版）での挙動は未確認

## 記録 N3 — bypass の子の起動で確認が大量に出た事例（`#bypass-から呼べる子エージェント`）

### 結果（元の文）

- 子は親が `bypass` でも自分の規則で動き、確認が自動で通るのは `bypass_agents` に載ったものだけ。承認制の子や一覧に無い子を起動すると、編集やシェルのたびに確認が出て無確認の前提が崩れる（2026-10-08 に、修正前の `explore` を並べて起動して確認が大量に出た）。
- **deny した子は `subagent` ツールの一覧から消える**（実測）。
- 実測（全体の deny だけで build からは `Permission denied: subagent`、bypass からは起動できる、子からの入れ子は不可。build に個別の `task = "allow"` があると全体の deny は上書きされ、plugin の deny でも、個別の規則の最後に置いた deny でも止まる）は [Bypass モードの調査 6 章](../opencode/permission/bypass-agent.md#6-bypass-からだけ呼べる子エージェント2026-09-28)。

## 記録 N4 — 常駐サービスのポートの衝突（`#常駐サービスのポート`）

### 問い

Windows の OpenCode の常駐サービスだけポートを変えるのはなぜか。

### 結果（元の文）

**理由**: 2026-10-02 に WSL と Windows の OpenCode（v2.0.14）がどちらも 127.0.0.1 の
4097 番を常駐サービスに使っていた。WSL と Windows が localhost を共有する構成では、
先に起きた側がポートを握り、もう一方は `Managed service port 4097 ... is already in use`
を繰り返したのち `Timed out waiting for the background service to start` で止まる
（Windows 側の `opencode.exe serve --service` が親の終了後も残っていた）。

Orca のセッションでは `~/.orca-relay/opencode-overlays/<hash>/service.json` が読まれる件の事故:
Orca 内で `opencode service set` を試すとそちらが書き換わる（2026-10-02、検証のつもりで `XDG_CONFIG_HOME` だけ
差し替えて `set port 4098` を実行し、WSL 側も 4098 になって Windows と衝突した。
`opencode service unset port` で戻した）

## 記録 N5 — モデルの階層の根拠（`#階層` ほか）

### 結果（元の文）

Copilot は Opus と Astra が制限されたので（2026-10）、`default`・`deep` は Sonnet 5.5、`second_opinion` は OpenCode の階層では Astra のままで、
pi の Copilot は `[pi.model.tier.github-copilot]` で Sol に上書きしている。`deep` の `xhigh` は Sonnet で通る確認が取れていないので `high` にした。

- **`routine`（`commit`）は Sonnet 5.5。** 子がコミットまで行っていた頃の測定。`commit` を haiku で動かすとメッセージの書式が崩れ、`claude-sonnet-5` ではそろった（[記録 E4 / E5](../opencode/commit-review-agents.md)）。Copilot の `claude-sonnet-5.5#medium` は `claude-opus-5.5#medium` と同等にコミット・書式がそろい、速く単価も半分で、`claude-sonnet-5` より `git commit` 以外の確認が少なかった（記録 E6）。effort を low / high にしても、コミット・書式・確認に差は無かった（[階層のモデルの計測](../opencode/tier-models.md)）
- **`worker`（`fleet-worker`）も Sonnet 5.5。** 小さな実装・バグ修正・リファクタリングなどの課題では、`claude-opus-5.5` と `claude-sonnet-5.5` の low / medium / high の合格率に差が無く、sonnet の medium は opus の medium の約 2/3 の時間で終わった。`claude-haiku-4.5` は難しめの課題で 0/4、担当外にファイルを残し、手数が多いぶん Bedrock の単価での試算も sonnet 5.5 より高かった（[階層のモデルの計測](../opencode/tier-models.md)）。Bedrock の値は Copilot で近似した判断で、Bedrock 上では未確認
- **effort はプロバイダの予算で分ける。** …公開のベンチマークでも、effort の差は難しいコーディングの課題で 1 段あたり 1〜3 ポイント程度（[階層のモデルの計測](../opencode/tier-models.md)の追記）。Bedrock の Sonnet 5.5 に effort を付けられることは、利用者が確かめた
- **`deep` は計測していない。** 良し悪しを機械的に採点できる課題を作れないため、opus の上位の effort のまま
- **Bedrock の `default` は Sonnet 5.5 のまま（再考の候補あり）。** 上位モデルを低い effort で使うほうが、仕事 1 件あたりの費用で得になる場合がある（公式の資料）ので、Opus 5.5 の `low` を候補として記録した。同じ条件での比較が無く、主エージェントに effort を付けられるかも未確認（[階層のモデルの計測](../opencode/tier-models.md)の追記）
- **`default` に `#variant` は付けられない**の顛末: Copilot の `default` を「Opus 5.5 の high」にしたかったが、手段が無かった。モデル単位の `settings.reasoningEffort`・別名モデル・`context` hook のどれで入れても、効くのは 1 回目の呼び出しだけで、ツール結果を受けた 2 回目以降（`/v1/messages`）では推論の強さが送られない（[実測 記録 E2](../opencode/agent-models.md#記録-e2--2026-09-28-既定モデルに推論の強さを持たせられるか)）
- `Bedrock は ocs では使えない`（コードから判断。実機では未確認）

## 記録 N6 — hooks の登録の撤去と外部ツールとの共存（`#hooks-の単一ソース化` ほか）

### 結果（元の文）

- **Claude / Copilot への hook の登録は撤去した（2026-10、[ADR-0017](../../adr/0017-pi-only-and-ts-judge.md)）。** 判定の hook（`check_bash.py`・`redirect-tmp.py`・`check_file_read.py`）は TS の判定器（`pi/harness/judge`）へ移し、`[retired_hooks].scripts` に載せた。
- （この節の Copilot の hooks 生成は撤去済み。Claude の hook の起動形式の記録として残す）
  - Copilot の起動キーは Windows では `powershell`、Linux / macOS / WSL では `bash`。生成先ごとのパスの表記と引用: Claude の `command` は絶対パス・`"..."`、Copilot の `bash` は `$HOME/...`・`"..."`、Copilot の `powershell` は絶対パス・`'...'`（`'` は `''` へ）。Windows で `$HOME` を使わないのは、PowerShell の `$HOME` が `HOMEDRIVE`+`HOMEPATH` 由来で chezmoi の `~`（`%USERPROFILE%`）と一致しないことがあるため。`powershell` を単一引用符にするのは、値が `-Command` へ渡された場合に二重引用符が外側の引用と衝突しうるため
- **ディレクトリではなくスクリプト名で所有権を決める。** …以前はディレクトリで判定していたので、apply のたびに herdr の hook を消し、直後の `run_after_140_herdr_integration` が足し直していた。2 回 apply しても `settings.json` が安定せず、その間は hook が無い状態になる（[Docker の検証で発覚](../testing/docker-cold-start-fixes.md#6-2-回目の-apply-でも-claudesettingsjson-の差分が消えない2026-09-27)）。
- herdr の hook を `common.toml` から生成する案は採らない。herdr の版や OS ごとにスクリプト名・引数・起動形式が変わり、それを追従する責任まで負うことになるため。herdr 自身が `run_after_140` / `343` で毎回導入し直す今の方式のほうが、`mise upgrade herdr` 後の追従や登録の消失からの復旧も兼ねられる。
- Generate.py が `hooks` を全置換していた頃は `chezmoi apply` のたびに Orca の 12 エントリが消えていた（`SessionStart` / `UserPromptSubmit` / `SubagentStart` などは**イベントキーごと**）。
- Claude Code のイベント名・timeout の注意（2026-08 時点の公式 docs 準拠）: `TaskCompleted` は `TaskCreate` ツール経由のタスク完了時にのみ発火する。「ターン終了時」に 1 回だけ動かしたい hook は `Stop` を使う（`Stop` = "When Claude finishes responding"、cadence は "once per turn"）。`SubagentStop` は `Stop` とは独立。`timeout` キーの単位は秒、`command` 型 hook のデフォルトは **600 秒**。

## 記録 N7 — Copilot のプラグインの重複（`#プラグイン-skill-の重複に注意`）

### 結果（元の文）

`document-skills` と `example-skills` は中身が完全に同一（実測: `skills/` 配下の差分は実行時生成物の `__pycache__` のみで、`pptx` / `docx` / `pdf` / `xlsx` など 17 スキルが一致）。

## 記録 N8 — コメントの書き分けの経緯（`#コメントの書き分け`）

### 結果（元の文）

経緯をファイル側に書くと、設定 386 行に対してコメントが 500 行を超えて「値を探すのが難しいファイル」になる。実際そうなっていたので分離した。
