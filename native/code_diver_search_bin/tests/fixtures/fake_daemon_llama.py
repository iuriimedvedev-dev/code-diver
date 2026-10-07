#!/usr/bin/env python3
import http.server
import json
import os
import sys
import time

port = int(sys.argv[sys.argv.index("--port") + 1])
model = sys.argv[sys.argv.index("--model") + 1]
with open(model + ".args.json", "w") as output:
    json.dump(sys.argv[1:], output)
with open(model + ".env.json", "w") as output:
    json.dump(dict(os.environ), output)
if os.path.exists(model + ".startup-delay"):
    with open(model + ".startup-delay") as delay:
        time.sleep(float(delay.read()))
print("synthetic-secret raw child output", flush=True)
print("synthetic-secret raw child output", file=sys.stderr, flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send(200, {"status": "ok"})

    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        text = value.get("query", value.get("input"))
        if text == "crash":
            os._exit(1)
        if text == "crash_once" and not os.path.exists(model + ".crashed"):
            with open(model + ".crashed", "w"):
                pass
            os._exit(1)
        if text == "slow":
            time.sleep(0.3)
        if text == "timeout":
            time.sleep(2)
        if text == "overflow":
            self.send(500, {"error": {"message": "input (20074 tokens) is too large to process. increase the physical batch size (current batch size: 4096) synthetic-secret"}})
            return
        if text == "long" or (isinstance(text, str) and len(text.split()) >= 3300):
            self.send(500, {"error": {"message": "input too large to process: synthetic-secret"}})
        elif self.path.endswith("rerank"):
            self.send(200, {"results": [{"index": 0, "relevance_score": 0.1},
                                       {"index": 1, "relevance_score": 0.9}]})
        else:
            inputs = value.get("input")
            count = len(inputs) if isinstance(inputs, list) else 1
            if isinstance(inputs, list) and inputs[0] == "incomplete":
                count = 1
            self.send(200, {"data": [{"index": i, "embedding": [0.6, 0.8]} for i in range(count)], "echo": value})


http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()