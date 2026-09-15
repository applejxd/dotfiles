# Copilot の開発ツール自動許可を切り、必要な範囲を明示する

- **ステータス**: Accepted
- **日付**: 2026-09-14
- **決定者**: applejxd

## コンテキスト

Copilot CLI の sandbox には `allowDevToolAccess` という設定がある。有効にすると
CLI が実行しようとするコマンドを見て、`PATH` 上のディレクトリ・`GOPATH` /
`JAVA_HOME` / `PYTHONPATH`・パッケージマネージャのキャッシュを**自動で**許可する。
既定は有効で、[ADR-0007](0007-filesystem-guard-boundary.md) までは
「Claude に無い機能を `claude_read_allow` で手動補償する」形で運用していた。

この自動付与が、取りこぼしと不具合の両方を抱えていることが分かった。

### 1. 取りこぼし

`uv` が対象から外れていた (実測)。

- `~/.cache/uv` が read-only で `uv run` が EROFS
- `~/.local/share/uv/python` が不可視で、インタプリタ自体が見つからない

`copilot_read_allow` / `copilot_write_allow` を新設して補償したが、
**何が拾われ何が拾われないかを事前に知る方法が無い**。新しいツールを入れるたび、
壊れてから気付くことになる。

### 2. ユーザ指定を自動付与が上書きする不具合

補償を入れても `~/.cache/uv` の EROFS が直らなかった。

- `/sandbox policy` は `~/.cache/uv` を **Read-write paths** に表示する
- しかし `findmnt` で見ると同じパスが `ro` で bind されている
- `allowDevToolAccess` を切ると、同じ mount が `rw` に変わり `uv run` が通る

原因は sandbox 実装 (`microsoft/mxc` の `normalize_filesystem_paths`) が、
同一パスに RO と RW の両方が来たとき「最も制限的な意図」として **RO を採る**
ことにある。この解決は**出所を区別しない**ため、ユーザが明示した RW が
自動発見された RO に負ける。公開 issue は `github/copilot-cli#4846`。

この不具合は「設定が効かない」だけでなく、**`/sandbox policy` の表示が
実効ポリシーを保証しない**ことを意味する。表示上は正しく見えるので、
原因の特定に mount レベルの確認が要った。

### 3. 運用上の影響

自動付与が有効な間は、エージェントが `uv run` や `mise install` を実行するたび
EROFS で失敗し、その都度「sandbox が壊れている」ところから調査が始まる。
設定ファイルを読んでも原因が分からない。

## 検討した選択肢

### 選択肢 1: 自動付与を有効のまま、取りこぼしを補償し続ける

- **利点**: 列挙する範囲が小さくて済む。新しいツールの多くは自動で通る
- **欠点**: 不具合 2 が残るので、補償を書いても効かない場合がある。
  しかも効いていないことが `/sandbox policy` からは分からない。
  「設定したのに効かない」は最も追跡コストが高い壊れ方

### 選択肢 2: 不具合の回避策を探す (パスの書き方を変える等)

`env python3` と `python3` で挙動が違うという報告があったので検証したが、
**再現しなかった**。起動形式に依存するのではなく、セッション全体で
同じ競合が起きている。回避できる書き方は見つかっていない。

- **利点**: 自動付与の利便性を保てる
- **欠点**: 上流の解決規則そのものが原因なので、設定側から回避できない。
  仮に回避策が見つかっても、上流の修正で挙動が変わる

### 選択肢 3: 自動付与を切り、必要な範囲を `common.toml` に明示する

- **利点**:
  - 許可の全体が 1 箇所に載り、`chezmoi` 管理下に入る
  - 足りなければ **不可視 = 即座に失敗** するので、壊れ方が見える
  - Claude 側の `claude_read_allow` とほぼ同じ内容になり、
    両 CLI の実効ポリシーを読み比べられる
- **欠点**: 列挙が要る。新しいツールチェーンを入れたら追記が要る

## 決定事項

**選択肢 3 を採用する。**

`[sandbox] copilot_allow_dev_tool_access = false` を新設し、
`copilot_read_allow` / `copilot_write_allow` で必要な範囲を明示する。

### 「補償」から「主たる許可リスト」への役割変更

`copilot_read_allow` は元々「自動付与の取りこぼしを埋める」ためのもので、
[ADR-0007](0007-filesystem-guard-boundary.md) では
「片方の自動付与を再現する**許可**」と位置付けていた。

自動付与を切った以上、このキーは **Copilot が $HOME 配下で読める場所の全体**を
決める。`claude_read_allow` と内容がほぼ同じになるのは、
補償の対象が無くなって両者が同じ役割になったため。

ただし ADR-0007 の原則「**CLI 固有キーに禁止を置かない**」は変わらない。
`copilot_*` に増えたのは許可だけで、遮断は共有キー `deny` と hook にある。

### 分類の方針

- **read-only を既定にする。** 書き込みはキャッシュ類に限る
- **read と write に同じパスを書かない。** RO/RW の競合解決は出所を区別しない
  ので、ユーザ指定どうしでも write が RO に潰される。write は read を含むため
  書きたい場所は write 側にだけ書く (`build_copilot_sandbox` が重複で失敗する)
- **`~/.local/share/mise` を write に入れない。** `PATH` 上のツールの実体を
  差し替えられてしまう。read だけで `mise exec` は動く
- **ホーム外 (`/usr/include` `/usr/local` `/usr/src` `/opt`) は Copilot にだけ要る。**
  Claude の `denyRead` は `~/` 配下だけなので元から読める

### 判断基準の変更

「自動付与に任せられるか」ではなく、
**「明示できない許可には頼らない」**を基準にする。

これは fail-closed を選ぶというこのリポジトリの一般方針と同じ向きで、
自動付与だけが例外的に fail-open 側 (壊れていても表示上は正常) だった。

## 完了条件

- [x] `copilot_allow_dev_tool_access` を `common.toml` に追加する
- [x] `build_copilot_sandbox` が `allowDevToolAccess` を出力する
- [x] `validate_sandbox_keys` の既知キーに加える
- [x] `copilot_read_allow` / `copilot_write_allow` を主たる許可リストへ改訂する
- [x] 「Copilot は Claude の許可リストを受け取らない」テストを
      「生成側が参照するキーが正しい」テストへ置き換える
- [x] read と write に同じパスを書けないよう生成側で検出する
      (ユーザ指定どうしでも RO に潰されるため)
- [ ] dev-tool OFF の状態で `pre-commit run --all-files` と
      `pytest test/agents/` が通ることを実測する

## 結果

### ポジティブな結果

- `~/.cache/uv` の EROFS が解消し、`uv run` が素で動くようになった
  (`findmnt` で同じ mount が `ro` → `rw` へ変わることを確認)
- Copilot が読み書きできる場所が `common.toml` だけで決まるようになった。
  `/sandbox policy` の表示と突き合わせなくても範囲が分かる
- 足りないパスは不可視 (ENOENT) か EACCES で即座に失敗するので、
  「効いているつもりで効いていない」状態が起きなくなった

### ネガティブな結果

- 新しいツールチェーンを入れたら `copilot_read_allow` への追記が要る。
  自動付与があれば不要だった作業
- 許可リストが `claude_*` と `copilot_*` でほぼ重複する。
  共有キーへ統合したくなるが、ホーム外の扱いが違う (Claude は元から読める) ため
  そのままにしてある

### 中立的な結果

- 上流が `github/copilot-cli#4846` を修正しても、この決定を戻す必要は無い。
  明示した許可は自動付与の有無に関わらず効く
- `allowDevToolAccess` は `/sandbox config` の TUI からも切り替えられるが、
  `chezmoi apply` で `common.toml` の値に戻る。手で変えた設定は残らない

## 関連 ADR

- [ADR-0007](0007-filesystem-guard-boundary.md): CLI 固有キーは許可の補償にだけ
  使うという原則。本 ADR で `copilot_read_allow` の役割が「補償」から
  「主たる許可リスト」へ変わったが、禁止を置かない点は維持している
- [ADR-0001](0001-external-tool-config-coexistence.md): 外部ツールが書き込む
  設定領域との共存。`settings.json` の sandbox キーもこの枠組みで扱う
