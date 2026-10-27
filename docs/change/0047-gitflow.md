# CHG-0047: gitflow ブランチモデルへ切り替え、feature の起票・クローズを AI が `git flow` で行う

- **状態**: Exploring
- **更新日**: 2026-10-28
- **基準**: コミット 8ec840a 以降、git-flow-next（2026-10-28 に公式の資料で確認）

## 目的と非目的

**目的**: main 一本の運用をやめ、**main（リリース）/ develop / feature の gitflow** に切り替える。feature と、その worktree の起票・クローズは、AI が `git flow` コマンドだけで行う。動機（利用者）は 3 つ。

1. **コミット粒度**: 細かいコミットを、feature の中に閉じ込め、develop へは 1 本に束ねる
2. **main の安定**: 動かないことがあるので、main は検証後にだけ更新する
3. **並列開発**: ブランチを切っていないことが、並列開発がうまくいかない一因。feature ごとにブランチ（と worktree）を持つ

**非目的**: `push` の自動化（利用者の手動のまま）。全リポジトリでの素の `git` のブランチ操作の deny（ブランチモデルがリポジトリごとに違うため。下の「モデルはリポジトリごと」）。release・hotfix ブランチ（初版は使わない）。GitHub のブランチ保護・PR の運用（別の判断）。

## 実施計画

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 1 | 設計の前提を実測で確かめる | 使い捨てのリポジトリで、`git flow` の実体・サンドボックス内での動作・ネットワークと push に当たる操作を確かめる（下の「実装・検証」） | 完了 |
| 2 | 許可の形を決める | 固定の引数の表（`[[pi.actions]]` の拡張）か、規則の許可か。承認の要否。素の `git` の branch 等は、既定の ask のまま、指示で `git flow` へ誘導する。`review` に見せる | 未着手 |
| 3 | AI が使える形にする | 許可の実装と試験。bypass で `git branch -D` などが通る穴（CHG-0041 の持ち越し）も、ここで塞ぐ | 未着手 |
| 4 | このリポジトリを切り替える | `develop` と `.gitflow` の作成、検査のスタンプの基準・CI のトリガー・`commit` スキル・docs の更新 | 未着手 |
| 5 | 並列開発の運用 | feature ごとの worktree で、pi を並列に動かす。`.tmp/`・スタンプ・サンドボックスの扱い | 未着手 |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

**時期**: [CHG-0046](0046-guarded-action-timeout.md) の段 3（承認の時間切れの実機の確認）の後に、段 3 以降（実運用）へ進む。段 1〜2（実測と設計）は並行して進めてよい。

## 現在地

### 実装の選択（ネットで確認。2026-10-28）

- `nvie/gitflow` は 2025-10-14、`gitflow-avh` は 2023-06-19 に、**アーカイブ済み**。後継の **git-flow-next**（Tower 製、Go 製）は保守されている（<https://git-flow.sh/docs/commands/>）
- git-flow-next の、この案件に関わる機能:
  - topic ごとの `upstream-strategy`（`merge`・`rebase`・`squash`）。`finish --squash`、`--squash-message`
  - `git flow worktree add|remove|list|prune|path`、`<topic> start --worktree`。`finish` は、git-flow が作った worktree を自動で片付ける。`rebase` 方式の `finish` は、別の worktree を持つ topic では拒否される（`merge`・`squash` は可）
  - `git flow integrate`（develop から main への merge。タグ・fetch は既定でオフ）
  - 設定の共有: `git flow init --shared` が、コミットできる `.gitflow` を作る
- **注意**: `start` は既定で `fetch` する（`--no-fetch` で止める）。`finish` は、リモート追跡ブランチを消す選択肢がある（`--keepremote`）。**ネットワークや push に当たる引数は、許可の形で固定する必要がある**

### このリポジトリの現状（`explore` の調査。2026-10-28。行は調査時点）

- **git の許可**（`common.toml.tmpl`）: `git flow` はどの規則にも当たらない（implementer・worker は既定の ask、bypass では allow。committer・explorer・reader は deny）。素の `branch`（`--show-current` 以外）・`switch`・`checkout`・`merge`・`tag`・`worktree add` も同様で、**bypass では全部通る**。`git branch -D`・`clean`・`tag -d` が全役割で allow になる件は、CHG-0041 の持ち越しのまま未起票
- **サンドボックス**: 書けるのは起動したディレクトリ、`~/.cache`、worktree の共有 `.git` など。共有 `.git` の `hooks` と `config` は書けない。兄弟の worktree と、本体の作業ツリーにも書けない（[CHG-0029](0029-worktree-isolation.md) の実測）。**`git flow` が実行時の状態（`gitflow.branch.<branch>.base`）を `.git/config` に書くなら、`pis` の内側では失敗する見込み**（推測。段 1 で確かめる）
- **検査のスタンプ**（`scripts/verify_stamp.py`）: 基準は HEAD やブランチではなく**ツリーの内容**で、worktree ごとに持つ。push 段の基準は `origin/main` の merge-base に**固定**（152 行付近）。develop や feature の push では範囲が過大になり、警告が増える
- **CI**: `linux.yml` は `push: branches: [main]`。develop を足さないと、develop への push で動かない。`windows.yml`・`e2e.yml` は影響なし
- **chezmoi**: 既定ブランチは main で、`chezmoi update` は main を pull する。他のマシンへ届くのは、main に入った後
- **docs**: ブランチ運用・粒度・gitflow の記述や案件は無い。worktree は CHG-0029（子の隔離。`.tmp/worktrees/`）だけで、人が並列に使う worktree は、そこでは**非目的**
- **`commit` スキル**: 「ブランチ操作には使わない」と書く。粒度は「論理単位で分ける」まで

## 設計（案）

### モデルはリポジトリごと、許可の仕組みは共通

ブランチモデルは、プロジェクトによって違う（GitHub を使うとは限らない）。そこで、次のように分ける。

| 層 | 決めるもの | 置き場 |
| --- | --- | --- |
| 共通 | AI が使える操作の種類（feature の起票・クローズ・worktree）と、危険な引数（ネットワーク・push・リモートの削除）の除外 | dotfiles の `common.toml` |
| リポジトリごと | どのモデルか（gitflow-lite・GitHub flow・main 一本など） | リポジトリの `.gitflow`（git-flow-next の共有設定。`classic`・`github`・`gitlab` の preset か自作の構成） |
| 既定 | `.gitflow` が無いリポジトリ | AI はブランチを切らない（今と同じ。現在のブランチにコミットするだけ） |

`push` は、どのモデルでも手動。ローカルで完結し、GitHub の有無に依存しない（PR を使う運用は、別の判断）。

### このリポジトリのブランチモデル（gitflow-lite）

- `main`: リリース。`chezmoi update` が見る。検証（`verify:all`）の後にだけ更新する
- `develop`: 統合。feature の `finish` の先
- `feature/<名前>`: topic。親は `develop`。`finish` は **squash**（1 feature = develop 上の 1 コミット）。feature の中のコミットは、細かくてよい（WIP）
- develop → main は `git flow integrate`。タグは付けない。**初版は利用者が実行**（自動化は、検査の条件を決めてから）
- release・hotfix は使わない

### 許可の形（段 2 で決める。候補）

| 候補 | 内容 | 長所 | 短所 |
| --- | --- | --- | --- |
| A 規則で、`git flow` の引数の形を許可 | 判定器の bash 規則で、`git flow feature start <名前> --worktree --no-fetch` などの形だけ allow | 実装が小さい | 引数の組み合わせの網羅が難しい。`git flow` が内部で動かす git は、判定器から見えない |
| B `guarded_action` の項目（毎回確認） | 固定の引数の表。引数は型で検証 | 引数が固定で検証される | AI の自動と相容れない（毎回、承認が要る） |
| **C 固定の引数の表＋確認なしの項目（案）** | B と同じ表で、安全と判断した項目は確認を出さずに実行する（`confirm = "never"` のような宣言）。`finish` だけ確認を残すか、事前の条件（作業ツリーがクリーン・検査済み）を満たすときだけ確認なしにするかを決める | 引数が固定・検証され、自動にもできる | ツール（`guarded_action`）の機能の追加が要る。確認なしの範囲の設計が、境界の判断になる |

- **素の `git` の branch・switch -c・checkout -b・worktree add/remove・merge・tag は、共通の規則では deny にしない**（既定の ask のまま）。`.gitflow` があるリポジトリでは、共通の指示と `commit` スキルで `git flow` を使わせる。迂回は、ask の承認で止まる。リポジトリごとに厳密に deny する仕組みは、必要になってから別に検討する（判定器にリポジトリ側の設定を読む仕組みが要る。**未確認**）
- `git branch -D`・`clean`・`tag -d` が bypass で全役割 allow になる件（CHG-0041 の持ち越し）は、gitflow とは別の修正として、段 3 で扱う
- ネットワークと push に当たる引数（`--fetch`・`publish`・`track`・リモートの削除など）は、固定の引数で除く。`--keepremote`・`--no-fetch` を固定し、段 1 の実測で、実際にネットワークを使わないことを確かめる

### 承認の考え方（案）

- `feature start`・`worktree add`: 確認なし（ブランチと worktree を作るだけ。取り消せる）
- `feature finish`（develop への squash の merge、branch の削除）: 事前の条件を満たすとき確認なし。条件: 作業ツリーがクリーン、feature の先端に検査済みのスタンプがある。満たさなければ、確認を出す。squash のメッセージは、`commit` スキルの上限（1200 字・箇条書き）に従う
- `integrate`（main の更新）: 利用者が実行する
- `push`: 利用者が実行する（変更なし）

### 並列開発（段 5。論点）

- feature ごとに worktree を持ち、worktree ごとに pi を動かす。`.tmp/`・スタンプ・サンドボックスの書き込み範囲は、worktree ごとになる
- worktree の置き場: 兄弟のディレクトリは、本体で動く pi から書けない。**`.tmp/worktrees/` の下**にするか、worktree ごとに利用者が pi を起動するかを、段 1 で確かめる（`gitflow.worktreePath` のテンプレートと、相対パスの解決）
- CHG-0029 の子の隔離（`isolation:"worktree"`）とは別の機構。名前と置き場を分ける

## 未解決点

- `git flow` の実体の導入方法（`mise` で入れられるか）と、版の固定
- ~~実行時の状態の書き込み先（`.git/config`）と、サンドボックスの書き込み拒否との衝突~~ → 実測で確定（上の「実装・検証」）。`start`・`finish` は警告つきで動き、worktree が残る。残る worktree の片付けを、固定の操作に含める。設定の変更は利用者が外で行う
- ~~公開済み feature の `finish` がリモートへ何をするか~~ → 実測で確定: `--keepremote` が無いとリモートのブランチを削除する。固定の引数に含める（公開（`publish`）は許可しない前提）
- 確認なしの項目（案 C）の宣言の形と、境界上の意味（`mustConfirm`・bypass との関係）
- develop → main の自動化の条件（検査済みのスタンプ・CI の結果）
- 既存の運用とのつなぎ: 進行中の案件（コミット粒度が細かい分）を、どの時点で feature に移すか

## 次の調査・実験（段 1）

使い捨てのリポジトリ（と、ローカルの bare リポジトリをリモートに見立てる）で確かめる。

1. git-flow-next の導入（`mise` の `github` / `ubi` バックエンドなど）と、`git flow init --shared`（custom: main・develop・feature、`feature` の `upstream-strategy = squash`）
2. `feature start --worktree --no-fetch` と、`gitflow.worktreePath` の相対パス（`.tmp/worktrees/…`）
3. `feature finish --squash --keepremote --no-fetch` の、ネットワーク・push の有無（`GIT_TRACE`・リモートの ref の前後比較）
4. **`pis`（Fence）の内側**での `start`・`finish`・`worktree add/remove`（`.git/config` への書き込みの失敗の有無）
5. worktree 内での pre-commit・スタンプの動作、`.tmp/` の扱い
6. 規則の素朴な allow（案 A）で、内部の git が判定器から見えないことの確認

## 評価基準

**必須**:

- `.gitflow` があるリポジトリで、AI が `git flow` の固定の形だけで、feature の起票・クローズができる。`.gitflow` が無いリポジトリでは、AI はブランチを切らず、今と同じに動く
- 許可の形が、ネットワークと push に当たる操作を含まない（実測で確認）
- `main` は、利用者の操作（`integrate` と `push`）でしか更新されない
- bypass でも、`git branch -D`・`clean`・`tag -d` が通らない（別の修正）
- feature の中の細かいコミットが、develop では 1 コミットに束ねられる

**望ましい**:

- feature ごとの worktree で、pi を並列に動かせる（書き込みの境界を弱めずに）
- スタンプ・CI が、develop と feature で、警告を増やさない
- 切り替えを、利用者の 1 回の操作で戻せる（`develop` と `.gitflow` を消すだけ）

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| A git-flow-next（`git flow`） | 保守されている。squash・worktree・`.gitflow` の共有がある。利用者の方針（`git flow` だけ許可）に合う | 内部の git が判定器から見えない。`.git/config` の書き込みがサンドボックスと衝突する見込み | 導入・実測 | **有望（段 1 で確かめる）** | 段 1 |
| B 素の git のブランチ操作を許可 | 実装が最小 | 方針に反する。bypass の穴が広がる。迂回できる | | 見送り | |
| C git-flow-avh | 古くから使われている | アーカイブ済み。squash・worktree が無い | | 見送り | |
| D 独自のスクリプト（`feature start/finish` を作る） | 引数を完全に制御できる | 作って保守する費用。git-flow-next が足りる | | 保留（A が衝突したときの代案） | 段 1 の結果 |
| E 現状（main 一本） | 変更なし | 利用者の 3 つの動機が解決しない | | 見送り | |
| F GitHub flow（main と feature だけ。squash で main へ）＋検証の関門 | 単純。短命の feature・squash・main を常に出せる状態に保つ、が標準的な推奨。git-flow-next にも `github` の preset がある | main への merge 前に検査を必須にしても、**統合先そのものが不安定になる**問題（動機 2）は、develop が無いと残る | | 保留（develop が重いと分かったときの縮小先。tool の設定だけで移れる） | 段 1 以降 |
| G スタック型のツール（jujutsu・git-branchless・Graphite・git-spice） | 依存する変更を積み重ねて並列に進められる | 学習と導入の費用が大きい。`git flow` だけを許可する方針と合わない | | 見送り | |
| H worktree の管理ツール（Worktrunk・git-worktree-runner など） | AI の並列実行向けに、worktree の作成・起動を自動化 | git-flow-next が `worktree` と `start --worktree` を持つので重複する | | 見送り（足りないときに再検討） | |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `common.toml.tmpl` の git の規則 | `git flow` は規則なし → 固定の形で許可（確認なしの項目）。素の branch 等は既定の ask のまま。`branch -D`・`clean`・`tag -d` の bypass の穴を塞ぐ | 本案件 | 未適用 |
| `scripts/verify_stamp.py` | push 段の基準が `origin/main` に固定 → 親のブランチ（develop）を基準にできる | 本案件 | 未適用 |
| `.github/workflows/linux.yml` | `push: branches: [main]` → `[main, develop]` | 本案件 | 未適用 |
| `commit` スキル | 「ブランチ操作には使わない」、粒度は論理単位 → feature の WIP と、squash のメッセージの書き方を足す | 本案件 | 未適用 |
| `docs/spec/development.md`・`testing.md` | `main` への言及 → ブランチモデルの節を足す | 本案件 | 未適用 |

## 実装・検証

実測（2026-10-28、git-flow-next v2.1.0・linux-amd64、配布の SHA-256 を公式の checksums と照合して一致、git 2.43.0。`$TMPDIR` に展開して使い、環境へは入れていない）。

| 確かめたこと | 結果 |
| --- | --- |
| 導入 | GitHub のリリースの tar.gz を展開すると、実体は `git-flow` 1 つ（PATH にあれば `git flow`）。`git flow init --preset=classic --defaults` のあと、`config edit topic feature --upstream-strategy=squash` と、`config delete topic release/hotfix/support/bugfix` で、gitflow-lite の構成にできた |
| worktree の置き場 | `gitflow.worktreePath = '.tmp/worktrees/{{ branchName }}'`（相対）は、リポジトリ直下から解決され、`<repo>/.tmp/worktrees/<名前>` に作られた（本体で動く pi の書き込み範囲に収まる） |
| squash | feature の中の 3 つの WIP コミットが、develop 上の 1 コミット（`--squash-message` の文）に束ねられた。feature のブランチと worktree は自動で消えた |
| integrate | `git flow integrate develop` で、main に merge され、develop が追従した（ローカルだけ） |
| ネットワーク | 到達できないリモート（`git://127.0.0.1:9/`）で、`feature start`（`--no-fetch` なし）は `Fetching from origin...` で止まった（15 秒で打ち切り）。**`start --worktree --no-fetch` と `finish --squash --no-fetch`（`--keepremote` の有無とも）は成功**し、ローカルの bare リモートの ref は変わらなかった（push なし）。`GIT_TRACE` は、`git-flow` が git を直接起動せず（トレースは 2 行だけ）、根拠にならなかった |
| 公開済みの feature の `finish` | ローカルの bare リモートに feature を push してから `finish --squash --no-fetch` を実行。**`--keepremote` を付けないと、リモートの feature ブランチが削除された**（`--no-fetch` でも。push に当たる操作）。`--keepremote` を付けるとリモートは不変。develop は、リモートへ push されない。**固定の引数に `--keepremote` を必ず含める**必要がある |
| worktree 内の hook・検査 | このリポジトリの複製に `pre-commit install` し、`feature start --worktree` の worktree で docs を変えてコミット。hook は、本体の `.git/hooks`（共通）から**そのまま動き**、全て通った。検査のスタンプは、worktree ごとの git ディレクトリ（`.git/worktrees/<名前>/`）に置かれる（案件の「現在地」の調査どおり） |
| `mise` での導入 | `mise ls-remote github:gittower/git-flow-next` で版（2.1.0 まで）を引けた。登録名は無く、`github:gittower/git-flow-next` の指定で入れる（段 4 で `mise` の設定へ 1 行足す。導入はまだしていない） |
| `.git/config` | **`feature start` は `.git/config` を書き換え、`finish` で元に戻す**（前後のハッシュで確認）。`list`・`config list`・`worktree list` は書かない |
| サンドボックス（Fence。`.git/config`・`.git/hooks` を denyWrite） | `start` は成功するが、「worktree の由来（provenance）と、feature の基点を記録できない」警告が出る。worktree の中のコミットは可。`finish` は成功（develop に 1 コミット、ブランチは削除）するが、**由来が無い worktree は「手作り」扱いで、ディレクトリが detached HEAD のまま残る**（`worktree list` に `(unmanaged)`）。`git worktree remove <パス>` は Fence の中で成功した |

実験の台本は `.tmp/keep/gitflow-exp/`（非コミット）。

**結論**:

- `.git/config` と `.git/hooks` は、サンドボックスの保護対象（`common.toml.tmpl` の `**/.git/config`・`**/.git/hooks/**`。任意のコードを動かせる設定を、AI が書けないようにする意図）。`git flow` は、この保護と**根本的に衝突する**が、`start`・`finish` は**警告つきで動く**
- したがって、**設定（`init`・`config`・`--shared` の同期）は、サンドボックスの外で、利用者が一度だけ行う**
- Fence の内側で動かすなら、`finish` の後に残る worktree の片付け（`git worktree remove .tmp/worktrees/<名前>`。クリーンで detached の worktree だけ）を、固定の操作に含める。フルガードだけの pi（Fence なし）では、完全に動く
- 案 D（自作のスクリプト）の必要性は、下がった（`git-flow-next` が足りる）

未確認: worktree ごとのスタンプの警告の出方（docs だけの変更では出なかった。コードの変更では未確認）、案 A（規則での許可）で、内部の git が判定器から見えないことの確認、Windows。

## 重要な更新

| 日付 | 更新 | 理由・証拠 |
| --- | --- | --- |
| 2026-10-28 | **段 1 の実測（主な項目）**。git-flow-next v2.1.0 を `$TMPDIR` に入れて、使い捨てのリポジトリで確認。squash・worktree（相対パス）・integrate・ネットワークなし（`--no-fetch`）は期待どおり。**`start` が `.git/config` を書くので、サンドボックスの内側では警告つきで動き、`finish` の後に worktree が detached で残る**。設定は利用者が外で行う、残る worktree を固定の操作で片付ける、を設計に反映 | 上の「実装・検証」 |
| 2026-10-28 | **モデルをリポジトリごとの設定にした**。共通は「許可の仕組み」（操作の種類と危険な引数の除外）、モデルは `.gitflow`、設定が無ければ AI はブランチを切らない。素の `git` の branch 等は、全リポジトリでの deny をやめ、既定の ask のまま指示で誘導する（利用者の選択） | 利用者の指摘（プロジェクトによってブランチモデルが違う。GitHub を使うとは限らない） |
| 2026-10-28 | **広いネット調査を行い、モデルを決めた**。ブランチモデル（gitflow・GitHub flow・trunk-based）の比較と、AI の並列実行向けの worktree の管理ツール（Worktrunk・git-worktree-runner など）、スタック型ツール（jujutsu・git-branchless・Graphite・git-spice）を調べた。利用者が **gitflow-lite（main / develop / feature。release・hotfix なし。feature は squash）**を選択。GitHub flow は縮小先として残す（git-flow-next の preset と設定で移れるので、許可の形の設計は、どちらでも変わらない） | 出典（2026-10-28 に検索）: <https://trunkbaseddevelopment.com/alternative-branching-models/>・<https://gitkraken.com/blog/how-to-choose-gitflow-vs-trunk-based-in-7-steps-2026>・<https://nx.dev/blog/git-worktrees-ai-agents>・<https://zylos.ai/research/2026-02-22-git-worktree-parallel-ai-development/>。一般に、頻繁にリリースする・人が少ない場合は GitHub flow や trunk-based が勧められ、gitflow は複数のリリースを並行して保守する場合に向くとされる。ただし利用者の動機（統合先の安定・粒度）は、develop を挟む形で直接満たせる |
| 2026-10-28 | 案件を起票 | 利用者の方針（コミット粒度が細かすぎる・main が不安定・並列開発の改善のために、gitflow へ。feature と worktree の起票・クローズは AI の自動。AI には `git flow` だけを許可）。ネットで git-flow-next を確認、`explore` の調査で現状を確認 |
