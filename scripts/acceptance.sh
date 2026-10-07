#!/usr/bin/env bash
# M6 0.5.0: opt-in acceptance against a supplied read-only shared collection.
set +x
set -euo pipefail
umask 077
step=preflight
work='' daemon_pid='' mcp_pid='' command_pid='' timer_pid=''
script_dir=$(cd "$(dirname "$0")" && pwd)
pass() { printf '| %s | PASS |\n' "$1"; }
stop_pid() {
    local pid=${1:-} i
    [[ -n $pid ]] || return 0
    kill -TERM "$pid" 2>/dev/null || true
    for i in {1..50}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
        return 1
    fi
    wait "$pid" 2>/dev/null || true
}
cleanup() {
    local rc=$? failed=0
    trap - EXIT
    set +e
    stop_pid "$command_pid" || failed=1
    stop_pid "$timer_pid" || failed=1
    stop_pid "$mcp_pid" || failed=1
    stop_pid "$daemon_pid" || failed=1
    if [[ -n $work && -f $work/service.pid ]]; then
        stop_pid "$(<"$work/service.pid")" || failed=1
    fi
    if [[ -n $work ]]; then rm -rf -- "$work" || failed=1; fi
    if (( rc != 0 )); then printf '| %s | FAIL |\n' "$step"; fi
    if (( failed != 0 )); then printf '| teardown | FAIL |\n'; rc=1
    else pass teardown; fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP
printf '| Step | Result |\n| --- | --- |\n'
[[ $# -eq 2 ]] || exit 1
profile=$1 key_file=$2
[[ -f $profile && -r $profile && -f $key_file && -r $key_file ]] || exit 1
for tool in jq curl mktemp mkfifo; do command -v "$tool" >/dev/null || exit 1; done
binary=$(command -v "${CODE_DIVER_BIN:-code-diver}")
[[ $binary = /* ]] || binary="$PWD/$binary"
port=${ACCEPTANCE_PORT:-19437}
timeout=${ACCEPTANCE_TIMEOUT:-600}
[[ $port =~ ^[0-9]+$ && $timeout =~ ^[0-9]+$ ]] || exit 1
(( port > 1024 && port < 65536 && timeout > 0 )) || exit 1
case $port in 8090|8001|8081|18081|8002|6333) exit 1 ;; esac
qdrant=${ACCEPTANCE_QDRANT_URL:?Supply shared Qdrant URL}
collection=${ACCEPTANCE_COLLECTION:?Supply shared collection}
query=${ACCEPTANCE_QUERY:-Where is configuration loaded?}
# Reject credentials in URLs and explicitly reserved endpoint ports, including profile text.
[[ $qdrant =~ ^https?:// && $qdrant != *@* && $collection =~ ^[A-Za-z0-9_-]+$ ]] || exit 1
reserved=':(8090|8001|8081|18081|8002|6333)([^0-9]|$)'
[[ ! $qdrant =~ $reserved && ! $(<"$profile") =~ $reserved ]] || exit 1
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
work=$(mktemp -d "$temp_base/code-diver-acceptance.XXXXXX")
export CODE_DIVER_HOME="$work/home"
export CODE_DIVER_CONFIG="$CODE_DIVER_HOME/config/config.toml"
export XDG_CONFIG_HOME="$work/xdg/config" XDG_CACHE_HOME="$work/xdg/cache"
export XDG_DATA_HOME="$work/xdg/data" XDG_STATE_HOME="$work/xdg/state"
export ACCEPTANCE_WORK="$work" ACCEPTANCE_BINARY="$binary" ACCEPTANCE_DAEMON_PORT="$port"
mkdir -p "$work/bin"
mkfifo "$work/timer"
exec 5<>"$work/timer"
# Only the fake manager may start a service, always foreground and PID-recorded.
cp "$script_dir/acceptance-manager.sh" "$work/bin/systemctl"
chmod 700 "$work/bin/systemctl"
cp "$work/bin/systemctl" "$work/bin/launchctl"
export PATH="$work/bin:$PATH"
runtime=(--config "$CODE_DIVER_CONFIG" --port "$port" --qdrant-url "$qdrant" --collection "$collection")
search=(--config "$CODE_DIVER_CONFIG" --daemon-port "$port" --autostart=false --qdrant-url "$qdrant" --qdrant-collection "$collection" --require-rerank
    --embedding-url "http://127.0.0.1:$port/v1/embeddings" --ce-url "http://127.0.0.1:$port/v1/rerank"
    --second-ce-url "http://127.0.0.1:$port/v1/rerank")
# Bounded commands; all output is private and deleted, never echoed even on failure.
run() {
    local rc=0
    "$@" >"$work/output" 2>"$work/error" & command_pid=$!
    (
        trap - EXIT INT HUP
        trap 'exit' TERM
        IFS= read -r -t "$timeout" -u 5 _ || true
        kill -TERM "$command_pid" 2>/dev/null || true
        IFS= read -r -t 5 -u 5 _ || true
        kill -KILL "$command_pid" 2>/dev/null || true
    ) & timer_pid=$!
    wait "$command_pid" || rc=$?
    command_pid=
    stop_pid "$timer_pid" || rc=1
    timer_pid=
    return "$rc"
}
pass preflight
step=setup
run "$binary" setup --yes --no-register --profile "$profile" --key-file "$key_file" "${runtime[@]}"
pass setup
if [[ -f $work/service.pid ]]; then
    stop_pid "$(<"$work/service.pid")"
    rm "$work/service.pid"
fi
step=update-index
run "$binary" update-index "${runtime[@]}"
pass update-index
step=daemon
"$binary" daemon --foreground --port "$port" >"$work/daemon.log" 2>&1 & daemon_pid=$!
ready=0
for ((i=0; i<60; i++)); do
    kill -0 "$daemon_pid" 2>/dev/null || exit 1
    if curl --silent --fail --noproxy '*' --max-time 1 "http://127.0.0.1:$port/health" >"$work/health" 2>/dev/null &&
        jq -e '.status == "ok" and .service == "code-diver"' "$work/health" >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
(( ready == 1 ))
pass daemon
step=doctor
run "$binary" doctor --json "${search[@]}"
jq -e '.passed == true and (.checks | length > 0)' "$work/output" >/dev/null 2>&1
pass doctor
step=search
run "$binary" search "$query" "${search[@]}"
[[ -s $work/output ]]
pass search
step=mcp-initialize
mkfifo "$work/in" "$work/out"
# Open both ends first so missing/broken servers cannot block FIFO opening.
exec 3<>"$work/in" 4<>"$work/out"
"$binary" mcp "${search[@]}" <"$work/in" >"$work/out" 2>"$work/mcp.log" & mcp_pid=$!
rpc() {
    local id=$1 request=$2 filter=$3 line
    printf '%s\n' "$request" >&3
    IFS= read -r -t "$timeout" line <&4 || return 1
    printf '%s\n' "$line" | jq -e --argjson id "$id" \
        ".jsonrpc == \"2.0\" and .id == \$id and (has(\"error\") | not) and ($filter)" >/dev/null 2>&1
}
rpc 1 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"acceptance","version":"0.5.0"}}}' '.result.serverInfo.name == "code-diver"'
pass mcp-initialize
printf '%s\n' '{"jsonrpc":"2.0","method":"notifications/initialized"}' >&3
step=mcp-tools
rpc 2 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' 'any(.result.tools[]; .name == "code_diver_search")'
pass mcp-tools
step=mcp-search
request=$(jq -cn --arg query "$query" '{jsonrpc:"2.0",id:3,method:"tools/call",params:{name:"code_diver_search",arguments:{query:$query,limit:3}}}')
rpc 3 "$request" '.result.isError == false and (.result.content | length > 0)'
pass mcp-search
step=teardown