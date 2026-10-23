#!/usr/bin/env bash
# CHG-0037 段 U7a の使い捨ての手順書: Copilot を、Envoy 経由 (内側にはダミーだけ) で pi から使えるかを試す。
# 境界の外 (ホスト) で実行する。使い方: scripts/agents/broker_spike.sh {check|up|status|pi-test|down|clean}
# 手順と観点は docs/change/0037-pis-usability-and-telemetry.md の「認証の方針」と段 U7。
set -eu

here="$(cd "$(dirname "$0")" && pwd)"
spike="$here/broker-spike"
state="${XDG_STATE_HOME:-$HOME/.local/state}/pis-broker-spike"
port=18080

say() { printf '%s\n' "$*"; }

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

cmd_check() {
	for tool in envoy pi python3; do
		if command -v "$tool" >/dev/null 2>&1; then
			say "ok: $tool = $(command -v "$tool")"
		else
			say "無い: $tool"
		fi
	done
	if command -v envoy >/dev/null 2>&1; then envoy --version | head -n 1; fi
	say "Envoy が無い場合: https://github.com/envoyproxy/envoy/releases のリリースの Linux x86_64 のバイナリを取得し、"
	say "同じリリースの checksum (sha256) と照合してから、~/.local/bin/envoy へ置く (署名・checksum を確かめずに実行しない)。"
	say "auth.json: ${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/auth.json に github-copilot の OAuth が要る (pi で /login)。"
}

cmd_up() {
	command -v envoy >/dev/null 2>&1 || { say "envoy が無い。check を見る"; exit 1; }
	mkdir -p "$state"
	chmod 700 "$state"
	sed "s#@STATE@#$state#g" "$spike/envoy-copilot.yaml" >"$state/envoy-copilot.yaml"

	if alive "$state/refresh.pid"; then
		say "refresh は起動済み"
	else
		nohup python3 "$spike/copilot_refresh.py" --out "$state/copilot-sds.json" --loop >"$state/refresh.log" 2>&1 &
		echo $! >"$state/refresh.pid"
	fi
	i=0
	while [ ! -f "$state/copilot-sds.json" ]; do
		i=$((i + 1))
		if [ "$i" -gt 30 ]; then
			say "SDS ファイルができない。$state/refresh.log を見る"
			exit 1
		fi
		sleep 1
	done

	if alive "$state/envoy.pid"; then
		say "envoy は起動済み"
	else
		nohup envoy --config-path "$state/envoy-copilot.yaml" --log-level info >"$state/envoy.log" 2>&1 &
		echo $! >"$state/envoy.pid"
	fi
	i=0
	until (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; do
		i=$((i + 1))
		if [ "$i" -gt 20 ]; then
			say "ポート $port が開かない。$state/envoy.log を見る"
			exit 1
		fi
		sleep 1
	done
	say "起動した: http://127.0.0.1:$port (Copilot へ中継)。ログ: $state/envoy.log、$state/refresh.log"
}

cmd_status() {
	for name in refresh envoy; do
		if alive "$state/$name.pid"; then say "$name: 動作中 (pid $(cat "$state/$name.pid"))"; else say "$name: 停止"; fi
	done
}

cmd_pi_test() {
	model="${MODEL:-}"
	[ -n "$model" ] || { say "MODEL を指定する (例: MODEL=<pi --list-models に出る Copilot のモデル ID>)"; exit 1; }
	agent="$state/pi-agent"
	mkdir -p "$agent"
	printf '%s\n' '{ "providers": { "github-copilot": { "baseUrl": "http://127.0.0.1:'"$port"'" } } }' >"$agent/models.json"
	say "pi を、ダミーのトークンと、baseUrl の上書きで起動する (本物のトークンは pi に渡さない)"
	COPILOT_GITHUB_TOKEN=dummy-not-a-real-token PI_CODING_AGENT_DIR="$agent" \
		pi -p "${PROMPT:-Say hi in one short sentence.}" --model "github-copilot/$model"
}

cmd_down() {
	for name in envoy refresh; do
		if alive "$state/$name.pid"; then kill "$(cat "$state/$name.pid")" && say "$name を止めた"; fi
		rm -f "$state/$name.pid"
	done
}

cmd_clean() {
	cmd_down
	rm -rf "$state"
	say "片付けた: $state"
}

case "${1:-}" in
check) cmd_check ;;
up) cmd_up ;;
status) cmd_status ;;
pi-test) cmd_pi_test ;;
down) cmd_down ;;
clean) cmd_clean ;;
*)
	say "使い方: $0 {check|up|status|pi-test|down|clean}"
	exit 2
	;;
esac
