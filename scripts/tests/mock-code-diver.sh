#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MOCK_RECORD/commands"
printf '%s\n' "$CODE_DIVER_HOME" > "$MOCK_RECORD/home"
[[ $HOME == "$MOCK_EXPECT_HOME" ]] || exit 19
case $1 in
    setup)
        [[ " $* " == *' --yes --no-register --profile '* && " $* " == *' --key-file '* ]] || exit 19
        previous=''
        for argument in "$@"; do
            if [[ $previous == --key-file ]]; then
                [[ -r $argument && $(<"$argument") == "$MOCK_SECRET" && $QDRANT_API_KEY == "$MOCK_SECRET" ]] || exit 19
            fi
            previous=$argument
        done
        # Deliberately hostile output: acceptance must never forward it.
        printf '%s' "$MOCK_SECRET" >&2
        if [[ ${MOCK_FAIL:-} == setup ]]; then exit 17; fi
        mkdir -p "$CODE_DIVER_HOME/config"
        systemctl --user start code-diver
        ;;
    update-index) if [[ ${MOCK_FAIL:-} == update-index ]]; then exit 17; fi ;;
    daemon)
        [[ " $* " == *' --foreground '* ]] || exit 19
        printf '%s\n' "$$" >> "$MOCK_RECORD/pids"
        sleeper=
        trap 'kill "$sleeper" 2>/dev/null || true; wait "$sleeper" 2>/dev/null || true; printf "%s\n" "$$" >> "$MOCK_RECORD/stopped"; exit 0' TERM INT
        while :; do sleep 1 & sleeper=$!; wait "$sleeper" || true; done
        ;;
    doctor)
        if [[ ${MOCK_FAIL:-} == doctor ]]; then exit 17; fi
        if [[ ${MOCK_FAIL:-} == doctor-json ]]; then printf '%s\n' '{"passed":false,"checks":[{}]}'
        else printf '%s\n' '{"passed":true,"checks":[{"name":"embedder"},{"name":"reranker"}]}' ; fi
        ;;
    search)
        [[ " $* " == *' --autostart=false '* && " $* " == *' --require-rerank '* ]] || exit 19
        [[ " $* " == *" --qdrant-collection $ACCEPTANCE_COLLECTION "* && " $* " == *"http://127.0.0.1:$ACCEPTANCE_DAEMON_PORT/v1/embeddings"* && " $* " == *"http://127.0.0.1:$ACCEPTANCE_DAEMON_PORT/v1/rerank"* ]] || exit 19
        if [[ ${MOCK_FAIL:-} == search ]]; then exit 17; fi
        printf '%s\n' 'src/config.rs:1 configuration'
        ;;
    mcp)
        printf '%s\n' "$$" >> "$MOCK_RECORD/pids"
        trap 'printf "%s\n" "$$" >> "$MOCK_RECORD/stopped"; exit 0' TERM INT
        while IFS= read -r line; do
            printf '%s\n' "$line" >> "$MOCK_RECORD/rpc"
            id=$(printf '%s' "$line" | jq -r '.id // empty')
            [[ -n $id ]] || continue
            if [[ ${MOCK_FAIL:-} == "mcp-$id" ]]; then
                printf '{"jsonrpc":"2.0","id":%s,"error":{"message":"bad"}}\n' "$id"
                continue
            fi
            case $id in
                1) result='{"serverInfo":{"name":"code-diver"}}' ;;
                2) result='{"tools":[{"name":"code_diver_search"}]}' ;;
                3) result='{"isError":false,"content":[{"type":"text","text":"results"}]}' ;;
                *) exit 1 ;;
            esac
            printf '{"jsonrpc":"2.0","id":%s,"result":%s}\n' "$id" "$result"
        done
        ;;
    *) exit 1 ;;
esac