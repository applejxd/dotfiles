# 権限の方針の経緯・実測・決め直しの根拠（2026-11）

この文書は、`docs/spec/agent-config-generation.md` から 2026-11-18 に分離した、権限の方針の経緯・実測・決め直しの根拠の記録。
現行の仕様（何が allow・ask・deny か、所有権、受容した限界、変え方）は [spec](../../spec/agent-config-generation.md) を参照する。

観測日は各節の日付（2026-11-10〜11-18）。移した本文は逐語で、話題ごとの見出しの下に置く。

## 再帰への備えの根拠

- **ディレクトリを根にした再帰への備え（2026-11-11）**: ゲートが見るのはパスのトークンだけで、`grep -r`・`find` の再帰は中を見ない（根のトークンが読み取りと投影されるだけ。判定エンジンで確認）。`~/.ssh/*` のように `/*` だけの規則は、ディレクトリ自体（`ls ~/.ssh`・`grep -r x ~/.ssh`）に一致せず、`path` は allow のまま外のフォルダの確認（ask）へ落ちる。そのため、**秘密のディレクトリの deny は、ディレクトリ自体の規則も併せて置く**（`~/.ssh`・`~/.aws`・`~/.gnupg`・`~/.config/gh`・`~/.pi/agent/ayu`）。読み取りの許可リストのうち、pi の公開ディレクトリ（`npm`・`install`・`agents`・`git`・`prompts`・`skills`・`themes`）には、ディレクトリ自体の allow を**追加しない**（`/*` の規則だけを置く。既存の `~/.agents/skills` と `/tmp` の根の allow は、別の判断（2026-11-10）で残っている）。根の allow は、根の直下に置かれた `.env`・鍵のように `path` の deny に当たる名前のファイルへ、根を起点にした再帰が確認なしで届くため（2026-11-11 の監査の指摘。実在は未確認）。`ls ~/.pi/agent/agents` のようなディレクトリ自体への確認は残るが、減る確認は実績で数件なので受け入れる（判定表に、根が ask のままである例を置いている）。根拠の再集計（YOLO を切った後の確認 92 件）: 外のフォルダ 73 件（79%）・bash 19 件。許可リストを足した後も、ディレクトリ自体の確認（`extensions` 3 件・`agents` 2 件）が出ていた。**既知の限界（受容）**: `extensions/<名前>` を根にした再帰は `extensions/*` の allow に当たり、`logs` の ask をすり抜ける。許可したディレクトリの下に `.env`・鍵が置かれても、根を起点にした再帰では `path` の deny に当たらない。pi の公開ディレクトリについて許可するのは、秘密を置かない前提の中身（`/*`）だけで、配下に秘密が無いことの確認は取れていない（運用の条件）。

## Orca の添付ファイル

- **Orca の添付ファイル（`~/.orca/agent-session-attachments/*`）は、読み取りだけ allow**（2026-11-16。利用者の指示。`external_directory_read` に足した。貼り付け画像と同じ層）。利用者が Orca から添付したファイル（zip など）の置き場で、`unzip -d <dir> x.zip` のような**向きを証明できないコマンド**（`unproven`。読み取りと書き込みの両方を調べる）が確認になっていた。**書き込みは allow にしない**（`external_directory_write` は ask のまま）。書き込みも allow にする案は、添付の配下の symlink（zip の展開で入りうる）が、実体の既定の ask を上書きして、リンク先（例: `~/.orca/config.json`）への書き込みまで通すので、`reviewer` の監査（MAJOR）で採らなかった。**確認を避ける手順**: `cat <添付のパス> > .tmp/<話題>/x.zip` で作業ツリーへ写してから展開する（`cat` は既知の読み取りで、リダイレクト先は作業ツリーの中。判定表の `access`。`unzip -d .tmp/notes .tmp/x.zip` は外部パスが 0 件）。添付のパスを直接 `unzip` に渡すと、従来どおり確認になる（`unproven`）。`cp` は送り元が書き込み側として扱われ（2026-11-16 に、`cp` の読み取り元が拒否された実測）、確認が減らない。コマンドごとの宣言（`commandEffects`）で `unzip` を `read` と宣言しない理由は、**推論（実機未確認）**: 展開先は引数に現れない暗黙の作業ディレクトリで、`cd` で許可済みの外のディレクトリへ移った後の展開が、確認なしで通りうる。**ディレクトリ自体と、`~/.orca/` の他のパス、似た名前（`agent-session-attachments-other`）は ask のまま**（判定表）。**限界（受容）**: 添付の配下の symlink 経由で、リンク先の**読み取り**は、実体の既定の ask を上書きして通る（`/var/log/syslog` の別名の例と同じ性質。判定表の `alias`）。`path` の deny（`~/.ssh` など）は実体にも効く（判定表の `alias`）。`..` を含む形は正規化されてから評価される（判定表の `access`）。実ゲートは判定表の範囲外で、表で確かめたのは規則の評価と外部パスの投影まで。

## 並び順と .. を含む綴り

- **`external_directory_read` の並び順と、`..` を含む綴り（2026-11-18）**: 同じ面では**最後に一致した規則が勝ち**、値は「書いたままの綴り」「`..` を含む綴り」「symlink の実体」のどれかに一致すればよい（エンジンの `getPathPolicyValues`・`evaluateAnyValue`。判定表の `alias` が同じ評価で確かめる）。そのため、方針は **allow を前、`..` を含む綴りの ask（`*/../*`・`*/..`）を次、deny・ask を最後**に並べる（試験で固定）。これで、symlink が `~/.pi/agent` などの deny・ask の場所を指しても、`<許可した場所>/../../.pi/agent/…` と書いても、deny・ask のまま。
  - **既存の穴を塞いだ**: これまで、`/tmp/../etc/shadow` や `~/.agents/skills/../../Documents/x` のように `..` を含む綴りが、`/tmp/*` などの allow に一致して、確認なしで通っていた（読み取りも、裸の `external_directory` を通る書き込みも）。`..` を含む綴りは、解決後の絶対パスと一緒に候補へ入り、allow に一致した側が勝つため。裸の `external_directory`（読み書き両方）にも `*/../*`・`*/..` の ask を足した。
  - **代償**: 評価の候補に `/../` か末尾の `/..` が残る綴り（bash のトークンなど、原形が候補に残る経路。`/tmp/a/../x`）は、解決後が許可の範囲内でも ask になる（`/tmp/x` と書けば通る。判定表の `alias` で固定）。規則の置き方では、安全な `..` だけを通せない（候補値の生成側の問題）。正規化したパスで書く。
  - **対象外の綴り**: 先頭だけの `../x` は `*/../*`・`*/..` に一致しない。ただし原形 `../x` は方針の allow（すべて絶対パス）に一致せず、許可されるのは解決後の絶対パスが許可の範囲にある場合だけなので、脱出の経路にはならない。組み込みのファイルツールは、絶対パスの `..` を正規化して渡し、原形を候補に残さない（判定表の `alias` の結果を、全ツール共通の追加確認と読まない）。
  - **限界**: リンク先が「既定の ask」の場所（deny でない）のとき、許可した場所の中の symlink は確認なしで通る（この方針の allow 全般に共通）。

## システム診断の許可リスト

- **システム診断の読み取りの許可リスト（2026-11-11。Linux / WSL の一覧。OS の条件は付けない）**: `/var/log` のような診断で読むパスを、先に許可しておく。許可の根拠は、承認の履歴ではなく、パスそのものの危険度。**ディレクトリではなく名前で許可する**（ゲートはトークンだけを見るので、`/var/log/*` のような広い許可は `btmp` などへ再帰で届く）。許可: ログ（`/var/log/` の `syslog`・`kern.log`・`dmesg`・`boot.log`・`dpkg.log` と、その回転 `*.<n>`）、`/proc`（`cpuinfo`・`meminfo`・`loadavg`・`uptime`・`version`・`mounts`・`net/*`、`sys/` の `vm/*`・`fs/*`・`kernel/` の `hostname`・`osrelease`・`ostype`・`version`・`pid_max`・`threads-max`、プロセスごとの `status`・`stat`・`limits`・`io`・`cgroup`）、`/sys`（**葉の名前だけ**: `class/net/*/` の `address`・`operstate`・`mtu`・`speed`・`carrier`・`statistics/*`、`block/*/` の `size`・`stat`・`queue/*`、`class/block/*/size`、`class/thermal/*/` の `temp`・`type`、`class/hwmon/*/` の `name`・`temp*_input`・`fan*_input`、`class/power_supply/*/` の `capacity`・`status`・`online`・`type`、`devices/system/cpu` の `online`・`offline`・`possible`・`present`・`cpu*/topology/*`・`cpu*/cpufreq/*`、`devices/system/node` の `online`・`node*/meminfo`、`fs/cgroup/*`、`kernel/mm/*`。sysfs は symlink（`device`・`subsystem`・`driver` など）で別の枝へ辿れ、判定は「書いたままの別名」と「解決した実体」の**どちらかに一致した最後の規則**で決まる（拡張の `evaluateAnyValue`。source で確認）。木全体の allow は、別名経由で `iscsi_session/…/password` に届くので置かない）、`/etc`（`os-release`・`lsb-release`・`hostname`・`hosts`・`resolv.conf`・`wsl.conf`・`passwd`・`group`・`timezone`）、導入済みのものの参照（`/usr/share/doc`・`/usr/share/man`・`/usr/include`・`/var/lib/dpkg/status`）、WSL（`/mnt/wslg/*.log`）。**許可しない（ask のまま）**: `btmp`・`wtmp`・`lastlog`・`auth.log`・`secure`・`cloud-init*`（誤入力のパスワードや生成された鍵が残りうる）、`/proc/*/environ`・`mem`・`kcore`、`/etc/shadow`・`gshadow`・`sudoers`・`ssh/ssh_host_*`・`apt/auth.conf*`・`NetworkManager/system-connections/*`・`wireguard/*`・`openvpn/*`、`/var/lib/docker`・`/run/user`、`/sys/kernel/debug`、`/sys/class/iscsi_session`（CHAP の `password`・`password_in`。`/sys/class/*`・`/sys/devices/*`・`/sys/bus/*` の包括許可はこれを含むので置かない）、`/var/log/apt/*`（`history.log` のコマンドラインにプロキシの認証が残りうる。`term.log` は導入スクリプトの出力）、`/etc/fstab`（CIFS の `password=`）・`/etc/apt/sources.list*`（URL に認証を書ける）・`/etc/sysctl*`・`/proc/sys/net/*`（`tcp_fastopen_key`・`stable_secret` など秘密値）。`/proc/*/status` などの `*` は貪欲なので、`/proc/<pid>/root/…` 経由で同名のファイル（`status` など）に届く。そこで `/proc/*/root/*`・`/proc/*/cwd/*`・`/proc/*/fd/*`（開いているディレクトリへの経路）を ask に戻す（後勝ち。判定表に例）。ディレクトリ自体（`/var/log`・`/proc`・`/etc` など）の allow は置かないので、`ls /var/log` は確認になる（`ls /var/log/syslog /var/log/syslog.*` の形なら通る）。OS の条件は付けない（macOS には `/proc`・`/sys` などが無く、`/etc/hosts`・`passwd`・`group` は同じ種類のファイルなので害は無い。macOS 固有のパスは後から足す）。末尾だけの `*` は、`sources.list.d` のようなディレクトリ自体に一致するので、完全名と `.*` で書く。この一覧は知識（FHS・systemd・WSL）に基づく草案で、この機械に実在するかは確認していない。足りないパスは、確認で足す。

## systemd の unit の決め直し

- **systemd の unit（2026-11-15。決め直しを 3 回したので、根拠を残す）**: 通常の pi（pib ではない）で、user unit の開発（設置・起動・検証・削除）をエージェントが手作業なしで行えることが条件。最初に 2 か所を読み書きとも deny にしたが、開発が手作業になり実質使えなくなったので改めた。
  - **読み取り**: `~/.config/systemd/user` と `/etc/systemd/system` の下の **unit の種類の名前だけ**（`*.service`・`*.timer`・`*.socket`・`*.target`・`*.path`・`*.mount`・`*.slice`・`*.conf`）を allow。**ディレクトリ自体と `/*` は allow にしない**: `EnvironmentFile=` 用の `app.env` が同じ場所に置かれるのが定番で、ディレクトリを根にした再帰（`grep -r`）は根の allow だけを見て配下の `*.env` の deny をすり抜ける（レビューで指摘。ディレクトリ自体の確認は受け入れる）。受容: `Environment=` に直書きされた秘密と、unit 名のシンボリックリンクが指す先は、名前では防げない。
  - **書き込み**: `~/.config/systemd/user` は ask（外のフォルダの既定）。**`/etc/systemd/system` は deny**（root で起動時に実行される。設置は利用者）。ask は防御ではなく操作の確認で、user unit に書くと有効化・起動で任意のコードが動く危険は、deny にすると開発できなくなるので**受容する**（`--user` の `systemctl` の起動・再起動は確認なし。当初書いた「書き込み ask と `systemctl` ask の二重の関門」は誤りだった）。
  - **`systemctl`**: `enable`・`link` は、`--user` や `--now` などの前置きが付いても ask（`*enable*`・`*link*`。ログイン後も残る変更）。`start`・`stop`・`restart`・`daemon-reload` は、前置きなしのシステム側の形だけ ask で、`--user` は確認なし（開発の往復）。判定表に前置きの順序違いを入れた。

## pi agent と watchdog_diff の deny

- **`~/.pi/agent` と `watchdog_diff` の deny（2026-11-14）**: `~/.pi/agent` 自体と `~/.pi/agent/pi-permissions.jsonc` は許可リストに当たらず ask だったので、deny を明示した（権限の設定そのものの元データはこのリポジトリ。子や離席中は ask で 5 分止まらず即座に拒否される）。`watchdog_diff` も deny にした。pi-subagents 0.87.0 の実装（`src/watchdog/diff-tool.js`）は `git diff --no-ext-diff` で `--no-textconv` が無く、textconv が設定されたリポジトリで外部コマンドが動き得る。また path 引数が無いと permission-system の path ゲート（`handlers/gates/path.ts`）が省かれ、追跡済み `.env` の差分が確認なしで返り得る。allow にも ask にもせず deny にしたのは、差分をファイルで渡す運用で足りることと、feature の作業ディレクトリ（worktree）で使えないことがあり（推測。審査ログでは未確認）、ask が出て 5 分止まるのを避けるため。見直しの条件: 上流が `--no-textconv` を付け、path 無しでも path の deny が効くようになったとき。

## nohup の deny の実測

- **`nohup`（2026-11-17。利用者の指示）**: `nohup *` を理由つきの deny にした（長い処理は `bg_run` へ誘導する。pi の指示は「`bg_run` を使い、`&` や `nohup` を使わない」。指示は守られなくても止まらず、ask は承認されるだけ（審査ログの `<indirection-bash-wrapper>` の確認は 7 件で、全件が承認。2026-11-17 時点。`nohup` だけの件数は出せない）、YOLO が入ると ask は自動承認されるので、YOLO でも効く明示の deny にした）。**deny は、ラッパーの床（強制 ask）より先に判定される**（拡張の上流の docs の `configuration.md` の「Fail-closed behavior」。実エンジンで、`nohup x &`・`FOO=1 nohup x`・`a && nohup x`・`a | nohup b` が deny、`git commit -m 'use nohup'`・`grep nohup README.md` が allow になることを確認した）。**子エージェント**: 定義ファイルで `bash` を持つのは `worker`・`scout`・`oracle` だが、実効の道具は `settings.json` の `subagents.agentOverrides` が決める（[下の「pi-subagents の設定」](../../spec/agent-config-generation.md#pi-subagents-の設定)）。**実際に `bash` を持つのは `worker` だけ**（`scout`・`oracle` は読み取り専用に絞られている。2026-11-17 に、`scout` の実行記録で `read`・`grep`・`find`・`ls`・`contact_supervisor` だけだったことを確認）。子は `tools` が許可リストで `bg_run` を持たない。**子の確認の実測**（2026-11-17。`worker`・変更前の方針）: `cmd &` と `FOO=1 cmd` は確認なしで実行された。`env FOO=1 cmd` と `nohup cmd &` は、どちらも床の確認（`<indirection-bash-wrapper>`）になり、**誰も答えず 300 秒待って拒否された**（子の bash はその間止まる。実行記録の文言は「Nobody in the session serving this request answered the approval prompt … within 300s」）。確認が親の画面に出たかは、こちらからは区別できない。deny にすれば、この待ちが即座の拒否と理由に変わる。**子だけに `env *`・`bash -c`・`eval` を deny にする手段は無い**（上の書式の制約）。全体の deny にすると、答えられる親の作業（`timeout 60 bash -c '…'` など。YOLO ではいま通る）まで止めるので採らない。代わりに、子に渡す指示（away-shift の `child-brief.md`、feature の `worker-contract.md`）に、確認が出ない書き方（`VAR=1 cmd`・直接書く・前景の `timeout -k 10`）を書いた。指示は守られないことがあり、その場合は従来の 5 分の停止が残る（**限界**）。**子の定義ファイルには、そもそも `bash` の規則を書けない**（pi-subagents は agent の `permission` に入れ子・`bash` を許さず、定義が無効になる。[下の「agent 定義の写し」](../../spec/agent-config-generation.md#pi-subagents-の設定)の書式の制約。試験 `test_agent_permission_is_valid_for_pi_subagents`）。以下は、エンジン単体で agent の層を重ねた確認: **子の定義ファイルで `allow` に上書きしても、床で `ask` に戻る**（2026-11-17 に実エンジンで確認。測った範囲は、YOLO を切った状態で、読み取りだけではない `nohup python x.py > run.log 2>&1 &` の形）: agent の frontmatter はグローバルの後に重なって勝つが、`nohup` はラッパーの床で `allow` が `ask` に引き上げられる（`<indirection-bash-wrapper>`）。無人の子では 5 分待って拒否になる。**YOLO が入っていると、床の `ask` は自動承認される**ので、この上書きは YOLO ではそのまま通る（範囲外。子が YOLO で動くかは未確認）。deny のままなら、YOLO でも効き、理由が即座に子へ届く。試験 `test_child_agents_keep_nohup_denied` が、bash を持つ子の実際の定義ファイルにグローバルの方針を重ね、YOLO を切った状態で、上の形の `nohup` が deny のままであること（子が allow に上書きすると落ちる）を固定する。それ以外の形（読み取りだけのコマンドへの `nohup` など）と、YOLO が入った状態は固定しない。**囲い（pib）の中では、バックグラウンドのジョブはコマンドの終了で消える**（2026-11-17 に実測。bubblewrap 0.9.0。`setsid timeout 30 python3 job.py > log 2>&1 &`（2 秒待ってマーカーを書く無害なジョブ）は、囲いなしではコマンドの終了後も残ってマーカーを書き、`PIB_SANDBOX=1 pib-shell -c` の囲いありでは書かれなかった。同じジョブを囲いの中の前景で動かすと書かれる）。原因は、runner が `--unshare-pid` を使い（`pi-sandbox-runner`）、bwrap が既定で PID 1 の reaper を入れる（`bwrap --help` の `--as-pid-1`）ので、コマンドの終了で PID 名前空間ごと消えるためと考える。カーネルの仕様（init の終了で残りを SIGKILL）は、手元に `pid_namespaces(7)` が無く未確認。したがって `nohup` による常駐は、囲いありでは元から成立しない（deny は、成立しない書き方を黙って試すのを止める効果もある）。`bg_run` を持たない子の行き先は、前景で `timeout -k 10 <秒> <cmd>` を実行するか（`timeout` は既定では TERM を送るだけで、TERM を無視・ブロックする処理には上限が効かない。`-k 10` で 10 秒後に KILL する。この機械の `timeout --help` で確認。`timeout -k 10 1500 cmd` は方針で allow。2026-11-17）、親に `bg_run` での起動を頼むこと（理由文もこう案内する）。囲いなしなら `setsid timeout -k 10 <秒> <cmd> > <log> 2>&1 &` は方針で allow で、実際にも残る。確認したのは、同じジョブが囲いの中の前景で完走すること（`pib-shell -c` の直接実行）まで。`bg_run` 経由の実行は未検証（この会話は囲いの外。`bg_run` がシェルをジョブの間だけ生かすのは、実装からの推論）。**既知の限界（受容）**: ① 別のラッパーの後ろ（`setsid nohup x`・`timeout 60 nohup x`・`time nohup x`・`env FOO=1 nohup x`）は規則に当たらず、床の ask のまま（YOLO では素通り。判定表に `setsid` の例）。② `bash -c 'nohup …'` は中身を再解析しない。③ 末尾の `&` だけの常駐（`python x.py &`。囲いありではコマンドの終了で消える）・`setsid`・`disown`・`sleep`・`tail -f` は止めない（`sleep` などは通常の開発でも使い、広い deny は正規の作業を止めるため。見直すなら、実測で問題が出てから）。

## git config の deny の根拠

- **`git config`（2026-11-15。利用者の指示）**: 書き込みは **deny**（`git config*`。理由つき）にし、**名乗りの鍵（`user.name`・`user.email`）だけは ask に残す**（`git config*user.name*` など。「勝手に他人を名乗らせない」ための利用者の判断で、deny にしない。確認画面で全文を見て決める）。読み取りは allow（`--get`・`--get-all`・`--get-regexp`・`--list`・`-l`）。規則の順序は、deny → 名乗りの ask → 読み取りの allow → 否定オプションの deny（後に書いた規則が勝つ）。deny の理由は、`core.hooksPath`・`core.sshCommand`・`core.fsmonitor`・`alias.*`・`credential.*`・`include*`・`url.*` などの書き込みが、以後の git の実行に任意のコマンドを仕込めること（`--global` なら全リポジトリ）。鍵の一覧で止めると漏れるので、**書き込みはすべて deny** とし、無害な鍵（`core.autocrlf` など）も利用者が行う（このリポジトリの試験とスクリプトは `git -c` か子プロセスの中で設定し、エージェントが直接 `git config` を書く用途は見つからなかった）。**`-C` 付き（`git -C <dir> config ...`）は deny にせず、従来どおり ask**（読み取りも ask）。glob の `*` は引数 1 個ではなく `.*` で、`-C` の後ろの `*` が引数をまたぐ。`-C` 付きの読み取りを allow にすると、`git -C . config core.sshCommand 'echo config --get x'` のように値の中の ` config --get ` に一致して書き込みが通る（`reviewer` の監査で指摘。判定表に反例）。deny にすると、`git -C . commit -m 'fix config'` のような通常の操作が実行不能になる（従来からの誤検知で、ask なら確認で通せる）。**読み取りの allow が書き込みを通さない根拠（原典の読解。実機では未実行）**: git 2.43.0 の `builtin/config.c` は、明示の動作（`--get`・`--get-all`・`--get-regexp`・`--list`・`--add`・`--unset`・`--edit` など）を `OPT_BIT` で受け、2 つ以上が立つと `only one action at a time` で拒否する（`HAS_MULTI_BITS`）。最新の master は `OPT_CMDMODE` で、`options ... cannot be used together` を出す。**ただし 2.43.0 の `OPT_BIT` は否定（`--no-get` など）を受け付け、動作のビットが消えて、暗黙の動作（引数 2 個なら書き込み）に落ちる**（`parse-options.h` の `OPT_BIT_F` は `NONEG` を持たず、`parse-options.c` の `OPTION_BIT` は unset で `&= ~defval`）。`git config --get --no-get core.hooksPath x` が書き込みになる。**既存の `--get *`・`--list*`・`-l*` の allow にも元からあった穴**で、2026-11-15 に `reviewer` の指摘で見つかった。対策は、読み取りの allow の後ろに `git config*--no-*` を deny で置くこと（否定オプションは常に deny）。値に `--no-` を含む読み取りも deny になるが、`--get` で `--no-` を使う用途は見つからなかった。**限界（受容）**: ① `git -c <鍵>=<値> <コマンド>`・環境変数 `GIT_CONFIG_COUNT`・`git --no-pager config` のような前置きは、この規則に当たらない（bash の既定が allow のため。同じ限界は他の規則にもある）。② 値に `user.name` や `user.email` を含む書き込みは、deny でなく名乗りの ask に当たる（人が全文を見て判断する）。③ 読み取りでも、先頭が表示オプション（`--show-origin`・`--name-only`）や範囲（`--global`・`--local`・`--file`）の形、`git config get`・`list`（git 2.46 以降のサブコマンド形）、`-C` 付きは、allow にならない（deny か ask）。`--get`・`--list` を先頭にして言い換える。④ `--no-includes` などの否定オプションが付くと、名乗りの書き込みも deny になる（付けずに書けば ask）。⑤ `--get-regexp` などの出力は鍵と値を含むが、`--list` が既に allow なので、露出は増えない。判定表は `permission_cases.json`。

## 読み取りの許可リストの経緯

- **読み取りの許可リスト**（2026-11-10。承認の手間を下げるため最優先で足した）: pi 自身のディレクトリ（`~/.pi/agent/` の `npm/`・`install/`・`extensions/`・`agents/`・`git/`・`prompts/`・`skills/`・`themes/`、`AGENTS.md`・`settings.json`）と、skill の置き場 `~/.agents/skills/`（2026-11-10。自作 skill の `references/`・`scripts/` を読むたびに確認が出ていた。**読み取りだけ**で、書き込みは ask のまま。配備先は `chezmoi apply` で元に戻り、skill の手順書を黙って書き換えられると次回以降の指示が変わりうるため）と、`/tmp` 自体（`cd /tmp`・`ls /tmp` で確認が出ていた。`/tmp/*` はディレクトリ自体に一致しない。読み取りだけで、書き込みは ask）と、Orca の貼り付け画像（Windows の Temp の `orca-paste-*`）。拡張が `read`・`grep`・`find`・`ls` のツールにだけ自動許可する「基盤のパス」と同じ範囲を、bash にも広げた形。**`extensions/*/logs` だけは ask のまま**（レビューログにはコマンドの文字列が残り、秘密が混ざりうるため。拡張も、ここは自動許可しない設計）。`~/.pi/agent/` の認証情報・`models.json`・`mcp.json`・`sessions/` は許可リストに無く、ask のまま。

## 子の出力の読み取り

- **子エージェントの出力の読み取り（2026-11-11）**: 子の結果が長いと、完了の通知に `~/.pi/agent/sessions/<プロジェクト>/subagent-artifacts/…` のパスが付く。親がこれを読むたびに確認が出ていた（承認しないと 5 分で拒否される）。**`*_output.md`（子の最終の出力）と `outputs/*`（保存された出力）の読み取りだけ**を allow にした（`~/.pi/agent/sessions/*/subagent-artifacts/*_output.md`・`.../outputs/*`）。`*_transcript.jsonl`（子の全やり取り）・`*_input.md`（依頼文）・セッション自体（`*.jsonl`）は、これまでどおり ask（広く許可しない。実機で `outputs/<id>/context.md` のような深い階層にも `*` が届くことを、判定表で確かめた）。

## commandEffects

- **`commandEffects`（パス引数の向きの宣言。2026-11-10）**: `git` の `log`・`status`・`diff`・`show`（`--output` が付くと外す）と、`python3` を読み取りと宣言する。skill のスクリプトの実行（`python3 ~/.agents/skills/<名前>/scripts/*.py`）は、宣言が無いと向きを証明できず（unproven）、書き込み側の ask になる（実測 2 件）。**`python3 -c`・`-m` が付くと宣言を外す**（`-m venv` などが書くため。読み取りと書き込みの両方を調べる）。宣言しても、許可リストの外のパスは読み取りの ask のまま。python3 のスクリプトが自分で書く先は検査できない（インラインコードの迂回と同じく受容する）。向きの表は `permission_cases.json` の `access`（`test_bash_path_effects_match_the_table`）。

## subagent_launch

- **`subagent_launch` は allow**（2026-11-09。当面の運用）。これは pi-subagents が、ワークフロー（`workflow`・`chain`・`tasks` で複数の子を組み合わせて起動する形）で子を起動する直前に出す入れ子の呼び出しで、ask のままだと子ごとに確認が出る。子の終了後に走る `gate`・`acceptance.verify` のシェルコマンドも載るが、**この呼び出しの時点では bash の規則で検査されない**（pi-subagents の docs `workflows.md`。この拡張が `commands` を検査するかは未確認）。運用では `gate`・`acceptance.verify` を使わない（[feature-orchestration の運用](../../../.agents/skills/feature-orchestration/references/pi-subagents.md)）ので、実害は出にくい。`ask` へ戻せば、毎回その内容を見られる。

## bash の規則の出典

`bash` の規則（spec）の出典と、受容した迂回の経緯。

- 出典は、撤去したフルガードの deny・confirm の一覧から利用者が選んだもの（2026-11-09）。`git reset --hard`・`git stash drop`・`git branch -D`・`git clean -f`・`mkfs` などは `cc-safety-net` が既に止めるので足さない（[評価の記録](pi-stock-packages-evaluation-2026-11.md)）。
- **受容するもの**: 変数経由（`cmd=push; git $cmd`）・インラインコード（`python -c`・heredoc の中のスクリプト）での迂回は検出しない。ガードは意図的な迂回を保証しない（ガードの範囲）。撤去したフルガードの判定器はこれらを検出したが、インラインコードから外部コマンドを実行する形を一律に deny するため、過去のコマンドの 1.3% を誤って止めた。判定器を自作して載せる案は、この誤判定と維持費で見送った。

## グローバルな環境変更の deny

`bash` の deny（spec）のうち、グローバルな環境変更の規則の根拠。

- グローバルな変更は確認（ask）にせず deny にする（離席中に利用者を待って止まらないため）。deny の `reason` がブロックのメッセージに付くので、`uv add`・`uvx`・`npx`・プロジェクト内の `mise use` など正しい手段へエージェントが自分で切り替えられる（常用ツールの追加は利用者へ依頼）。

## git worktree remove

強制 ask（spec）のうち、`git worktree remove` の例外の根拠。

- `git worktree remove` も、パスが `.tmp/worktrees/` の下で、`--force`・`-f`・`..` を含まないときだけ allow （git 自身が、未コミットの変更がある worktree の削除を断り、枝は残る。`--force` は cc-safety-net も拒否する。消えるのは ignored のファイルだけ。2026-11-10）。

## pi agent の deny の置き方

- **`~/.pi/agent/` の、pi が読み込む・実行するもの**: `settings.json`（`shellPath`）・`AGENTS.md`・`extensions/`（権限の設定を含む）・`agents/`・`npm/`・`install/`・`prompts/`・`skills/`・`themes/`・`missions/`・`permission-mode/`・`pi-subagents/`・各拡張の設定（`compaction.json` など）・**`bin/`**（pi のランチャー `pi` と、pi が管理する `fd`・`rg`。**`PATH` の先頭**で、`find`・`grep` はこれを `shellPath` を通さず直接起動する）・`git/`（git の package）・**`tmp/`**（`-e` で指定した一時 package の置き場 `tmp/extensions`。更新に失敗するとキャッシュを再利用するので、置かれたコードが次の `pi -e` で実行される）。**許可リスト型（`~/.pi/agent/*` を deny して `sessions/*` だけ allow）にはしない**: 方向別の規則は共通の `path` の後ろに足されるので、後ろの allow が `*.env` の deny やリンク先の保護を上書きしてしまう（再監査の指摘）。そのため、`sessions/`（子エージェントの成果物。実ログでは、ファイルの道具が書いていたのはここだけ）を除いて、1 つずつ deny を置く。**chezmoi が `~/.pi/agent` へ配るものは、すべて deny に入っていることを試験で固定する**（新しく配るものを足し忘れない）。

## /sandbox と YOLO の連動

- **`/sandbox`（ローカルの拡張）は、囲いに合わせて YOLO も切り替える**（囲いあり = ON、囲いなし = OFF。起動時にも揃える。2026-11-15、[ADR-0040](../../adr/0040-pi-sandbox-session-toggle.md)）。囲いの内側で動かすコマンドは、YOLO でも OS が守る。囲いの外（MCP・ファイルの道具・pi 本体）の強制 ask は、YOLO で働かなくなる。YOLO を入れるのは、囲いと権限の設定を守るパスへの書き込みが、実効の方針で deny だと permission-system 自身に確かめられたときだけ。信頼済みのプロジェクトの設定が `yoloMode` を on にしていると（global の後に重なって勝つ）、囲いを外せない。仕様は [実行中の切り替え](../../spec/sandbox/pi-sandbox-runner.md#実行中の切り替え)。

## 囲いの読み取り専用の一覧

- **囲いの中で読み取り専用に見せるものすべて（`runner.toml` の `visible.read`）**: `~/.local/bin/`（pib の部品を含む）・`~/.local/share/mise`・`~/.local/share/uv`・`~/.config/mise`・`~/.config/uv`・`~/.gitconfig` と git の設定・`~/.cargo`・`~/.rustup`。囲いが読み取り専用にしているのは、書き換えられると囲いが外れるから（例: mise・uv が管理するツールや、`~/.local/bin` のランチャーは、ホストで後から実行される。runner 自身は、システムの `/usr/bin/python3 -I -S` で動かすので、mise の Python には依らない）。**この一致は `test_pi_sandbox_runner` が固定する**。

## 囲いの保護の固定

- **この保護は既定の場所に固定**: `pib` は、`PI_CODING_AGENT_DIR`・`PI_SANDBOX_RUNNER_CONFIG`・`XDG_CONFIG_HOME` が既定と違うと起動しない。制御ファイル（runner・`pib-shell`・`runner.toml`・`runner.local.toml`・`~/.pi/agent/settings.json`・管理済みの `bin/fd`・`bin/rg`・`bin/pi`）と、その置き場のディレクトリがリンクで既定の位置の外を指していても起動しない（拒否は名前に付くので、リンク先を直接指されると効かない）。

## path の deny と hide

- **`path` の deny は、pib の囲いの `hide`（`runner.toml`）と同じ集合に保つ**（2026-11-12）。`~/.config/gcloud`・`~/.docker`・`~/.kube`・`~/.azure`・`~/.password-store`、`~/.git-credentials`・`~/.config/git/credentials`・`~/.pypirc`・`~/.vault-token`、Hugging Face のトークン、`~/.pi/agent/oauth.json` も deny。囲いの中で隠しても、囲いの外で動く `read` ツールで読めてしまうため（YOLO は ask を自動で許可するので、確認にも頼れない）。食い違いは `test_pi_sandbox_runner` が検出する。

## 確認で待たせない方針

「確認で待たせない方針」（spec）の補足。

- （`promptTimeoutMs: 300000`。2 分では焦るため 5 分にした。初期値だけで、変えた値は apply で戻らない。拒否しても承認にはならない。モデルには「誰も答えなかった」と伝わるので、他の作業を続けられる。答え始めると（キーを押すと）時計は止まる。拡張の docs の「Unanswered prompts」）。
- **実測**（yolo を切って約 1 時間、レビューログ）: 確認 16 件のうち 13 件が作業ツリー外の読み取り（pi 自身のファイルを bash で読んだもの）、強制 ask は 1 件（`chezmoi apply`）、床（`bash -c` など）は 0 件。頑度はエージェントの読み方と許可の不足が原因だった。

## pi-rewind の警告の調査

- **`pi-rewind` の警告「Checkpoint failed: Command failed with exit code 1」（2026-11-10 に確認）**: `/reload` の直後のターンで出た。
  - 確かめたこと: 拡張のコードは、ターンの開始時に `git commit`（`--allow-empty` なし）を呼ぶ。変更が無いと git は「nothing to commit」を**標準出力**に出して終了コード 1 になる（使い捨ての repo で再現。標準エラーは 0 バイト）。拡張は、標準エラーが空だと「exit code 1」とだけ表示する。
  - 推測（未確認）: 拡張が覚えている「前回の記録」が `/reload` 後に古く、作業ツリーが記録済みの状態と一致して、食い違いで失敗した。確かめるには記録用の git（`~/.pi/agent/ayu/`）を読む必要があるが、方針で deny。
  - 観察: `/reload` のあと、ターンごとに繰り返し出た（1 つの依頼の途中のターンでも出る。最初の記録が失敗すると、拡張が次のターンでも作り直すため）。主な作業ツリーに変更が無いあいだ、直らない。
  - コードから分かること: 拡張が覚える「前回の記録」は、`/reload` 後にセッションの最後の記録（`afterCommit`）から決まる。これが記録用 git の先頭とずれ、作業ツリーが先頭と同じだと、毎回「nothing to commit」で失敗する。作業ツリーに変更が入ると、commit が成功して覚える値が更新され、直る見込み（統合など、主な作業ツリーを変える操作のあとで確かめる。未確認）。
  - 影響: 警告が出たターンは、巻き戻しの地点にならない。データは失われない。
  - 上流: 0.4.6 が npm の最新で、リポジトリ `ayu-exorcist/oh-my-pi` は 2026-07-28 にアーカイブ済み（読み取り専用）。同じ警告の Issue は無く、直る見込みもない。
  - 方針: 利用者が `/rewind` を使う予定なので、拡張は残す。毎ターン出るようなら（変更の有無に依らず）、拡張を外すか代わりを探す。

## Tailscale の指示の経緯

`~/.pi/agent/AGENTS.md` の行（spec の「配るもの」）にあった、Tailscale の指示の経緯。現行の指示の置き場はスキル `tailscale-serve`。

`agent-instructions-stock.md`（ツール非依存の短い指示）。委譲の常設の指示を含む。**家の機（`is-work` が `false`）だけ**、末尾に `agent-instructions-home.md` を足す（2026-11-16。開発中の Web サービスは、Tailscale が使えるなら tailnet だけに公開する。待ち受けは `127.0.0.1` で、`tailscale serve` で出す。`funnel` は利用者が明示したときだけ。2026-11-17: tailnet の端末は利用者本人のものだけという利用者の方針で、tailnet への公開に事前の確認・警告は要らないとした。WSL では Windows 側の `tailscale.exe` を呼ぶ・既存の https ポートを上書きしない、を足した）。会社 PC には出さない。`AGENTS.md.tmpl` が出し分ける。出典は Tailscale の公式 docs（<https://tailscale.com/docs/reference/tailscale-cli/serve>・<https://tailscale.com/docs/features/tailscale-funnel>）。**2026-11-16 に本文を取得して確認した**: `--bg` は外すまでバックグラウンドで残り、再起動や `tailscale down` / `up` の後も再開する（付けなければ止まる）／外すには、有効にしたコマンドの末尾に `off` を付ける／`tailscale serve reset` は設定を全て消す／`tailscale serve status` で一覧／Funnel は tailnet 外の誰にでも公開し、tailnet 内だけなら Serve を使う。構文は版で違いうるので、指示の中で「実行前に `--help` で確かめる」としている。**2026-11-17 に WSL2（mirrored）の実機で確かめた**: WSL の中に `tailscale` の CLI は無く、Windows 側の `tailscale.exe` を WSL から呼べた（`serve status`・`ip -4`・`serve --bg --https=8443 3080`）。Windows の serve にはすでに `https :443`・`tcp 50022` があり、`--bg <ポート>` だけでは :443 を上書きするので別のポートにした。Windows の `curl.exe` で、公開した URL に届くこと（アプリのトークン認証の 401 と、トークン付きの 303）を確かめた。WSL の中から自分の `100.x` の公開ポートへは、タイムアウトした（`platform-wsl.md` の既知の挙動と同じ）。Host ヘッダを検査するアプリ（dsh）は、`--public-url` と `--trusted-host` で公開 URL のホスト名を許可した。`serve` は tailnet だけ、`funnel` は公開、`--bg` は外すまで残る、という区別を指示に入れた

## T3 Code の MCP ツールと添付ファイル

2026-11-19。T3 Code の MCP ツール（71 本）と、T3 の添付ファイルの置き場を、権限の方針に足したときの根拠・実測。現行の仕様は [spec](../../spec/agent-config-generation.md#t3-code-の-mcp-ツールの権限)。

- **経緯**: 利用者が、T3 の MCP のツールのうち、allow してよいものを権限に足すよう依頼した。ツールは、直接見えるのが 3 本（`orchestrator_capabilities`・`delegate_task`・`task_status`）で、残りの 68 本は `tool_search` 経由で見える。利用者は、外へ情報を出すものを仕事の機で deny にする案も出したが、T3 側の改修後に再判断するとして保留した。今回は、確実に allow にしてよいものだけを反映した。
- **照合の対象**: `mcp.json` に無いサーバなので、名前は最初の `__` で分けられる（拡張 42.0.0 の `src/access-intent/mcp-targets.ts` の `createPiMcpToolTargets`）。実ゲートは、これに面全体の `mcp` を足した 7 つ（`t3-code_<名前>`・`t3-code:<名前>`・`t3-code`・`<名前>`・完全名・`mcp_call`・`mcp`。`input-normalizer.ts` の `normalizeMcpTargets`）の、どれかに一致した最後の規則を採る。
- **実測**（判定エンジン。2026-11-19）: 変更前の方針では 71 本すべてが ask。変更後は 21 本が allow、50 本が ask。判定表の T3 の行（72 行。表に無い新しいツールが ask になる行を含む）は、変更前の方針で 21 行が食い違い、変更後は 0 行。対象の生成は手で書かず、実ゲートの `normalizeInput` を通した（試験の駆動の `mcpTools`）。
- **分類の根拠**: ツールの定義（何を読み、何を変えるか）。承認の審査ログ（`friction_scan.py --approvals --since 2026-09-01`）に、T3 のツールの確認の記録は無く、件数は根拠にならない。
- **監査（reviewer。2026-11-19）**: 初版は、`preview_resize`・`preview_set_appearance` を「開いたあとの無害な操作」として allow にしていた。reviewer が、表示を変えるとページの `resize`・`matchMedia` の処理が動き、外部のページなら通信を起こせるとして MAJOR を指摘した。「確実」とは言えないので ask に戻した（承認を防御に数えない方針。利用者が先に承認した 4 本のうちの 2 本だが、利用者の最新の指示は「確実なものだけ」）。`t3_thread_read` の「配信済み」の更新の範囲、`t3_environment_read` の返却項目、`send_to_user` の外部画像は、T3 の実装が資料に無く、未確認の MINOR だった。最初の監査の reviewer は、`t3_thread_read` を、所有者の範囲を確認するまで ask に残すよう勧めた。実装者（親）は、毎回使う読み取りで、承認を防御に数えない方針なので、3 本とも allow に残した（利用者は、提案の段階で、この分類に異議を出していない。明示の承認ではない）。再監査（OK with notes）でも、「確実なものだけ」の基準との不整合が MINOR として残った。そのため spec には、「確実」ではなく、リスクを受容した例外として区別して書き、利用者に報告する。T3 の実装は作業ツリーの外にあり、子（reviewer）は読めない。
- **deny の見え方**（ソースの読み。実機では確かめていない）: MCP のツールは、対象のどれかに一致した最後の規則が deny なら、ツールごと隠れる（拡張 42.0.0 の `src/policy/permission-manager.ts` の `isToolFullyDenied`・`resolvePiMcpTool`。`before-agent-start.ts` の `shouldExposeTool` が、隠すツールを外す）。「すべての値が deny のときだけ隠す」のは `bash` などの面の話で、MCP は、名前だけから決まる 1 つの答え（`evaluateAnyValue`）で決まる。したがって、`t3-code:<名前>` を deny にすると、ツールは隠れ、deny の理由はモデルに届かない。仕事の機で deny にして代替を案内するときは、理由ではなく、仕事の機だけに足す指示文に書く。
- **添付ファイル**: T3 は、利用者が添付した画像・ファイルを `~/.t3/userdata/attachments/<識別子>…` に保存し、そのパスを指示に添える。作業ツリーの外なので、`external_directory_read` の既定（ask）になっていた（変更前の方針で、この置き場の読み取りの 2 行が ask）。Orca の添付と同じ形で、読み取りだけ allow にした。判定表は、`..` を含む綴り・ディレクトリそのもの・名前が前方一致する別の場所・状態の DB が ask のままであることも確かめる。

## T3 Code の MCP ツールの allow の拡大（2026-11-21）

2026-11-19 に、確実なものだけ（21 本）を allow にして、残りを保留にした。2026-11-21 に、利用者が分類ごとに方針を決めて、39 本へ広げた（外へ出うる 4 本は、利用者がリスクを受容して allow）。現行の仕様は [spec](../../spec/agent-config-generation.md#t3-code-の-mcp-ツールの権限)。

- **利用者の方針（要約）**: ブラウザは、閲覧系を allow、操作系（`preview_act`・`preview_evaluate`・`preview_dialog`）を ask。HTML の描画は、「描画のみでフォーム送信などを想定してないものであれば allow」（当初の条件。実際には強制されず、のちのリスク受容で allow）。元に戻せる整理は allow。起動・送信・停止・スケジュール・設定・プロジェクトの変更は ask のままにして、オーケストレーションの面で allow がよいものを尋ねた。その他の 10 本は、別途検討。
- **起動・送信・停止の評価**（親の意見。利用者が「`delegate_task` と `task_cancel` だけ」を選んだ）: ツール単位の許可は、対象のスレッドを見分けられない。自分の子にだけ効くのは `delegate_task`（起動）と `task_cancel`（自分のタスクの取消）。ほかは、ほかのスレッドに効く（`t3_thread_interrupt`・`t3_workflow_stop`・`t3_queue`・`t3_thread_send` の `restart`・`t3_thread_transfer` の `merge_back`・`t3_thread_configure`）。このスレッドは `full-access` なので、T3 の「呼び手より広い権限の相手へは送れない」歯止めは効かない。
- **仕事の機での再確認**: 2026-11-19 に「外へ出すものは仕事では deny」の案を保留していた（T3 側の改修後に再判断）。利用者は、改修はしなかったので、前提にせず再確認するよう求め、「HTML は、ローカルのブラウザで描画する。内部の独自コンテンツは、外部へ送信しない（LLM プロバイダなどを除く）と聞いた」と伝えた。T3 のソースを読んで確かめた（spec の「T3 のソースで確かめたこと」）: 描画は、`html_render` が利用者のローカルのブラウザ、`html_preview` が T3 のホストの headless Chrome で、外部の描画サービスは使わない（利用者が聞いた内容と合う）。ただし、配信の CSP は `sandbox …` だけで、`connect-src`・`img-src`・`form-action` の制限が無く、モデルが書いた HTML は外部のホストへ要求を送れる。`html_preview` は、プライベートな宛先を拒否する `publicProxy` を通る。`preview_*` のブラウザには、同様の制限が見つからなかった。
  - **結論（2026-11-21）: 外への送信は防がない。4 本は、利用者がリスクを受容して allow**。reviewer の指摘（監査 1〜3 回目。BLOCK）は、「囲いの中の bash が、囲いが見せる範囲のデータを送れる」ことと、T3 のツール（囲いの外。利用者の権限。ログイン済みのブラウザ・読めるファイル・サーバが届く宛先）とは、届く範囲が同じとは限らないこと、そして、利用者の発言から「送信側の対策が未実装のまま、仕事の機でも allow」への了承は読み取れないこと。経緯（利用者の発言。時系列。1 つめは、仕事の機の扱いに関する質問なので、要約にとどめる）: ① 外へ出るのは LLM プロバイダだけか、という質問。② 「1かな？ログイン済みのページを見る可能性のあるのは使用中のLLMプロバイダーだけですよね？」。③ 「LLMプロバイダーが更にどこに渡すかはT3codeの責務外ですよね？ならT3側は問題なし。LLMプロバイダーの読み取り側を制限するのではなく、送信側を制限・監視する方針で。この方針だと？」（T3 の責務外かと尋ねたのは、LLM プロバイダから先の転送）。④ 4 本の allow を、送信側の対策が未実装のまま許すかと尋ねると、「対策できるならまずはそれを教えて。見てから判断します」。⑤ 対策の候補と、リスクの具体例（悪意のあるページの指示で、会話の内容が URL に載って外へ出る）を示すと、「プロンプトインジェクション対策するとかなり制限することになる気がします。pi ハーネス側も対策するのを諦めました。どう？」。⑥ 親が、「4 本を家も仕事も allow に戻し、『プロンプトインジェクションによる外部送信は防がない。リスクを受け入れる（利用者の判断）』と docs に書き、対策の候補は見送った案として残す。害を生む操作の deny と秘密のファイルの読み取りの deny は残る」と提案すると、「OK」。
  - **見送った対策の候補**（未実施。効果は未検証。T3 の fork は利用者のもので、改修は利用者が行う）。利用者は、対策すると制限が大きいとして、取らない判断をした。利用者の前提（LLM プロバイダから先の転送は T3 の責務外）に従い、T3 の 4 本が**直接**外へ出す経路だけを扱う（LLM プロバイダへ渡る分は、通常のモデルの利用と同じ経路）。
    - `html_render`（利用者のブラウザの iframe）: 配信の CSP を `default-src 'none'` を基本にして、必要なものだけ足す（`script-src 'unsafe-inline'`・`style-src 'unsafe-inline'`・`img-src data:`・`font-src data:`）、`form-action 'none'`、iframe の sandbox から `allow-forms` を外す。狙う経路（未検証）: `fetch`・XHR・WebSocket・画像・フォント・メディア・外部スクリプト・iframe の埋め込み・フォームの送信。**対象のブラウザで確かめる項目**（未検証）: iframe 自身のナビゲーション（`location` の書き換え・`<meta http-equiv=refresh>`。CSP の `navigate-to` の対応状況も確認する）、DNS のプリフェッチ。確かめるまで、「止まる」とは書かない。
    - `html_preview`（T3 のホストの headless Chrome）: 既存の `publicProxy` の宛先制限（プライベート・ループバックの拒否）は維持したまま、公開の宛先も拒否して、ページ自身の origin と `data:` だけを通す（描画は自己完結の HTML が前提）。止まる経路: プロキシを経由する、許可外の宛先への通信。確かめる項目: 全通信がこのプロキシを通るか（読んでいない）。別に残る経路: `html_preview` は PNG とコンソール出力を、ツール結果として返す（描画ブラウザの通信を止めても、読み取った内容は、結果としてモデルの入力に載る。この経路は、この対策の対象外）。副作用（未検証）: プロキシを経由する外部の画像・CDN のフォントが、読めなくなりうる。描画への影響と、ほかの通信経路は、検証項目。
    - `preview_open`・`preview_navigate`（任意の URL を開くブラウザ）: URL を開くこと自体が、そのホストへの GET で、クエリに情報を載せられるので、CSP では塞げない。候補は、T3 の fork で、このブラウザの通信先を許可リスト（ループバック・指定のホスト）に絞る（調べた範囲では、同様の宛先制限は見つからなかった）。または、ask のまま（YOLO を切った状態で承認を求める。確認画面での URL の表示範囲は未確認）。仕事の機では、`is-work` の重ね（未実装）で deny にして、仕事用設定の代替候補（`agentcore-websearch`・`webfetch`。`webfetch` にも、URL 経由の送信は残る）へ案内する。
    - 埋め込まれるローカル画像（`html_preview` の `inlineLocalImages`）: 場所を絞らずに、T3 のサーバの権限で読める画像を埋め込める。上の「通信を止める」対策は、プロキシを経由する、許可外の宛先への通信を遮断する狙い（読んだ画像は、`html_preview` の PNG として、モデルの入力に載りうる。この経路は、対象外）。単独では、画像の読み取り元を、作業ディレクトリの下などに絞る改修が要る。
    - 囲い（`pib`）の通信の許可リスト: 囲いの中の bash の出口（`curl` など）を絞る。**T3 のツールには及ばない**（囲いの外）ので、この 4 本の対策にはならない。別の課題。
    - 記録・監視: 拡張の `configuration.md` は、「policy allow は、審査ログに残らない」と述べる（877 行。`toolInputPreview` は、ログが書かれるとき、bash と `mcp` プロキシ以外のツール呼び出しに入る。1649 行）。したがって、allow にすると、拡張の審査ログに項目が残らない。ask にしたときの出力（ログの有効化の設定は既定値）、対象のツールの URL の記録範囲（`toolInputPreview` の除外・マスク・文字数の制限）、T3 のスレッドの記録（`t3_thread_read` の `activity`）にツール呼び出しが残るかは、いずれも要確認。送信先の監視が実証済みとは扱わない。
  - **見送りの記録**: 上の候補は、将来、機密を扱う作業が増えたとき、T3 の fork を改修するときの材料として残す。再検討の目安は、仕事の機で、通信の遮断が要る作業が増えたとき。再許可の条件（遮断またはリスクの受容を済ませる）は、今回は、利用者のリスクの受容で満たした。
  - **通信の遮断**（`pib --offline`・`/sandbox offline`）は、T3 のツールに及ばない。YOLO では ask も自動承認される。遮断が要る作業では、T3 のツールを使わない。
  - 未確認: 仕事の機の、会社の方針が「T3 のブラウザ・描画」を禁じていないか（利用者が聞いた範囲は、内部の内容を外部へ送らない、まで）。`preview_open` のプロファイルの既定（利用者のもの）に、ログイン情報があるか。サーバ側のタブとデスクトップ側のタブの経路の違い。
- **監査（reviewer。2026-11-21 の 1 回目。BLOCK）**: BLOCKER は、`task_cancel` の「自分の子だけ」が資料から確認できないこと。T3 のソース（`readTask` が呼び手のスレッドに絞る。`assertStoppable`）で確認でき、docs に根拠を書いた。MAJOR は、仕事の機の結論が利用者の判断として記録できないこと（利用者に尋ねて、上の方針を記録した）、HTML の「描画のみ」と実際の許可の差（外部への送信と、ローカルのファイルの読み取りを別々に記録した。ページ本体の `path` は `.html`・`.htm` に限る。画像の経路は別で、検査が違う）、ブラウザの閲覧 7 本の性質（閲覧・取得と保存・表示状態の変更に分けて記録し、「追加のリスクは無い」を削った）、`delegate_task` の文脈の送信先と実行モード（記録した）、「元に戻せる整理」の対象範囲と副作用（記録した。戻せないものを明記した）。
- **監査（2 回目。BLOCK）**: BLOCKER は無し（`task_cancel` は解消）。MAJOR は、仕事の機の allow への了承が読み取れないこと（4 本を暫定で ask にして、「対策を見て判断する」と記録した）、対策の候補の効果の書きすぎ（対象と残る経路を候補ごとに書き、`pib` の許可リストが T3 に及ばないことを明記した）、ローカル読み取りの範囲の断定（`/\.html?$/i` を確認して引用し、画像の経路には `readPageFile` の検査が無いことを記録した）、改名の例外（利用者が受容した）。
- **利用者の判断（2026-11-21）の後**: 4 本を allow に戻した（allow 39・ask 32）。監査の MAJOR（文書の書き方）は、対策の効果・監視の可否・了承範囲を、根拠の範囲に直した（4 回目の監査で確認する）。
- **監査（4 回目。BLOCK）**: 利用者の了承（4 本を家も仕事も allow）は確認できた。権限の JSON と判定表は、意図どおり。MAJOR は、了承の範囲を 4 本の外へ広げた記録・`permission.path` を外部送信の防止と結びつけた記述・当初の HTML の許可条件の取り違え・見送った対策の効果と責務の断定。いずれも文書の直しで解消した。
- **監査（5 回目。BLOCK。最後の回）**: BLOCKER は無し。MAJOR は、判定表の説明が、39 本全体の外部送信のリスクを受容したように読めること（4 本に限定した）。MINOR は、「任意のホスト」「送信側の制限・監視が無い」と `html_preview` の既存の宛先制限の整合、対策の対象の書き方（直した）。判定値の変更は無く、文書の直しだけなので、6 回目は行わず、直したあとに pre-commit・試験・全件検証で確かめた。
