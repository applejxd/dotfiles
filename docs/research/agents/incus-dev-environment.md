# 開発単位の環境のバックエンド: ネイティブ Ubuntu の Incus（導入前調査）

- **日付**: 2026-11-06
- **目的**: [ADR-0027](../../adr/0027-isolation-unit-is-environment.md) の「開発単位の環境」を、ネイティブ Ubuntu で Incus（LXD の fork）のシステムコンテナが担えるかを調べる。**動かしていない**。公式 docs（lxc/incus の `doc/`）・runc の issue・Debian の BTS・第三者のブログを読んだだけ（ブログは主張。一部の公式ページは取得できなかった）。
- **用途**: ①SLAM（GPU 推論・ROS 2 の DDS・rerun）②`docker compose` のサービスが GPU を使い、認証つきのレジストリから pull する ③apt でしか入らないパッケージのビルド。

## 結論（暫定）

| 用途 | 判定 | 要点 |
| --- | --- | --- |
| ① SLAM | 要調整 | GPU の共有は問題ない。DDS のマルチキャストは既定の `incusbr0`（NAT）では LAN に出ない見込みで、macvlan か host bridge が要る。GUI のソケット共有は隔離を弱める |
| ② compose・GPU・認証つき pull | 要調整 | `security.nesting=true`・環境内の nvidia-container-toolkit・`no-cgroups = true` で通る報告がある。runc と AppArmor の既知の回帰があり、この構成の実機確認は未了 |
| ③ apt のビルド | 満たす見込み | システムコンテナは通常の Ubuntu として使える |

推奨のバックエンドは **Incus**（Zabbly の `lts-7.0`、代替は `lts-6.0`）。ストレージは btrfs か ZFS（clone と snapshot が即時）。LXD は、Ubuntu Pro のサポートなど固有の理由がなければ選ばない（これは調査に含まれた意見）。

## 事実（要点）

- **導入**: Ubuntu 24.04 以降は `apt install incus`（native は 6.0 系）。Zabbly の APT に `lts-6.0`・`lts-7.0`・`stable`・`daily`。Incus 7.0 LTS は 2026-05 に公開され 2031-06 までサポート。
- **GPU**: コンテナは `gpu` デバイスでホストのドライバを共有し、1 枚を複数のコンテナで共有できる。`nvidia.runtime=true` はホスト側の toolkit が要る。VM は VFIO で専有（単一 GPU の機では現実的でない）。
- **入れ子の Docker**: `security.nesting=true` で非特権のまま動く。GPU を使うには、コンテナ内に toolkit を入れ、`no-cgroups = true` にする。**runc 1.2.8 / 1.3.3 以降と liblxc の AppArmor の profile で、入れ子の Docker が全コンテナ起動に失敗した前例**がある（上流の修正は liblxc 6.0.6 と 7.0。Debian trixie は 2026-09 に修正）。
- **ネットワーク**: 既定は L2 の bridge `incusbr0`（NAT）。LAN のロボットとの通信には macvlan か host bridge（macvlan はホストと直接通信できない）。ホストの Docker は FORWARD を drop にして、Incus の通信を止めることがある。
- **隔離**: コンテナは既定で非特権（user namespace）。ホストのディレクトリは `disk` デバイスで共有しない限り見えない。ただしコンテナは**ホストのカーネルを共有**し、GPU の device node を渡すとホストの NVIDIA ドライバが攻撃面に入る。`incus-admin` グループのソケットは実質 root なので、環境の中のエージェントに渡さない。
- **作成・削除**: btrfs・ZFS・LVM は clone が即時で、2 つ目以降のインスタンスの作成はほぼ即時（実測はしていない）。`incus snapshot`・`incus copy`・`incus publish`・プロファイル・cloud-init が使える。

## 推奨の構成案（推測）

- 1 開発単位 = 1 つの非特権の Incus コンテナ。プロファイルを層に分ける（`dev-base`: 資源制限／`dev-gpu`／`dev-nest`／`dev-net-lan`）。GUI のソケットは別のプロファイルで、既定では付けない。
- 資格情報: 環境の中で、環境専用の読み取り専用トークンで `docker login`。ホストの home・認証情報・Incus のソケットは渡さない。
- コマンドの割り当て: `dev-new` = `incus launch`、`dev-rm` = `incus delete -f`、`dev-ls` = `incus list`、`dev-snap` = `incus snapshot`、テンプレート = `incus publish`。

## 未確認（主なもの）

- native の 24.04 パッケージ（6.0 系）と Zabbly の各版が、入れ子の Docker の回帰の修正を含むか。
- 入れ子の Docker で GPU が通るか（compose の `deploy.resources.reservations.devices` を含む）・`nvidia.runtime=true` と自前の toolkit の差。
- DDS のマルチキャストが `incusbr0`・macvlan・bridged のそれぞれで通るか。
- `proxy` デバイスの記法・`limits.*` のキー・`ubuntu:` remote の有無・作成削除の実測時間。

次: 手元のネイティブ Ubuntu で、導入・GPU・入れ子の Docker と GPU・DDS・否定試験の小さな試行を行い、結果を ADR-0027 の「未決」へ反映する。

## 追補（2026-11-06。実機なしの事前調査）

この節は、[CHG-0064](../../change/0064-dev-environment-isolation.md) の T1〜T5 の前に、文献で確かめたこと。**動かしていない**。出典は Linux Containers のフォーラム・NVIDIA Container Toolkit の issue・Incus の公式文書・解説記事（主張を含む）。Incus の公式文書の一部（`devices_disk` など）は取得できず、記述は一般知識で未確認。

### 1. 入れ子の Docker ＋ NVIDIA GPU（T3 の確認項目）

| 事実 | 出典 |
| --- | --- |
| Incus の開発者の発言（2024-02）: NVIDIA が作った LXC 連携（`nvidia.runtime`）は非特権でだけ、Docker 連携は特権でだけ動く。回避: Incus 側で `nvidia.runtime` を使わず、`gpu` デバイスだけ渡し、**コンテナの中に NVIDIA のドライバと toolkit を入れて特権にする** | Linux Containers フォーラム「Incus, docker and NVIDIA GPU」 |
| **非特権で通す報告**: 内側の `/etc/nvidia-container-runtime/config.toml` で `no-cgroups = true`（エラー「failed to add device rules」の回避。toolkit 1.14.0 では効かず 1.14.1 以降で効く）。古い報告ではさらに LXC の AppArmor 設定（`raw.apparmor`）で `/proc/driver/nvidia/gpus/...` を許す必要があった | NVIDIA Container Toolkit issue #290（2021〜2023。現在 closed） |
| 2025-08 の利用者も同じエラー（`bpf_prog_query(BPF_CGROUP_DEVICE) failed`）に当たり、上の手順で解決したと返信 | 同フォーラム |
| LXD の文書にも、`security.nesting` と BTRFS のプールを使う「Docker で GPU」の手順がある（本文は未読） | LXD 文書 |

結論: **非特権で通る経路は報告されているが、纏細で版依存**。T3 で、(a) 非特権＋`no-cgroups = true`（toolkit 1.14.1 以降）、(b) 非特権＋`raw.apparmor`、(c) 特権＋コンテナ内のドライバ、(d) VM への GPU パススルー（VFIO）をこの順に試す。ホストのドライバと、コンテナ内の toolkit の版を記録する。

### 2. 土台イメージを Incus へ配る方法

| 事実 | 出典 |
| --- | --- |
| Incus 6.3 以降は OCI イメージ（Docker のイメージ）を直接起動できるが、**アプリケーションコンテナ**になる（イメージのプロセスが PID 1、init なし）。**systemd も入れ子の dockerd も動かない** | Stephane Robert の解説・Incus の発表（FOSDEM 2025） |
| Incus は OCI イメージを「使う」が、Dockerfile から「作らない」。podman で作って import する手順はある | 同上、フォーラム「Build OCI images with podman and import into Incus」 |
| システムコンテナの初期設定は cloud-init（プロファイルの vendor-data、インスタンスの user-data）でできる。`incus publish` でテンプレートイメージにできる | Incus 公式文書「How to use cloud-init」 |

示唆: **Incus 専用の別イメージを作らずに済む案**。Incus のシステムコンテナ（Ubuntu）に、cloud-init で docker-ce・nvidia-container-toolkit・compose だけを入れ、**同じ OCI の土台イメージ（ghcr）を、箱の中の docker で動かす**。箱は「自前の docker を持つホスト」として扱うので、agent コンテナにこの箱の docker のソケットを渡しても、穴は箱の中に閉じる（内側の `--network host` は箱のネットワーク名前空間）。この場合、WSL 側と native 側で、イメージと compose の定義が共通になる。

### 3. ホストの Docker との衝突

- Docker がホストの FORWARD を DROP にすると、`incusbr0` からの通信が止まる。公式文書の対処: `DOCKER-USER` チェーンに、ブリッジ向けの ACCEPT を足す（Incus の「How to configure your firewall」）。新しい Incus は独自の ACCEPT 規則を FORWARD に書くという記事もある（未確認）。native 機のホストで Docker を使っているなら、T1 で確かめる。

### 4. リポジトリの置き場とブランチの受け渡し（設計案。未確認）

- リポジトリは native 機のホストに置き、Incus の `disk` デバイスで箱へマウントする（`shift=true` で UID を合わせる。`readonly` を設定できる）。`.git/hooks` と `.git/config` は、別の `disk` デバイスを `readonly` で重ねる。**オプションとファイル単位のマウントは公式文書を取得できず未確認**。
- ブランチの受け渡し: 箱の中のエージェントはローカルのブランチに commit する（push の資格情報は渡さない）。**native 機の SSH セッション（箱の外）で、人が `git push`**。Windows 側の作業用のリポジトリは GitHub から取り込む。PR ビューアを廃止すれば、この受け渡しを単純にできる（別で検討中）。

### 5. WSL2 での実機確認（2026-11-07。使い捨てディストロ。T1〜T7 すべて合格）

WSL2 の中で Incus のシステムコンテナ（以下「箱」）が動くかを、使い捨てのディストロ（Ubuntu 24.04。systemd 有効）で確かめた（確認用のスクリプトは非公開メモ。RTX 3070・mirrored ネットワークの機）。**要件の主要部分は、すべて満たせた**。ただし、いくつかの設定が要る。

環境の事実（T0）:

| 項目 | 結果 |
| --- | --- |
| カーネル | 6.18 系の WSL2 カーネル |
| AppArmor | **無効**（カーネルが対応していない） |
| ファイルシステム | **overlay のみ**（btrfs と ZFS は無い）。Incus のストレージは `dir`（clone は丸ごとコピー。9 秒前後） |
| `/dev/kvm` | **無い**（Incus の VM は使えない。VM への GPU パススルーは WSL では不可） |
| GPU | `/dev/dxg` と `/usr/lib/wsl/lib` があり、ホスト側で GPU が見える |

試験の結果:

| 試験 | 結果 | 要点と必要な設定 |
| --- | --- | --- |
| T1 導入と起動 | 合格 | Ubuntu 24.04 の標準パッケージ（6.0.0）。初期化は `incus admin init --minimal`（`dir` と `incusbr0`）。`images:ubuntu/24.04` の起動は 30〜45 秒 |
| T1b 箱の外向き通信 | 合格（**要対処**） | 既定では**通らない**。WSL2 は全ディストロが 1 つのネットワーク名前空間を共有し、別のディストロの Docker が `FORWARD` を `policy drop` にするため、`incusbr0` 向けの許可が無い。`nft insert rule ip filter DOCKER-USER iifname incusbr0 accept` と、`oifname incusbr0 ct state related,established accept` で通る（VM の再起動で消える。恒久化は別途） |
| T2 GPU を箱へ | 合格（**要設定**） | `/dev/dxg` を `unix-char` で渡し、`/usr/lib/wsl/lib` と `/usr/lib/wsl/drivers` を**別々の読み取り専用の `disk` デバイス**で渡す。`/usr/lib/wsl` を 1 つで渡すと、`lib` が別マウントのため中身が空になる。再帰と読み取り専用の併用は、カーネルが未対応で失敗する。箱の中で `ld.so.conf.d` に `/usr/lib/wsl/lib` を足して `ldconfig` |
| T3 入れ子の Docker | 合格 | **非特権**の箱＋`security.nesting=true`。docker.io 29.1.3、ストレージは `overlayfs`（containerd のスナップショッター）。コンテナが動く |
| T3 入れ子の GPU | 合格（**CDI のみ**） | `docker run --gpus all`（従来方式）は、既定でも `no-cgroups = true` でも失敗（`nvml error: not supported`）。**CDI は成功**: `nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml` のあと、`docker run --device nvidia.com/gpu=all`。`nvidia-ctk config --set nvidia-container-runtime.mode=cdi` なら、`--runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all` も通る（`--gpus all` は不可）。toolkit は 1.20.1。compose は `devices` に CDI 名か `runtime: nvidia` を使う（compose での確認は未実施） |
| T4 ネットワーク隔離 | 合格 | 箱から、ディストロの `127.0.0.1` と Windows の `127.0.0.1` で待ち受けるカナリアに届かない（比較対象のディストロ自身からは届く＝mirrored のループバック共有）。入れ子の Docker の `--network host` でも届かない。**`0.0.0.0` で待ち受けるサービスは、ゲートウェイ（`incusbr0` のホスト側アドレス）経由で届く**（想定どおり。ホストの `0.0.0.0` の待ち受けは箱から見える） |
| T5 D ドライブ | 合格 | `/mnt/d` を読み取り専用の `disk` で渡せ、一覧できて、書き込みは拒否される |
| T6 git の重ね | 合格（**要設定**） | リポジトリを書き込み可で渡し、`.git/hooks` と `.git/config` を読み取り専用で重ねられた。hooks は箱の中で実行され、書き換えは拒否される。`shift=true`（idmapped mount）は**この環境では使えない**（`Required idmapping abilities not available`）。代わりに `/etc/subuid` と `/etc/subgid` に `root:1000:1` を足し、箱に `raw.idmap "both 1000 1000"` を設定する（ホストの uid 1000 と箱の uid 1000 を対応させ、箱で作ったファイルの所有者がホストでも uid 1000 になる） |
| T7 複製の速度 | 合格 | `incus copy`（`dir`）で 8〜9 秒 |

読み取り:

- **箱は、ホストの `127.0.0.1` で待ち受ける認証なしのサービス（PR ビューアなど）に届かない**。専用ディストロでは届いてしまう（共有されるため）。これが、専用ディストロより箱を採る実測の根拠になる。
- **共有ネットワーク名前空間の副作用**: 別のディストロの Docker の `FORWARD drop` が、箱の通信を止める。箱の `incusbr0` は、ほかのディストロからも見える。WSL では、Incus を入れる場所（主ディストロ）と、そこで動く Docker の規則の相互作用を設計に入れる必要がある。
- **箱の外向き通信は制限していない**（T4 は、ホスト内の待ち受けへの到達だけを調べた）。許可した宛先だけに絞る仕組み（ADR-0028 の relay 型）は別に要る。
- 未確認: 再起動後の永続化（`FORWARD` の許可・`raw.idmap`）、compose での GPU、箱の中で長く動かしたときの安定性と速度、ホストの `0.0.0.0` で待ち受ける Windows 側のサービスが箱から見えるか。

### 6. 制限つきプロジェクトの実測（T10）と、箱の結合試験（e2e）

2026-11-07。使い捨ての WSL ディストロ（Incus 6.0.0）での実機の確認。（注: 実測した当時の道具の名前は試作名 `box`。名前は `kcage` に確定したので、この節のコマンド名・パスは新しい名前で書いてある。）

**T10: 管理権限のないユーザーに、Incus の制限つきプロジェクトと制限つき証明書で何を許せるか。**

| 項目 | 結果 |
| --- | --- |
| 管理ソケットへの接続・他のプロジェクトの操作・特権化・許可表（パスの一覧）にないホストパスの重ね・`raw.lxc`・`raw.idmap`・サーバー設定・ネットワーク設定 | 拒否される |
| 制限つきプロジェクトの成立条件 | 独自のプロファイルが必須（共有の default のプロファイルでは設定できない）。管理者でも、`unix-char`・`proxy` を制限つきプロジェクトのプロファイルに入れられない |
| GPU（`unix-char`）とブローカー（`proxy`）のために、それらを許す | 利用者が任意の `proxy` デバイスを足せる。**ホストの Incus の管理ソケットを箱へ転送でき、箱の中から `default` プロジェクトのインスタンス一覧を取得できた（完全な脱出）** |
| `restricted.idmap.uid` | `raw.idmap "both 0 0"` を拒否しなかった |

結論: デバイスを作れる権限は管理者権限と同じ。デバイスの作成は、root 所有の補助が許可表から固定生成するしかない（ADR-0028 の 9）。

**e2e（`kcage setup`・`kcage-root up`・箱の中の確認。proxy なしの nat モード）**

| 項目 | 結果 |
| --- | --- |
| `setup`（Incus の導入・初期化・`subuid`/`subgid`・root 所有の配備コピー・許可表・sudoers の検証と配置・`FORWARD` の許可のユニット） | 合格。ユーザーは `incus-admin` に入らない |
| 権限モデル | `rm` はパスワード必須、`sudo incus`・`incus` の直接実行は拒否、不正な id・動詞は拒否、`up`・`exec`・`ls` はパスワードなし |
| `up`（非特権・`nesting`・`raw.idmap "both 1000 1000"`・ラベル・リポジトリ rw・`.git/hooks` と `.git/config` ro・データ ro・GPU・ポートの `proxy`） | 合格 |
| 箱の中 | uid 1000、新規ファイルの所有者はホストでも uid 1000、hooks・config・データは書き込み不可、ホストのホームは見えない、GPU が見える、nat の外向き通信が通る |
| 冪等・`ls`・`stop` と再 `up` | 合格 |

e2e で見つけて直した不具合（単体試験では見つからなかったもの）:

- 配備される `kcage-root` の入口が `main()` を引数なしで呼び、全動詞が `TypeError` で落ちていた（入口を実際に実行する試験を足した）。
- `kcage register` が補助の引数の形（`--path` 必須）と合っていなかった。
- WSL のディストロの既定のユーザーに `NOPASSWD: ALL` があり、`sudo incus` が通った（`kcage doctor` に検出を足した。設計の前提）。
- `disk` に `/var/run/docker.sock` を重ねられた（`/var/run` は `/run` への symlink）。拒否リストと `.sock` の拒否を足した。

**e2e 第 3 段（`proxy-only`・`offline`・`kcage.toml` の締め付け。上流は擬似プロキシ）**

| 項目 | 結果 |
| --- | --- |
| `proxy-only` の箱 | NIC なし（箱の中のリンクは `lo` のみ）、`proxy` デバイスあり。直通は遮断、プロキシ経由は通る。DNS と IPv6 は遮断。環境変数と apt のプロキシ設定が入る。プロキシを止めると外へ出られない（fail-close） |
| `offline` の箱 | NIC もプロキシも付かず、外へ出られない |
| `kcage.toml` の締め付け | nat の許可表に `offline` を要求すると NIC なし。`proxy-only` の許可表に `nat` を要求しても NIC なしのまま。`data` の `..` と未知のキー（`privileged`）は拒否 |

見つけて直した不具合: NIC なしの箱用のプロファイルを `incus init` の後に作っていた（先に作る必要がある）。擬似プロキシが IPv4 を先に試さず、到達しない IPv6 のタイムアウトで CONNECT が応答しなかった。

e2e 第 4〜6 段（実際のテンプレート作成・箱の中の docker と GPU・gh ブローカー・selftest）の結果:

| 項目 | 結果 |
| --- | --- |
| 実際の `kcage template`（docker・compose・buildx・NVIDIA toolkit の鍵の指紋の照合・CDI ユニット・Node 24・pi） | 合格。一時の箱は後始末される |
| 箱の中の GPU（uid 1000） | RTX 3070 が見える |
| 入れ子の Docker・入れ子の GPU（`--device nvidia.com/gpu=all`）・compose の GPU 予約 | 合格 |
| 再起動後の CDI | 起動のたびに生成される |
| `gh` ブローカー | Envoy が PAT を注入して `api.github.com` に届く（箱から認証ヘッダーなしで「Bad credentials」が返る。直接送ると「Requires authentication」）。`gh` CLI も動く。本物のトークンは、箱のファイル・Incus の設定・ホストの引数のどこにも無い。箱を消すとブローカーのユニットも止まる |
| `copilot` ブローカー（ダミーの認証） | 短命トークンへの交換が失敗して `up` がきれいに止まる（箱・ユニット・引数に残らない） |
| `kcage selftest`・`kcage doctor` | 全項目 OK |

実機で見つけて直した不具合（単体試験では見つからなかったもの）:

- `incus file push -r` は、宛先のディレクトリが無いと Not Found になる（`/opt` へ push してから移す）。
- apt の Node 18 では pi が動かない（Node 22.1 以上が要る。公式配布を SHASUMS256 で検証して入れる）。
- `incus exec` は gid 0 で、docker のソケットに届かず、リポジトリに作るファイルのグループもずれる（`--group` を渡し、`docker.socket` の drop-in でソケットのグループを揃える）。
- `/dev/dxg` を重ねても mode 0660（root だけ）で、uid 1000 が GPU を開けない（mode 0666 で重ねる）。
- GPU のライブラリの索引がビルド時の `ldconfig` に載らない（CDI ユニットで起動のたびに `ldconfig` し、`--mode=wsl` で生成する）。
- `/run` は起動のたびに tmpfs で作り直され、`proxy` デバイスの listen（`bind=instance`・unix ソケット）が間に合わない（イメージに持つ `/var/lib/kcage-sock` に変更）。
- net・ブローカーの環境変数が、定義だけで箱に入っていなかった（`environment.*` へ入れる）。
- `kcage selftest` が、ブローカーのダミーの認証を秘密と誤検出した。

未検証: 本物の Copilot トークンでの動作、`aws` ブローカー（本物のロールが要る）、`hf-cache`、会社の機（TLS 検査・プロキシ・認証の粒度）、Windows 側。
