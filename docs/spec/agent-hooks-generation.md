# hook の単一ソース化と Copilot CLI の制約

Claude Code / Copilot CLI の hook を `common.toml` の `[[hooks]]` から生成する仕様（外部ツールとの共存・matcher・イベント名）と、Copilot CLI の制約。生成の全体は [設定の生成と所有権](agent-config-generation.md)。

## hooks の単一ソース化

**Claude / Copilot への hook の登録は撤去した（[ADR-0017](../adr/0017-pi-only-and-ts-judge.md)）。**
`[[hooks]]` は、pi のフルガードが edit / write の後に呼ぶスクリプト（`post_edit = true`。整形と markdownlint）だけを持つ。
判定の hook（`check_bash.py`・`redirect-tmp.py`・`check_file_read.py`）の判定は TS の判定器（`pi/harness/judge`）が担い、`[retired_hooks].scripts` に載せた。
Python 版のファイルは `home/dot_claude/hooks/` に残るが、登録されず実行時は呼ばれない（正解データの書き出し元。[CHG-0035](../change/0035-retire-python-judge-oracle.md)）。

| 生成先 | 生成方法 | 扱い |
| --- | --- | --- |
| `~/.claude/settings.json` の `hooks` | `modify_settings.json.py.tmpl` → `--target claude-settings` | 登録は空。`retired_hooks` に載せたスクリプトの古い登録を外し、外部ツール（Orca など）の hook は残す |
| `~/.copilot/hooks/from-claude.json` | （撤去。`--target copilot-hooks` は無い） | 配備済みのファイルは `.chezmoiremove` で消す |

- hook スクリプトの実体は `~/.claude/hooks/` に 1 つだけ置き、Copilot からも
  同じファイルを呼ぶ
- Copilot の起動キーは Windows では `powershell`、Linux / macOS / WSL では
  `bash`。パスの表記と引用は起動キーごとに変える

  | 生成先フィールド | パス | 引用 |
  | --- | --- | --- |
  | Claude の `command` | 絶対パス | `"..."` |
  | Copilot の `bash` | `$HOME/...` | `"..."` |
  | Copilot の `powershell` | 絶対パス | `'...'` (`'` は `''` へ) |

  Windows で `$HOME` を使わないのは、PowerShell の `$HOME` が
  `HOMEDRIVE`+`HOMEPATH` 由来で chezmoi の `~` (`%USERPROFILE%`) と一致しない
  ことがあるため ([structure.md](structure.md))。生成は `chezmoi apply` 時に
  対象マシン上で走るので、絶対パスは必ずそのマシンのホームを指す。
  `powershell` を単一引用符にするのは、値が `-Command` へ渡された場合に
  二重引用符が外側の引用と衝突しうるため。
  Windows の Python hook は bytecode を生成せず日本語 JSON を壊さない
  `py -3 -B -X utf8` で起動する。
  （Copilot の hooks 生成は撤去済み。[記録](../research/agents/agent-config-generation-notes.md)）
- `hooks` キーは Orca などの**外部ツールも追記する共有領域**なので、apply では
  このリポジトリの hook スクリプトを起動しているエントリだけを差し替える (後述)
- CLI UI で手動追加した hook も、このリポジトリのスクリプトを指していなければ
  残るが、再現性が無いので `common.toml` に転記すること
- `*_event` を空にすればその CLI には出力されない
- `*_matcher` を省略すると `matcher` キー自体が出力されない (= 全マッチ)。
  `Stop` / `UserPromptSubmit` など matcher 非対応イベントでは省略すること

### 外部ツールとの共存 (Orca / herdr)

Orca は `~/.claude/settings.json` と `~/.gemini/settings.json` の `hooks` へ
直接エントリを注入する。`permissions` が chezmoi の専有領域なのに対し、
`hooks` は**共有領域**である。generate.py が `hooks` を全置換していた頃は
`chezmoi apply` のたびに Orca の 12 エントリが消えていた
(`SessionStart` / `UserPromptSubmit` / `SubagentStart` などは**イベントキーごと**)。

現在の `merge_claude_hooks()` は次の規則で動く。

| 判定 | 扱い |
| --- | --- |
| コマンドが `~/.claude/hooks/<名前>` を起動し、`<名前>` が `[[hooks]].script` か `[retired_hooks].scripts` にある (ホームの表記と引用は問わない) | chezmoi の生成物。除去して `common.toml` から再生成 |
| それ以外 | 外部由来。そのまま温存 |

**ディレクトリではなくスクリプト名で所有権を決める。** `~/.claude/hooks/` は
共有ディレクトリで、herdr（`herdr integration install claude`）も
`herdr-agent-state.sh` をここに置き、`SessionStart` に登録する。
ディレクトリで判定すると herdr の hook を apply のたびに消してしまう
（[経緯](../research/testing/docker-cold-start-fixes.md#6-2-回目の-apply-でも-claudesettingsjson-の差分が消えない2026-09-27)）。

`[retired_hooks].scripts` は撤去した hook の名前で、`settings.json` に残った
古い登録を消すためにある。一覧は git 履歴から作った
（`block-dangerous-commands.sh` / `update-adr-on-stop.py` / checkpoint の 3 本）。
**hook を撤去したらここへ足す。** 足し忘れると古い登録が外部の hook として残る。
名前の直後が引用符・空白・末尾でない場合（`check_bash.py.bak` など）は一致させない。

逆に言えば、このディレクトリにスクリプトを置いて `settings.json` へ手で
登録しても、`common.toml` に転記していなければ外部の hook として残り続ける。

herdr の hook は `common.toml` から生成せず、herdr 自身が `run_after_140` / `343` で毎回導入し直す
（理由は[記録](../research/agents/agent-config-generation-notes.md)）。

- 絞り込みは**エントリ単位ではなくコマンド単位**。1 エントリの `hooks` リストに
  管理対象と外部由来が混在していても、外部由来だけが残る
- 削除するのは「全コマンドが自分の生成物だと確認できたエントリ」だけ。
  解釈できない形（リストでない、`hooks` リストを持たない等）は将来のスキーマ
  変更や未知のツールの書き込みでありうるので**そのまま残す**。
  ただし chezmoi も生成するイベント（`PreToolUse` など）で値がリスト以外だった
  場合は結合できないため生成物を優先する（Claude のスキーマ上リスト以外は
  元々無効。完全に温存されるのは管理外イベントのみ）
- 出力順は「管理エントリ → 外部エントリ」で、既存ファイルの並びと一致するため
  差分が出ない。2 回適用しても結果は変わらない (冪等)

他の CLI は元から衝突しない。

| 設定ファイル | Orca の書き込み方 | chezmoi の管理方式 |
| --- | --- | --- |
| `~/.claude/settings.json` | `hooks` へ注入 | 管理エントリのみ差し替え |
| `~/.gemini/settings.json` | `hooks` へ注入 | `GEMINI_MANAGED` の枝だけ上書き |
| `~/.copilot/hooks/orca.json` | 専用ファイルを新規作成 | `from-claude.json` のみ生成 |
| `~/.codex/config.toml` | 書き込み無し | `chezmoi-managed:start/end`（トップレベルのキー）と `chezmoi-managed:tables:start/end`（テーブル）のマーカー間のみ |

Orca 本体が作るファイル (`~/.orca/`, `~/.orca-wsl/`, `~/.orca-relay/`,
`~/.local/share/orca/`, `~/.local/bin/orca-ide`, `~/orca/`) と、`npx skills` が
管理する skill ストア (`~/.agents/`) は chezmoi では追跡しない。
マシン固有のパスやバージョンを埋め込んでおり、Orca 自身が更新機構を持つため。
`home/.chezmoiignore.tmpl` に列挙してあるので `chezmoi add` も拒否される。

### matcher の書き分け (共通化してはいけない)

| CLI | 意味論 | 書き方 |
| --- | --- | --- |
| Claude Code | tool 名の完全一致を `\|` で OR 連結 | `Edit\|Write` |
| Copilot CLI | `^(?:pattern)$` として anchored される | `^(Edit\|Write\|edit\|create)$` |

Copilot は PascalCase イベント名で書くと Claude の tool 名 (`Edit` / `Write` …)
で照合するため、両方の名前を列挙する。

### Claude Code のイベント名・timeout の注意 (2026-08 時点の公式 docs 準拠)

> 旧 Claude hook の記録。登録は撤去済み（[記録](../research/agents/agent-config-generation-notes.md)）。

- `TaskCompleted` は実在するが、`TaskCreate` ツール経由のタスク完了時にのみ発火する。
  「ターン終了時」に 1 回だけ動かしたい hook は `Stop` を使う
  (`Stop` = "When Claude finishes responding"、cadence は "once per turn")
- `SubagentStop` は `Stop` とは独立。サブエージェント終了も拾いたいなら両方に登録する
- `timeout` キーの単位は秒。`command` 型 hook のデフォルトは **600 秒**と長いため、
  `timeout_sec` を明示している (Copilot 側のキー名は `timeoutSec`)

## Copilot CLI の制約 (実機確認済)

- `~/.copilot/permissions-config.json` は **対話モードでのみロード** される。
  `copilot -p` (非対話モード) では一切無視される。
- `tool_approvals` の `kind: "commands"` の `commandIdentifiers` は
  **command 名の完全一致** のみで、`shell(git:*)` のような glob パターンの
  永続化サポートは未確証。よって本仕組みでは `[bash.allow]` の first token を
  ユニーク化して `commandIdentifiers` に集約する粗粒度方式を採用している。
- `kind: "write"` は MCP write tool 用で、shell tool (`touch`/`rm` 等) には
  効かない。
- `~/.copilot/settings.json` の `copilotTokens` / `loggedInUsers` /
  `installedPlugins` 等は Copilot 自動管理なので、generate.py はキー名
  ホワイトリスト方式で温存する。

### プラグイン (skill) の重複に注意

`anthropic-agent-skills` マーケットプレイスの **`document-skills` と
`example-skills` は中身が完全に同一**（17 スキルが一致。[実測](../research/agents/agent-config-generation-notes.md)）。両方有効にすると全スキルが二重に登録される。

`common.toml` の `[copilot.enabled_plugins]` でどちらを残すかを宣言し、
`merge_copilot_settings` が `settings.json` の `enabledPlugins` へ反映する。
**書いたキーだけを上書き**し、ここに無いプラグインはユーザーの設定を残す
(マーケットプレイスから別途入れたものを消さないため)。

なお個別スキル単位の無効化はできず、プラグインごとの on/off しかない。
`pptx` だけを外すことはできないので、`document-skills` を落とすと
`docx` / `pdf` / `xlsx` なども一緒に消える点に注意。

自前の `powerpoint-studio` スキル (`home/dot_claude/skills/`) は
プラグインの `pptx` と**競合しない**。前者は新規作成・大幅改稿の専用で、
description に「単なる .pptx のテキスト抽出や軽微な一語置換には使わない」と
明示してあり、抽出・軽微修正は後者が担当する。
