# Cross-Encoder Runtime Capacity Repair

## Incident Summary
The Cross-Encoder (CE) server used in the `full-e2e1065` evaluation failed when processing specific document pairs that exceeded the physical batch size of the `llama-server`.

- **Original Server**: PID 82564, Port 8081
- **Error**: `input (769 tokens) is too large to process. increase the physical batch size (current batch size: 768)`
- **Affected Case**: `0034.json` (ID: `symbol-java-vcs-src-com-intellij-openapi-vcs-contentannotation-vcscontentannotationexceptionfilter.java-vcscontentannotationexceptionfilter`)

## Reproduction
The failure was reproduced using the exact payload from the second call of Arm A in `0034.json`.

```bash
curl -X POST http://127.0.0.1:8081/rerank -H "Content-Type: application/json" -d @repro_payload.json
# Result: HTTP 500 {"error":{"code":500,"message":"input (769 tokens) is too large to process. increase the physical batch size (current batch size: 768)","type":"server_error"}}
```

## Resolution: Repaired Server
A new server instance was launched with increased batch size capacity.

### Launch Command
```bash
/opt/homebrew/bin/llama-server \
  --model .code-diver/models/rerankers/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B-Q4_K_M.gguf \
  --host 127.0.0.1 \
  --port 18081 \
  --embedding \
  --reranking \
  --pooling rank \
  --batch-size 2048 \
  --ubatch-size 2048 \
  --ctx-size 8192
```

### Server Details
- **Version**: 9430 (d48a56eff)
- **Model Hash (GGUF)**: `c04f5f5657c52e04538c455e8c62817db3d3b795b39e9f547f8581510445f075` (verified via `sha256sum`)
- **Endpoint**: `http://127.0.0.1:18081/rerank`

## Verification Evidence
The repaired server successfully processed the failing payload and passed a smoke test covering all calls from the problematic case.

### Repro Payload Fix
```bash
curl -X POST http://127.0.0.1:18081/rerank -H "Content-Type: application/json" -d @repro_payload.json
# Result: HTTP 200 OK
```

### Smoke Test (Case 0034)
| Arm | Call | Docs | Status | Time |
|-----|------|------|--------|------|
| A | 0 | 34 | 200 | 2.00s |
| A | 1 | 4 | 200 | 0.59s |
| S | 0 | 34 | 200 | 1.78s |
| S | 1 | 2 | 200 | 0.24s |

Full results stored in `artifacts/research/2026-09-05/full-e2e1065-selective-second-pass/server-repair/smoke_results.json`.
Server logs available in `artifacts/research/2026-09-05/full-e2e1065-selective-second-pass/server-repair/llama_repair.log`.
