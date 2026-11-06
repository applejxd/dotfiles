# 隔離方式の選び直し（microVM・Docker・nono）の調査と試作

- **日付**: 2026-11-05〜06
- **対象**: 他のリポジトリ（外部コード・依存・Web アプリ・GPU を実行する）で、AI コーディングエージェント（pi）を動かす隔離方式。dotfiles は隔離を使わない（[ADR-0025](../../adr/0025-dotfiles-dev-without-os-sandbox.md)）。
- **方法**: Web 調査は `explore` の子 5 本（読み取りと検索だけ。親が代表の行を確かめた）。試作は親が実機で行った（この機械: WSL2・カーネル 6.18.54.1・NVIDIA RTX 3070・rootless Docker 29.9）。別系統のモデル（GPT-6 Astra）へ、事実と暫定の結論を渡して相談した。**動かして確かめたのは「試作」の節だけ。それ以外は文書ベース**。
- **関連**: 過去の見送り（Docker 系・OpenShell・nono。いずれも文書ベース）は [CHG-0009](../../change/closed/0009-ocs-simplify-for-accidents.md)・[CHG-0033](../../change/0033-sandbox-build-value-assessment.md)・[OpenShell 比較](openshell-comparison.md)・[代替候補の比較](sandbox-alternatives-comparison.md)・[nono の WSL2 での試験（CHG-0036）](../../change/0036-nono-trial-on-wsl2.md)。

## 要件

①作業リポジトリだけを見せ、秘密を持ち込まない ②GPU を使う開発 ③内側の Web アプリをホストのブラウザで開く ④Windows 側の画像を読み取り専用で渡す ⑤独自の自作コードを増やさない ⑥ホストの道具（mise・uv）と pi の設定・履歴の二重管理を避ける。守る対象は「うっかり」とプロンプトインジェクションの緩和（[ADR-0012](../../adr/0012-ocs-boundary-for-accidents.md)）。

## 調査の要点（出典は子の原文。2026-10〜11 の公式 docs・Issue・一次記事）

- **microVM と GPU は WSL2 では両立しない（間接的な根拠）。** microVM の GPU は VFIO（IOMMU）が前提。WSL2 の GPU は `/dev/dxg` の GPU-PV で、IOMMU は出ず、PCI パススルーの要望は 2020 年から未解決。Firecracker は GPU 不可。Docker Sandboxes（`sbx`）の `--gpu` は VFIO・実験的・専有 GPU が前提。KVM 自体は WSL2（Windows 11・amd64）で使える見込み。
- **microVM の流行の主因は、サーバ側・多テナント・未信頼コードの実行。** ローカルの CLI（Claude Code・Codex・Gemini・Cursor・Copilot CLI）は OS 機構（Seatbelt・bubblewrap・Landlock）が主流。Cursor は VM を起動の遅さ・メモリで退けた。ローカルで VM を選んだのは Docker Sandboxes（2026-04）と Claude Cowork。サーバ側は gVisor と Firecracker が併存。
- **この目的の決め手は隔離の強さではなく、外部通信の遮断・秘密を持ち込まない・マウント範囲の限定。** Anthropic（2026-05）: 流出事例はどちらも許可された経路から出た・許可リストは「機能の付与」・最も弱かったのは自作の層。エージェント自身が防御を回避した事例がある。
- コンテナの脱出 CVE（runc 2025-11・NVIDIA Container Toolkit 2024・2025）は、悪意あるイメージ・設定が前提。GPU 付きは固有の追加リスク（toolkit の hook・ドライバの ioctl 面。gVisor の nvproxy も素通し）。Toolkit は 1.17.8 以上に保つ。
- pi 公式 docs は Plain Docker・Docker Sandboxes（pi-kit）・OpenShell（`--from pi`）・Gondolin（pi 本体と認証をホストに残し、ツールだけを microVM に回す）を載せた。ホストの道具をそのまま使える既製品は OS 隔離型（nono・srt・Fence）だけ。OpenShell は WSL2 が experimental のまま。
- WSL2 の注意: 作業ツリーは ext4 に置く（`/mnt/c` は 9P で遅く、Landlock の強制も不安定）。git worktree は `.git` が絶対パスの指し先で、そのままマウントすると壊れる（共有 `.git` の hooks 経由でホストのコード実行に繋がりうる）。rootless ではコンテナの uid 0 がホストの利用者に対応する。

## 試作 P2: nono v0.81.0（実測）

導入は版固定（`gh release verify` とチェックサムで検証）、一時領域に置いて試験場だけで実行。WSL2 のカーネル 6.18 で Landlock V7 検出・V6 強制。

| 項目 | 結果 |
| --- | --- |
| ファイル境界 | 合格。許可外の canary は読めず、ディレクトリの一覧と書き込みは拒否。ただし完全なパスの `stat` は成功し存在は見える。環境変数は継承 |
| **ホストへの実行経路** | **不合格。** `cmd.exe` の実行は拒否されたが、**WSL interop・rootless Docker・systemd ユーザーマネージャのソケットに内側から `connect` できた**（pathname の Unix ソケットは非仲介。WSL2 では仲介が seccomp notify の EBUSY で使えず、ソケットを隠す mount namespace は未提供） |
| 通信遮断（`--block-net`）・GPU 列挙（`--allow-gpu`） | 合格 |
| 資格情報（プロキシ型） | 未実施。WSL2 では `wsl2_proxy_policy` の opt-in が要る。公式 pack に Copilot は無い |

判定: ホストへの実行経路を閉じるのに、別に mount namespace の層が要る（現行の Fence が `/run/user` を隠しているのと同じ）。この WSL2 では nono 単体は要件①の境界が迂回可能。再評価の条件は AF_UNIX の仲介が WSL2 で使える（WSL#9548）か、ソケットの不可視化が提供されること。

## 試作 P1: rootless Docker（実測。既存の ubuntu:24.04・PyTorch 入りイメージと、pi 公式の Dockerfile で作ったイメージ）

定型: `docker run --rm --gpus all --network none --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp --pids-limit N --memory M -v <作業>:/work`。

| 項目 | 結果と実測 |
| --- | --- |
| ファイル境界・ホストの実行経路 | 合格。ホストの canary は**存在しない**。`/run/user`・`/run/WSL`・docker.sock・`/mnt/c`・ホームが無い |
| 特権・資源 | 合格。`CapEff=0`・`NoNewPrivs=1`・メモリとプロセス数を制限 |
| GPU | 合格。上の定型のまま PyTorch 2.10（cu128）の行列積が完走（RTX 3070） |
| Web | 合格（条件つき）。`-p 127.0.0.1:PORT` で Windows の `curl.exe` からも 200。既定の bridge は外向きが開いている。`--internal` にするとポート公開も効かない。**転送コンテナ（sidecar）を bridge と internal の両方へ繋ぐと、ブラウザから届き、app は外向き不可が両立した** |
| 画像 | 合格。単一ファイルの `:ro` bind mount で、画像だけが見え、書き込み・削除・隣のファイルは不可 |
| pi の起動 | 合格。pi 公式の Plain Docker の Dockerfile（pi 1.5.0 固定。`node:24-bookworm-slim` に git・ripgrep）で、硬化した run のまま `pi --version`。資格情報が無いと `No API key found` で正常終了 |
| 独立 clone の git | 合格。`git clone --depth 1 --no-hardlinks` の clone をマウントし、内側で branch・commit・diff。コミットは clone の中だけに残り、元のリポジトリは不変。push は origin が見えず通信も無いので失敗＝取り込みはホスト側の `git fetch` |
| ホストのループバック | 隔離されている。ホストの `127.0.0.1` のサーバに、コンテナ（bridge）から `host.docker.internal` 経由で接続できない。ホスト側の Envoy ブローカーはコンテナから届かない＝ブローカーはコンテナの網の中に置く |
| 外向きの許可リスト | 合格（構成の実証）。`--internal` の pi コンテナは外向きが無い（DNS も IP 直も不可）。**既存の Envoy のバイナリを `debian:12` に `:ro` で入れた sidecar（bridge と internal の両方）**を介してだけ、宣言した上流に届き、`Host` ヘッダを偽装しても上流は固定。資格情報の注入（SDS）は未実測 |

### 資格情報の置き方（比較。実測は構成まで）

| 案 | 中身 | 利点 | 欠点・未確認 |
| --- | --- | --- | --- |
| A. 内側のボリューム | pi 公式の Plain Docker。コンテナ内で `/login`、トークンは名前つきボリューム | 追加の部品なし | トークンが内側にある（エージェントが読める）。外向きを絞らないと持ち出せる。Astra の整理では要件の見直し |
| B. Envoy の sidecar | 本物の認証は sidecar だけがマウント。pi にはダミーとブローカーの URL だけ | 本物の認証が内側に出ない。外向きがブローカー経由の 1 経路になり許可リストが自然に成立 | Envoy の設定を `0.0.0.0` で待ち受けるよう直す・agent 置き場（設定の写し）の組み立ては自作が残る。pi・GitHub・検索の 3 経路は未実測 |
| C. pi をホストに残しツールだけをコンテナへ（Gondolin 型） | 認証はホストのまま | 認証が出ない | pi の拡張・ハーネス（フルガード）と tool の差し替えの整合が要る。microVM 前提で GPU 不可 |

### 未実施

- 実際の LLM 呼び出し（本物の認証が要る。利用者の操作）・案 B の資格情報の注入（SDS）。
- agent 置き場（`AGENTS.md`・skills・ハーネス拡張・設定の写し）の組み立て。現行の `pis` が自作している部分の、コンテナ版。
- ホストの mise・uv（プロジェクトごとの道具）のイメージへの導入。GPU 付きの pi の run（pi のイメージと PyTorch の同居はイメージの合成が要る）。

## 外部への相談（GPT-6 Astra。回答は意見であって事実ではない）

結論: 「最も強い隔離」ではなく「必要な境界を、最少の例外と最少の自作で維持できる方式」を選ぶ。nono を先に判定し、難所を自作で埋めず Docker に切り替える。指摘: ①「見せる」の意味（内容か存在か）を固定する ②共有 `.git` は hooks だけの問題ではなく、使い捨ての独立 clone で試す ③外部通信は 3 つに分ける（ツール・pi からモデル・ブラウザ） ④資格情報は pi と認証を外に残す→既製の代理→要件の見直しの順で、内側の短命トークンは要件変更 ⑤ホストの mise/uv は同じ宣言ファイルから内側へ導入するほうが安いことがある ⑥承認は境界の拡張にだけ置く。撤去の優先は、広いシェル解釈を行う判定器・独自ネットワークブローカー・多段の中継・同期処理。

## 暫定の方針と次

Docker（rootless・硬化）を第一候補にする。microVM は WSL2 で GPU と両立しないので主方式にせず、非 GPU・高リスクの作業の将来の選択肢（Gondolin・sbx）に残す。

pi は公式の Dockerfile でそのまま動き、独立 clone と外向きの許可リスト（既存 Envoy の sidecar）は構成として通った。**残る決め手は、資格情報を外に置く案 B を、実 LLM 呼び出しで確かめること**（利用者の操作が要る）。内側のボリュームに置く案 A は部品が増えないが、トークンが内側に入る。

現行の Fence と自作一式の縮小・撤去は、案 B の実測の後に、費用つきで判断する。縮小の対象の候補は Fence の境界の組み立て（`boundary.py` 約 700 行）と起動の一部。残るのは資格情報のブローカー（`broker.py` 約 1,100 行）。
