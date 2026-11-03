# CHG-0057: プロジェクトごとの統合先・作業ブランチ接頭辞の設定（リポジトリ内の `pi.json`。フルガードを流儀の違う他のリポジトリへ広げる）

- **状態**: In progress
- **実装の前提**: v3（2026-11-02）。利用者の決定「グローバルへの集約は管理上よくない。プロジェクト内設定にしたい」と、独立 `review`（BLOCKER 2・MAJOR 4）を反映した
- **更新日**: 2026-11-02
- **基準**: pi 1.4.0、[CHG-0053](0053-worktree-integration-gate.md)（統合ゲート・自由区）・[CHG-0055](closed/0055-async-approval.md)（`git_integrate`）の上。方針は [ADR-0022](../adr/0022-containment-first-minimal-approvals.md)

## 1. 要約と状態

フルガードの統合まわりは、**このリポジトリの流儀**（統合先は `develop`、作業ブランチは `feature/*`・`bugfix/*`）を、コードの数か所に固定している。
他のリポジトリでは、自由区が働かず、統合の計算が断られ、`git flow … finish` の確認画面が別のブランチを見せうる。

- 方針（v3）: **各リポジトリの `.agents/config/pi.json`（JSON）で、統合先・統合元の接頭辞・自由区の接頭辞だけを変えられる**
- **保護ブランチは全体設定（`[pi.integrate] protected_refs`）のまま**。`pi.json` は保護を足さず・除かない
- 読むのは **HEAD にコミットされた内容（blob）だけ**。作業ツリーの編集は、コミットするまで反映されない
- 無効な設定は、設定全体を無効にして全体の既定へ戻す（診断は固定のコードとキー名だけ）
- **自由区は fail closed**（確認を省く側なので、設定の出所が信頼できない・読めないときは自由区にしない。§5）。`git_integrate` は承認があるので、読めないときは既定へ戻す
- 状況: S1+S2・S3a・S3b・`risk_paths`・分類器の穴 2 件は、すべて取り込み済み（2026-11-02）。**S4 の実機確認（架空の一時リポジトリ）は未実施**。確認省略（自由区の `pi.json`）の配備は実機確認の後で、実際の `pi.json` はどのリポジトリにもまだ無い（§7）

## 2. 目的と非目的

**目的**: 流儀の違うリポジトリでも、同じ安全の保証（保護ブランチへの統合は必ず確認・自由区は linked worktree の作業ブランチだけ）を保ったまま、フルガードを使えるようにする。

**非目的**:

- 保護ブランチをリポジトリ内の設定で足す・除くこと
- 他のリポジトリの実パスを、この公開リポジトリへ置くこと
- git-flow の設定（`.git/config` の `gitflow.*`）の自動読み取り
- `hotfix`・`release`・`support` の接頭辞
- pi の project trust との連動（後から足せる。§8）

## 3. 現状（固定している場所）

| 場所 | 固定していること |
| --- | --- |
| `judge/protectedrefs.ts`（`isFeatureSourceRef`）・`freezone.ts` | 自由区の接頭辞は `feature/` だけ（`bugfix/` は自由区ではない） |
| `integration-gate.ts`（96〜98 行付近） | 自由区なら、HEAD を動かす統合の操作の必須確認を省く。自由区の集合が省く範囲を決める |
| `integrate-plan.ts`（`bad_source`・`stackedOf`） | 統合元は `feature/*`・`bugfix/*`。積み重ねの列挙も同じ |
| `index.ts`（`integrationTarget`）・`confirm-view.ts`（`parseFinishTarget`） | 統合先は全体の `target` 1 つ。`git flow <型> finish <名前>` のブランチ名を `<型>/<名前>` に合成して履歴・差分・衝突を調べる |
| `actions.ts`・`pending-adapters.ts`・`integrate-action.ts` | 設定を、対象の cwd を解決する前に取る |
| `board.ts`・`board-collect.ts` | 表示の `feature/`・`bugfix/` |
| `[pi.integrate]` の `target`・`protected_refs` | 全体で 1 つ（生成器が下限 `main`・`master`・`develop`・`release/*`・`hotfix/*` を検査） |

自由区（`feature/`）と統合元（`feature/`・`bugfix/`）は**別の集合**。1 つのリストに潰すと、`bugfix/*` の確認条件が変わる。

## 4. 利用者の決定と段 0 の回答

| 項目 | 内容 |
| --- | --- |
| 設定の置き場 | 各リポジトリの中（`.agents/config/pi.json`）。グローバルへ集約しない（管理上） |
| 形式 | JSON（ハーネスは TOML を読めない） |
| pi の project trust | 連動しない（後から足せる） |
| 保護ブランチ | 全体設定のまま（既定。回答が無かったので、安全側の推奨で進めた） |
| 読む対象 | HEAD のコミット済みの内容だけ（同上） |

段 0 の回答（2026-11-02。利用者の報告。条件つき）:

- 統合先: `production`・`develop` など、リポジトリごとにケースバイケース。今の保護ブランチの既定には `production` が無かった
- 作業ブランチの接頭辞: 決まっていない（`feature/*` で開発する例がある）
- 統合方式: squash
- 確認できた必要のうち、「`production` が保護でない」は全体の `protected_refs` への追加（feature `protect-production`）で足りる。接頭辞と統合先の選択は、`pi.json` で各リポジトリが決められるようにした

## 5. 確定した設計

詳細な仕様は [pi の拡張](../spec/guard/pi-extensions.md#プロジェクトごとの設定pijson)・[保留（撤去済み・履歴）](../spec/guard/pi-pending.md)・[利用者マニュアル 7.6](../spec/pi-manual.md#76-プロジェクトごとの設定pijson)。

| 項目 | 決めたこと |
| --- | --- |
| 置き場 | `<repo>/.agents/config/pi.json` |
| 形 | `{"integrate": {"target": …, "source_prefixes": […], "free_zone_prefixes": […]}}`。全て省略可 |
| 省略の既定 | `target` = `[pi.integrate] target`・統合元 `["feature/", "bugfix/"]`・自由区 `["feature/"]` |
| 変えられないもの | 保護ブランチ。`protected_refs`・`extra_protected_refs` は `protected_refs_not_allowed`（設定全体が無効） |
| 読み方 | HEAD の blob だけ（`git --no-replace-objects ls-tree -l` → `cat-file blob`。`git replace` で差し替えさせない）。ファイルが無いときは「設定なし」。`ls-tree`・`cat-file` の失敗・`ls-tree -l` の出力を解釈できない（blob 欠けはサイズ欄が `BAD` で終了コード 0）は `readFailed` |
| 読めないとき（扱いを分ける） | `git_integrate`・`/board`: 全体の既定へ戻す（承認・表示だけで、確認を省かない）。**自由区・raw `finish` のプレビュー: fail closed**（自由区にしない・「確認できない」）。`readFailed` と「設定が無い・無効」は別（後者は従来どおり既定）。`ls-tree` が失敗する場合（HEAD が無い＝未コミットを含む）も `readFailed`（コード上の事実。`profile` は既定のまま） |
| 無効のとき | 設定全体が無効 → 全体の既定 + 診断コード（入力の本文・値は出さない） |
| キャッシュ | blob ID（と全体の既定）が鍵 |
| 検査 | `target` は全体の保護の完全一致の要素。接頭辞は形の検査と、保護との非交差（C5） |
| `git_integrate` | 要求は要求した pi の cwd の設定、承認と再検査は承認する pi の cwd（統合先の主 worktree）の設定で作り直す |
| 自由区の設定元 | 接頭辞は主 worktree（common dir）の HEAD の `pi.json` だけから読む。feature 自身の HEAD の設定は読まない |
| 自由区の信頼条件（C2 の例外） | **common dir の HEAD が、保護ブランチ上の symbolic ref でなければ自由区にしない**（detached・判定不能・非保護ブランチ）。**設定の有無にかかわらず**。設定が無いリポジトリでも、主 worktree が detached・非保護ブランチ上だと自由区は効かず確認が増える。理由は §10 |
| 自由区のその他の条件 | linked worktree の管理ディレクトリが `<common dir>/worktrees/` の下にある（`.git` ファイルの書き換えによる偽の worktree を除く）。保護ブランチの拒否は残る。観測の添え書き（`details.freeZone.profile`）は診断コードだけ |
| 自由区の git の起動 | `rev-parse` + `symbolic-ref`（feature）+ `symbolic-ref`（主 HEAD）+ `pi.json` の `ls-tree`（計 4 回。blob があれば `cat-file` が 1 回増える） |
| raw `git flow … finish` のプレビュー | **cwd の HEAD と主 worktree（common dir）の HEAD の両方**を読み、どちらかが `target` か `source_prefixes` を既定から変えている・読めないときは「統合の内容は確認できない」。`free_zone_prefixes` だけの変更では止めない |
| `/board` | 実効の `source_prefixes` で feature を拾う。比較先は実効の `target`（設定が無い・無効でも、全体の既定か `pi.json` の値）。有効で既定と違う・無効のときだけ 1 行 |
| 統合ゲートの再判定（S7） | execute 直前に `tightenIntegration` をかけ直す（tool_call で決めた判定を再利用するときも）。tool_call の後に主設定が変わって自由区でなくなっても、古い許可で実行しない。拒否・必須確認はそのまま、許可だけを再判定する。RPC の回帰試験がある |
| 後片付け | 直前にも、統合元が全体の保護に入っていないことを確かめる |
| 変更の可視化 | `risk_paths` に `.agents/config/pi.json` を足す（承認待ち。§7） |
| 診断コード | `invalid_json`・`not_object`・`unknown_key`・`protected_refs_not_allowed`・`bad_type`・`too_large`・`too_many`・`bad_target`・`bad_prefix`・`prefix_overlaps_protected`・`not_regular_file`・`read_failed`・`ls_tree_unparsed` |

上限: ファイル 4096 バイト・配列は各 8 要素・文字列は各 64 字（`target` は 128 字）・ネストは 2 段まで。

なぜ保護を `pi.json` に置かないか: エージェントが書き換えられるファイルに保護を置くと、変更・削除・古い worktree で保護を外せる。保護は全体のままなので、`pi.json` を書き換えられても保護は 1 つも弱まらない。変えられるのは、保護でないブランチの確認の省略範囲と、`git_integrate` の統合先の選択（保護の中から。統合は人の承認のまま）だけ。分類器・統合ゲート（`judge/*`・`integration-gate.ts`）は変えない。

## 6. 守る条件

| 番号 | 条件 |
| --- | --- |
| C1' | 保護は書き換えられない（全体設定）。リポジトリ内の設定は、保護を弱められない範囲の値だけを、実行時の検査つきで受け取る |
| C2 | `pi.json` が無いリポジトリは、判定結果が今と同一。既存の golden・試験が無修正で通る。`bugfix/x` は自由区にならない・`feature/x` は自由区（今のまま）。**例外**: 主 worktree が detached・非保護ブランチ上のときは、設定の有無にかかわらず自由区が効かない（確認が増える側。§5） |
| C3 | 保護は全体の設定だけ（`pi.json` は保護を足さない・除かない） |
| C4 | `target` は実効の保護の完全一致の要素 |
| C5 | 接頭辞が許すブランチ名の集合は、実効の保護と交差しない（大文字小文字を区別しない） |
| C6 | 設定が無効のときは、全体の既定のまま + 診断（保護は全体なので緩まない）。**読めないとき（`readFailed`）は、確認を省く側（自由区）では自由区にしない（fail closed）**。承認のある `git_integrate` は既定へ戻す |
| C7 | 表示と判定は同じ値を使う（`/board`・承認画面・計画） |
| C8 | 設定の変更は、統合の承認画面で見える（`risk_paths`） |
| C9 | 公開リポジトリに他のリポジトリの具体を置かない。docs・試験・fixture には架空の例だけ。診断に入力の本文を出さない |

## 7. 段階と状況

| 段 | 内容 | 状況 |
| --- | --- | --- |
| 0 | 必要性の確認（§4） | 回答済み（2026-11-02） |
| S1+S2 | 解析・検査（`judge/integrateprofile.ts`）・ローダー（`integrate-profile-load.ts`）・試験 | **取り込み済み** |
| S3a | `git_integrate` の経路（`integrate-plan.ts`・`integrate-action.ts`・`pending-adapters.ts`・`integrate-exec.ts`） | **取り込み済み** |
| S3b | 自由区（`freezone.ts`）・`/board`（`board-collect.ts`・`board.ts`）・プレビュー・execute 直前の再判定（`index.ts`）。独立 review 4 回の指摘を反映（§10） | **取り込み済み** |
| 分類器の穴 2 件 | 別の feature。[pi-decide.md](../spec/guard/pi-decide.md) に記載済み（§10） | **取り込み済み** |
| S4（`risk_paths`） | `common.toml.tmpl` に `.agents/config/pi.json` を足した | **取り込み済み** |
| S4（docs） | 本案件・[pi の拡張](../spec/guard/pi-extensions.md#プロジェクトごとの設定pijson)・[保留（撤去済み・履歴）](../spec/guard/pi-pending.md)・[マニュアル 7.6](../spec/pi-manual.md#76-プロジェクトごとの設定pijson) | この feature（保存待ち） |
| S4（実機確認） | 架空の一時リポジトリでの確認。**確認省略を配備する前**に行う | **未実施** |

**反例を先に書く試験**（S1+S2 の試験と配線の試験）:

- C5 の表: `feature/`・`Feature/` × 保護 `feature/base`、`x/`・`x/y/` × `x/*`、下限の `release/*`・`hotfix/*` × `release/`・`hotfix/`、`target=release/a`（保護が `release/*` だけ）・`target=release/*`
- 保護を減らせない: `extra_protected_refs`・`protected_refs` → 無効。`pi.json` を空にする・消す → 全体の既定
- 無効の倒し方: 壊れた JSON・未知キー・型違い・サイズ超過・symlink・サブモジュール → 全体の既定 + 診断コード（入力の本文を含まない）
- ローダー: 無い・HEAD が無い・コミット後に blob が変わる・作業ツリーだけの編集は無視される
- 自由区の fail closed（`test_pi_freezone_profile.py`）: 主 HEAD が detached・非保護ブランチ（設定の有無とも）・`update-ref --no-deref main-worktree/HEAD` による主 HEAD の偽装・`git replace` による差し替え・設定を読めない（狭めた設定が読めないとき既定へ戻らない）・偽の worktree の管理ディレクトリ・診断コードだけの添え書き・プレビューの両側・`/board` の比較先・execute 直前の再判定（RPC）

## 8. 未解決・未確認

- pi の project trust との連動（今は連動しない。trust は `.pi` の設定・拡張の読み込みを決めるだけ。`pi.json` は別の仕組み。後から連動を足せる）
- 保護ブランチの置き場は全体のまま（リポジトリごとの保護の追加が要るときは、別の案件で、設定の変更・削除・古い worktree で保護を外せない設計を作ってから）
- **S4 の実機確認（架空の一時リポジトリ）は未実施**。確認省略の配備は、その後
- Windows は未確認
- 実機（`pis`・実 TUI）での見え方は未確認
- 既知の制限（独立 review は 4 回で止めた。残りは既知の制限として扱う）:
  - 主 worktree の HEAD が存在しないブランチを指す bare リポジトリでは、自由区が効かない（確認が増える側）
  - 主 worktree が detached・非保護ブランチ上のとき、自由区が効かない（C2 の例外）
  - 自由区の土台は「保護ブランチの先端は承認を経た」という前提で、**分類器が保護ブランチへの書き込みを網羅していること**に立つ。網羅は保証しない（保証範囲はガードが識別する直接経路。`git config remote.*.fetch` を先に書く 2 段の手順などは範囲外）
  - 承認画面の summary で、統合先と接頭辞が同じ行にある（長い統合先名で接頭辞が落ちる。全文表示には残る）
  - 古い保留の記録（`profileBlob` が無い）で現在の `pi.json` があると、「要求時と違う」と出る（安全側の警告）
  - 任意の外部プロセスによる HEAD の更新との競合を、完全に原子的に防ぐ保証ではない（既存の契約）
- 構造化統合は、外部 filter・merge driver・統合先の checkout の状態などを理由に断る。**接頭辞に対応するだけでは、使えるようにならない場合がある**

## 9. 却下した案と理由

| 案 | 理由 |
| --- | --- |
| v2: 全体設定にプロジェクトごとの表（実パス）を置く | 公開リポジトリに他のリポジトリの実パスを置けない。非公開の置き場所の設計が無い（`chezmoi` の `[data]` は `init` 時にしか更新されない） |
| `local.toml` に表を置く・実行時に読む非公開 JSON・テンプレートが外部ファイルを読む・`.chezmoidata`（計画役の案） | 利用者の「グローバルへの集約は管理上よくない。プロジェクト内設定にしたい」で採らなかった |
| 保護ブランチをリポジトリ内の設定で足せるようにする | 設定の変更・削除・古い worktree で保護を外せる（review の BLOCKER）。保護は全体のままにした |
| 作業ツリーの `pi.json` を直接読む | symlink・特殊ファイル・読む途中の差し替えの問題。HEAD の blob にした |
| 自由区の接頭辞を、feature 自身の HEAD の `pi.json` から読む | エージェントが自分で書いた設定で、自分の自由区を広げられる。主 worktree の HEAD から読む |
| 主 HEAD の信頼性検査を「設定があるときだけ」にする | 主 HEAD を設定の無いブランチへ切り替える偽装で、狭めた設定が消えて既定の自由区が復活する。設定の有無にかかわらず検査する |
| 設定の読み取り失敗を「設定なし」として既定に戻す（自由区で） | fail open。確認を省く側なので、読めないときは自由区にしない |
| 環境変数で指定 | 宣言が散る |
| 自由区と統合元を、1 つの接頭辞のリストに潰す | `bugfix/` の確認条件が変わる |
| `gitflow.*`（`.git/config`）を自動で読む | git-flow を使わないリポジトリには効かない |

## 10. 経緯

- v1・v2（2026-11-01〜02）: dotfiles の `common.toml.tmpl` にプロジェクトごとの表を置く案（B）。独立 `review`（MAJOR 6）で縮小した（パスは完全一致・接頭辞は用途別・解決は 3 値）。段 0 の回答で、表の必要性が確認できず、実パスの置き場の穴もあり保留した
- v3（2026-11-02）: 利用者の決定でリポジトリ内の `pi.json` へ。計画役の案は §9 のとおり。独立 `review` で BLOCKER 2・MAJOR 4（保護の置き場・作業ツリーの読み方・自由区の読み元など）を反映した
- S3a・S3b の取り込み（2026-11-02）。S3b の独立 review を **4 回**行い、見つかった穴を**実 git で再現してから**直した:
  - 自由区の設定元の主 HEAD を、feature の worktree から `git update-ref --no-deref main-worktree/HEAD <OID>` で広い設定のコミットへ向けられた → 主 HEAD が保護ブランチ上の symbolic ref であることを要求
  - 主 HEAD を設定の無いブランチへ切り替えて狭めた設定を消せた → 検査を設定の有無にかかわらず行う（C2 の例外）
  - `git replace` で HEAD のコミットの中身を差し替えられた → 読み取りに `--no-replace-objects`
  - 読み取りの失敗が「設定なし」になった（blob 欠けは `ls-tree -l` のサイズ欄が `BAD` で終了コード 0）→ `readFailed` として自由区にしない
  - raw `git flow … finish` のプレビューが cwd の HEAD しか見なかった → 主 HEAD も読む
  - tool_call の後に主設定が変わると、古い許可で実行できた → execute 直前の再判定（S7）
  - 偽の worktree（`.git` ファイルの書き換え）→ 管理ディレクトリが `<common dir>/worktrees/` の下にあることを確認
- 分類器の穴 2 件は別の feature で閉じた（[pi-decide.md](../spec/guard/pi-decide.md)）: 他の worktree の ref の別名（`main-worktree/…`・`worktrees/<id>/…`）への `update-ref`・`symbolic-ref`、`git replace`、`git fetch --refmap`・`-c remote.<名>.fetch=` が、保護ブランチを確認なしで動かせた（実 git で再現）
- 設計の訂正: 設計の「読めない場合は設定なし（既定）」は、`git_integrate`（承認があるので既定へ戻してよい）と、自由区（確認を省く側。fail closed）で扱いを分けた

## 11. 関連

- [CHG-0053](0053-worktree-integration-gate.md)（統合ゲート・自由区）、[CHG-0055](closed/0055-async-approval.md)（`git_integrate`）、[保留](../spec/guard/pi-pending.md)
- [pi の拡張](../spec/guard/pi-extensions.md#プロジェクトごとの設定pijson)・[利用者マニュアル 7.6](../spec/pi-manual.md#76-プロジェクトごとの設定pijson)
