#!/usr/bin/env python3
import errno
import json
import os
import pty
import select
import signal
import sys
import time

inputs = json.load(sys.stdin)
pid, terminal = pty.fork()
if pid == 0:
    # Installer pipes have non-TTY stdin; /dev/tty must still work.
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    os.execv(sys.argv[1], sys.argv[1:])

transcript = bytearray()
pending = [(b"Team profile URL or file: ", inputs["profile"]),
           (b"Read-only Qdrant key: ", inputs["key"])]
deadline = time.monotonic() + 30
try:
    while time.monotonic() < deadline:
        if not select.select([terminal], [], [], 0.1)[0]:
            continue
        try:
            data = os.read(terminal, 65536)
        except OSError as error:
            if error.errno == errno.EIO:
                break
            raise
        if not data:
            break
        transcript.extend(data)
        if pending and pending[0][0] in transcript:
            _, value = pending.pop(0)
            os.write(terminal, value.encode() + b"\n")
    else:
        raise TimeoutError("PTY setup did not finish")
    _, status = os.waitpid(pid, 0)
    sys.stdout.buffer.write(transcript)
    sys.stdout.buffer.flush()
    if pending:
        raise RuntimeError("setup did not prompt for profile and key")
    sys.exit(os.waitstatus_to_exitcode(status))
finally:
    os.close(terminal)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass