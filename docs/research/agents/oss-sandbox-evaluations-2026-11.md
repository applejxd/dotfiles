# 同種の OSS（coi・isx）の評価と、kcage との比較

- **日付**: 2026-11-08（静的調査。実機では動かしていない）
- **対象**: AI コーディングエージェントを Incus のコンテナで動かす OSS。coi（`code-on-incus`。[mensfeld/coi](https://github.com/mensfeld/coi)。のち coipond/coi へ移転）と isx（[Sanne/incus-spawn](https://github.com/Sanne/incus-spawn)）。
- **方法**: ソースを blobless clone し、`explore` の子で読んだ（権限・認証・git、機能、保守と統合の方式）。git の指標は親が計った。原本は archive の `oss-evaluations/`。外部の内容なので鵜呑みにしない。
- **関連**: ADR-0028・[CHG-0065](../../change/closed/0065-agent-stack-freeze.md)

## 結論

**どちらも、kcage の上に載せる・置き換える候補にならなかった**（制御面の分離・GPU・WSL2 の要件を満たさない）。ただし、coi の設計の一部は、kcage の欠陥（`mv .git` の迂回）の発見につながり、isx の git の方式（箱の中で独立 clone し、ホストからは箱の `git-upload-pack` だけに接続して取り出す）は clone モードの参考になった。

## 要件との対応

| 要件 | coi | isx |
| --- | --- | --- |
| 制御面の分離（利用者を `incus-admin` に入れない） | 逆（incus-admin に入れ、`NOPASSWD: nft` の sudoers も入れる） | 満たさない（incus-admin。特権の補助なし） |
| GPU・WSL2 | GPU の実装なし。WSL2 は「experimental・未試験」と明記 | GPU は Wayland 用の `gpu` デバイスだけ。Windows 非対応と明記 |
| proxy-only（NIC なし）・offline | なし（open・restricted・allowlist の nft） | proxy-only は NIC の ACL（NIC なしではない）、airgap あり。既定は NAT |
| pi をフルガードの拡張つきで起動 | 旗を渡せない（ラッパーで回避可）。`~/.pi/agent` の 4 ファイル（auth.json を含む）を複製 | 任意の起動文字列（`shell-command`）で `-e` を書ける。ホストの `~/.pi` は複製しない |
| 認証 | ツールの認証ファイルを箱へコピー | MITM の proxy が注入（箱は proof だけ）。実トークンはホストの設定ファイルに平文 |
| repo の渡し方 | 作業ツリーを rw で重ねる。`.git/hooks`・`config` などを ro | 箱の中で独立 clone。ホストは箱の upload-pack だけに接続して取り出す |
| 規模・保守 | Go 約 5.6 万行。上位 1 人が 91%。0.x で破壊的変更が毎リリース。SECURITY.md なし | Java 約 11 万行。上位 1 人が 85%。AI 駆動で変更が速い。Quarkus は Beta。Fedora 固定 |
| 箱の堅さ | 非特権。カーネル攻撃面の削減（opt-in）・監視（既定は無効） | 弱い（`lxc.cap.drop =`・nesting・tun 0666・idmap の分離なし） |

## 借りる価値があった点

- **coi**: `.git` の**親ディレクトリの固定**（`.git` を自分自身へ bind して `mv .git` を封じる。kcage に取り入れた）・保護パスの拡張（`.vscode`・`.husky`・`.envrc`・`.pre-commit-config.yaml`。未実装）・`security.syscalls.deny`・NIC の防御・`max_duration`。
- **isx**: 独立 clone＋fetch の git の方式・起動ごとの制限の再適用と許可外のデバイスの拒否（fail closed）・doctor の 4 値（OK／WARN／FAIL／NOTE）と `--bundle`。

## 未確認

実機での動作（GPU・WSL2・認証・競合）・coi の wiki の network 文書・isx の履歴と issue・同じ WSL に coi と kcage を入れたときの競合（`coi health --fix` が nft・sudoers を書く）。
