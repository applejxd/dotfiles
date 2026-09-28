# OpenCode の DB を srt の境界の内外で共有できるか

> **後続の観測**: 記録 E1 の書き込みの負荷に使った `session.synthetic` は、外側の serve では既定モデルの
> エージェントを境界の外で動かしうる（[Fence の調査](permission/fence.md) の「実験中の事故」）。
> E1 のセッション数は期待値と一致していたが、同じ方法を繰り返さない。

<!-- 現在の総合判断は docs/change/0009-ocs-simplify-for-accidents.md の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 E1 — 2026-09-29

- **対象バージョン**: OpenCode `v2.0.14`（`~/.opencode/bin/opencode`）/
  `@anthropic-ai/sandbox-runtime` `0.0.76`（`cli.js --version` は `1.0.0` と出るが、
  `package.json` は `0.0.76`）
- **環境**: Ubuntu（WSL）/ 基準コミット `62efd96`
- **実施**: 子エージェント（`bypass-worker`）。ホストの実 DB・常駐サービス・実設定には触れていない

### 問い

`ocs`（OpenCode を `srt` の境界で包むランチャー。[仕様](../../spec/opencode-sandbox.md)）は、
ワークスペースごとの隔離用 DB を使っている。これをやめ、ホストの DB とデータディレクトリを
境界の内側と外側（常駐サービス）で共有したとき、次が成り立つか
（[CHG-0009](../../change/0009-ocs-simplify-for-accidents.md) の段 1）。

1. 内外から同時に書いても DB が壊れないか
2. 内側で作ったセッションを外で再開できるか
3. 内側で取った snapshot から、外で `/undo` できるか
4. 内側から書けるようにする範囲はどこまで要るか

### 事前の予想

SQLite の WAL なら同時書き込みは通る。snapshot は置き場のパスの決め方しだいで、
内外で別の場所になるかもしれない。

### 方法・条件

「ホストのデータディレクトリ」を一時ディレクトリで見立てた。

- 環境: `env -u OPENCODE_CONFIG` にし、`XDG_DATA_HOME` / `XDG_STATE_HOME` /
  `XDG_CACHE_HOME` / `XDG_RUNTIME_DIR` / `OPENCODE_DB` / `OPENCODE_CONFIG_DIR` を
  すべて一時ディレクトリへ向けた
- 外側: 見立てた DB で `opencode serve --port 47291` を動かし、常駐サービスの代わりにした
- 内側: `srt` の境界の中で `opencode --standalone`（`opencode api --standalone …`、
  `session list --standalone`、`script` 越しの TUI、`run --standalone`）
- 境界: `ocs` の `build_boundary` を最小限で真似た。`denyRead` は `~`・`/mnt`・`/tmp`・
  `/var/tmp`・`/dev/shm`。`allowRead` / `allowWrite` にワークスペースと
  `<見立てた XDG_DATA_HOME>/opencode` を入れた（`allowRead` には `~/.opencode` と mise も）
- 書き込みの負荷: モデルを呼ばない `session.create` と `session.shell`（外側は
  `session.synthetic` も）をループで回した
- snapshot と再開だけは、モデルを呼ぶ必要があるので `scripts/opencode_probe.sh`
  （資格情報の行だけを一時の DB へ写す試験の方法）を使った。資格情報を含む DB は終了後に削除した
- 整合性: sqlite3 の CLI が無いので、Python の sqlite3（3.45.1）で `PRAGMA integrity_check`

```console
opencode api --standalone session.create -d '{"title":"inner-loop-1","location":{"directory":"<ws>"}}'
opencode api --standalone session.shell --param sessionID=<ID> -d '{"command":"echo inner-1 >> loop-inner.txt"}'
```

### 結果

| 問い | 結果 |
| --- | --- |
| 1. 同時書き込み | **通った。** 内側の TUI を 90 秒動かしたまま、内側 15 回・外側 30 回の作成と shell を並行、さらに内側 3 本 × 8 回と外側 3 本 × 15 回を同時に流して全件成功。セッションは 146 件で期待値と一致。ログに busy / locked は 0 件。`integrity_check` は serve の動作中も停止後も `ok`。`-wal` / `-shm` ができる。OpenCode は `journal_mode=WAL` と `busy_timeout=5000` で開く（バイナリの中の文字列で確認） |
| 2. 外での再開 | **通った。** 内側で作ったセッションを、外から `session list` / `get` / `export` と TUI の `-s <ID>` で開けた。内側で覚えさせた合言葉を、外から `opencode run --server … -s <ID>` で尋ねると答えた |
| 3. snapshot | **通った。** 内側の `run --standalone` がモデル経由で `a.txt` を編集して snapshot が記録され、外の serve で `revert.stage` → `revert.commit`（`/undo` 相当）を実行すると `a.txt` が戻った |
| 4. 書き込みの範囲 | `XDG_DATA_HOME/opencode/` 全体が要る（下の表） |

snapshot の置き場は `$XDG_DATA_HOME/opencode/snapshot/<projectID>/<sha1(worktree の realpath)>`。
中身は `objects/info/alternates` でワークスペースの `.git/objects` を参照する。
`projectID` は origin があれば `sha1("git-remote:<host>/<path>")`（実 DB の chezmoi の値と一致）、
無ければ gitdir の `opencode` ファイル、それも無ければ root commit（この 2 つはバイナリを読んだだけ）。
`srt` の境界は同じパスをそのまま見せるので、内外で同じキーになる。

`XDG_DATA_HOME/opencode/` の中身（実データディレクトリは名前だけ確認。中身は読んでいない）:

| 名前 | 用途 |
| --- | --- |
| `opencode.db`・`-wal`・`-shm` | DB。資格情報は別ファイルではなく DB の `credential` / `account*` テーブルにある |
| `snapshot/` | 全プロジェクトの snapshot |
| `shell/<projectID>/*.out` | shell の出力 |
| `log/opencode.log` | 内外が同じファイルへ追記する |
| `repos/`・`tool-output/` | — |

`~/.local/state/opencode/` には `service.json`（0600。常駐サービスへの接続情報とみられる）・
`model.json`・`prompt-history.jsonl`・`locks/` がある。ここは開けなくても動いた
（内側のモデルの選択と入力履歴が残らないだけで、今の `ocs` と同じ）。

**実験中に見つけた別件**（今の `ocs` にも当てはまる）:

- **ignore していないリポジトリでは snapshot が取れない（確認済み）。** `srt` は、
  ワークスペースに無い `.bashrc` / `.bash_profile` / `.gitconfig` / `.mcp.json` / `.vscode`
  などの名前へ `/dev/null`（文字デバイス）をマウントする。OpenCode の snapshot は
  `can only add regular files` で毎回失敗し、ログに WARN が出るだけだった。
  これらの名前を `.git/info/exclude` に並べると取れた。このリポジトリは `.gitignore` で
  ignore 済みなので影響しない
- **`TMPDIR` が境界の内側から見えない場所だと、通信が全部止まる（確認済み）。**
  `srt` の proxy が使う unix socket が内側から見えず、許可したドメインでも
  `CONNECT aborted` になった。`ocs` は `TMPDIR` をそのまま渡すので、`TMPDIR` が
  起動ディレクトリの外を指したまま起動すると同じことが起きるはず（推測）

### 考察

- 同時書き込み・外での再開・外からの `/undo` がどれも通ったので、DB とデータディレクトリの
  共有を妨げる事実は、この範囲では見つからなかった
- 共有にすると、境界の内側から書けるのは `XDG_DATA_HOME/opencode/` 全体になる。
  エージェントのうっかりで壊れるのは全プロジェクトの履歴と snapshot になり、
  他のプロジェクトの会話も内側から読める（[ADR-0012](../../adr/0012-ocs-boundary-for-accidents.md) で
  保証しないと決めた範囲）。資格情報は今の隔離用 DB にも写しているので、その点は変わらない

### 次の問い

- 同じセッションを内と外で同時に開いて操作したとき（未検証）
- 常駐サービスが古い版のまま、新しい版の内側が DB を移行したとき。起動時に 47 本の
  スキーマ移行が走る。更新したら常駐サービスを再起動する運用が要るかは推測
- 本物の `ocs` と本物の常駐サービスの組み合わせ（未検証）

### 参照

- 実験のスクリプト・境界の定義・ログはリポジトリに入れていない（`.tmp/opencode/chg9-db/`）
- SQLite の WAL: <https://www.sqlite.org/wal.html>
