# CHG-0064: 開発単位の環境で隔離する（WSL は専用ディストロ、ネイティブ Ubuntu は Incus 系。ネイティブ側は保留）

- **状態**: Exploring
- **保留中の範囲**: ネイティブ Ubuntu 側（段 N1〜N3）。ネイティブ機のセッションで再開する（この案件が引き継ぎの正本）
- **更新日**: 2026-11-06
- **基準**: [ADR-0027](../adr/0027-isolation-unit-is-environment.md)（隔離の単位は開発環境）。環境は WSL2（Ubuntu 24.04）と、別のネイティブ Ubuntu の機

## 目的と非目的

**目的**: ADR-0027 の P3（開発単位の環境）を実現する。SLAM（GPU 推論・ROS 2・rerun）・`docker compose`（GPU つきのサービス・認証つきレジストリの pull）・apt でしか入らないパッケージのビルドを、**開発単位ごとに作って消せる専用の環境**の中で行う。WSL では専用ディストロ、ネイティブ Ubuntu では Incus 系のシステムコンテナを使う。作成と削除を手順 1 つにし、資格情報は環境ごとに限定する。

**非目的**:

- コンテナの入れ子（`pisd --dind`）と入れ子の中の GPU の実装（実装は保留の枝に残す。再開の条件は、専用環境で足りないと分かったとき）
- Fence（OS サンドボックス）の縮小・撤去（別の案件で、費用つきで提案する）
- 会社固有の情報の記述（公開リポジトリ。用途は一般化して書く）

## 実施計画

段ラベルの定義表。`W` は WSL 側、`N` はネイティブ Ubuntu 側、`C` は共通。

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| W1 | 既存の専用ディストロ（`docs/spec/sandbox/wsl-sandbox.md`）が通しで使えるか分からない | 隔離の否定試験・docker と compose・GPU（compose の GPU 指定を含む）・`docker login` の保存先を実機で測る（AI の `ssh` は拒否されるため、利用者が手元の端末で実行する） | 未着手（利用者の実行待ち） |
| W2 | 環境の作成と削除が重い | WSL 版の `dev-new` / `dev-rm` / `dev-ls` / `dev-snap`（テンプレートの `wsl --export`・`--import`、単位ごとのポート割当）。既存の `scripts/windows/wsl-sandbox/create.ps1` を拡張する（Windows 資産。実機は利用者） | 未着手 |
| W3 | エージェント（pi）の置き場と、LLM の認証の置き場が決まっていない | 「環境の中で pi を動かす」か「ホストの pi が `ssh` で操作する」か。後者は `remote_exec` の確認の緩和が展開後にも効くかの確認が要る。ホストに認証ブローカーを常駐させ、mirrored のネットワークで共有される `localhost` 経由で使う案の検証 | 未着手 |
| N1 | ネイティブ Ubuntu で Incus が要件を満たすか分からない | 導入と小さな試行（下の「次の調査・実験」の T1〜T5） | **保留**（ネイティブ機のセッションで継続） |
| N2 | 既存の OSS（下の「候補比較」）を使うか、借りるか、自作するか | 候補の導入前調査と、小さな試行 | **保留**（同上） |
| N3 | WSL と同じ操作の形（`dev-*`）をネイティブでも使いたい | `dev-*` の Incus バックエンド（`incus launch` / `delete -f` / `list` / `snapshot`）の設計。N2 で既存の OSS を採るなら不要 | **保留**（同上） |
| C1 | バックエンドごとに操作が変わる | `dev-*` の共通の形（引数・プロファイル・資格情報の入れ方・ポート割当）の仕様化 | 未着手（W2 と N3 の前） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

調査の根拠は [隔離方式の選び直し](../research/agents/isolation-reselection-2026-11.md) と [Incus の導入前調査](../research/agents/incus-dev-environment.md)（いずれも動かして確かめたのは前者の「試作」の節だけ。Incus は文書の読解）。

- **プロセス単位の OS サンドボックスは、docker・compose・GPU・apt と両立しない**。主流は環境（VM・コンテナ）ごとの隔離で、エージェントも docker も環境の中で動かす。
- **WSL2 の専用ディストロ**は既存の設計がある（rootful の Docker・NVIDIA toolkit・Tailscale SSH。通しの実行は未検証）。評価で分かったこと: compose と GPU は素直に動く見込み。要調整は、認証つきレジストリの資格情報の置き場・コードの渡し方（記述なし）・ポート公開（設計は不可。mirrored なら届く見込み）・`remote_exec` の緩和・ゲストからホストの `localhost` と tailnet への経路。境界は「VM を共有する別のディストロ」で、VM の境界ではない。
- **ネイティブ Ubuntu の Incus**（導入前調査。動かしていない）: GPU の共有・非特権のまま入れ子の Docker（`security.nesting=true`）・clone と snapshot の即時性に見込みがある。要調整は、DDS のマルチキャスト（既定の NAT の `incusbr0` は LAN に出ない見込み。macvlan か host bridge）・入れ子の Docker の runc と AppArmor の回帰（修正済みの版があるが、導入する版で確認が要る）・GPU の compose 指定。コンテナはホストのカーネルを共有する。
- **Incus を使う既存の OSS が複数ある**（検索の説明文の範囲。内容は未確認。「候補比較」）。とくに `isx`（旧 incus-spawn）は、Incus のシステムコンテナに、**ホスト側の proxy が要求に認証を付ける（環境の中に認証を入れない）**、テンプレートからの copy-on-write の clone、Docker Compose・入れ子のコンテナ、KVM の VM への切り替え、`pi` を含む複数のエージェント、を持つと説明されている。**このリポジトリの P3 と認証ブローカーの方針に最も近い**ので、自作する前に評価する（新しい規則: 公開情報に既にあるものは、まず評価する）。

## 未解決点

- **N1〜N3（保留の再開条件）**: ネイティブ Ubuntu の機のセッションで、「次の調査・実験」の T1〜T5 を実行し、結果をこの案件と [Incus の導入前調査](../research/agents/incus-dev-environment.md) に追記する。再開は、そのセッションで始めてよい（この案件が引き継ぎの正本）。
- N2: `isx` などの OSS が、GPU（NVIDIA・`/dev/nvidia*`）・DDS・rerun・pi を満たすか。WSL2 の中でも動くか（Incus が WSL2 で動くか。未調査）。保守の状況・ライセンス・認証の proxy の仕組み（TLS を中継するのか）。
- W3: LLM の認証を環境の中に入れない方法。
- 環境の中のエージェントから、ホストの認証・ファイル・Incus のソケットへ届かないことの否定試験の手順。

## 次の調査・実験

### ネイティブ Ubuntu のセッションで行う試行（N1。各段 15 分以内。利用者が手元の機で行う）

前提: ホストで `nvidia-smi` が通り、nvidia-container-toolkit が入っている。ここで使う版・コマンドは調査時点の文書に基づく（**実行前に公式 docs で確かめる**）。

| 段 | 内容 | 合格の目安 |
| --- | --- | --- |
| T1 | 導入と初期化。Zabbly の APT（`lts-7.0` を第一候補、`lts-6.0` を代替）を、**鍵の指紋を確かめて**追加し、`apt install incus`。`incus admin init`（ストレージは btrfs。試行は loop でよい。ネットワークは既定の `incusbr0`）。ホストに Docker があれば `incusbr0` からの外向き通信が通るか | 初期化が通り、`incus launch images:ubuntu/24.04 t1` が起動する |
| T2 | GPU。`nvidia.runtime=true` と `gpu` デバイスで `t1` に渡し、`nvidia-smi -L`。`incus snapshot` と `incus copy t1 t2` と `incus delete -f t2` の所要時間 | 中で GPU が見える。clone が数秒以内（実測を記録） |
| T3 | 入れ子の Docker と GPU。`t1` に `security.nesting=true`。中に docker-ce と nvidia-container-toolkit を入れ、`nvidia-ctk runtime configure --runtime=docker`、`/etc/nvidia-container-runtime/config.toml` の `no-cgroups = true`。`docker run hello-world`（runc と AppArmor の回帰の確認）・`docker run --gpus all <CUDA の base イメージ> nvidia-smi`・compose の `deploy.resources.reservations.devices`・`docker login ghcr.io`（環境専用の読み取り専用トークン）での pull | 非特権のまま compose と GPU が通る |
| T4 | DDS と rerun。macvlan か host bridge の NIC のプロファイルを作り、別の機（ロボットの代用）との間で ROS 2 のマルチキャスト（`ros2 multicast`）。rerun の Web ビューアの外部公開（`proxy` デバイス） | LAN の別の機と DDS の発見が通る。ビューアにブラウザから届く |
| T5 | 否定試験。`t1` の中から、ホストの Incus のソケット（`/var/lib/incus/unix.socket`）・ホストの home・`~/.docker` などの認証情報が見えない。ホスト側で `incus config show t1 --expanded` に、意図しない `disk` と `proxy` が無い | 見えない・付いていない |

### OSS の評価（N2）

`isx`（`github.com/Sanne/incus-spawn`）を最初に評価する。確かめること: インストール（Ubuntu 用の APT が公開されている）・`isx init`・テンプレートの定義（YAML）・`isx branch`（clone）・認証の proxy の仕組み・`pi` の対応・GPU の渡し方・Docker Compose・DDS・ライセンス・保守の状況。次に `code-on-incus`・`lincubate`（LXD）・`agent_incus` などを、同じ観点で短く比べる。

### WSL 側（W1〜W3）

利用者が `pk wsl-sandbox-probe`（`.tmp/keep/wsl-sandbox-probe/`。私用のスクリプトで、手順は W1 の内容に書いたとおり）を実行し、結果で W2・W3 を設計する。

## 評価基準

**必須**:

1. 環境の中で、compose・GPU・apt・ROS 2・rerun が動く
2. 環境の作成と削除が、手順 1 つで繰り返せる（テンプレート・clone）
3. 環境の中のエージェントから、ホストの認証・ファイル・管理用のソケットへ届かない
4. 資格情報を、環境ごとに限定できる（読み取り専用・短命）。LLM の認証を環境の中に入れない方法がある

**望ましい**:

- 既存の OSS をそのまま、または少しの設定で使える（自作を増やさない）
- WSL とネイティブで、同じ操作（`dev-*`）で使える
- 保守されている・ライセンスが明確

## 候補比較

下の表の根拠は、**検索結果の説明文だけ**で、内容は未確認（N2 で確かめる）。

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| Incus（素。`dev-*` を自作） | 公式・活発。GPU の共有・非特権の入れ子の Docker・clone と snapshot | `dev-*`・資格情報の proxy・テンプレートの運用を自作する | T1〜T5 の全部 | 未評価 | T1〜T5 |
| `isx`（旧 incus-spawn。Incus を使う OSS） | 認証を環境に入れない proxy・copy-on-write の clone・Docker Compose・入れ子・VM への切り替え・`pi` を含むエージェントに対応と説明されている | Java（GraalVM）製の新しい OSS。成熟度・保守者の人数は不明 | GPU・DDS・rerun・WSL2・proxy の仕組み・ライセンス | 未評価（最優先） | N2 |
| `code-on-incus`（`mensfeld/code-on-incus`） | エージェントごとに独立した機械（root・Docker・systemd）・脅威の検知と説明されている | Claude Code 中心（README は今回取得できず） | 同上 | 未評価 | N2 |
| `lincubate`（`popey/lincubate`。LXD） | LXD のコンテナ・プロジェクトの bind mount・複数のエージェント | LXD（snap）。ホストの bind mount は隔離を弱める | 同上 | 未評価 | N2 |
| `agent_incus`・`BlindMatty/incus` など | Incus のコンテナ・資源制限・ネットワーク隔離・セッションの永続 | 小規模の個人の OSS | 同上 | 未評価 | N2 |
| Distrobox・devcontainer | 手軽 | home を共有する前提（Distrobox）・入れ子の Docker に特権が要る | — | 見送り寄り（隔離が弱い） | — |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `docs/spec/sandbox/wsl-sandbox.md` | 専用ディストロの 1 つの環境 → 開発単位の環境を作る・消す手順（テンプレート・ポート割当・資格情報） | ADR-0027・W1〜W3 の結果 | 未適用（W2 の後） |
| `docs/spec/sandbox/` に開発単位の環境の仕様を新設 | なし → `dev-*` の共通の形と、WSL・Incus の各バックエンド | C1・N3 | 未適用 |

### W2・C1 の設計案（2026-11-06。計画役の案。実装は未着手）

- **共通の形は「前段 1 本＋バックエンドの薄い実行器」**。前段は Python の `dev`（`argv[0]` で `dev-new` などに分岐。Linux 上で試験できる）。名前の検証・スロットとポートの割当・状態・削除の確認・プロファイルは前段に置く。WSL 版の実行器は PowerShell（JSON を返すだけ）、Incus 版は同じ動詞表を実装する（`isx` を採るなら adapter）。
- コマンド: `dev-new <単位> [--template T] [--profile gpu,docker,ros] [--ssh] [--keepalive] [--cred ...]`・`dev-rm <単位> [--yes] [--discard]`（`--yes` なしは計画の表示だけ。未コミット・未 push があれば拒否）・`dev-ls`・`dev-snap`（restore は常に新しい単位を作る）・`dev-tmpl`・`dev-shell`・`dev-exec`・`dev-stop`（`wsl --terminate`。`wsl --shutdown` は呼ばない）・`dev-cred`。
- 名前: 単位 `^[a-z][a-z0-9-]{0,19}$`、バックエンド上は `dev-<単位>`（接頭辞で、メインのディストロや既存の `sandbox` に削除が届かない）。状態は `~/.local/state/dev-env/`（秘密を含めない。存在の真実はバックエンドの一覧）。
- **ポート割当**（mirrored では単位間で衝突する）: スロット 0〜49、`20000 + 100*slot` から 100 個（sshd・rerun の Web と gRPC・compose 用 `DEV_PORT_APP_<n>`）。`ROS_DOMAIN_ID` もスロット。
- **資格情報の口は `dev-cred` の 1 か所**（stdin → 単位内の tmpfs `/run/dev-cred`。テンプレートに口は無く、封印時に監査する）。LLM の認証（W3）の決定は、kind の表の 1 行の違いで吸収する。
- **WSL 版**: 既存の `create.ps1` は変えず、`scripts/windows/dev-env/` を新設（W1 が検証中のため。W1 の後に統合）。テンプレートは一時ディストロを rootfs から作り、封印（machine-id・ホスト鍵・認証の削除）と監査（認証ファイル・トークンの接頭辞）を通してから `wsl --export`。単位の作成は `wsl --import` → 単位の初期化。削除は `wsl --unregister`（計画→`--yes`・接頭辞・状態ファイルの記録・既定ディストロの除外）。メインの WSL からは interop で PowerShell を呼ぶ（呼べないときはコマンドを表示して pending を記録し、後で `dev-ls --reconcile`）。
- **最大の懸念（推測）**: 複数のディストロで dockerd を同時に動かすと、共有のネットワーク名前空間で `docker0` と iptables が衝突する可能性。**実機で先に確かめる**（確かめるまでは「同時に動かす docker の単位は 1 つ」を既定にする）。
- **新しい権限は既定で無効**: `--ssh`・`--keepalive`・`--cred`・LAN 公開。AI からの `dev-new/rm/snap/tmpl/cred/exec/shell/stop` は `[bash] deny` へ（狭める変更）。
- 実装の分担（契約書を先に固定して見込みで並列）: A 前段（Python。Linux で試験）・B WSL 実行器（`dev-wsl.ps1`）・C ゲスト資材（`template-build.sh`・`template-audit.sh`・`unit-init.sh`・`cred-install.sh`）・D docs・E 実機確認用のスクリプト・F ガード（deny）。
- **利用者への確認（推奨つき）**: ①状態の置き場を前段（Linux の `~/.local/state`）にする（推奨） ②同時に動かす docker の単位の既定を 1 にする（推奨） ③AI からの `dev-*` を deny にする（推奨） ④入口を単一の `dev` ＋ symlink にする（推奨） ⑤テンプレートをプロファイルごとに作る（推奨） ⑥ポート範囲 20000〜24999 が既存のものと衝突しないか ⑦`create.ps1` との統合は W1 の後にする（推奨） ⑧`isx` を採るなら C1 の範囲が変わる（ネイティブ側は保留）。

## 実装・検証

採用が決まった部分だけ具体化する。現時点で実装したものは無い（`pisd` は P2 の別の案件。ここでは扱わない）。

## 重要な更新

| 日付 | 更新 | 理由・証拠 |
| --- | --- | --- |
| 2026-11-06 | 案件を作成。ネイティブ Ubuntu 側（N1〜N3）を**保留**にし、ネイティブ機のセッションで継続する | 利用者の指示。手元にネイティブ Ubuntu の機がある。ADR-0027 で隔離の単位を環境に決めた |
| 2026-11-06 | Incus を使う既存の OSS（特に `isx`）が複数あると分かり、N2 を追加した | 検索（プロジェクトの説明文）。自作より先に評価するため |
