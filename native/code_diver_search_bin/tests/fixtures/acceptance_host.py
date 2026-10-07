#!/usr/bin/env python3
import json
import os
import pathlib
import sys

path = pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"]) / ".claude.json"
value = json.loads(path.read_text()) if path.exists() else {"mcpServers": {}}
args = sys.argv[1:]
if args[:2] == ["mcp", "add"]:
    env = {}
    for i, arg in enumerate(args):
        if arg == "--env":
            key, val = args[i + 1].split("=", 1)
            env[key] = val
    tail = args[args.index("--") + 1:]
    value["mcpServers"]["code-diver"] = {
        "type": "stdio", "command": tail[0], "args": tail[1:], "env": env
    }
elif args[:2] == ["mcp", "remove"]:
    value["mcpServers"].pop("code-diver", None)
else:
    sys.exit(1)
path.write_text(json.dumps(value))