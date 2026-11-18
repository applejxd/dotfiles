# 権限ポリシーを変えるとき

対象は `home/.chezmoitemplates/pi-permission-policy.json`。**編集の前に**、正本 [permission-system の設定](../../../../docs/spec/agent-config-generation.md#permission-system-の設定)の、承認の扱い・deny の方針・ディレクトリを根にした再帰への備え・対象パスごとの節（systemd など）を読む。方針と既知の限界はそこが正本で、ここは手順だけを持つ。審査ログの件数は「何が ask になっているか」を知る入口で、**allow を足す根拠にしない**（承認は内容を理解しないまま通る）。

1. **守りたい害と、受容する危険を分ける**（秘密の流出か、囲いの外での実行か）。パスそのものの危険度で決める。操作ごと（読み取り・書き込み、システム側・ユーザー側）に、allow・ask・deny の期待値を決める。
2. **害を生む操作だけを deny にする。** 正規の開発を止める広い deny（利用者が手作業をするなら、エージェントを使う意味が無い）や、判断を先送りした ask を避ける。正本が受容した ask は、防御とは数えず、そのまま維持する。
3. **外部パスの allow を足す前に、根・配下・シンボリックリンクの到達範囲を確認する。**`external_directory_read` は、**allow を前、`..` を含む綴りの ask・deny・ask を後ろ**に並べる（後勝ち。値は symlink の実体・`..` を含む綴りのどれかに一致すればよく、後ろに置かないと allow が deny・ask を上書きする。試験で固定）。 根を起点にした再帰（`grep -r`）は、根の allow だけを見て配下の deny（`*.env` など）をすり抜ける。名前で限定した対象には、ディレクトリ自体や `/*` の allow を足さない。
4. **判定表に、通常の作業と、通してはいけない形の両方を入れて回す**（`test/agents/pi_stock/permission_cases.json`、`uv run --with pytest --with pyyaml --no-project pytest test/test_pi_permission_decisions.py -q`）。ディレクトリ自体・深い階層・似た名前・コマンドの前置きオプションと順序違い・`path` と外のフォルダの両方の面を入れる。deny を狭めたら両方を回し直す。
5. **判定表の証明範囲を超えて「確認した」と書かない。** bash から `path`・`external_directory` へ届く実ゲートは判定表の範囲外で、拡張が無い環境では試験が skip される（[権限の方針の試験](../../../../docs/spec/agent-config-generation.md#権限の方針の試験)）。範囲外と skip は「未検証」と報告し、必要な実装の読解を特定する。ask を防御に数える説明（「二重の関門」）は書かない。
6. 方針を変えたら仕様を直し、`reviewer` に、差分と判定エンジンのソースを渡して監査させる（子は外部のファイルを読めないので、参照先は `.tmp/review/` に、`read` と `write` で複製して渡す）。
