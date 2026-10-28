# sudo を使う chezmoi スクリプトを Ansible に寄せると楽になるか

観測日: 2026-10-29。対象: このリポジトリの `home/.chezmoiscripts/`（読み取りだけ。実行も実機の検証もしていない）と、Ansible・chezmoi の公開情報。

- **問い**: sudo を使うスクリプトを Ansible に置き換えると、楽になるか（sudo の扱い・冪等性・保守）。
- **結論（先に）**: **全面的な置き換えは勧めない**。楽になる分（パスワードの尋ね方・apt と `/etc` の宣言的な記述・dry-run）は実在するが、このリポジトリの sudo は
  Linux の 4〜5 本のスクリプトに限られ、**sudo の扱いの不便の大半は、既存のキープアライブ（macOS 用）を Linux にも使うだけで解ける**。Ansible は、導入・構成・試験の費用が先に要る。
  やるなら、Linux の apt と `/etc` の部分だけを 1 本の playbook にする**小さな試作**から（下の「勧める順」）。

## 1. このリポジトリの sudo（`explore` の読み取り。パスは調査時点）

sudo の行が多いのは `100_linux/run_once_after_121_ubuntu.sh.tmpl`（23 行。全体の約 4 分の 1）。ほかは 111（9）、120（7）、125（6）、130（6）、macOS の 205・210・250、Windows の 309（`sudo.exe` の有効化だけ）。

| OS | 場所 | 内容 | Ansible のモジュールで書けるか |
| --- | --- | --- | --- |
| Linux | 121 | apt の更新・導入、Pi 専用の `/etc`（zram・earlyoom）、サービス、ClamAV（個人機） | **書ける**（`apt`・`copy`/`template`＋`notify`・`systemd`・`sysctl`） |
| Linux | 111 | Microsoft の鍵と VS Code の apt ソース | 書ける（`deb822_repository`・`apt`） |
| WSL | 120 | `/etc/wsl.conf`・timesyncd の mask・adjtimex の tick | 前 2 つは書ける（`copy`・`systemd`）。tick（Python の ctypes）は `command` で包むだけで、楽にならない |
| Linux | 130 | zsh の導入と `chsh` | 書ける（`apt`・`user`） |
| Linux | 125 | Python が無いときだけビルド用の apt | 書けるが、判定が chezmoi 側（sudo 無しモード）にある |
| macOS | 205・210・250 | Homebrew・Rosetta・`defaults write`・`nvram`・ファイアウォール | 旨みが小さい（sudo の行が少数。`community.general` の module はあるが、`defaults`・GUI アプリが中心） |
| Windows | 309 | `sudo.exe` を有効にするだけ（昇格は別方式） | 対象外（Ansible の制御側は、Windows を直接は使えない） |

## 2. 今の sudo の扱いの不便（`docs/spec/development.md` の「sudo パスワード」）

- パスワードは保存せず、各スクリプトの冒頭の `sudo -v` で尋ねる（Linux は 111・120・121・125・130 の各自）。
- **macOS には、50 秒ごとの `sudo -n true` のキープアライブ**（`sudo-keepalive.sh.tmpl`）があるが、**Linux には無い**。長い `apt-get upgrade` が、既定の約 15 分の有効期限を超えると、再度の尋ね直しになりうる（推測。実測していない）。
- sudo 無しモード（`no-sudo` テンプレート）は、`.chezmoiignore.tmpl` で root 系のスクリプトを丸ごと除外する。

## 3. Ansible の側の事実（公開情報。2026-10-29 に確認）

- **chezmoi の公式 FAQ が、この使い方を勧めている**: ホームの外の少数のファイルを超えるなら、Puppet・Chef・Ansible・Salt の方が向いていて、`run_` スクリプトから呼べる。マニフェストは、chezmoi が無視するディレクトリに置く
  （<https://www.chezmoi.io/user-guide/frequently-asked-questions/design/>）。
- **実例が多い**: `run_onchange_` のスクリプトで `ansible-playbook` を、`--connection=local` と localhost の inventory で呼ぶ
  （<https://github.com/johnramsden/dotfiles>、<https://github.com/bosmak/dotfiles>、<https://github.com/Patruxs/dotfiles>、<https://knuth.info/posts/the-solo-stack/dotfiles/installing-software-with-ansible-and-chezmoi/>）。
  「システムは Ansible、ツールは mise、ホームのファイルは chezmoi」という分担も報告されている（<https://github.com/alunduil/alunduil-chezmoi/issues/842>）。
- **become（sudo）**: 尋ねる方法は `--ask-become-pass`（`-K`）・環境変数・パスワードファイル・`ansible-vault`（<https://oneuptime.com/blog/post/2026-02-21-how-to-pass-become-password-in-ansible-securely/view>）。
  `--ask-become-pass` なら、**playbook の始めに 1 回尋ね、全タスクにその値を渡すので、有効期限の問題が起きない**（推測を含む。公開情報の読みで、実測していない）。
- **落とし穴の報告**: `/etc/sudoers` の `Defaults use_pty` があると、`become` が「パスワードの入力待ちで時間切れ」になる（<https://github.com/dominhtim/workstation-setup>。この報告者は、ブートストラップで該当行を消している）。
  端末が要る（パイプ・バックグラウンドは不可）。
- **導入**: `uv tool install ansible-core`（公式は `pipx` を案内。<https://docs.ansible.com/projects/ansible/latest/installation_guide/intro_installation.html>）。ansible-core の版により、制御側の Python に下限がある（3.11 以上など。版ごとに確認が要る）。
  `deb822_repository` などは `ansible.builtin`、`homebrew`・`osx_defaults` などは `community.general`（`ansible-galaxy` で別に取る）。
- **反対側の意見**: dotfiles を Ansible で全部書くと、ツールの設定のファイルの再現が面倒（<https://sumit.me/posts/setting-up-developer-system-with-ansible-and-dotfiles>）。chezmoi は、書き換える前に退避するなど、ファイルの扱いが優れる
  （<https://github.com/Luolc/dataforge/pull/232>）。→ ホームのファイルは chezmoi に残し、**システムの状態だけ**を Ansible に、という分担が妥当。

## 4. 評価（私の判断。実機で確かめていない部分は推測と明示）

| 観点 | 今（シェル） | Ansible に寄せた場合 |
| --- | --- | --- |
| パスワードの尋ね方 | スクリプトごとの `sudo -v`。Linux にキープアライブ無し | playbook の始めに 1 回（`-K`）。**楽になる** |
| 冪等性 | 各スクリプトで `cmp -s`・`grep -Fqx`・`command -v` を手書き。`/etc` は毎回 `tee` | モジュールが担う。差分・`--check`（dry-run）・`notify` が標準。**楽になる** |
| 宣言性・読みやすさ | 121 は約 160 行の命令的なシェル | YAML で短くなる。ただし Jinja と YAML の字下げが増える |
| 導入の前提 | 追加なし（`005` が `uv` と Python を入れる） | `uv tool install ansible-core` が先に要る（`005` の後、100_linux の前。sudo は不要）。**新しい前提** |
| sudo 無しモード | `.chezmoiignore` で除外 | 同じ除外が要る（**楽にならない**。playbook 側に持ち込み直す設計が要る） |
| テンプレートの変数（Pi・個人機・WSL） | chezmoi のテンプレートで分岐 | chezmoi が vars ファイルを描画して渡す（可能。追加の仕組みが要る） |
| 試験 | Docker の 4 サービス・月次の cold start | イメージに Ansible が要る（「素の機械にあるものだけ」の方針と衝突）。`--check` や `ansible-lint` を検査に足す |
| macOS・Windows | — | 旨みが小さい・対象外 |
| 実行の時間 | シェル | 起動に数秒（推測）。Raspberry Pi での負担は未確認 |

**sudo の扱いだけ**を楽にするなら、Ansible より安い手がある: **macOS のキープアライブのテンプレートを Linux のスクリプトにも使う**（追加の依存なし。長い `apt-get upgrade` の途中の尋ね直しも防げる）。
Ansible 固有の利点は、**冪等性・差分・`--check`・宣言的な記述**で、これは sudo というより、「`/etc` と apt の管理」の楽さ。

## 5. 勧める順

1. **（安い・先に）Linux にもキープアライブを使う**。111・120・121・125・130 の `sudo -v` を、共有のテンプレートへ寄せる。試験は既存の静的な試験（`test_bootstrap_scripts.py`）に足す。
2. **（試す価値がある）121 の Pi 専用の `/etc` 設定（zram・earlyoom・sysctl）だけを、小さな playbook にする試作**。`ansible-core` を `uv tool` で入れ、`ansible-playbook -K --check` で差分を見る。得られるか（行数・読みやすさ・冪等性・実行時間）を、実測で比べる。
3. 試作が良ければ、apt の導入・鍵とソース・`chsh` へ広げる。**悪ければ撤退**（費用は、1 つのスクリプトの分だけ）。
4. macOS・Windows は、Ansible にしない。

## 6. 未確認

- `Defaults use_pty` が、Ubuntu 22.04・24.04 と WSL・Raspberry Pi の既定の sudoers にあるか、`become` が実際に詰まるか。
- Linux の `apt-get upgrade` が、実際に sudo の有効期限を超えるか（推測）。
- Raspberry Pi での `ansible-core` の導入の時間と容量。
- Docker の cold start（`test/`）に Ansible を足したときの試験の費用。
- `scripts/` と `config/` の sudo は、読み取りの範囲が切れて未確認（`.chezmoiscripts/` と `.chezmoitemplates/` は、全体を grep で確認した）。

## 7. 追記 2026-10-29: IaC ツールそのものを入れる価値があるか（保守性の観点）

- **問い**: 実装の費用はエージェントが担うので問わない。**長く保守する側の費用**（コードの量と読みやすさ・正しさの担保・ツールの更新による破損・OS の範囲・試験・エージェントの扱いやすさ・撤退のしやすさ）で、IaC ツールを入れる価値があるか。
- **結論（先に）**: **Linux のシステム層（apt・`/etc`・systemd・apt の鍵とソース・`chsh`）に限って、Ansible を入れる価値がある（条件付き）。全体への導入の価値は無い。** Nix・pyinfra・mitamae は、この条件では Ansible に劣る。決め手は、**自作の小さな「IaC もどき」の保守を避け、apt のロックや鍵・サービスの端の事例を、コミュニティの module に任せられる**こと。代償は、ツールの更新による破損と、構成要素（chezmoi・mise・uv・Ansible）が 1 つ増えること。

### 7.1 このリポジトリの保守の実績（`git log`。2026-10-29 に集計。コミットの件名が `fix` で始まるものを数えた概数）

| 領域 | スクリプトに触れたコミット | うち `fix` |
| --- | --- | --- |
| `home/.chezmoiscripts/` 全体 | 171（3260 行） | 68 |
| `100_linux`（Linux・WSL・Pi） | 73 | 29 |
| `300_windows` | 86 | 28 |
| `000_unix`・`400_unix`・`200_mac` | 17・15・8 | 7・6・5 |

- 月別の件数は、2026-02 が 26、2026-09 が 40、2026-10 が 59 と、**直近に集中**している（新しい機能と検査の追加を含むので、すべてが不具合の修正ではない）。
- `fix` の中身（件名から。推測を含む）は、**プラットフォームの癖**（Windows の ACL・PATH・GPU の電力・フォントの導入、WSL の時刻同期、Rosetta、`wsl.conf` の退避）が多く、**冪等性・安全性の不足**（上書き前の退避・`rmdir` を空のときだけ・導入の完了を確かめてから削除）が次に多い。
- したがって、**IaC で防げるのは「冪等性・安全性」の一部**で、**プラットフォームの癖は、どのツールを使っても書く必要がある**。Windows は、Ansible の制御側が直接は使えないので、対象外。

### 7.2 候補の比較（保守性の観点。公開情報は 2026-10-29 に確認）

| 候補 | 保守性の利点 | 保守性の不利 | このリポジトリでの判断 |
| --- | --- | --- | --- |
| **現状（シェルと PowerShell）** | 追加の依存なし。全員が読める | 冪等性・差分・dry-run を手書き（`cmp -s`・`grep -Fqx`・`tee` で毎回上書き）。スクリプトごとに同じ癖を再実装。3260 行 | 基準 |
| **Ansible**（<https://docs.ansible.com/>） | 最大の資産: module（`apt`・`systemd`・`deb822_repository`・`copy`＋`validate`・`user`）が端の事例を持つ。`--check`・差分・`notify`。エージェントの知識が最も多い | **主要な更新で破損がある**（コミュニティ版の major と各 collection に breaking change。collection は ansible-core と別に版管理。制御側の Python の下限が上がる。<https://docs.ansible.com/projects/ansible/latest/reference_appendices/release_and_maintenance.html>）。YAML と Jinja の層が増える。Windows は制御側に使えない | **Linux のシステム層だけ採用候補**。`uv` で `ansible-core` と collection の版を固定して、破損を抑える（このリポジトリは、Fence・`git-flow` で版とチェックサムの固定を既にしている） |
| **Nix / home-manager / nix-darwin** | 再現性と巻き戻しが最強。長い shell を減らせた報告（<https://www.bekk.christmas/post/2021/16/dotfiles-with-nix-and-home-manager>） | **学習曲線が急**。文書が散らばり矛盾する報告（<https://rasyidanaf.com/blog/the-nix-experience-managing-macos-with-nix/>）。mise・apt・chezmoi と役割が衝突し、移行は全面。Windows は対象外 | **採用しない**（全面の移行で、保守対象が別の世界になる） |
| **pyinfra**（<https://pyinfra.com/>） | Python で書ける（このリポジトリは Python と `uv` が既にある）。条件分岐が自然。速い | **コミュニティが小さい**（module と事例が少なく、エージェントの知識も少ない）。保守者が少ない（推測。確かめていない）。Windows は限定的 | 将来の選択肢。**今は、Ansible の資産の方が保守に効く** |
| **mitamae**（<https://github.com/itamae-kitchen/mitamae>） | 単一のバイナリ（Python 不要）。Chef 風の DSL。dotfiles の導入例が多い | 保守者が少ない。Ruby の DSL の知識が要る。Windows は対象外 | 採用しない |
| **自作の共有ライブラリ**（`ensure_file`・`ensure_apt` を `.chezmoitemplates/` に） | 依存なし。小さく始められる | **自分で IaC もどきを保守する**ことになり、apt のロック・鍵・サービスの端の事例を、自分で持つ。長期では Ansible の方が安い（推測） | 比較用。Ansible を採らないときの代案 |

### 7.3 判断

- **全体に入れる価値は無い**: 保守の負担の大きい Windows（86 コミット・`fix` 28）と、プラットフォームの癖は、IaC の範囲の外。構成要素が 1 つ増える代償に見合わない。
- **Linux のシステム層には、価値がある**: 範囲は、`121`（apt・Pi 専用の `/etc`・サービス）・`111`（鍵とソース）・`130` の `chsh`・`120` の `wsl.conf` と timesyncd の mask。ここは、**手書きの冪等性が一番多く、module で置き換えられる**。
  - 利点（保守性）: 端の事例を持つ module に任せる・`--check` と差分で変更の影響が見える・宣言なので読むだけで状態が分かる・sudo の尋ね方が 1 回で済む（セクション 4）。
  - 代償と対策: (a) 更新による破損 → `uv` の lock で `ansible-core`、`requirements.yml` で collection の版を固定し、**上げるのは意図したとき**（Renovate などは使わない）。(b) 構成要素の増加 → 「システム＝Ansible、ツール＝mise、ホームのファイル＝chezmoi」と責務を文書に書く。(c) sudo 無しモードは、`.chezmoiignore` で Ansible のスクリプトごと除外（今と同じ）。
- **撤退の条件（試作の成否を決める）**: 試作（`121` の Pi 専用 `/etc`、次に apt）で、次のどれかなら撤退する。(1) 手書きの冪等性の検査が、実際には減らない、(2) `--check` が実用にならない（`command` の包みが多い）、(3) 固定した版を上げたときに、直すのに多くの手がかかる、(4) 実行の時間が、Raspberry Pi で許容できない。

### 7.4 未確認（追加分）

- pyinfra と mitamae の、**現在の保守の状況**（最終のリリース・保守者の数）。今回は、公式のページと紹介記事の記述だけを見た。
- Ansible の major の更新で、実際に何が壊れるか（このリポジトリで使う module の範囲での影響）。
- Windows を Ansible（WSL を制御側に、WinRM 経由）で扱う費用。今回は対象外としたが、調べていない。
- `fix` の分類は、コミットの件名の読みで、1 件ずつ原因を確かめていない。
