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
