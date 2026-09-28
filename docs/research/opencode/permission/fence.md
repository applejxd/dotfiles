# Fence は srt の代わりに OpenCode を包めるか

<!-- 現在の総合判断は docs/change/0009-ocs-simplify-for-accidents.md の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 E1 — 2026-09-29

- **対象バージョン**: Fence `v0.1.67`（Linux x86_64。GitHub Releases の `checksums.txt` と sha256 が一致）/
  OpenCode `v2.0.14` / 比較対象の `@anthropic-ai/sandbox-runtime`（`srt`）`0.0.76`
- **環境**: WSL2（カーネル 6.6、mirrored networking）/ bubblewrap 0.9.0 / Landlock ABI v3 / 基準コミット `b5ef47b`
- **実施**: 子エージェント（`bypass-worker`）。Fence は実験用ディレクトリにだけ置いた

### 問い

`ocs`（OpenCode を境界で包むランチャー。[仕様](../../../spec/opencode-sandbox.md)）の境界の道具を
`srt` から Fence に替えると、`srt` の癖（一部だけの `denyRead` が効かない、規則 R1、無い名前への
`/dev/null` のマウント、`TMPDIR`）が消え、[CHG-0009](../../../change/0009-ocs-simplify-for-accidents.md)
の評価基準の必須の項目を満たせるか。

### 事前の予想

Fence の文書（[configuration](https://github.com/fencesandbox/fence/blob/main/docs/configuration.md)、
[bwrap mount sequence](https://github.com/fencesandbox/fence/blob/main/docs/linux-bwrap-mount-sequence.md)）
どおりなら、読み取りは `--ro-bind / /` で全部許し、`denyRead` を `--tmpfs` / `/dev/null` で隠せる。

> Normal Mode: When `filesystem.defaultDenyRead` is **false**, Fence starts with: `--ro-bind / /`

### 方法・条件

- 設定の基本形（`fence.json`）: 通信は `api.githubcopilot.com`・`*.githubcopilot.com`・`opencode.ai`・
  `*.opencode.ai`・`models.dev`。`denyRead` は `~/.ssh`・`~/.gnupg`・`~/.aws`・`~/.config/gh`・
  `~/.git-credentials`・`~/.local/state/opencode`・`~/.local/share/opencode`・
  `~/.local/state/opencode-sandbox` と目印。`allowWrite` はワークスペースと実験用の HOME。
  `denyWrite` はワークスペースの `.opencode`
- 派生: 祖先を `allowRead` に入れる（R1）、`defaultDenyRead`、`TMPDIR` を隠す、worktree
- OpenCode は `env -u OPENCODE_CONFIG` にし、XDG・DB・設定を実験用ディレクトリへ向けた。
  モデルを呼ぶ試験は `scripts/opencode_probe.sh` と同じ方法の一時 DB（終了後に削除）
- 秘密の場所は中身を読まず、内側から見えるエントリの数で判定した

```console
fence --settings fence.json -- opencode run --standalone -m github-copilot/gpt-5-mini '<a.txt を編集させる指示>'
```

### 結果

| # | 項目 | 結果 | `srt` との違い |
| --- | --- | --- | --- |
| 1 | 秘密が読めない | 通った。目印は読めない。`~/.ssh` などは内側のエントリ数 0（ホスト側は 24・4・0・2・5・8・2） | `srt` では一部だけの `denyRead` が無視された |
| 2 | 起動ディレクトリの外が読める | 通った。`~/src`・`~/worktrees`・`~/papers`・chezmoi の README が読める | `srt` は `allowRead` に書いた所だけ |
| 3 | R1 | 起きない。祖先を `allowRead` に入れてもワークスペースへ書ける。祖先を `allowWrite` にしても `denyRead` は効く | `srt` では起きた |
| 4 | 外へ書けない | 通った。ワークスペース外・HOME・`~/.bashrc`・`~/.cache` は EROFS。`.git/config` と `.git/hooks` も既定で読み込み専用 | — |
| 4' | `denyWrite` | **まだ存在しないパスには効かない。** `ws/.opencode` を mkdir できた（glob でも同じ）。存在すれば拒否 | `srt` は存在しないパスの作成も止めた |
| 5 | 通信 | 通った。許可ドメインは HTTP / SOCKS とも通り、example.com・github.com は拒否。プロキシを無視した接続・IP 直接・ホストの loopback は不可 | 同等 |
| 6 | OpenCode | 通った。TUI は `script` 越しに描画（`allowPty` の有無とも）。Copilot のモデルで a.txt を編集できた | 同等 |
| 7 | snapshot / `/undo` | 通った。ignore の無いリポジトリで WARN が出ず、置き物も無い（`git status` は `M a.txt` だけ）。外の serve の revert で戻った | **`srt` の `/dev/null` の置き物は起きない** |
| 8 | DB の共有 | 通った。内側 10 件と外側の並行作成で `integrity_check` は `ok`（serve の稼働中に読み取り専用の接続で測定。停止後は未測定） | 同等 |
| 9 | `TMPDIR` | 見えない場所でも通信は止まらない（プロキシのソケットを直接マウントする）。ただし `TMPDIR` が `denyRead` の下だと、内側の `TMPDIR` が書けないまま残る | `srt` では通信が全部止まった |
| 10 | worktree | 通った。共有 `.git` を `allowWrite`、`hooks` と `config` を `denyWrite` にすると、`status` と `commit` が通り、hooks と config は書けない | 同じ設計で動く |
| 11 | WSL の `/mnt/c` | Landlock で一覧・読み取りはできないが、stat は通る（存在は分かる）。`denyRead: ["/mnt/c"]` で完全に隠れる | `srt` では `/mnt` ごと拒否していた |

そのほかの観測:

- **起動時間**: `true` の実行で Fence 約 1.17 秒、`srt` 約 0.4 秒（各 3 回）。機能の検出に約 0.65 秒
- **残骸**: 起動ごとに `$TMPDIR/fence-seccomp/*.bpf` が 1 個残る（19 回で 19 個）。プロキシのソケットもホストの `TMPDIR` に作られる
- **設定の探し方**: `--settings` を省くと、カレントディレクトリとその親から `fence.json` を探す。
  リポジトリが境界を決められてしまうので、ランチャーは必ず `--settings` を渡す
- **既定で守られるもの**: `~/.bashrc`・`.zshrc`・`.profile`・`.gitconfig` などは読み込み専用。
  `systemctl`・`unshare`・`chroot` などの実行ファイルは `/dev/null` で潰される
- `defaultDenyRead`（`srt` と同じく広く拒否して開け直す形）でも R1 は起きなかった

### 考察

- `srt` の癖 4 つのうち、一部だけの `denyRead`・R1・snapshot の置き物は消え、`TMPDIR` は通信が
  止まらなくなった。評価基準の必須の項目は、4'（存在しないパスへの `denyWrite`）を除いて通った
- 既定の「全部読めて名指しで隠す」形では、**新しくできた秘密の置き場が既定で見える。**
  `defaultDenyRead` にして読める場所を並べる形なら、今の `ocs` と同じく未知の場所は見えないまま、
  R1 に縛られずに親ディレクトリを開けられる
- 起動が約 0.8 秒遅くなる

### 次の問い

- `~/.config/opencode/service.json`・sops / age の鍵を名指しで隠せるか（未試験）
- Landlock が使えないカーネルでの挙動、長時間の TUI（リサイズなど）、停止後の DB の `integrity_check`
- WSL の `/mnt/c` を境界チェックで「読めるか」で判定できるか（stat は通るので「在るか」では誤判定しうる。推測）

### 実験中の事故

外側で起動した一時の `opencode serve` に `session.synthetic` を送ったところ、既定モデル
（`opencode/longcat-2.5-preview-free`）のエージェントが**境界の外で**動き、実験用のスクリプトを
繰り返し実行して、一時 DB にセッションを約 10 分で 1111 件作った。書き込みは実験用ディレクトリの
ログだけで、実 DB には `SELECT` とファイル一覧だけがあった（DB に残ったコマンド履歴で確認）。
serve は停止し、一時パスワードも削除した。**モデルを呼びたくない試験で `session.synthetic` を使わない。**
[DB の共有の調査](../shared-db.md) の記録 E1 も同じ API を使っている。

### 参照

- 実験のスクリプト・設定・ログはリポジトリに入れていない（`.tmp/opencode/chg9-fence/`）
- Fence: <https://github.com/fencesandbox/fence>（リポジトリの `configuration.md`・`linux-bwrap-mount-sequence.md`・`security-model.md`）
