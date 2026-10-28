# 121_ubuntu の apt と Pi 専用の /etc を Ansible に移した試作の実測

観測日: 2026-10-29。対象: `home/.chezmoiscripts/100_linux/run_once_after_121_ubuntu.sh.tmpl` の apt 導入・Raspberry Pi 専用の `/etc`（zram・earlyoom・sysctl）・サービス操作。
環境: Docker の `ubuntu:24.04`（amd64。コンテナなので systemd と実際の Pi は無い）、`ansible-core==2.18.6`（`uv tool install`）、`worker`（子）が playbook を書き、親が補って再測定した。
問いと背景は [調査記録](ansible-for-sudo-scripts.md)、案件は [CHG-0048](../../change/closed/0048-ansible-system-layer.md)。

## 結果（実測）

| 項目 | 結果 |
| --- | --- |
| 行数 | 元のスクリプト 168 行（該当部分は約 120 行）。playbook 133 行。**短くなっていない**（設定の中身を YAML に書くため） |
| ansible-core の導入 | `uv` の導入込みで約 80 秒。容量 31MB（uv の Python を取ると別に 117MB）。前提に `python3`・`python3-apt` が要る（素のイメージには無く、無いと失敗する） |
| 実行 | 1 回目 428 秒（大半は apt の取得）、2 回目 **30 秒・changed=0**（冪等） |
| `--check`（まっさらな環境） | **失敗した**。「apt で入れた clang を使う読み取りの task」が、check では apt が実行されないため、clang が無く、`rc=127` で落ちる |
| 回避策（playbook が新しく要った） | `changed_when: false` が 4・`failed_when: false` が 1・`check_mode: false` が 3・`assert` が 1 |

## 分かった落とし穴（3 つ。どれも一般的な Ansible の性質）

1. **`command` と `shell` は check モードで実行されない**（公開情報で確認: <https://oneuptime.com/blog/post/2026-02-21-how-to-use-ansible-check-mode-to-test-playbooks/view>、<https://github.com/ansible/ansible/issues/14950>。確認日 2026-10-29）。出力を後続が使うと、`register` が空になって落ちる。読み取りだけの task には、`check_mode: false` を 1 つずつ付ける保守が要る。
2. **それでも、同じ実行で入れるパッケージに依存する task は、まっさらな環境の `--check` で落ちる**（clang の例）。`when: not ansible_check_mode` で飛ばす必要があり、**check の結果が、実際の実行を予測しなくなる**。既に入っている環境（更新の用途）では動くと見られる（未測定）。
3. **コマンドラインの `-e is_raspi=false` は、文字列の `"false"` になり、`when: is_raspi` が真になる**。最初の測定は、これで Pi の設定が走り（`linux-modules-extra-raspi` の導入に失敗）、子は「`is_raspi=false` の実行」と誤って報告した。実際の運用では、chezmoi のデータを Ansible に渡す口が新しく要り、真偽値の型を保つ（JSON で渡す、`| bool`）必要がある。**黙って別の分岐に入る型の誤りは、シェルの `{{ if }}` には無い種類の不具合**。

## 良かった点

- 設定ファイルの内容と、条件（`when`）が、YAML に宣言的に並び、読みやすい。
- 設定が変わったときだけ、サービスを再起動する（`notify`／handler）。2 回目が `changed=0` で、手書きの `cmp -s` の判定が要らない。
- `--diff` で、変更の中身が見える。

## 評価（[CHG-0048 の撤退の条件](../../change/closed/0048-ansible-system-layer.md) に照らして）

- **手書きの冪等性の検査が減るか**: この範囲は、元から `tee` と `apt-get install` が中心で、検査は少なかった。**減る分より、新しい回避策（上の 5・3・1）の方が多い**（実測）。
- **`--check` が実用になるか**: 更新の用途では動くと見られるが、まっさらな環境では予測にならず、`check_mode` の注記が要る（実測）。
- **版を上げたときの手直し**: 未評価。
- **Raspberry Pi での時間と容量**: 未実施（amd64 のコンテナだけ）。実行は 1 回目の大半が apt で、シェルと同じ。追加の費用は、導入 80 秒と 31MB、2 回目の実行 30 秒。

## 限界（未確認）

- 実際の Raspberry Pi（aarch64・systemd あり）と、`become` を付けた形（一般ユーザ）、ClamAV、`do_upgrade=true`、非 Pi 側の正しい真偽値での実行は、未実施。
- 元のシェルの実行時間は、測っていない（比較は、playbook の側だけ）。
