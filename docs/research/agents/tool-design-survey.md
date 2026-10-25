# 他のコーディングエージェントの、ファイル操作・シェルツールの作りと、シェルから専用ツールへ寄せる仕掛け

- **観測日**: 2026-10-24。`explore` の子 3 件（公式 docs・ソース・第三者の転記。取得日が分からないものは日付を書かない）。実行は無し
- **目的**: 自作ハーネスの `guarded_read`・`guarded_write`・`guarded_edit`・`guarded_bash` を、モデルの使用コストが下がるように作り込む（[CHG-0038](../../change/0038-guard-reclassification.md) 段 G8）ための参考

## 結論

- **「末尾から読む（tail）」「複数ファイルの一括読み」「追記」「標準入力・スクリプト本文を渡す専用の引数」は、調べた製品のどれにも、現行では無かった**（かつてあったものも、削られている）。一括読みは、Gemini CLI の `read_many_files` が非推奨（理由: 並列の `read_file` で足りる、ツール数を減らしてコンテキストを節約）、Roo も単一ファイルの読みに寄せ、Amp も「並列で呼べ」と書く。**複数ファイルは、一括の引数ではなく、並列の呼び出しで足りる、が実績のある流儀**
- **cat などの bash 読みを「拒否」する製品は、見つからなかった**。専用ツールへの誘導は、**bash の説明文**（Claude Code・Crush・Amp・Continue・Gemini）が主で、Claude Code は、読み取りの記録では、`cat`・`head`・`tail`・`sed -n`・`grep` の単一ファイル実行も「読んだ」とみなす。つまり、**自作の deny は、他社より厳しい**
- **Claude 系モデルの先験が、ヒアドキュメントの書き込みを選ばせている可能性がある**: Anthropic の公式の bash ツールの例は、`cat > fetch_joke.py << 'EOF'` と、ヒアドキュメントで書く。`str_replace_based_edit_tool`（`view`・`str_replace`・`create`・`insert`）は、スキーマがモデルに組み込まれている（"schema-less … built into Claude's model"）
- 追記は、Anthropic の `insert`（`insert_line`）と Roo の `insert_content`（行 0 で末尾）にあるが、Crush は「Cannot append」と明記し、他は無い

## 製品別（事実はソース・公式 docs。URL は参照）

| 製品 | 読み | 書き・編集 | シェル | 特記事項 |
| --- | --- | --- | --- | --- |
| **Claude Code** | `Read`（file_path、offset、limit。既定 2000 行。行番号つき） | `Edit`（old_string・new_string・replace_all。一意一致）、`Write`（上書き。追記なし） | `Bash`（command、timeout、run_in_background） | Bash の説明に「**DO NOT use it for file operations**」「Read（NOT cat/head/tail）」「Edit（NOT sed/awk）」「Write（NOT echo >/cat <<EOF）」（第三者の転記）。先読みの強制あり。Linux では Glob・Grep を出さず、find・grep を埋め込みの `bfs`・`ugrep` で動かす |
| **Charm Crush** | `view`（offset・limit、既定 200）。見つからないとき**似た名前を最大 3 件提案** | `edit`（空白だけの違いを吸収）、`multiedit`、`write`（「Cannot append」） | `bash`（background への自動移行） | bash の説明に「Use View/LS tools instead of 'cat'/'head'/'tail'/'ls'」。先読みは、変更時刻の比較で強制 |
| **OpenCode** | `read`（offset・limit。ディレクトリも一覧）、2,000 行・50KiB で切る | `edit`・`write`・`patch`（GPT 系だけ） | `shell`（background） | 複数ファイルは、Code Mode（JS）で並列に読む。説明の原文は未取得 |
| **Codex CLI** | `read_file`（offset・limit・**`mode`: slice / indentation**。インデントの構造で関数ブロックを取る）。実験的 | `apply_patch` | `shell`（command は配列）、`exec_command` と `write_stdin`（実行中のセッションの標準入力へ書く） | Windows の説明に、インラインの Python を stdin で渡す例（`@'…'@ \| python -`） |
| **Gemini CLI** | `read_file`（start_line・end_line）。説明に「**MUST use start_line/end_line**」「token-inefficient」 | `write_file`（説明に「use 'replace' for targeted edits to large files to minimize token usage」）、`replace` | `run_shell_command` | `read_many_files` は非推奨（上の結論）。grep の説明に「PREFERRED over `run_shell_command("grep ...")`」 |
| **Roo Code** | `read_file`（1 回 1 ファイル。「issue multiple parallel read_file calls」。mode: slice / indentation） | `edit`（先読みを要求。行番号を `old_string` に含めるな）、`insert_content`（行 0 で末尾）、`apply_diff` | `execute_command`（timeout 超過はバックグラウンドで継続） | 2026-05-15 にアーカイブ済み |
| **Cline** | `read_file`（path のみ） | `write_to_file`（「COMPLETE intended content」）、`replace_in_file`（SEARCH/REPLACE を複数並べる） | `execute_command` | 現行ソースは取得できず（2025-06 時点の転載） |
| **Continue** | `readFile`（filepath のみ） | `editFile`（`// ... existing code ...`） | `runTerminalCommand` | 説明に「IMPORTANT: To edit files, use Edit/MultiEdit tools instead of bash commands (sed, awk, etc).」 |
| **VS Code Copilot** | `read_file`（filePath・offset・limit。「Invalid offset N: file only has M lines」と、**ファイルの長さを返す**） | `replace_string_in_file`・`multi_replace_string_in_file`・`apply_patch`（モデルごとに切替） | `run_in_terminal` | ヒアドキュメントの破損は、コミュニティ製の指示ファイルで補う（公式の拒否ではない） |
| **Zed** | `read_file`（start_line・end_line。大きいファイルは **outline を返し、「Do NOT retry reading the same file without line numbers」**） | `edit_file`（edits の配列）、`write_file` | `terminal`（command・cd・timeout_ms・**`head_lines`・`tail_lines`**） | terminal の説明に「Do not pipe output to `head`, `tail`…. Instead, use `head_lines` and/or `tail_lines`」。`$VAR`・`$(...)` を禁じ、`cd` は引数で |
| **Amp** | `Read`（`read_ranges`。既定は先頭 1000 行）。「call this tool in parallel for all files」 | `edit_file`（diff を返す）、`create_file`、`undo_edit` | `Bash`（cmd・cwd） | 説明に「VERY IMPORTANT to use specific tools … Use Read tool rather than cat, and edit_file rather than sed」（第三者の抜粋）。edit_file の説明が、全文の置換は create_file の方がトークンが少ないと案内 |
| **Goose** | 現行は `read` が無い（`write`・`edit`・`shell`・`tree`） | 旧 `text_editor`（view・write・str_replace・insert・undo_edit） | `shell`（bash を優先。ヒアドキュメントを通すため） | メンテナーは「専用の read は不要。frontier モデルは shell で範囲読みする」 |
| **Aider** | — | テキスト形式の編集（whole・diff・diff-fenced）。モデルごとに最適なものを選ぶ | — | ツール呼び出しではない |
| **pi 1.3.0**（本体） | `read`（path・offset・limit。画像対応） | `write`（path・content。上書き）、`edit`（path・`edits[{oldText,newText}]`。複数編集を 1 回で） | `bash`（command・timeout。snippet は「Execute bash commands (ls, grep, find, etc.)」） | `read` の方針に「Use read to examine files instead of cat or sed.」。`codemode` で複数のツール呼び出しをまとめられる。`tail`・追記・stdin は無い |

## 自作ハーネスへの示唆（推測を含む）

1. **bash の説明文を、Claude Code・Crush・Amp の型に書き直す**（「ファイル操作に使うな」と、`cat`・`sed`・`echo >` ごとの具体的な言い換え）。pi の組み込みの snippet は、ファイル操作の `ls`・`grep`・`find` を例示しており、逆方向
2. **複数ファイルの一括読みは作らない**。並列の呼び出しを、説明で案内する（Gemini・Roo・Amp の流儀）。複数のファイルを 1 回の `bash` に詰める癖には、説明で「並列の `guarded_read` で足りる」と書く
3. **`tail` と追記は、他社に無いが、実績のある誘導の欠けを埋める**（自作の実績: 読み取りの誘導のうち `tail` が 9 件、書き込みの誘導のうち追記が 6 件）。追記は Anthropic の `insert` と Roo の `insert_content` が前例
4. **読みの失敗のヒントが安い改善**: 不正な offset でファイルの長さを返す（Copilot）、似た名前を提案する（Crush）、大きいファイルでは構造を返し、同じものを行番号なしで読み直すなと案内する（Zed）
5. **説明にトークン効率を書く**（Gemini: 「小さく読め」、Amp: 全文の置換は create_file）
6. **bash の出力の絞り込みは、パイプでなく引数で**（Zed の `head_lines`・`tail_lines`）。これは、ファイルの読みではなく、コマンド出力の絞り込み
7. **拒否（deny）より、説明と注記が主流**。Claude Code は単一ファイルの `cat` を読みとして扱う。自作の deny は、保護の意図があるので、保護と UX を分けて見直す

## 未確認

- Cursor、Kilo Code、oh-my-pi は未調査。OpenCode の bash・edit・write の説明の原文、Codex の `apply_patch` の指示文は未取得
- Anthropic の「モデルがこれらのツールに訓練されている」という明文は取れていない（「スキーマがモデルに組み込まれている」まで確認）
- Amp の説明は第三者の抜粋で、版・時点が不明。Claude Code の Bash の説明も第三者の転記（2025-12 時点）

## 参照

- <https://code.claude.com/docs/en/tools-reference>、<https://blog.thepete.net/claude-code-tools/>
- <https://opencode.ai/v2/docs/tools/>、<https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/core/src/tool/read-filesystem.ts>
- <https://github.com/charmbracelet/crush>（`internal/agent/tools/` の `view.go`・`write.go`・`bash.md.tpl`）
- `openai/codex` の `codex-rs/core/src/tools/spec.rs`
- <https://github.com/google-gemini/gemini-cli>（`packages/core/src/tools/definitions/`）、<https://github.com/google-gemini/gemini-cli/discussions/12970>
- <https://github.com/RooCodeInc/Roo-Code>（`src/core/prompts/tools/native-tools/`）、<https://github.com/continuedev/continue>（`core/tools/definitions/`）
- <https://github.com/microsoft/vscode-copilot-chat>（`src/extension/tools/node/readFileTool.tsx`）、<https://code.visualstudio.com/blogs/2026/05/15/agent-harnesses-github-copilot-vscode>
- <https://github.com/zed-industries/zed>（`crates/agent/src/tools/`）、<https://johndamask.com/blog/2025/11/24/amp-all-prompts.html>、<https://github.com/aaif-goose/goose/issues/12612>
- Anthropic: <https://platform.claude.com/docs/en/agents-and-tools/tool-use/text-editor-tool>、同 `bash-tool`、<https://aider.chat/docs/more/edit-formats.html>
