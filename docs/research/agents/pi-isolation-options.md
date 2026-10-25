# pi をどこで・どこまで守って動かすか（権限の有無と隔離の選択肢）

<!-- 現在の運用の正本は docs/spec/guard/pi-guard.md。ここは「いつ何を調べ・測ったか」を積む場所 -->

## 記録 I1 — 2026-10-13

- **対象バージョン**: pi 1.1.0 / 1.2.0（npm の global）、WSL 3.0.3.0、Windows 11 Pro（ビルド 26100）
- **環境**: Windows 11 の個人機。web 調査は Brave / Exa 経由の検索と本文取得。
  **各拡張・各ツールは README を読んだだけで、動作は確かめていない**（確かめたものは「実測」と書く）

### 結論

- **pi 本体にはツール実行の承認（permission）の機能が無い。** 公式の方針は「承認の画面ではなく、OS・コンテナ・仮想マシンの境界で安全を作る」。
  拡張の `tool_call` で呼び出しを止めることはできるが、判定の規則・伏字化・子エージェントは自前で書く必要がある
- **`!`（ユーザーの直接実行）と、読み込んだ拡張・MCP は、ツールの判定の外にある。**
  ツール承認の拡張やハーネスだけでは、この経路は塞げない。塞ぐなら pi のプロセス全体を境界の内側で動かす
- **Windows ネイティブには、WSL の Fence / bubblewrap に相当する手軽な境界が無い。**
  使える手段はどれも、隔離の強さ・使い勝手・永続性のどれかを諦める（下の比較）
- **運用の判断（2026-10-13）**: Windows ネイティブの `pi` は、**信頼できる環境でだけ開き、ガードは付けない**。
  守りが要る作業は、WSL の `pis`（ハーネス ＋ 境界）で行う。ハーネスの Windows への移植は見送る
  （理由は下の「ハーネスの Windows 移植の見送り」）

### pi の権限まわり（一次情報）

| 事実 | 出典 |
| --- | --- |
| ツールは pi プロセスの OS 権限で動き、ツール呼び出しごとの承認は無い | `docs/security.md`（同梱のドキュメント） |
| `-a` / `--approve` はプロジェクトの `.pi/`（拡張・MCP・設定）を読み込んでよいかの判断（project trust）で、ツール承認ではない | `docs/security.md`、`docs/cli.md` |
| 拡張は `tool_call` で `{ block: true }` を返してツールを止められる（同梱の例 `permission-gate.ts`） | `examples/extensions/` |
| 隔離の公式な手段は 4 つ: Plain Docker、Docker Sandboxes、OpenShell、Gondolin 拡張（組み込みツールと `!` だけをマイクロ VM へ回す） | `docs/containerization.md` |
| native Windows の `bash` ツールと `!` は Git Bash（無ければ `bash.exe`）を使う。`powershell` ツールは任意で、`!` は常に Bash | `docs/windows.md` |

### コミュニティの動き（README・記事の記述。動作は未確認）

| やり方 | 例 |
| --- | --- |
| 権限の拡張で allow / ask / deny を足す | `pi-permission-system`（MasuRii 版と、その fork の `@gotgenes/pi-permission-system`）。bash のワイルドカード規則、機密パスの拒否（シンボリックリンク解決後も）、作業フォルダ外の確認、fail-closed、子エージェントの確認の転送を掲げる。`@sysid/pi-sandbox` は、組み込みの read / write / edit が Node の中で動き OS の sandbox が効かないことを理由に、ツールの前段にガード層を足す。`pi-permission-modes` もある |
| コンテナ・VM に入れる | Docker、Lubuntu の VM（作業フォルダを共有）、Windows Sandbox（作業フォルダを渡す）。公式 Discussion に「WSL でもよいので VM で動かせ」という回答 |
| OS の機能で包む | bubblewrap（`--ro-bind / /` ＋作業フォルダだけ `--bind`）、Firejail（事故防止程度）、systemd-nspawn、agent-safehouse |

### Windows の隔離の選択肢

Codex の Windows サンドボックスの記事（2026-05）が挙げる、エージェントの境界の 4 要件は次のとおり。
(1) 実行時に任意のバイナリを選べる、(2) ホストの作業フォルダを読み書きできる、(3) 管理者権限を要求しない、(4) 制限が子プロセスに伝わる。
AgentPatterns.ai の整理では、単独でこれを満たす Windows の仕組みは無い。

| 手段 | 永続 | 隔離 | 要点 |
| --- | --- | --- | --- |
| Windows Sandbox | ✕（共有フォルダだけ残る） | 強い | 使い捨ての軽量 VM。要件 (2) を満たさない。毎回コールドスタート。Windows Home では使えない（AgentPatterns.ai の整理） |
| Hyper-V の VM | ◎ | 強い | ゲストの Windows のライセンスとイメージが要る。チェックポイントで戻せる |
| WSL2 | ◎ | 中〜強（境界を足せば） | Linux のみ。Windows 専用ソフトは動かせない |
| `wslc`（WSL containers） | ○ | 中 | **Linux コンテナ専用**（Windows のイメージは動かない）。Docker 互換の CLI、常駐デーモンもディストロも不要。この機に入っている（WSL 3.0.3.0） |
| Windows コンテナ | ○ | 中 | GUI が無く、ホストとビルド番号を揃える必要がある |
| AppContainer | — | — | 実行時にバイナリを選ぶ用途に不向きで、ファイアウォール規則が子プロセスに効かない（要件 1・4 を満たさない） |
| 専用の標準ユーザー ＋ OS の制限 | ◎ | 弱〜中（同じ OS） | Codex と `fmuecke/agent-win-sandbox` が採る「うまくいく組み合わせ」。VM 級の隔離ではない |

- **WSL2 と Hyper-V・Sandbox の併用は、今は問題ない。** 実測（この機）: WSL2 の Ubuntu が稼働し、同時に Windows Sandbox が起動した（`HypervisorPresent = True`）。
  この機には Hyper-V の管理サービス（`vmms`）は無く、基盤だけが有効。昔の衝突は他社のハイパーバイザー（VirtualBox / VMware）との排他が主因
- **ライセンスの都合で Docker Desktop を使えない場合の代替として `wslc` がある**が、Linux 専用

### 専用ユーザー方式（`fmuecke/agent-win-sandbox`）

README を読んだ範囲（未導入・未実測）。

- エージェントを別の標準ユーザー（`C:\Users\AgentSandbox`）として、独立した logon session と非対話のデスクトップで動かす
- そのユーザーの外向き TCP / UDP を、Windows Filtering Platform（`wfp-lock`）でローカルのプロキシのポートだけに絞る。
  プロキシ（`network-sandbox`）は許可リストの `host:port` にだけ中継する。プロキシは別のアカウント（起動したユーザー）で動く
- 書き込みは作業フォルダに限る想定。ランチャー・設定・ネットワークツールは管理者だけが書ける場所に置く
- 到達範囲の点検コマンド（`sandbox-exposure`）があり、作者の実測で 17〜31 点（通常の開発者セッション）→ 51〜67 点（導入後）。**制御の評価であって、リスクの倍率ではない**と注記されている
- 作者が明記する限界: VM 級の隔離ではない。悪意あるコード・プロンプトインジェクションには対抗できない。許可リストに入れたサービス経由の持ち出し、`AgentSandbox` が読めるデータ、スナップショット・資源制限・監査ログ・自動停止は守備範囲外
- 導入と削除に管理者権限が要る。使い捨ての Windows Sandbox の中で試す `Run-Demo.ps1` がある

#### 専用ユーザーに引き継がれないもの（一般的な Windows の挙動。この方式での実測はしていない）

| 項目 | 引き継ぎ |
| --- | --- |
| WinHTTP のプロキシ（`netsh winhttp`）、マシンの証明書ストア | 引き継ぐ（マシン全体の設定） |
| ユーザーごとのプロキシ（WinINET、PAC）、環境変数、`.npmrc`、git の設定 | 引き継がない |
| ドメインの SSO（Kerberos / NTLM）による認証 | 引き継がない。ローカルのユーザーには資格情報が無く、認証付きの上流プロキシは `407` になりうる |
| ユーザーのストアに入れた CA、Node・Python の独自の CA | 引き継がない。別途設定が要る |

- `network-sandbox` の README には、TLS を検査するファイアウォールの下では CA を各ツールに信頼させればよいという説明がある。
  **上流の（認証付き）プロキシへ中継する機能の記載は見当たらない**（README を読んだ範囲。コードは未確認）。
  許可リストの宛先へ直接接続する作りに見えるので、出口が「認証付きの明示プロキシ」の環境では、そのままでは届かない可能性が高い
- 設計としては、許可リストのプロキシを**ドメインの資格情報を持つ自分のユーザー**で動かし、上流へ中継させ、
  エージェントのユーザーはローカルのプロキシとだけ話す形が筋がよい（改造か自前の薄い中継が要る。未実装）

### Windows Sandbox の `wsb` コマンド

新しい Windows Sandbox は `wsb` の CLI を持つ（`wsb --help`、この機の実測）。

| コマンド | 用途 |
| --- | --- |
| `wsb start [--id] [-c <設定>]` | 起動（設定は `.wsb` 相当の文字列） |
| `wsb share --id … -f <ホスト> [-s <中>] [-w]` | 実行中のインスタンスへフォルダを追加で共有（`-w` で書き込み可） |
| `wsb exec --id … -c <コマンド> -r ExistingLogin\|System [-d <作業ディレクトリ>]` | 中でコマンドを実行（標準出力は取れない） |
| `wsb connect --id …` | リモートセッションを開く |
| `wsb list` / `wsb stop` / `wsb ip` | 一覧・停止・IP の取得 |

- Microsoft は CLI が将来変わりうると注意している（4sysops の記事）。**複数インスタンスの同時起動は未確認**
- **Sandbox の内側から判定する方法**: ユーザー名 `WDAGUtilityAccount`（実測。transcript に `Username: <乱数のホスト名>\WDAGUtilityAccount`）。
  廃止された Defender Application Guard も同じ名前を使い、偽装もできるので、安全のための判定には使えない。
  環境に合わせた挙動の切り替えには、`.wsb` が共有する印のファイルを併用する

### Windows Sandbox で chezmoi の導入を検証して分かったこと（実測、2026-10-13）

`scripts/windows/sandbox/` の検証用スクリプトで、まっさらな Sandbox に README の手順で導入した。

| 事象 | 内容 |
| --- | --- |
| winget が無い | Sandbox には App Installer が無い。`Repair-WinGetPackageManager` は何も出さずに失敗した。winget-cli の公式リリースの `DesktopAppInstaller_Dependencies.zip`（x64）を `-DependencyPath` に渡して msixbundle を入れると通った |
| `msstore` ソース | Rest API エラー（`0x8a15003b`）になり、`--source` 無しの `winget install` が全て失敗する。`winget source remove --name msstore` で回避 |
| Python 3.12 のインストーラー | **約 20 分**かかる（固まってはいない。MSI の最終段階まで 8 分以上）。Defender のリアルタイム監視を切っても短くならなかった（切れたかは未確認） |
| 連鎖する 1618 | タイムアウトで `winget` だけを止めると、残ったインストーラーが Windows Installer を占有し、後続が `1618`（別のインストールが進行中）で連鎖して失敗する。`taskkill /T` でプロセスの木ごと止める |
| 出力の取得 | ネイティブコマンドの出力は `Out-Host` を通さないと transcript に残らず、transcript は終了時にまとめて書かれる。進捗は別ファイルへ随時書く |
| 起動中のインスタンス | 起動済みだと、新しい `.wsb` の設定が反映されない。検証が終わったら Sandbox 自身が `shutdown` して終了する |
| 管理者での実行 | Sandbox の既定のユーザーは管理者。管理者での実行を拒否するスクリプトは失敗する |
| 全体の所要 | 約 50 分〜1 時間（Python のインストールが約 20 分） |

### 実装していない案（今後の検討用、未検証）

- **`pisb`（仮称）**: `wsb start` → `wsb share` → `wsb exec` → `wsb connect` で、カレントのフォルダを共有した Sandbox を 1 コマンドで開く
- **導入の高速化**: ホストの導入済みの node（`mise where node`）・pi（`%APPDATA%\npm`）・Git のフォルダを読み取り専用で共有して PATH に足す。
  再配置して動くか、共有フォルダ越しの起動が遅くないかは未確認（遅ければ共有 → ローカルへコピー → 実行）。専用のバンドル（ポータブル版の node・導入済みの pi・PortableGit）も代案
- **最小プロファイル**: Sandbox では pi の動作に要るものだけを導入する。検知で自動に切り替えると「導入の検証」と「作業場」の用途が混ざるので、`launch.ps1 -Profile` のような明示のスイッチが筋がよい

### ハーネスの Windows 移植の見送り

別系統のモデル（`second_opinion` 階層の `review` 役）に、ハーネスの設計と Windows 移植案をレビューさせた結果（コードを読んだ上での指摘。実機試験はしていない）。

| 重大度 | 指摘 |
| --- | --- |
| BLOCKER | 境界が無いと、ハーネスを通らない経路（`!`、明示ロードした拡張、MCP）を守れない。ツールの承認と OS の境界は別物 |
| MAJOR | 現行のコードは Windows の子エージェントで動かない（`spawn("pi")` が `pi.cmd` 経由、負の PID への `kill`）。`subagents` 拡張は Node で CLI を直接起動し、`taskkill` で止めている |
| MAJOR | 「Git Bash なので判定器がそのまま使える」は未確認（パス変換、ドライブパス、Windows の実行ファイル・PowerShell を呼ぶ経路） |
| MAJOR | 判定を毎回 `spawnSync` で呼ぶので、pi のイベントループが止まる。Windows での待ち時間の実測は無い。判定器の停止は fail-closed（安全側） |
| MAJOR | ルールの反映が 2 段（拡張のロード時に固定される部分と、判定 API が毎回読み直す部分）に分かれる |
| MAJOR | MCP や追加の拡張は、承認後の副作用を伏字化では取り消せない |

- 推奨された順序: 判定器は当面外部の Python のまま → 常駐化は測定の後 → JS への移植はさらに後。
  Windows では「保護付き」として出さず、守れない経路を明示した入口にとどめ、保護が要る用途は pi 全体を隔離する
- これらを踏まえ、**Windows への移植は見送り**（判断は上の「運用の判断」）。需要が増えたら再検討する

### 出典

- pi の同梱ドキュメント: `docs/security.md`、`docs/containerization.md`、`docs/windows.md`、`docs/extensions.md`、`docs/cli.md`
- <https://github.com/earendil-works/pi>
- <https://github.com/gotgenes/pi-packages/tree/main/packages/pi-permission-system>
- <https://github.com/MasuRii/pi-permission-system>
- <https://www.npmjs.com/package/@sysid/pi-sandbox>
- <https://github.com/fmuecke/agent-win-sandbox>
- <https://github.com/fmuecke/network-sandbox>
- <https://agentpatterns.ai/security/windows-sandbox-primitives-coding-agents/>
- <https://botmonster.com/ai/pi-never-asks-permission-before-touching-your-files/>
- <https://learn.microsoft.com/en-us/windows/wsl/wsl-container>
- <https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-cli>
- <https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file>
- <https://4sysops.com/archives/new-windows-sandbox-configuration-options-with-gui-and-cli/>

## 記録 I2 — 2026-10-24（OpenShell で、PowerShell の `pis` が使えない問題を解決できるか）

- **対象**: NVIDIA OpenShell v0.1.5（公式 docs の「Latest」）と、現行の `pis`（ADR-0017 決定 5）。取得日は 2026-10-24
- **方法の限界**: OpenShell は**動かしていない**。保存した公式の docs・issues と、`explore` の子の抜き書き（親が代表の行を原文で確かめた。確かめた行は「確認済み」）

### 問い

Windows ネイティブ（PowerShell）では、`pis`（フルガード + サンドボックス）が使えず、素の `pi` を信頼できる環境でだけ使っている（[ADR-0017](../../adr/0017-pi-only-and-ts-judge.md) 決定 5）。OpenShell を使えば、この状態を解決できるか。

### 事前の予想

OpenShell の対応表では Windows は「WSL 2 + Docker Desktop」の Experimental なので、PowerShell のネイティブの `pi` を直接包む形にはならず、WSL2 を経由する形になる。解決にはならない可能性が高い。

### 結果

**現状の事実（このリポジトリ）**:

- 文書が言い切っていること: Windows ネイティブにはフルガード・`pis`・サンドボックスが無い。サンドボックスが Fence に依るため。判定器は TS で動くが、フルガードの Windows 版は未着手で優先度は低い（`docs/spec/guard/pi-guard.md:151`）。守りが要る作業は、WSL の `pis` で行う（同 `:165`、ADR-0017 決定 5）
- 文書が言い切っていないこと: 「使えない」の原因を 1 つにしていない（Fence が Linux/macOS 専用、`spawn("pi")` が `pi.cmd` 経由、負の PID への `kill`、Windows での判定の待ち時間は未実測、など。別モデルによるレビューの指摘で、実機試験はしていない。`pi-isolation-options.md` の「ハーネスの Windows 移植の見送り」）。**PowerShell で `pis` を使いたい理由を、利用者の動機として書いた文書は見つからなかった**（Orca・Zed が素の `pi` を呼ぶ記述はある）
- 再検討の条件: ADR-0017 は、Windows でガード付きで使う需要が増えたときに見直す、としている

**OpenShell 側の事実**（ベンダーの一次情報。issue の日付は 2026-09〜10）:

- Windows は「WSL 2 + Docker Desktop」が **Experimental**（確認済み: `nvidia-openshell-support-matrix.md:102`）。Windows ネイティブは、`mxc` ドライバとして docs に載っているが、実行環境の一覧では「Coming soon」（確認済み: `nvidia-openshell-runtimes.md:72`。ドライバの設定の記述は `nvidia-openshell-gateways-configuration.md:1030`）
- ネイティブ Windows の提案（issue #2050。Microsoft の MXC を使う。「Linux VM・Docker Desktop・WSL なし」）は、**2026-10-13 に、無活動による stale の自動処理で「not planned」として閉じた**（確認済み: `openshell-issue-2050-native-windows-mxc.md:93`、`:766`、`:801`、`:804`）。決定として却下されたのではなく、無活動で閉じた。docs の `mxc` の記述との関係は未確認
- WSL2 + Docker Desktop では、gateway は WSL のディストロの中の systemd のユーザーサービスで動き、エンジンは Docker Desktop。サンドボックスは**コンテナ**（イメージの例: Ubuntu 24.04）。supervisor が `network_mode: host` で動くため、Docker Desktop ではホストのネットワークが WSL ではなく Docker Desktop の VM となり、supervisor が gateway に届かない。回避策は `host.docker.internal` の指定（確認済み: `openshell-issue-3880-*.md:70`、`:78`）。報告は v0.1.2、修正の PR #3924 は triage 時点で未レビュー、本体の最終状態は未確認
- WSL2 のカーネル 6.6.87 では、seccomp の probe で `sandbox create` が失敗し、報告者は「WSL2 で使うこと自体の hard blocker」と書く。カーネル 6.18 では通るという報告と、6.18 でも Windows 11 で失敗し Windows 10 で成功するという報告がある（子の抜き書き: `openshell-issue-3842-*.md:103`、`:166〜176`、`:246〜248`。issue は Closed、理由は未確認）
- ワークスペースは `openshell sandbox upload` / `--upload ./src:/workspace/src` で入れ、`download` で戻す。ホストの bind mount は、gateway のホストのパスで、既定は無効（`enable_bind_mounts = true` が要る。隔離とファイル方針を迂回しうる）（子の抜き書き: `sandboxes-overview.md:919`〜`:964`、`runtimes.md:224`）。Windows の `C:\` のパスの扱いは**原文に記述なし**
- **PowerShell から `openshell` の CLI を実行できるか、サンドボックスの中で動くのが Linux のプロセスか Windows のプロセスかは、原文に記述なし**（docker 経由は Linux コンテナ。ただし「pi は Linux 版になる」と明記した文は無い）。エディタ連携は SSH（`--editor vscode` など。子の抜き書き: `sandboxes-overview.md:317`、`:906`）

**Windows ネイティブ向けの他の候補**（子の抜き書き。ベンダー・個人ブログ・第三者を区別。取得日 2026-10-24。この子は Web 検索を実行せず、保存済みの原文だけで答えた）:

- Docker Sandboxes（`sbx`）: Windows 11（x86_64）で動き、Docker Desktop は要らない。HypervisorPlatform を管理者の PowerShell で有効にする（個人ブログ `andrewlock-…:77〜81`、確認済み: `:77`）。pi を包めるかは記述なし。ワークスペースだけを共有し、ホストの Node・git・mise が使えるかは記述なし。資格情報はネットワーク境界で注入（ベンダー、確認済み）。experimental（個人ブログ）
- Anthropic の sandbox-runtime（`srt`）: Windows のネイティブが **alpha**。管理者権限で 1 回だけインストールし、専用アカウント `srt-sandbox`、ファイルの ACL、Windows Filtering Platform で外向きの通信を制御する。**任意のプロセスを包める**（ベンダーの README と第三者の記事）。ユーザープロファイルは、資格情報ストアを除いて読める。ユーザーごとのツールが使えない可能性がある。TLS の証明書失効の互換問題と、システムの DNS が囲われない問題がある（第三者）
- Codex の Windows サンドボックス: restricted tokens（個人の gist と第三者）。Codex 専用で、他の CLI を包めるかは記述なし（二次資料のみ）
- nono: WSL2 は対応、**ネイティブ Windows は非対応**（第三者）
- Windows Sandbox・Hyper-V・WSL2 の上に自分で組む方法、AppContainer・Job Object のランチャー: 保存済みの原文には記述なし（既存の 記録 I1 に整理がある）

### 考察

言える:

- **OpenShell を使っても、「PowerShell のネイティブの `pi` を、そのまま守る」ことにはならない。** サンドボックスの中で動くのは、Docker 経由の Linux コンテナで、そこで動く `pi` は Linux 版になるとみられる（明記は無い）。つまり、WSL の `pis`（現行）で足りている「Linux の中で守る」形を、Docker Desktop と gateway を足して作り直すことになる。ネイティブの Windows の `pi`（Windows のパス・ツール）を包む手段は、docs に「Coming soon」のみ
- 事前の予想は、原文と整合した。WSL2 の不具合報告（Open の #3880、Closed の #3842）が複数あり、実運用の安定性は未確認

言えない:

- PowerShell から OpenShell の CLI を使えるか、`C:\` のリポジトリを渡す具体的な手順は、原文に無く、動かしていないので不明
- 「PowerShell で `pis` が使えない」の動機（Zed の pi-acp、Orca、制約のある環境の PC、Windows 側のリポジトリ）が文書に無い。動機によって、解決策が違う（`wsl` 経由で WSL の `pis` を呼ぶ薄いラッパー、Windows ネイティブの境界、など）

### 次の問い

- 利用者に、動機を尋ねる（どのツールから、どのリポジトリで、どの PC で）
- `explore` の子に、`websearch.py` の検索を明示して頼み直し、`srt` の Windows の既知の制限、Docker Sandboxes の対応エージェントとカスタムのテンプレート、Windows の AppContainer 系のランチャーを調べる
- `wsl` 経由で WSL の `pis` を呼び、Windows 側のリポジトリ（`/mnt/c`）を扱う薄いラッパーが、Fence の境界と両立するか（読み取りの許可の追加、速度）を確かめる

### 参照

- <https://github.com/NVIDIA/OpenShell/issues/2050>、`/3880`、`/3842`、`/1803`
- <https://docs.nvidia.com/openshell/about/support-matrix>、`docs.nvidia.com/openshell/how-it-works/sandboxes/runtimes`
- <https://andrewlock.net/running-ai-agents-safely-in-a-microvm-using-docker-sandbox/>（個人ブログ）、<https://github.com/anthropics/sandbox-runtime>、<https://rywalker.com/research/local-agent-sandboxes>（第三者）

## 記録 I3 — 2026-10-24（動機の確認と、I2 への影響）

- **観測日**: 2026-10-24。利用者への質問（`ask`）の回答

### 問い

記録 I2 で未確認だった、PowerShell で `pis` を使いたい理由。

### 結果

- 利用者の回答: **リポジトリが Windows 側にある**。自由記述: 「**Windows 起動が前提のサーバやアプリも開発するため**」
- （選択肢のうち「Windows のツールから pi を呼ぶ」「WSL を使えない PC がある」「操作を統一したいだけ」は選ばれていない）

### 考察

- 推測: Windows でしか動かないサーバ・アプリを、エージェントが**ビルド・起動して確かめる**必要がある。OpenShell の経路（WSL2 + Docker Desktop）のサンドボックスは Linux コンテナなので（I2 の確認済みの記述）、Windows 専用のアプリはその中で動かせない。**この動機では、OpenShell は解決策にならない**（I2 の見込みが、動機の面からも裏づけられた）
- 同様に、WSL の `pis` を `wsl` 経由で呼ぶ薄いラッパーも、Windows のプロセスを起動できないので、この動機には足りない（ラッパーは別の動機向け）
- 候補になるのは、**Windows ネイティブの境界**に限られる。I2 の抜き書きでは、`srt` の Windows alpha（専用アカウント・ACL・Windows Filtering Platform。任意のプロセスを包める）と、専用の標準ユーザー + OS の制限（I1）。Docker Sandboxes の microVM のゲストが Linux か Windows かは、今回の原文では確かめていない
- 言えない: どの候補も、`pi` を Windows ネイティブで包んで動かした実測が無い

### 次の問い

- `srt` の Windows alpha の既知の制限と、`pi` を包む使い方（`explore` の子が Web 検索中。[CHG-0033](../../change/0033-sandbox-build-value-assessment.md) の「重要な更新」）
- Windows ネイティブの境界で、Windows のサーバ・アプリを起動できるか（子プロセスへの制限の伝播、ポートの待ち受け、ファイアウォールの扱い）

## 記録 I4 — 2026-10-24（Windows ネイティブで `pi` を包む候補の、Web 検索による確認）

- **観測日**: 2026-10-24（検索の出力に日付は無く、取得日は実行日）。`explore` の子が `websearch.py` で検索した（Web 取得は 1 件が HTTP 403）。親が確かめた行は「確認済み」

### 問い

Windows ネイティブ（PowerShell）で、`pi` を OS の境界つきで動かす手段のうち、公式の文書で確かめられるものは何か。

### 結果

- **`srt`（Anthropic の sandbox-runtime。ベンダー、Apache-2.0、README は「Beta Research Preview」）**: 任意のコマンドを包める（確認済み: `srt-readme-official.md:325` 「wraps any command with security boundaries」）。Windows は alpha で、専用のローカルユーザー `srt-sandbox`、Windows Filtering Platform の外向きの遮断、write-restricted token、ファイルの ACL を使う（確認済み: `:968`）。導入は 1 回、`npx @anthropic-ai/sandbox-runtime windows-install`（UAC の確認が 1 回。子の抜き書き）。**既知の制限**（確認済みは行番号つき）: Schannel を使うクライアントは動かない（`:1306`）。ユーザーごとのツール（nvm/fnm の Node、ユーザー単位の winget・Scoop など）は、プロファイルの読み取りを許可しないと届かない（`:1308`）。システムサービス経由の通信（SMB など）はフェンスに当たらない（`:1314`）。システムの DNS は遮断されない、匿名トークンなどでネットワークの遮断を迂回できる、共有マシンでは他のユーザーが残存する書き込み許可を使える、トークンがコマンドラインに見える（子の抜き書き）。Windows では `NODE_USE_ENV_PROXY=1` が要る（Node 22.21 以上・24.5 以上）
- **Docker Sandboxes（`sbx`）**: Windows ネイティブで動く（ベンダー、個人ブログ）。任意のエージェントは `sbx run shell`（「Bash のログインシェル」。エージェントは入っていない）で試せる（確認済み: `docker-sbx-shell-agent.md:1882`、`:1892`）。ゲストの OS は原文で確かめていない（Bash なので Linux とみられる。推測）
- **Codex の Windows サンドボックス**: 昇格モードでは、専用のローカルユーザーにファイアウォールの規則を当て、子プロセスは restricted token（write_restricted）で動かす（ベンダーの記事の抜粋。本文は HTTP 403 で未取得）。第三者は、昇格なしのモードを「現在のユーザーから派生した restricted token」と述べる。Windows は、restricted token のファイアウォール規則を、主体でない ID に対応づけられないため、専用ユーザーを使う、との説明がある（第三者）。他の CLI を包める公式の手順は**見つからなかった**
- **オープンソースのランチャー**（名前と URL のみ。ライセンス・最終更新・Star は未取得）: `fmuecke/agent-win-sandbox`（「Docker・WSL なしで、ネイティブのビルドツールを使う」）、`akitaonrails/ai-jail`、AppContainer と Job の計画の issue（`ChristianPresley/zigguro`、完成品かは不明）。AppContainer の問題報告に「Git Bash が AppContainer の中で起動しない」
- **`pi` を Windows ネイティブで包んだ報告**: `srt`・`sbx`・Codex・nono で包んだ報告は**見つからなかった**。個人のリポジトリ（`psychobarge/pi-sandbox-windows`、0 Star）は、Docker Desktop のコンテナで `pi` を動かす（ネイティブではない）。第三者の記事は、`pi` は「ユーザーの権限で動き、組み込みのサンドボックスが無い」と述べる

### 考察

言える: `srt` の Windows alpha が、公式の文書の範囲で、**任意のコマンド・Windows ネイティブ・管理者権限は導入時の 1 回**を満たす唯一の候補。ただし alpha で、既知の制限が、開発の道具（ユーザーごとの Node、Schannel を使うクライアント）に当たる可能性がある。言えない: `pi` を包んで動くか、Windows のサーバ・アプリを起動できるか（実測が無い）。

### 次の問い

[CHG-0034](../../change/0034-windows-native-pi-boundary.md) の段 W1（Windows 実機で `srt` に `pi` を包む）。`agent-win-sandbox` の README とライセンス。

### 参照

- <https://github.com/anthropics/sandbox-runtime>（ベンダー）、<https://docs.docker.com/ai/sandboxes/agents/shell/>（ベンダー）
- <https://openai.com/index/building-codex-windows-sandbox/>（ベンダー）、<https://agentpatterns.ai/security/windows-sandbox-primitives-coding-agents/>（第三者）
- <https://github.com/fmuecke/agent-win-sandbox>、<https://github.com/psychobarge/pi-sandbox-windows>（個人）
