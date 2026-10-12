#!/usr/bin/env bash
# Fake service manager for isolated acceptance, not a production service installer.
set -eu
case " $* " in
    *' start '*|*' bootstrap '*)
        if [[ ! -f $ACCEPTANCE_WORK/service.pid ]]; then
            "$ACCEPTANCE_BINARY" daemon --foreground --port "$ACCEPTANCE_DAEMON_PORT" \
                >"$ACCEPTANCE_WORK/bootstrap.log" 2>&1 &
            printf '%s\n' "$!" > "$ACCEPTANCE_WORK/service.pid"
        fi ;;
esac