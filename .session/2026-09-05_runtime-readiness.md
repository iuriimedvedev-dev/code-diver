# Runtime Readiness Report - 2026-09-05

## 1. Model Verification
- **GGUF File**: `.code-diver/models/rerankers/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B-Q4_K_M.gguf`
- **SHA256 Hash**: `c04f5f5657c52e04538c455e8c62817db3d3b795b39e9f547f8581510445f075` (Verified via `sha256sum`)
- **Status**: Match (Verified against research requirements)

## 2. Server Configuration Comparison
| Parameter | Old Server (PID 82564) | New Server (PID 25811) |
|-----------|------------------------|------------------------|
| Port      | 8081                   | 18081                  |
| Binary    | `/opt/homebrew/bin/llama-server` | `/opt/homebrew/bin/llama-server` |
| Backend   | Metal (MTL) + Accelerate | Metal (MTL) + Accelerate |
| Threads   | 12 (Default)           | 12 (Default)           |
| Batch Size| 768                    | 2048                   |
| Context Size| Default (likely 512/2048) | 8192                   |

## 3. Capacity Verification (pair0034)
- **Query Tokens**: 14
- **Max Doc Tokens**: 683
- **Max Pair Sequence**: ~700 tokens (including special tokens)
- **Total Batch Tokens**: 2700
- **Validation Result**: New server (18081) returns HTTP 200. Old server (8081) returns HTTP 500 on same payload.

## 4. Finite Scores (Sample pair0034)
Model: `qwen3-reranker-0.6b` (Q4_K_M)
- `index 0`: 0.4208945930
- `index 1`: 0.1854269058
- `index 3`: 0.0928365812
- `index 2`: 0.0712600797

## Conclusion
Runtime is **READY** for full e2e1065 execution. Backends are equivalent (Metal/Accelerate), model identity is confirmed by hash, and capacity is verified by real tokenization of the failing payload.
