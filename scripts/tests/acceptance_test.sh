#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d "$root/scripts/tests/.acceptance-test.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
mkdir "$work/bin"
cp "$root/scripts/tests/mock-code-diver.sh" "$work/bin/code-diver"
cp "$root/scripts/tests/mock-curl.sh" "$work/bin/curl"
chmod 700 "$work/bin/"*
export PATH="$work/bin:$PATH" CODE_DIVER_BIN="$work/bin/code-diver"
export MOCK_EXPECT_HOME="$HOME" MOCK_SECRET='test-secret-never-print-47'
export QDRANT_API_KEY="$MOCK_SECRET"
export ACCEPTANCE_QDRANT_URL=http://127.0.0.1:19438 ACCEPTANCE_COLLECTION=shared_test
export ACCEPTANCE_TIMEOUT=30
printf '%s' "$MOCK_SECRET" > "$work/key"
chmod 600 "$work/key"
printf '%s\n' 'name = "acceptance"' > "$work/profile"
count=0
for failure in success setup update-index doctor doctor-json search mcp-1 mcp-2 mcp-3; do
    export MOCK_RECORD="$work/$failure" MOCK_FAIL="$failure"
    mkdir "$MOCK_RECORD"
    rc=0
    bash "$root/scripts/acceptance.sh" "$work/profile" "$work/key" > "$MOCK_RECORD/table" 2>&1 || rc=$?
    table=$(<"$MOCK_RECORD/table")
    [[ $table != *"$MOCK_SECRET"* ]] || { printf 'FAIL output safety\n'; exit 1; }
    [[ -f $MOCK_RECORD/commands && -f $MOCK_RECORD/home ]] || { printf 'FAIL mock CLI was not reached\n'; exit 1; }
    [[ $(<"$MOCK_RECORD/commands") != *"$MOCK_SECRET"* ]] || { printf 'FAIL argv safety\n'; exit 1; }
    [[ ! -e $(<"$MOCK_RECORD/home") ]] || { printf 'FAIL isolated cleanup\n'; exit 1; }
    if [[ $table != *'| teardown | PASS |'* ]]; then printf 'FAIL mock case: %s\n%s\n' "$failure" "$table"; exit 1; fi
    if [[ $failure == success ]]; then
        if [[ $rc != 0 || $table == *FAIL* ]]; then printf '%s\n' "$table"; exit 1; fi
        [[ $(<"$MOCK_RECORD/commands") == *update-index* && $(<"$MOCK_RECORD/commands") == *doctor* && $(<"$MOCK_RECORD/commands") == *search* ]] || exit 1
        [[ -f $MOCK_RECORD/rpc ]] || exit 1
        [[ $(<"$MOCK_RECORD/rpc") == *notifications/initialized* && $(<"$MOCK_RECORD/rpc") == *tools/list* && $(<"$MOCK_RECORD/rpc") == *tools/call* ]] || exit 1
    else [[ $rc != 0 && $table == *FAIL* ]] || { printf 'FAIL expected rejection: %s rc=%s\n%s\n' "$failure" "$rc" "$table"; exit 1; }; fi
    if [[ -f $MOCK_RECORD/pids ]]; then
        while IFS= read -r pid; do
            if kill -0 "$pid" 2>/dev/null; then exit 1; fi
            [[ $'\n'$(<"$MOCK_RECORD/stopped")$'\n' == *$'\n'"$pid"$'\n'* ]] || exit 1
        done < "$MOCK_RECORD/pids"
    fi
    count=$((count + 1))
    printf 'PASS mock acceptance: %s\n' "$failure"
done
[[ $(<"$work/key") == "$MOCK_SECRET" && $HOME == "$MOCK_EXPECT_HOME" ]] || exit 1
printf 'PASS: %s cases; full sequence, failure cleanup, key/argv safety, HOME unchanged\n' "$count"