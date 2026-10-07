#!/usr/bin/env python3
import http.server
import json
import pathlib
import sys

with (pathlib.Path(__file__).parent.parent / "runtime/llama-args").open("a") as log:
    log.write(json.dumps(sys.argv) + "\n")

if "--version" in sys.argv:
    print("version: 9430")
    sys.exit(0)

port = int(sys.argv[sys.argv.index("--port") + 1])


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, value):
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send({"status": "ok"})

    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("rerank"):
            self.send({"results": [{"index": i, "relevance_score": 0.9}
                                   for i, _ in enumerate(value["documents"])]})
        else:
            inputs = value.get("input")
            count = len(inputs) if isinstance(inputs, list) else 1
            self.send({"data": [{"index": i, "embedding": [0.6, 0.8]}
                                for i in range(count)]})


http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()