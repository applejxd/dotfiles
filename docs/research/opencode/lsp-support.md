# OpenCode V2 は LSP を使えるか

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

**結論（2026-10-01、v2.0.14〜v2.0.21）: 使えない。** V2 は設定の `lsp` を
受理・保持するだけで、言語サーバを起動せず、LSP ツールも診断も出さない。
公式の移行ガイドが明記しており、ソースと手元のバイナリでも裏付けた。
LSP の実装は V1（`dev` ブランチの `packages/opencode/`）にだけある。

## 記録 E1 — 2026-10-01

- **対象バージョン**: `@opencode/cli` v2.0.14（手元）。ソースは v2.0.14 と
  v2.0.21 のタグ、比較に `dev`（V1 1.18.34）
- **環境**: Ubuntu / WSL、`~/.opencode/bin/opencode`

### 問い

編集直後の診断を得るために、OpenCode V2 へ LSP（Python / シェルなど）を
設定できるか。設定するなら `common.toml` から生成するか。

### 事前の予想

V1 に `lsp` 設定があったので、V2 でも動き、設定方法だけ変わっていると予想した。
**外れた。**

### 方法・条件

対象のコードは実行していない。資料・ソース・バイナリの文字列だけを読んだ。

1. 公式の移行ガイド（<https://opencode.ai/v2/docs/migrate-v1/>）。
   `https://opencode.ai/v2/docs/lsp/` は 404
2. `anomalyco/opencode` のタグのファイル一覧を GitHub API で取り、`lsp` を含む
   パスを比べた。アーカイブ（約 48 MB）は取得が時間切れになったので使わず、
   必要なファイルだけ contents API で読んだ
3. 手元のバイナリを `grep -a` で文字列検索した
4. issue / PR とリリースノート（v2.0.15〜v2.0.21）を `gh` で検索した

| ref | commit SHA |
| --- | --- |
| v2.0.14 | `08462140ec0de1e4b17d4a353d8d5827f53cf7b0` |
| v2.0.21 | `8a8bd622a3d7dc29ccf30ec17f84e363ed95ed72` |
| dev | `0112a92c416f5ad833d96e7a8308441f0a875d94` |

### 結果

**移行ガイド**（「Supported fields without direct native equivalents」節）:

> V2 accepts and preserves `lsp` configuration, but it does not run language
> servers, expose LSP tools, or produce LSP diagnostics.

代わりに、プロジェクトの lint / typecheck / compiler のコマンドを使うよう勧めている。

**ソースのファイル一覧**（docs の翻訳ファイルを除く）:

| ref | `lsp` を含むパス |
| --- | --- |
| v2.0.14 / v2.0.21 | `packages/schema/src/config/lsp.ts`（設定の型）、`packages/core/src/v1/config/lsp.ts`（V1 設定の型）、`packages/schema/src/lsp-event.ts`、`packages/app/` の設定一覧の表示だけ |
| dev（V1） | 上記に加えて `packages/opencode/src/lsp/{client,diagnostic,launch,lsp,server}.ts`、`packages/opencode/src/tool/lsp.ts` |

- v2.0.14 の `packages/cli/package.json` は `@opencode/cli` 2.0.14、
  dev の `packages/opencode/package.json` は `opencode` 1.18.34
- V2 の設定の型は `command` / `extensions` / `disabled` / `env` /
  `initialization`（サーバごと）か boolean。V1 と同じ形
- `lsp-event.ts` は中身の無い `lsp.updated` イベントを定義するだけ
- `app` の `configured-lsp.ts` は、設定にあるサーバ名を並べるだけ

**手元のバイナリ**:

```console
$ opencode --version
opencode v2.0.14
$ grep -a -o -E 'textDocument/publishDiagnostics|initializationOptions|vscode-jsonrpc|pyright-langserver|bash-language-server|typescript-language-server|lsp\.updated|LSP diagnostics|<diagnostics' ~/.opencode/bin/opencode | sort | uniq -c
      2 lsp.updated
```

LSP クライアントが持つはずの文字列（`publishDiagnostics` など）は 0 件。

**issue / リリースノート**:

- [#50916](https://github.com/anomalyco/opencode/issues/50916)
  「LSP support gutted from v2?」（2026-09-23 起票）は OPEN。利用者のコメント
  3 件（V1 へ戻した等）だけで、メンテナの回答は無い
- v2.0.15〜v2.0.21 のリリースノートに `lsp` / `language server` /
  `diagnostic` の記述は無い
- 2026-09 の LSP 関連 PR（#44757 lsp tool の既定有効化、#47392 idle TTL など）は
  いずれも `fix(opencode)` / `feat(lsp)` で、V1 側（`packages/opencode/`）のもの
  （タイトルからの判断。差分は読んでいない）

### 考察

- 言えること: v2.0.14〜v2.0.21 では `lsp` を書いても診断は得られない。
  書いても害は無い（受理・保持される）が、効果も無い
- 言えないこと: 削除が一時的かどうか。公式の回答は見つからなかった
- V2 で LSP を使う外部手段（プラグイン・LSP を包む MCP サーバ）は
  `gh search repos` で 0 件だったが、検索自体が正しく動いたか確かめていない。
  **未確認**であって「無い」ではない

### 次の問い

- #50916 にメンテナの回答が付くか、V2 のリリースノートに LSP が現れるか
- 外部の LSP-MCP を使う場合の、`ocs` の境界（起動・通信・書き込み先）と
  診断が会話に入る量

### 参照

出典: <https://opencode.ai/v2/docs/migrate-v1/>、
<https://github.com/anomalyco/opencode/tree/08462140ec0de1e4b17d4a353d8d5827f53cf7b0/packages/schema/src/config/lsp.ts>、
<https://github.com/anomalyco/opencode/issues/50916>
