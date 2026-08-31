# 外部ツールが書き込む設定領域と chezmoi の共存

- **ステータス**: Accepted
- **日付**: 2026-08-30
- **決定者**: applejxd

## コンテキスト

このリポジトリは AI CLI（Claude Code / Copilot CLI / Codex / Gemini CLI）の
permission と hook を `home/dot_config/agents/common.toml` に単一ソース化し、
`scripts/agents/generate.py` を通して各 CLI の設定ファイルへ展開している。
詳細は [`docs/agents-permissions.md`](../agents-permissions.md)。

ここに Orca（[stablyai/orca](https://github.com/stablyai/orca)）を導入した。
Orca はコーディングエージェントを統括するデスクトップアプリで、
インストール時および初回起動時に各 AI CLI の設定ファイルへ hook を直接注入する。

調査した結果、書き込み方は CLI ごとに異なっていた。

| 設定ファイル | Orca の書き込み方 | chezmoi の管理方式 | 衝突 |
| --- | --- | --- | --- |
| `~/.claude/settings.json` | `hooks` キーへ 12 エントリ注入 | `hooks` を**全置換** | **あり** |
| `~/.gemini/settings.json` | `hooks` キーへ 4 エントリ注入 | Sprig `merge` で枝ごと上書き | なし |
| `~/.copilot/hooks/orca.json` | 専用ファイルを新規作成 | `from-claude.json` のみ生成 | なし |
| `~/.codex/config.toml` | 書き込み無し | `chezmoi-managed:start/end` マーカー間のみ | なし |

Claude だけが衝突していた。`chezmoi diff ~/.claude/settings.json` で、
`chezmoi apply` のたびに Orca の 12 エントリが全て消えることを確認した。
うち `SessionStart` / `UserPromptSubmit` / `SubagentStart` / `PermissionRequest` 等は
chezmoi 側に同名イベントが無いため**イベントキーごと**消滅していた。

問題の本質は、`permissions` が chezmoi の専有領域であるのに対し、
`hooks` は Orca・herdr・CLI 本体の UI など**複数の書き手が追記する共有領域**
であることを設計が織り込んでいなかった点にある。

加えて Orca は多量のランタイム生成物（`~/.orca/`、`~/.orca-wsl/`、
`~/.orca-relay/`、`~/.local/share/orca/`、`~/.local/bin/orca-ide`、`~/orca/`）と、
`npx skills` 経由の skill ストア（`~/.agents/`）を作る。
これらを dotfiles として追跡するかも判断が必要だった。

## 検討した選択肢

### 選択肢 1: 由来を判定して管理エントリのみ差し替える

`hooks` の各コマンドが `~/.claude/hooks/` 配下を起動しているかで所有権を判定し、
自分の生成物だけを除去して `common.toml` から再生成する。それ以外は温存する。

- **利点**: Orca のバージョンが上がってコマンド文字列が変わっても追随不要。
  未知のツールが増えても自動的に共存できる。
  `common.toml` から消したスクリプトの残骸も掃除できる。
  既存の `COPILOT_MANAGED_KEYS` と同じ「管理範囲を明示する」流儀に揃う
- **欠点**: 所有権の判定がパス基準のヒューリスティック。
  `~/.claude/hooks/` にスクリプトを置いて `common.toml` に転記せず手で登録すると
  次の apply で消える

### 選択肢 2: Orca の hook を `common.toml` に取り込んで生成する

Orca が注入するコマンドを `common.toml` に転記し、chezmoi 側から出力する。

- **利点**: 単一ソースの原則を崩さない。生成物が完全に決定的になる
- **欠点**: 1 コマンドが 2165 文字あり、Windows 用の base64 エンコード済み
  PowerShell を含む。Orca の更新のたびに手写しが必要で確実に腐る。
  イベントの追加・削除にも追随できない

### 選択肢 3: `~/.claude/settings.json` を chezmoi の管理外にする

hook 設定の管理をやめ、CLI と Orca に任せる。

- **利点**: 衝突が原理的に起きない
- **欠点**: permission と hook の単一ソース化という既存の仕組みが丸ごと失われる。
  新環境のセットアップが再現できなくなる

## 決定事項

**選択肢 1 を採用する。**

理由: 外部ツールの実装詳細に依存せずに共存でき、単一ソースの利点も保てる。
選択肢 2 は Orca の更新に追随できず必ず腐るため却下。
選択肢 3 は本リポジトリの中核機能を失うため却下。

具体的な規則は次のとおり。

1. **所有権はディレクトリ単位で判定する。**
   コマンドが `~/.claude/hooks/`（または `$HOME/.claude/hooks/`）を起動していれば
   chezmoi の生成物とみなす。このディレクトリは `home/dot_claude/hooks/` として
   リポジトリが全体を所有しているため、パス基準の判定が成立する。
   副作用として、ここに手で置いた hook は `common.toml` に転記しない限り消える。
   これは `common.toml` を単一の真実とするための**意図的な挙動**とする

2. **絞り込みはエントリ単位ではなくコマンド単位で行う。**
   1 エントリの `hooks` リストに管理対象と外部由来が混在しても外部由来だけが残る

3. **解釈できない形は削除しない。**
   リストでない値、`hooks` リストを持たないエントリなどは、将来のスキーマ変更や
   未知のツールの書き込みでありうるためそのまま残す。削除するのは
   「全コマンドが自分の生成物だと確認できたエントリ」だけ。
   ただし chezmoi も生成するイベントで値がリスト以外の場合のみ、結合できないので
   生成物を優先する（Claude のスキーマ上リスト以外は元々無効）

4. **Orca のランタイム生成物と skill ストアは追跡しない。**
   `~/.orca/`、`~/.orca-wsl/`、`~/.orca-relay/`、`~/.local/share/orca/`、
   `~/.local/bin/orca-ide`、`~/orca/`、`~/.agents/` を
   `home/.chezmoiignore.tmpl` に列挙する。
   理由は、Windows 側の絶対パスやバージョンピン、worktree 実体といった
   マシン固有の内容を含み、いずれも Orca 自身が再生成・更新機構を持つため。
   列挙しておくと `chezmoi add` も警告を出して取り込みを拒否する

5. **Gemini も同じ考え方に揃える。**
   `home/dot_gemini/modify_settings.json`（Sprig テンプレート）は
   Go の `toPrettyJson` が map のキーをアルファベット順に並べ替えるため、
   Gemini CLI や Orca が書き戻すたびに差分ノイズが出ていた。
   Python の dict は挿入順を保つので、`generate.py` の `gemini-settings`
   ターゲットへ移し、管理する枝だけを上書きする方式に統一する

## 完了条件

- [x] `generate.py` に `is_managed_hook_command()` / `strip_managed_claude_hooks()` /
      `merge_claude_hooks()` を実装し、`merge_claude_settings()` から呼ぶ
- [x] `generate.py` に `gemini-settings` ターゲットを追加し、
      `home/dot_gemini/modify_settings.json.py.tmpl` へ移行
- [x] `home/.chezmoiignore.tmpl` に Orca 関連パスを理由コメント付きで列挙
- [x] `test/agents/test_generate_hooks.py` に外部 hook 温存・冪等性・
      解釈不能な形の温存の回帰テストを追加（修正を戻すと 7 件が失敗することを確認）
- [x] `docs/agents-permissions.md` と各 CLI の `README.md` を更新
- [x] `uv run --with pytest --no-project pytest test/agents/` が全通過（957 件）
- [x] `uv run pre-commit run --all-files` が全通過
- [x] `chezmoi diff ~/.claude/settings.json` と
      `chezmoi diff ~/.gemini/settings.json` がともに空

## 結果

### ポジティブな結果

- `chezmoi apply` が Orca の hook を壊さなくなった
- Orca 以外の外部ツール（herdr など）が同じ領域へ書き込んでも自動的に共存できる
- Gemini の設定ファイルで毎回出ていた差分ノイズが消え、`chezmoi diff` の
  シグナル・ノイズ比が改善した
- `hooks` が共有領域であるという前提がコード・テスト・ドキュメントに残った

### ネガティブな結果

- 所有権の判定がパス基準のヒューリスティックであり、`~/.claude/hooks/` に
  スクリプトを置いて `common.toml` に転記しないと消える罠が残る
  （ドキュメントに明記して緩和）
- 生成ロジックが「全置換」より複雑になり、冪等性や順序の保証が必要になった
  （回帰テストで担保）
- Orca の skill を chezmoi で再現しないため、新環境では Orca 側の
  インストール手順を踏む必要がある

### 中立的な結果

- `generate.py` の責務に Gemini が加わり、対象 4 CLI のうち JSON を扱う 3 つが
  同じ `modify_json.py.tmpl` ラッパー経由に揃った
- Codex のみ TOML のためマーカー方式が残るが、
  「管理範囲を明示して外部の追記を壊さない」という考え方は共通になった

## 関連 ADR

- なし（このリポジトリ最初の ADR）
