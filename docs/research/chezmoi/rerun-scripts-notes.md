# 再実行の印（retry marker）の置き場に関する記録

`docs/spec/troubleshooting-bootstrap.md#スクリプトを走らせ直す` から移した記録。
移設時点で再測定していない。元の節に観測日は無い（コードの読解に基づく記述）。

> **現行の仕様**: 印の仕組みは [再実行の印の仕組み](../../spec/script-artifacts.md#再実行の印の仕組み)、
> 症状と対処は [スクリプトを走らせ直す](../../spec/troubleshooting-bootstrap.md#スクリプトを走らせ直す)。

## 記録 E1 — 日付なし（置き場の選定と旧置き場）

- **対象バージョン**: `home/.chezmoitemplates/retry-marker.sh.tmpl`（chezmoi 管理の印の実装）
- **環境**: Linux / WSL / macOS（コードの読解）

### 問い

再実行の印をどこに置くと、sandbox 内のエージェントから差し替えられずに済むか。

### 結果

印は apply（ホスト）が書くので、置き場はどのエージェントの sandbox からも書けない
場所にする。`~/.local/state` は Claude Code / Copilot CLI の sandbox から書ける
（[agent-sandbox.md](../../spec/sandbox/agent-sandbox.md)）ので使わない。書けると、印を `~/.bashrc` への
symlink に差し替えてホストの apply に中身を書き潰させられる。
同じ理由で、印は同じディレクトリの一時ファイルから `mv` で差し替え、既存の symlink を
追わない。中身を埋め込まないのは、書き換えられたときにスクリプトへコードが入らないため。
OS の境界を持たない実行（ocs を通さない OpenCode、omp）からは、この置き場でも守れない。

以前の置き場 `~/.local/state/dotfiles/agent-cli-failed` はもう読まない。残っていても
害は無く、消してよい。

### 未確認

- 印を消したときの再実行（`docs/spec/script-artifacts.md` の記述と同じく、コードからの推測）
