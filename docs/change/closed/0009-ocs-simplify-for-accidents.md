# CHG-0009: ocs をうっかりの防止に必要な分まで簡素にする

- **状態**: Done
- **更新日**: 2026-09-29
- **終了日**: 2026-09-29
- **基準**: `62efd96`（OpenCode `v2.0.14` / `@anthropic-ai/sandbox-runtime` `0.0.76`）

> **この文書は当時の記録。** 現在の仕様は [opencode-sandbox](../../spec/opencode-sandbox.md)。
> 採用したもの・見送ったもの・反映先・移管した未完事項は「終了結果」にまとめた。
> 「未解決点」と「次の調査・実験」は、配備の前（2026-09-29 の実装時点）の記録。

## 目的と非目的

`ocs` は、OpenCode を `srt`（OS の境界を張る道具。bubblewrap・seccomp・通信の proxy）で
包んで起動するランチャー（[仕様](../../spec/opencode-sandbox.md)）。

**目的**: [ADR-0012](../../adr/0012-ocs-boundary-for-accidents.md) で境界の目的を
「エージェントのうっかり（外部への誤送信、ワークスペース外の破壊、秘密の誤読）を防ぐ」に
絞った。その目的に要らない上乗せを外し、使い勝手を Claude Code の sandbox に近づける。
中でも次の 3 つの不便を解消する。

- 履歴が通常起動と分かれ、`ocs --handoff` / `ocs --list-sessions` で行き来する必要がある
- 起動ディレクトリの外（別のリポジトリや資料）をエージェントが読めない
- 起動時に、承認の確認や境界チェックで待たされたり断られたりする

**非目的**:

- 悪意あるワークスペースやプロンプトインジェクションへの耐性（ADR-0012 の「保証しないもの」）
- `ocs` をハーネス非依存にすること（[CHG-0007](../0007-harness-profiles.md) の段 3）
- 改名（CHG-0007 の段 4）

## 実施計画

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 0 | `srt` の癖（一部だけの `denyRead` が効かない、無い名前への `/dev/null` のマウント、`TMPDIR`）を避けたい | 境界の道具を `srt` から Fence（bubblewrap + Landlock + seccomp とドメイン単位のプロキシ）へ替えられるか、評価基準の必須の項目で試す。段 2 以降の形がこの結果で変わる | 完了（Fence に替えた。読み取りは `defaultDenyRead` で読める場所を並べる形。`c752f69` / `e4c525b`） |
| 1 | 履歴を分けたくない | ホストの DB を境界の内外で共有できるかを、一時の DB で確かめる | 完了（通った） |
| 2 | 同上 | DB を共有し、`--handoff` / `--list-sessions` と隔離用 DB の用意を消す。今ある隔離セッションを先に移す | 完了（`e4c525b`。本物の `ocs` で確認） |
| 3 | 起動時の承認の確認をなくしたい | `.opencode/sandbox.toml` の承認の記録（`trusted.json`・`--trust`）をやめ、追加する書き込み先と通信先を表示するだけにする | 完了（同上） |
| 4 | 起動時の検査の待ちをなくしたい | 境界チェックを `ocs --check` の手動実行にする。自動で走らせるなら、境界の定義か `srt` が変わったときだけ | 完了（同上。手動のみ） |
| 5 | 起動ディレクトリの外を読みたい | 秘密を含まない作業用の親ディレクトリを `allowRead` で開ける。秘密の目印が読めないままかを確かめる | 完了（同上。`work_read`） |
| 6 | 保守の手間を減らしたい | 隔離版の設定の毎回の書き出しを、`chezmoi apply` 時の生成へ寄せられるか検討する | 検討済み（寄せられる。実装は未着手。下の「段 6 の検討」） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

- 2026-09-29 に ADR-0012 を Accepted にし、この案件を起こした
- 2026-09-29 に代わりの道具を調べた（NVIDIA OpenShell、Docker Sandboxes、nono、landrun、Fence ほか）。
  不便の多くは `ocs` の設計が原因で、道具を替えても消えない。`srt` の癖が原因のものは、
  Fence が文書上は解消している（読み取りは `--ro-bind / /` の後に `denyRead` を `--tmpfs` で隠す、
  内側で `TMPDIR` を直す）。コンテナや microVM の方式は、道具の二重管理と設定・履歴の分離が
  戻るので合わない。Landlock だけの方式（nono・landrun）は、広く許した中の一部を隠せない
- **段 0 の実験で、Fence は 11 項目中 10 項目を満たした**（[Fence の調査](../../research/opencode/permission/fence.md)）。
  一部だけの `denyRead`・R1・snapshot の置き物・`TMPDIR` の問題は消えた。満たさなかったのは
  「まだ存在しないパスへの `denyWrite`」で、起動前に作っておけば避けられる。代わりに起動が約 0.8 秒遅く、
  起動ごとに `TMPDIR` へ残骸が 1 個残る。`ocs` 本体は約 50〜60 行減る見込み
- **2026-09-29 に利用者が Fence へ替えると決めた。** 読み取りは `defaultDenyRead` で広く拒否し、
  読める場所（道具の置き場と `~/src`・`~/worktrees`・`~/papers`・`~/.local/share/chezmoi`）を並べる。
  名指しで隠す形は、新しい秘密の置き場が既定で見えるので採らない。Fence には R1 が無いので、親ディレクトリを丸ごと開けられる
- **隔離用のデータ領域が原因の暴走を見つけた（2026-09-29）。** `ocs` は `XDG_DATA_HOME` を
  `.opencode-sandbox/data` へ向けるので、境界の内側の mise は導入済みの道具を見つけられず、
  そこへ入れ直していた（このリポジトリで 796 MB）。Ruby の入れ直しでは、`gem` の shim が自分を
  呼び続ける連鎖になり、9/23 から `gem sources` が 846 個入れ子で残っていた（止めて片付け済み）。
  段 2 で `XDG_DATA_HOME` の上書きをやめれば起きなくなる
- **段 1 は通った**（[DB の共有の調査](../../research/opencode/shared-db.md)）。一時の DB で、
  境界の内外からの同時書き込み（146 件、`integrity_check` は `ok`）、内側のセッションの外での
  再開、内側の snapshot からの外での `/undo` がどれも動いた。境界の内側から書けるように
  する範囲は `XDG_DATA_HOME/opencode/` 全体（DB・WAL・SHM・snapshot・shell の出力・ログ）。
  `~/.local/state/opencode/`（常駐サービスの接続情報 `service.json` がある）は開けなくてよい
- 段 1 の途中で、今の `ocs` にも当てはまる不具合が 2 つ見つかった。
  - `srt` がワークスペースに無い `.bashrc` などの名前へ `/dev/null` をマウントするので、
    ignore していないリポジトリでは OpenCode の snapshot が毎回失敗し、`/undo` が効かない
  - `TMPDIR` が境界の内側から見えない場所だと、`srt` の proxy へ届かず通信が全部止まる
- ADR-0012 に合わない過去の修正（ホストで動く `git` / `opencode` の固め、各エージェントへの
  deny の差し込み）は、コミット前に取り下げ済み（`58c4dfb`〜`62efd96` の組み直し）
- 段 5 には制約がある。`srt` 0.0.76 では `~/.ssh` のような一部だけを拒否する `denyRead` が
  黙って無視される（[sandbox-runtime の調査](../../research/opencode/permission/sandbox-runtime.md) 3 章）。
  「全部読めて秘密だけ拒否」にはできず、「広く拒否して必要な所を開ける」形のまま、
  開ける範囲を広げる

- **段 0・2〜5 を worktree `loop/fence` で実装した（2026-09-29、未コミット・未配備）。**
  実機の Fence 0.1.67 で評価基準の必須の項目が全部通った（下の「実装・検証」）。
  実装中に、`~/.local/state` を開けないと opencode が起動時に `EROFS` で止まることを
  見つけ、内側の `XDG_STATE_HOME` を内側の `/tmp` へ向けた

## 未解決点

> 2026-09-29 の配備前の時点。配備と本物の `ocs` での確認は「実装・検証」の「配備後」で済んだ。

- **配備**: 利用者が `mise install`（Fence）と `chezmoi apply` をするまで、実機の `ocs` は
  旧版のまま。mise の github backend が `~/.local/share/mise/installs/github-fencesandbox-fence/latest/fence`
  に入れることは、他の backend の命名と tar.gz の中身からの推測で、未確認
  （違えば `rules.json` に境界が出ず、`ocs` は起動を断る）
- **本物の常駐サービスとの組み合わせ**: 一時 DB での再開と `/undo` は通ったが、実 DB と
  本物の常駐サービスでは未確認（下の段 2 の項目と同じ）
- 起動ディレクトリがリポジトリの下位ディレクトリのとき、そのリポジトリの共有 `.git` が
  書ける（worktree と同じ扱い。`srt` のころから同じ）。うっかりで `.git` を壊しうるが、
  commit には要る。仕様の「既知の制約」に書いた
- **段 2**: 同じセッションを境界の内と外で同時に開いて操作したとき（未検証）。
  運用で避ける（同じ ID を内外で同時に開かない）と仕様に書いた
- 常駐サービスが古い版のまま新しい版が DB の形を移行すると壊れうる（推測）。
  OpenCode を更新したら常駐サービスを再起動する運用と仕様に書いた
- **段 5 の置き場**: 4 つの作業用ディレクトリは `common.toml` の `work_read` に置いた。
  無いものは起動時に落とすので、機械ごとに違っても `local.toml` は要らない
- 解決済み: 段 1 で見つけた 2 つの不具合（`srt` の `/dev/null` の置き物、`TMPDIR`）は
  Fence で起きない（記録 E2 で `git status` は `M a.txt` だけ）。存在しないパスへの
  `denyWrite` は起動前に空のディレクトリを作って塞いだ。`TMPDIR` の残骸は次の起動で
  掃除する。Fence は mise の github backend で版とチェックサムを固定した

## 次の調査・実験

> 2026-09-29 の配備前の時点。1〜3 は済んだ（隔離セッションは試験用の 4 件だけで、移さなかった）。4・5 は「終了結果」で移管した。

worktree `loop/fence` の変更をコミットして配備する前後の作業。

1. **配備の前に**、残したい隔離セッション（`.opencode-sandbox/opencode.db`。このリポジトリにも
   実在）を、配備済みの旧 `ocs --handoff <ID>` でホストの DB へ移す。新しい `ocs` には
   `--handoff` が無い。移し忘れても `OPENCODE_DB=<パス> opencode --standalone` で開ける
   （仕様「セッションの引き継ぎ」）
2. 配備: `mise install`（Fence）→ `chezmoi apply`。`rules.json` に `sandbox` 節が出て、
   `~/.local/share/mise/installs/github-fencesandbox-fence/latest/fence` が在ることを確かめる
3. 本物の `ocs` で `ocs --check` が合格し、本物の常駐サービスで外での再開と `/undo` が
   通ることを確かめる
4. 同じセッションを内と外で同時に開いたときの挙動（未検証。運用で避ける）
5. 段 6（隔離版の設定の生成を `generate.py` へ寄せる）を実装するか決める

## 評価基準

ADR-0012 の「決定の確認方法」をそのまま使う。

**必須**:

- 秘密の目印（無害なファイル）を `~/.ssh` 相当の場所に置き、境界の内側から読めない
- 許可していないドメインへ出られない
- 起動ディレクトリの外（許可した例外を除く）へ永続的に書けない
- 普段の作業（別のリポジトリや資料を読む、worktree で commit する）ができる
- 境界の内側で作ったセッションを、境界の外で再開でき、snapshot から戻せる
- `test/agents/` が全件通る

**望ましい**:

- `ocs` のコードが減る
- 起動時に確認や検査で待たない

**レビューの終わり方**: 外部レビューには上の必須の項目と ADR-0012 の「保証しないもの」を渡す。
「保証しないもの」に入る指摘は docs への記載で閉じ、コードで追わない。

## 候補比較

段 0（境界の道具）。

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| `srt` のまま | 段 1 で DB の共有が動いた。Claude Code と同じ実体で、導入済み | 一部だけの `denyRead` が効かない、R1、`/dev/null` のマウントで snapshot が取れない、`TMPDIR` で通信が止まる | — | 見送り（`ocs` では替える。Claude Code は引き続き使う） | — |
| Fence | 段 0 の実験で必須の項目を満たした（存在しないパスへの `denyWrite` を除く）。`srt` の癖 4 つが消えた。脅威モデルが ADR-0012 と一致 | 0.1.x で開発元が 1 社。Go の実体を新しく入れる。起動が約 0.8 秒遅い。`TMPDIR` に残骸。名指しで隠す形では新しい秘密の置き場が既定で見える（`defaultDenyRead` で避ける） | 停止後の DB の整合性、Landlock が使えないカーネル | 採用（`defaultDenyRead` の形） | 実装 |
| NVIDIA OpenShell | 資格情報の注入、ポリシーの監査 | alpha、Docker と gateway が要る、WSL2 は experimental。道具をイメージに入れ直し、設定と履歴が分かれる | — | 見送り（使い勝手を戻す目的に逆行する） | — |
| Docker Sandboxes / 各種コンテナ | 独立したカーネル（microVM） | サインインと KVM、利用者の設定を持ち込まない。道具の二重管理 | — | 見送り（同上） | — |
| nono / landrun（Landlock） | 軽い。nono は資格情報をプロキシで注入できる | 広く許した中の一部を隠せない。OpenCode の Copilot の資格情報は DB の中にある | — | 見送り（段 5 を表せない） | — |

段 2 の形。

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| ホストの DB を共有する | 履歴が 1 つになり、`opencode -s <ID>` がそのまま使える。`--handoff` / `--list-sessions` と隔離用 DB の用意（資格情報の写し）が消える。段 1 で同時書き込み・外での再開・外からの `/undo` が通った | エージェントのうっかりで DB を壊すと全部の履歴と snapshot に響く。他のプロジェクトの会話が境界の内側から読める（ADR-0012 で保証しないと決めた） | 同じセッションの内外での同時操作、版の違い、本物の `ocs` との組み合わせ | 採用 | 段 2 の実機確認 |
| 隔離用 DB を残し、外で再開するコマンドだけ足す | DB の被害が 1 プロジェクトに留まる。`OPENCODE_DB=… opencode --standalone -s <ID>` で外から開ける（仕様「隔離用 DB」） | 履歴は分かれたまま。外で再開すると通常版の設定になる | — | 見送り（段 1 で共有が通ったため。共有で DB の破損が実際に起きたら再検討） | — |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `docs/spec/opencode-sandbox.md` 全体 | `srt` と R1〜R4 → Fence（`defaultDenyRead`）の規則 | 段 0 | 適用済み（worktree） |
| 同「隔離用 DB」「セッションの引き継ぎ」 | 隔離用 DB と移送 → DB の共有 | 段 1・2 | 適用済み（worktree） |
| 同「状態の置き場」の承認（`trusted.json`） | 承認を記録 → 表示だけ | 段 3 | 適用済み（worktree） |
| 同「境界チェック」 | 24 時間ごとに自動 → 手動（`ocs --check`） | 段 4 | 適用済み（worktree） |
| 同「境界の中身」の `allowRead` | 個別に開ける → 作業用の親ディレクトリも開ける | 段 5 | 適用済み（worktree） |

## 実装・検証

### 段 1（2026-09-29）

一時の DB を「ホストの DB」に見立て、`opencode serve`（常駐サービスの代わり）と `srt` の
内側の `opencode --standalone` で共有した。結果と方法は
[DB の共有の調査](../../research/opencode/shared-db.md) の記録 E1。

| 確認 | 結果 |
| --- | --- |
| 同時書き込み | 内外で並行して 146 件作成、busy / locked 0 件、`integrity_check` は `ok` |
| 外での再開 | 内側のセッションを外の `-s <ID>` で開け、会話の文脈も続いた |
| 外からの `/undo` | 内側の編集を外の `revert.stage` / `revert.commit` で戻せた |
| 書き込みの例外 | `XDG_DATA_HOME/opencode/` 全体。`~/.local/state/opencode/` は不要 |

### 段 0・2〜5（2026-09-29）

worktree `loop/fence`（基準 `39ac692`）で実装し、実機（WSL2、Fence 0.1.67、OpenCode v2.0.14）で
確かめた。**配備済みの `ocs` は使わず**、worktree のコードを読み込んで境界の設定と起動の
引数を組み立てる試験用のスクリプトで、Fence に包んだ（`XDG_DATA_HOME` などは一時
ディレクトリへ向け、DB は資格情報の行だけを写した一時 DB。終了後に削除）。
観測の詳細は [Fence の調査](../../research/opencode/permission/fence.md) の記録 E2。

| 必須の項目 | 結果 |
| --- | --- |
| 秘密の目印が読めない | 通った。`~/.ssh`・`~/.gnupg`・`~/.aws`・`~/.config/gh`・`~/.config/sops/age`・`~/.local/state/opencode` は存在しない、`~/.git-credentials`・`service.json`（2 か所）・目印は開けない。開けた `~/.config/chezmoi` の中の `key.txt` は `/dev/null`。`/run/user` は空。WSL の `/mnt/c` は存在しない |
| 許可していないドメインへ出られない | 通った。`github.com` は 200、`api.githubcopilot.com` は 404（届いている）、`example.com`・`www.google.com` は拒否。`.opencode/sandbox.toml` で足した `example.com` だけは 200 |
| 起動ディレクトリの外へ書けない | 通った。`~`・`~/.bashrc`・`~/.config/opencode` は `EACCES`、`~/src`・`~/.local/share/chezmoi` は `EROFS`、`~/.local/state` は存在しない。`/tmp` は書けるがホストへ反映されない |
| 普段の作業 | 通った。`~/src`（13 件）・`~/worktrees`・`~/papers`・chezmoi の README が読める。linked worktree で commit でき、共有 `.git` の `hooks`・`config` と main 側のファイルは書けない。`~/.gitconfig` 経由の利用者名が見える |
| 内側のセッションを外で再開し、snapshot から戻せる | 通った。内側の `opencode run --standalone` がモデル経由で `a.txt` を編集（`git status` は `M a.txt` だけ）、外の `session list` に出て、外の `run -s <ID>` で内側の合言葉に答えた。外の `opencode api --standalone session.revert.stage` / `session.revert.commit` で `a.txt` が戻った。`integrity_check` は `ok` |
| `test/agents/` が全件通る | 通った（`test/` 全体で 2466 passed, 11 skipped） |

そのほか確かめたこと: `ocs --check` 相当の処理が合格（読めるかでの判定・データ
ディレクトリへの書き込みを含む）、TUI が `script` 越しに描画され、既定モデル
（Claude Opus 5）が選ばれた、Fence の `fence-seccomp/*.bpf` の古いものが次の起動で
消えた、`/dev/shm` は内側だけ、`/var/tmp` は見えない。

望ましい項目: `ocs` の本体（`~/.local/share/ocs/*.py`）は 1300 行から 945 行に減った。
起動時の確認と検査の待ちは無くなった（境界チェックは `ocs --check` だけ）。

### 配備後（2026-09-29）

`e4c525b` を push し、利用者が `chezmoi apply` と `mise install` で配備した。

- 初回の apply では `rules.json` に境界の設定が出なかった。`rules.json` はファイルとして先に
  作られ、Fence を入れる `125_mise.sh` はその後に走るため。境界の設定を Fence の有無に関係なく
  出すように直した（実体が無ければ `ocs` が起動を断る）
- 本物の `ocs` で `ocs --check` が合格した
- 本物の `ocs` と常駐サービス・実 DB で、利用者が次の 4 点を確かめた: `~/src` が読める、
  `~/.ssh` が見えない、`/undo` が効く、終了後に外の `opencode -s <ID>` で再開できる

### 段 6 の検討（2026-09-29）

隔離版の設定（`~/.config/opencode-sandbox/opencode.json`・`AGENTS.md`）の毎回の書き出し
（`ocs` の `config.py`、約 130 行）は、**`chezmoi apply` 時の生成（`generate.py`）へ寄せられる。**

- 差し替えるキー（`permissions`・`snapshots`・`policies`・`plugins`）と `AGENTS.md` は、
  どれも `common.toml` だけから決まる。`generate.py` は既に `rules.json` の `sandbox` 節で
  同じ値を作っているので、書き先を増やすだけで済む
- 利用者が TUI で選んだキーを残す処理は、通常版の `opencode.json` の生成
  （`merge_opencode_config`）と同じ形で書ける
- 失うもの: (1) 既定モデルの選択が、起動時の DB の資格情報ではなく apply 時のものになる。
  (2) 通常版から見た目のキーを引き継ぐのが apply 時だけになる。(3) 設定が外から
  書き換えられても次の起動では戻らない（ただし `~/.config/opencode-sandbox` は境界の
  内側から書けないので、守りの差は小さい）
- 寄せると `ocs` から `config.py` が消え、起動時の処理が境界の組み立てと退避だけになる。
  実装は別の段で行う（この段では変えていない）

## 重要な更新

- **2026-09-29**: 起票。ADR-0012 を Accepted にしたのに合わせ、実装を追う案件として起こした
- **2026-09-29**: 段 1 が通り、段 2 は DB を共有する形に決めた。隔離用 DB を残す案は見送り
- **2026-09-29**: 利用者の依頼で境界の道具そのものを見直し、段 0（Fence との比較）を足した
- **2026-09-29**: 利用者の判断で Fence に替える（`defaultDenyRead` の形）。隔離用のデータ領域が原因の mise の暴走を見つけて片付けた
- **2026-09-29**: 段 0 の実験で Fence は必須の項目を概ね満たした。実験中に、外側の serve へ送った `session.synthetic` でホストのエージェントが動く事故があった（書き込みは実験用ディレクトリだけ）
- **2026-09-29**: 段 0・2〜5 を worktree で実装し、必須の項目を実機で確かめた。段 6 は検討だけ（寄せられる）
- **2026-09-29**: 配備し、本物の `ocs` で必須の項目を確かめて終了した。初回の apply で境界の設定が出ない問題を直した

## 終了結果

**採用・配備済み。** `ocs` の境界を Fence に替え、履歴を通常の起動と共有し、承認と起動時の検査をやめた。
評価基準の必須の項目は、試験用のスクリプトと本物の `ocs` の両方で満たした。

### 採用したもの

- 境界の道具は Fence 0.1.67（mise の github backend で版とチェックサムを固定）。読み取りは
  `defaultDenyRead` で広く拒否し、道具の置き場と `work_read`（`~/src`・`~/worktrees`・`~/papers`・
  `~/.local/share/chezmoi`）を開ける
- DB と `XDG_DATA_HOME` をホストと共有する。`--handoff`・`--list-sessions`・隔離用 DB の用意を削除
- `.opencode/sandbox.toml` は確認なしで適用し、足す分を表示する。境界チェックは `ocs --check` の手動だけ
- 境界の設定は Fence の有無に関係なく `rules.json` に出す（初回の apply を 1 回で済ませる）

### 撤回・見送りしたもの

| 項目 | いつ | 理由 |
| --- | --- | --- |
| `srt` のまま続ける | 2026-09-29 | 一部だけの `denyRead`・R1・`/dev/null` の置き物・`TMPDIR` の癖が使い勝手を落としていた。Claude Code 用には残す |
| NVIDIA OpenShell・Docker Sandboxes・各種コンテナ | 2026-09-29 | 道具の二重管理と、設定・履歴の分離が戻る |
| nono・landrun（Landlock だけ） | 2026-09-29 | 広く許した中の一部を隠せない |
| Fence の「全部読めて名指しで隠す」形 | 2026-09-29 | 新しい秘密の置き場が既定で見える |
| 隔離用 DB を残し、外で再開するコマンドだけ足す | 2026-09-29 | 段 1 で DB の共有が通った。共有で DB の破損が実際に起きたら再検討 |
| 既存の隔離セッションの移送 | 2026-09-29 | 試験用の 4 件だけだった。古い `.opencode-sandbox/` は残り、`OPENCODE_DB=<パス> opencode --standalone` で開ける |

### 反映先

- 仕様: [opencode-sandbox](../../spec/opencode-sandbox.md)、[構成](../../spec/structure.md)、[セキュリティ](../../spec/security.md)
- 方針: [ADR-0012](../../adr/0012-ocs-boundary-for-accidents.md)
- 実装: `c752f69`（docs）、`e4c525b`（`ocs`・生成・mise・テスト）と、境界の設定を常に出す修正
- 観測: [Fence の調査](../../research/opencode/permission/fence.md)、[DB の共有の調査](../../research/opencode/shared-db.md)

### 移管した未完事項

| 内容 | 移管先 |
| --- | --- |
| 段 6: 隔離版の設定の書き出しを `chezmoi apply` 時の生成へ寄せる（検討は「実装・検証」の「段 6 の検討」） | 未起票 |
| 同じセッションを境界の内と外で同時に開いたときの挙動（仕様では運用で避けると書いた） | 未起票 |
| 常駐サービスが古い版のまま新しい版が DB を移行したとき（推測。仕様では更新後に再起動すると書いた） | 未起票 |
| Fence を Landlock が使えないカーネルで動かしたとき | 未起票 |
