# インストール済み実体と配布物の同定

いずれも**読むだけ**。対象のコードを実行する手段（`python -c "import x"`、
`importlib.metadata` の呼び出し、`npm ls`、`cargo metadata` など）は使わない。

## 共通: まず実体のパスを確定する

1. 起動経路: `command -v <cmd>` で実行ファイルを特定し、シンボリックリンクは
   `readlink -f` で解く。ラッパースクリプトなら中身を読んで本体を探す（実行はしない）。
2. どの環境か: mise / asdf / nvm / pyenv の shim なら、shim ではなく実体のディレクトリを
   追う。プロジェクトの仮想環境か、ユーザー全体か、別ツールの隔離環境かを区別する。
3. 見つけたパス・版・ハッシュ（`sha256sum`）を報告に残す。

## 作業ツリーの外にある実体の読み方

作業ツリーの外を read / grep / glob ツールで開くと、確認が出る環境がある。配布元の dotfiles の
OpenCode では、shell の引数に書いた外のパスでは確認が出ず、`grep -n` は許可済みと実測している
（`docs/research/opencode/permission/external-read-and-skill-scripts.md`）。これを使ってよいのは、
**利用者がその対象の調査を頼んでいる場合だけ**。確認待ち・拒否になった読み取りの回避には使わない。
shell / sandbox 側の確認と拒否にも従う。

- **検索だけ**: shell の `grep -n <パターン> <外のパス>` を使う。
- **通して読む**: 必要な通常ファイルだけを選んで `.tmp/oss/<調査ID>/installed/` へコピーし、
  そこを read / grep ツールで読む。
  - コピー元のルートが symlink なら、解決先を対象として確かめ直す。
  - 先に `du -sh` とファイル数で容量を確かめ、`safe-acquisition.md` の上限を超えるなら
    必要なファイルに絞る。失敗したコピーは不完全として扱う。
  - ディレクトリごとコピーするのは公開配布物（インストールされた wheel の中身など）に限る。
    開発・editable の実体は `.env`・資格情報・利用者データを含みうるので、ファイルを選ぶ。
    秘密のファイル・symlink・特殊ファイルはコピーしない（コピー先の read_deny は、
    コピーすること自体は防がない）。
  - コピー後も symlink をたどって読まない。コピーしたものは実行しない。
  - コピー元のパス・版・ハッシュを `.tmp/oss/<調査ID>/SOURCE.txt` に記録する。
- **単一バイナリ**: コピーせず、外のまま `grep -a` などで読む（大きいため）。

コピーは調査が終わったら消す（`safe-acquisition.md` の「後片付け」）。

## Python

- 仮想環境は `pyvenv.cfg` と `lib/python3.X/site-packages`（Windows は `Lib/site-packages`）。
  どの python かは、起動スクリプトの shebang か環境内の `bin/python` のリンク先で見る。
- 版と由来は `site-packages/<名前>-<版>.dist-info/` のファイルを直接読む:
  - `METADATA`（Name / Version / Home-page / Project-URL）
  - `RECORD`（収録ファイルとハッシュ）、`INSTALLER`（pip / uv など）
  - `direct_url.json`: あれば URL・VCS のコミット・`dir_info.editable`。
    `"editable": true` なら手元のディレクトリが実体。
- editable の見分け: `direct_url.json` の editable、`__editable__*.pth`、
  `*.egg-link`。実体は手元の作業ツリーなので、上流の版と同一とは限らない（未コミットの
  修正がありうる）。
- 手元の修正の疑い: `RECORD` のハッシュと実ファイルの `sha256` を比べる（RECORD は
  urlsafe base64 の sha256）。
- OS パッケージ由来（`/usr/lib/python3/dist-packages`、`*.egg-info`）は
  ディストリビューションのパッチを含みうる。上流ソースとは別の証拠として扱う。

## Node

- `node_modules/<pkg>/package.json` の `name` / `version` / `repository` / `gitHead`（あれば）。
- lockfile（`package-lock.json` / `pnpm-lock.yaml` / `yarn.lock` / `bun.lock`）の
  `resolved` と `integrity` で、解決された tarball とハッシュを確認する。
- pnpm は `node_modules/.pnpm/<名前>@<版>/` に実体がある。グローバル導入は
  `npm root -g` 相当のパスを実行せずに推定できないときは、ユーザーに尋ねる。

## Go / Cargo

- Go: `go.mod` / `go.sum` で版とハッシュを見る。モジュールキャッシュは
  `$GOMODCACHE`（既定 `$GOPATH/pkg/mod`、`~/go/pkg/mod`）の `<module>@<版>/`。
  `vendor/modules.txt` があればそれも実体。
- Cargo: `Cargo.lock` の `version` / `source` / `checksum`。取得済みソースは
  `~/.cargo/registry/src/<index>/<crate>-<版>/`、git 依存は `~/.cargo/git/checkouts/`。
  crate 内の `.cargo_vcs_info.json` に公開時のコミット SHA がある。

## 単一バイナリ同梱のバンドル

Bun / Deno / pkg などの単一実行ファイルは、JS が文字列として埋まっていることがある。

- 読み方: `grep -a -o -E '.{0,80}<キーワード>.{0,120}' <binary>` や `strings -a <binary>`。
  出力が巨大にならないよう、前後の文字数と `head` で絞る。
- バイナリ自体のバージョン表示を実行して確かめたくなっても、**実行しない**。版は
  配布元のリリース、同梱メタデータ、インストール先のパスやディレクトリ名から推定し、
  推定であることを書く。
- 注意: minify されていて変数名・構造が元のソースと違う。近い文字列が複数あると
  別の箇所を読み違える。定数や既定値は、使われる箇所（参照側）まで追ってから断定し、
  上流ソースの該当箇所（SHA 固定）と突き合わせる。
- 見つけた位置（バイトオフセットや周辺の文字列）とバイナリの `sha256` を報告に残す。
