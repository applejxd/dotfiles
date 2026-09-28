# Copilot CLI の開発ツール自動許可（`allowDevToolAccess`）の実効権限

- **観測日**: 2026-09-14 〜 2026-09-15（記録したコミットは `3778396` と `2da3566`、
  どちらも 2026-09-15）
- **対象**: GitHub Copilot CLI 1.0.84-5、Ubuntu、`allowDevToolAccess = true`
  （Copilot の既定）
- **一次情報**: 上記 2 コミットの本文と、そこで `docs/spec/agent-permissions.md` に
  書いた表。確認に使ったのは `/sandbox policy` の表示、sandbox 内でのコマンドの
  実行結果、`findmnt -T <path> -o TARGET,SOURCE,OPTIONS`。**生の出力は残っていない**
- **関連する不具合**: [github/copilot-cli#4846](https://github.com/github/copilot-cli/issues/4846)

いまは `allowDevToolAccess` を切り、必要な範囲を `copilot_read_allow` /
`copilot_write_allow` に並べている。現在の規則は
[sandbox (Claude Code / Copilot CLI)](../../spec/agent-sandbox.md#copilot-が読み書きできる場所-copilot_read_allow--copilot_write_allow)、
判断は [ADR-0008](../../adr/0008-explicit-dev-tool-grants.md)、自動付与の仕様の網羅は
[sandbox 機能の包括調査](sandbox-capabilities.md) が正本。
ここには、自動付与が有効だった間に見たものだけを残す。

## 1. 取りこぼしと上書き

| パス | 実効権限 | 結果 |
| --- | --- | --- |
| `~/.cache/uv` | read-only（`readwritePaths` に書いても） | `uv run` が lock を作れず EROFS |
| `~/.local/share/uv/python` | 不可視 | `.venv/bin/python` の実体を辿れない |
| `/usr/include` | 不可視 | C/C++/cgo のビルドが `fatal error: stdlib.h` で落ちる |
| `/usr/local` 配下 | 不可視 | ローカル導入のヘッダ・ライブラリ・CUDA を参照できない |

`~/.cache/uv` は `/sandbox policy` では Read-write と表示されていたが、
`findmnt` では `ro` で bind されていた。`allowDevToolAccess` を切ると同じ mount が
`rw` に変わり、`uv run` が通った（`2da3566`）。

## 2. 見える範囲の粒度

sandbox 内で見えたエントリ数（数えたコマンドの記録は無い）。
**ライブラリは見えるのにヘッダが見えない**。

```text
見える  : /usr/lib (136) /usr/lib/x86_64-linux-gnu (2864) /usr/bin (3083)
          /usr/share (336) /usr/libexec (135) /etc (277) 各種 pkgconfig
見えない: /usr/include /usr/local/* /usr/src /opt /sys /var/lib
```

## 3. PATH 上のディレクトリは read-only

PATH に載っているディレクトリそのものが read-only になり、その親は rw のままだった。

| パス | 権限 | PATH に載っているか |
| --- | --- | --- |
| `~/.local/share/mise` | rw | ✗ |
| `~/.local/share/mise/installs` | rw | ✗ |
| `.../npm-markdownlint-cli2/0.22.1` | rw | ✗ |
| `.../npm-markdownlint-cli2/0.22.1/bin` | **r- (EROFS)** | ○ |
| `.../node/24.5.0/bin` | **r- (EROFS)** | ○ |

このため `mise install --force` は、使用中のツールの `bin/` を消そうとして
`Read-only file system (os error 30)` で失敗した。

## 4. mise の `latest` symlink が消える

PATH には `<tool>/latest/bin` が載るが、sandbox 内では `installs/node/` に
`24.5.0` だけがあり `latest` が無かった。`node: not found` になり、node を
shebang で呼ぶ npm 製ツール（`markdownlint-cli2` など）と `npx` が動かなかった。
`/bin` `/lib` `/sbin` でも同じ現象が出ていた。

親ディレクトリごと許可すると消えなかった。`/usr/local` を許可した後は
`cuda -> /etc/alternatives/cuda` が symlink のまま見えている。
