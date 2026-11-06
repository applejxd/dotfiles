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
