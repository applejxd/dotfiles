# OpenShell と現行サンドボックスの比較（境界の位置・資格情報・WSL2・既知の問題）

<!-- 現在の総合判断は docs/change/ の候補比較表が正本（CHG-0033）。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 O1 — 2026-10-23

- **対象バージョン**: NVIDIA OpenShell v0.1.5（公式 docs の「Latest」）。比較の相手は、この環境の `pis`（Fence 0.1.67、pi 1.3.0）
- **環境**: WSL2（カーネル 6.18.54.1-microsoft-standard-WSL2）、基準コミット `0573900`
- **方法の限界**: OpenShell は**動かしていない**。公式の docs・README・issues・NVD と、第三者の記事を読んだだけ

### 問い

OpenShell は、現行の `pis` のサンドボックス（Fence + `ocs` + ハーネスの判定器 + 子の worktree/Landlock）と比べて、境界の位置・資格情報・ネットワーク・方針の検証・WSL2/GPU・導入コスト・成熟度の点でどう違うか。何を取り入れられるか。

### 事前の予想

以前の調査（2026-09-29。[CHG-0009](../../change/closed/0009-ocs-simplify-for-accidents.md)）では、OpenShell は alpha で、Docker と gateway が要り、WSL2 は experimental、と評価した。予想: 現在も alpha で、導入は重く、WSL2 では動かない。

### 方法・条件

`imozuru`（芋づる式に原文を保存する調査のスキル）で 5 周。**要る主張 8 つ**（場、信頼境界と資格情報、ネットワークとファイル、WSL2・GPU・対応表、失敗と制約、形式検証、先行例、エージェントでの事例）ごとに、原文を保存して行番号を付けた。原文は `.tmp/research/openshell-vs-pis-sandbox/sources/`（リポジトリには入れない。以降の「出典」の URL から再取得できる）、抜き書き 51 件は、原文の指定の行と機械で照合して一致を確かめた。調査の経過は同じディレクトリの `log.md`。

### 結果

**成熟度と対応**（公式の対応表。2026-10-23 取得）

- 安定版は「週に 1 回ほど」出る。Windows は「WSL 2 + Docker Desktop」が **Experimental**、Linux（Debian/Ubuntu）と Apple Silicon の macOS が Supported
- 実行環境は Docker・Podman・Kubernetes・MicroVM。**コンテナや VM なしの実行は無い**。Docker は Engine 28.0 以上
- Landlock **ABI 3 以上**（Linux 6.2 以上）と、seccomp のユーザー通知が必須。満たさなければ起動に失敗する、と書かれている
- 以前の記録の「alpha」は、古い版の時点のもの（比較記事は v0.0.116 を基準にしている）。「WSL2 は experimental」は今も同じ

**境界と資格情報**（公式の architecture と security best practices）

- 信頼側の `supervisor` が判定・資格情報の供給・DNS・接続の確立を行い、エージェント側の `sandbox` は判定しない。**エージェントは本物の資格情報を持たず**、不透明な placeholder を受け取る。placeholder は、許可されたホスト・ポート・パスにだけ解決される
- ネットワークは既定で全拒否。接続を、観測した**実行ファイルの識別**（SHA256 を初回の観測値に固定）に結び付ける。L7（HTTP のメソッド・パス）の検査は `protocol` を指定したときだけで、**既定は audit（ログに出すが通す）**
- ファイルは Landlock の必須の基準線。追加のファイル方針の既定は `best_effort`（使えないパスを飛ばすことがある）。広すぎる読み書きのパス（`/` など）は検証で拒否される
- 方針の形式検証（prover）は、ネットワーク方針と資格情報の範囲から Z3 のモデルを作り、4 つの質問（リンクローカルへの到達、HTTP でない通信方式による資格情報の及ぶホストへの到達、資格情報の到達の拡大、能力の拡大）に答える。**ファイル方針は対象外**。エージェントが提案した規則の自動承認を、1 件でも検出があれば止める

#### 導入の形

- サンドボックスは**イメージから作る**（`openshell sandbox create --from <image> -- <command>`）。ファイルは `upload` で入れる（主コマンドとの併用は未対応）。ホストの bind mount は、**既定で無効**で、有効にすると「OpenShell の隔離とファイルの制御を無効にしうる」と明記されている

**既知の問題と脆弱性**（GitHub の issues、NVD）

| 件 | 内容 | 状態 |
| --- | --- | --- |
| #3880（2026-09-29） | WSL 2 + Docker Desktop で、サンドボックスが Ready にならない（supervisor が gateway に届かない） | Open |
| #3842（2026-09-29） | WSL 2（カーネル 6.6.87）で `sandbox create` が seccomp の probe で失敗。コメントに、6.18 のカーネルでは動く、mirrored のネットワークモードを無効にすると動く、との報告 | Closed |
| #803（2026-04-10） | 0.0.26 で、正しい方針でも Landlock のファイル制限が強制されない | Closed |
| #3911（2026-09-29） | `hard_requirement` を指定しても、Landlock ABI 0 のホストで起動に成功する | Open |
| #1169（2026-05-05） | DNS の名前解決が、データ漏洩の経路になる | Closed |
| CVE-2026-65083（NVD、2026-08-25 公開） | サンドボックスの provisioning API で、禁止する入力の一覧が不完全になりうる。CVSS 9.9 Critical | 修正済みの版は**不明** |
| CVE-2026-65091（NVD、2026-08-25 公開） | 悪意のある gateway による OS コマンドの注入。CVSS 8.8 High | 修正済みの版は**不明** |

#### 第三者の見方

- 比較記事（Ry Walker、2026-09-16 更新）は、**現行で使っている Fence**、Anthropic の sandbox-runtime、nono、Landrun、OpenShell などを並べている。「OS の隔離を使う道具（srt・nono・Fence・Landrun）は、道具を別のゲストに作り直さずに済む一方、ホストのカーネルと監督プロセスを信頼し続ける」と整理している
- レビュー記事は、「ベンダーは長い期間の敵対的な実験を報告しているが、独立した再現は公表されていない」「個々に許可した操作の組み合わせが、許可していない経路になりうる」と述べる
- **先行例**: nono は、OS の隔離 + 信頼側の監督 + 資格情報の代理（placeholder）を、OpenShell より軽量な形で持つ。Anthropic の sandbox-runtime にも、プロキシでの署名（`credentials.sigv4`）がある。環境変数で渡した値は子から見える、許可された API の誤用は防げない、という限界は共通

#### 食い違い

- 公式は「基準線を強制できなければ起動に失敗する」と書くが、利用者の報告（#3911、Open）は、`hard_requirement` でも ABI 0 で起動すると言う
- 比較記事は OpenShell を「Alpha」とするが、公式の対応表は「stable を毎週」と書く（版の時点が違う）

**届かなかったもの**: OpenShell-Research の記事（形式検証の経緯）、Z3 の prover を試した記事、Windows と WSL2 の運用記事、資格情報の付け足しの先行例の記事（3 本）、NVIDIA の脆弱性アドバイザリ（修正済みの版）。理由は、URL が長い・URL の語が保護対象のパスの規則に当たる、で取得を見送ったため（[CHG-0032](../../change/0032-guard-url-false-positive.md)）。pi を OpenShell で動かした事例は、探した範囲では無かった。

### 考察

言える: OpenShell は、(1) 判定する側を境界の外に置く、(2) 資格情報をエージェントに渡さない、(3) ネットワークを実行ファイル単位・API 単位で縛る、(4) 方針の変更を形式検証する、という点で、現行より強い設計を**文書の上では**持つ。一方、導入にはコンテナまたは VM が要り、ホストの道具をそのまま使えず、WSL2 は experimental で、実際の不具合報告がある。2026-08 に重大な脆弱性が 2 件公表されている。

言えない: OpenShell の実際の強さ。独立した検証は見つからず、記述はベンダーのもの。現行より安全か、乗り換えて得か、は、この記録では決められない。

### 次の問い

取れなかった一次資料の再取得（修正済みの版、形式検証の経緯、資格情報の代理の先行例）、候補ごとの WSL2・複数 CLI・子エージェント隔離への対応、現行の保守の費用の実測。これらは [CHG-0033](../../change/0033-sandbox-build-value-assessment.md) で扱う。

### 参照

- 公式 Support Matrix: <https://docs.nvidia.com/openshell/about/support-matrix>（「Windows (WSL 2 + Docker Desktop)x86_64Experimental」「ABI 3 or newer, introduced in Linux 6.2」）
- 公式 Security Best Practices: <https://docs.nvidia.com/openshell/security/best-practices>（「The agent receives an opaque placeholder, not the real API key or access token.」）
- 公式 Architecture: <https://docs.nvidia.com/openshell/about/architecture>（「The supervisor is trusted and makes the decisions.」）
- prover の README: <https://github.com/NVIDIA/OpenShell/blob/main/crates/openshell-prover/README.md>
- issues: <https://github.com/NVIDIA/OpenShell/issues/3880>、同 `/3842`、`/803`、`/3911`、`/1169`、`/1444`
- NVD: <https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2026-65083>（同 `CVE-2026-65091`）
- 比較記事: <https://rywalker.com/research/local-agent-sandboxes>（「They avoid rebuilding the toolchain into a separate guest」）、nono の README: <https://github.com/always-further/nono>
- 第三者のレビュー: <https://aireiter.com/blog/nvidia-openshell-review-security-runtime>

出典の取得日はすべて 2026-10-23。
