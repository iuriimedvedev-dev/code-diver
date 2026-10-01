# Retrieval Engine & MCP Architecture

This document details the architectural design, operating modes, and retrieval algorithms powering **Code Diver**. It covers the dual operating paradigms (external MCP tool vs. standalone agent), the **H-91a Champion Retrieval Pipeline** that outperforms single-pass cloud search engines like `jbcontext`, and the complete model fleet specification.

---

## 1. Two Operating Modes

Code Diver is engineered around two distinct execution modes:

```
               +-----------------------------------------------------------+
               |                   CODE DIVER ARCHITECTURE                 |
               +-----------------------------+-----------------------------+
                                             |
             --------------------------------+--------------------------------
             |                                                               |
             v                                                               v
   +--------------------+                                         +--------------------+
   |       MODE A       |                                         |       MODE B       |
   | MCP / knotgate     |                                         | Standalone CLI     |
   | Service Mesh       |                                         | Autonomous Agent   |
   +--------------------+                                         +--------------------+
   | - Zero LLM hops    |                                         | - Local 4B LLM     |
   | - 600-800ms latency|                                         | - Autonomous loop  |
   | - Raw JSON hits    |                                         | - Grounded answers |
   | - Deterministic    |                                         | - Prompt templates |
   +--------------------+                                         +--------------------+
```

---

### Mode A: MCP / knotgate Service Mesh (Zero Intermediate LLM)

In **Mode A**, Code Diver functions strictly as a high-performance, deterministic retrieval and code-intelligence microservice. It is consumed by external frontier reasoning agents (such as **OpenCode**, **Claude Desktop**, **Cursor**, or Kubernetes agents connected via **knotgate** gRPC service mesh).

#### Zero Intermediate LLM Principle
When a frontier model (e.g., `gemini-2.5-pro`, `claude-3-7-sonnet`, `gpt-5`) invokes `code_diver_search`, **no intermediate LLM processes, rewrites, summarizes, or filters the data**.
- **Information Preservation**: Intermediate LLM summaries inevitably discard critical AST declarations, type annotations, and subtle control-flow cues. Mode A passes the raw, ranked code snippets directly to the frontier agent.
- **Ultra-Low Latency**: Eliminating intermediate LLM generation reduces tool execution latency from 4–15 seconds down to **~600–800 ms** (fully warmed on Apple Silicon M3 Max / Linux CUDA).
- **Deterministic Reproducibility**: Exact inputs yield identical candidate rankings, token spans, and relevance scores.

#### Data Flow Diagram (Mode A)

```
+------------------------------------------------------------------------------------+
|                               HOST AGENT RUNTIME                                   |
|   (OpenCode CLI / Claude Desktop / Cursor IDE / knotgate Kubernetes Mesh)         |
|                                                                                    |
|   Frontier Model Reasoning Loop (Claude-3.7-Sonnet / Gemini-2.5-Pro / GPT-5)       |
+-----------------------------------------+------------------------------------------+
                                          |
                     Tool Invocation:     |  tool: "code_diver_search"
                     JSON-RPC 2.0 / gRPC  |  args: {"query": "...", "limit": 10}
                                          v
+------------------------------------------------------------------------------------+
|                                CODE DIVER SERVER                                   |
|   Transports: stdio | HTTP/SSE POST /mcp (:8000) | gRPC MCPService (:50051)        |
+------------------------------------------------------------------------------------+
|                                                                                    |
|   [1] Parse Tool Arguments & Validate Query                                        |
|   [2] Execute H-91a Champion Search Pipeline                                      |
|       ├── Qwen3-Embedding-0.6B (MLX/Metal :8001)                                   |
|       ├── In-Memory Lexical BM25 Engine                                            |
|       ├── AST Symbol Index & Path Matcher                                          |
|       ├── Qwen3-Reranker-0.6B Two-Pass Cross-Encoder (llama.cpp :8081)             |
|       └── LightGBM LambdaRank Meta-Ranker (Native In-Process GBDT)                 |
|   [3] Extract Line Ranges & Generate Truncated Previews (No LLM generation)       |
|                                                                                    |
+-----------------------------------------+------------------------------------------+
                                          |
                     Ranked JSON Hits:    |  [
                     Pure Deterministic   |    {"path": "...", "score": 0.942, ...},
                     Output Payload       |    ...
                                          v  ]
+------------------------------------------------------------------------------------+
|                               HOST AGENT RUNTIME                                   |
|   Frontier model ingests exact JSON hits, inspects code lines via code_diver_read, |
|   and synthesizes final response with verified ground-truth citations.             |
+------------------------------------------------------------------------------------+
```

#### Exact JSON Return Payload
The calling frontier agent receives structured JSON items ready for immediate context injection:

```json
[
  {
    "path": "platform/lang-impl/src/com/intellij/refactoring/rename/RenameProcessor.java",
    "score": 0.9421,
    "start_line": 64,
    "end_line": 182,
    "title": "RenameProcessor",
    "content_preview": "public class RenameProcessor extends BaseRefactoringProcessor {\n  private static final Logger LOG = Logger.getInstance(RenameProcessor.class);\n  protected LinkedHashMap<PsiElement, String> myAllRenames = new LinkedHashMap<>();\n..."
  },
  {
    "path": "platform/lang-impl/src/com/intellij/refactoring/rename/PsiElementRenameHandler.java",
    "score": 0.8875,
    "start_line": 35,
    "end_line": 98,
    "title": "PsiElementRenameHandler",
    "content_preview": "public class PsiElementRenameHandler implements RenameHandler {\n  public static boolean canRename(DataContext dataContext) {\n..."
  }
]
```

---

### Mode B: Standalone Autonomous CLI Agent (`code-diver chat` / `code-diver answer`)

In **Mode B**, Code Diver operates as a self-contained autonomous agent. A local on-device LLM (e.g., `Qwen3.5-4B-OptiQ-4bit` or `Gemma-4-e4b` running via MLX / llama.cpp) or a remote model via LiteLLM acts as the central reasoning orchestrator.

#### Key Components of Mode B
1. **Autonomous Reasoning Loop**: The agent iteratively formulates search queries, invokes inspection tools, analyzes compiler/AST symbols, and evaluates candidate code blocks.
2. **Repository Context Prefix**: At startup, `RepositoryContextBuilder` analyzes the target repository (README, build system, module topology, primary languages) and compiles a compact orientation artifact (`.code-diver/context/repository-context.md`). This prefix grounds the local model against hallucinating nonexistent architectures.
3. **Prompt Templates**: Structured system prompts enforce citation grounding, strict JSON schema compliance, and line-level verification.
4. **Tool Suite**: The local agent has access to `code_diver_search`, `code_diver_symbols`, `code_diver_read`, `code_diver_grep`, and `code_diver_tree`.

#### Data Flow Diagram (Mode B)

```
+------------------------------------------------------------------------------------+
|                             USER INTERACTION (CLI)                                 |
|                   code-diver chat "Explain rename refactoring flow"                |
|                   code-diver answer "Where is VFS refresh scheduled?"              |
+-----------------------------------------+------------------------------------------+
                                          |
                                          v
+------------------------------------------------------------------------------------+
|                           AUTONOMOUS AGENT ORCHESTRATOR                            |
|                                                                                    |
|   +----------------------------------------------------------------------------+   |
|   | 1. System Prompt Construction                                              |   |
|   |    ├── Base Instructions & Tool Schemas                                    |   |
|   |    ├── Repository Context Prefix (.code-diver/context/repository-context.md)|  |
|   |    └── Output Schema Constraints (Citations, Path:Line verification)       |   |
|   +-------------------------------------+--------------------------------------+   |
|                                         |                                          |
|                                         v                                          |
|   +----------------------------------------------------------------------------+   |
|   | 2. Local Reasoning Model (MLX / llama.cpp :8012 / LiteLLM)                 |   |
|   |    Qwen3.5-4B-OptiQ-4bit (44 tok/s) / Gemma-4-e4b-it-4bit (43 tok/s)      |   |
|   +-------------------+------------------------------------+-------------------+   |
|                       |                                    ^                       |
|        Tool Call      |                                    | Tool Result           |
|        (ReAct Loop)   v                                    |                       |
|   +--------------------------------------------------------+-------------------+   |
|   | 3. Execution Engine (Local Tools)                                          |   |
|   |    ├── code_diver_search  -> Deterministic H-91a retrieval                |   |
|   |    ├── code_diver_symbols -> Tree-sitter AST symbol spans                  |   |
|   |    ├── code_diver_read    -> Exact line-bounded source reader              |   |
|   |    └── code_diver_grep    -> Literal & regex fast search                   |   |
|   +----------------------------------------------------------------------------+   |
|                                         |                                          |
|                                         v (Final Turn)                             |
|   +----------------------------------------------------------------------------+   |
|   | 4. Line-Level Citation Verification & Markdown Response Synthesis          |   |
|   +----------------------------------------------------------------------------+   |
+-----------------------------------------+------------------------------------------+
                                          |
                                          v
+------------------------------------------------------------------------------------+
|                           STREAMED RESPONSE TO USER                                |
|   Synthesized explanation citing verified file paths and exact line windows        |
+------------------------------------------------------------------------------------+
```

---

### Comparison of Operating Modes

| Feature | Mode A: MCP / knotgate Service Mesh | Mode B: Standalone Autonomous Agent |
| :--- | :--- | :--- |
| **Primary Invoker** | External frontier agent (OpenCode, Claude, Cursor) | Terminal user via `code-diver chat` or `answer` |
| **Reasoning Engine** | Frontier host model (Claude 3.7, Gemini 2.5, GPT-5) | Local 4B model (`Qwen3.5-4B`, `Gemma-4-e4b`) or LiteLLM |
| **Intermediate LLM** | **None (Zero LLM)** | 1 local model loop for query planning & synthesis |
| **Search Latency** | **Subsecond (~600–800 ms)** | 3.5–8.5 seconds (full closed-loop reasoning) |
| **Output Type** | Structured JSON hits (`path`, `lines`, `score`) | Natural language markdown with verified citations |
| **Transport** | MCP stdio, HTTP JSON-RPC 2.0, knotgate gRPC | Interactive TTY / CLI stdout |
| **Best For** | Daily IDE coding, multi-agent mesh, automated CI | Air-gapped offline investigation, self-contained terminal RAG |

---

## 2. The H-91a Champion Retrieval Pipeline (How We Beat `jbcontext`)

### Benchmark Overview: `code-diver` vs. `jbcontext 0.9.14`

Evaluated on the full IntelliJ Community codebase (135,404 files, commit `c6143439a2a4`) across 1,065 ground-truth query answer sets (`datasets/intellij_eval_1000.answer_sets.jsonl`):

```
+------------------------------------------------------------------------------------+
|                 IntelliJ Community Benchmark (1,065 Cases)                         |
|                                                                                    |
|   File Hit@1:                                                                      |
|     code-diver H-91a  [==================================] 66.9%  (+29.0 pp)       |
|     jbcontext 0.9.14  [====================] 37.9%                                 |
|                                                                                    |
|   File Hit@10:                                                                     |
|     code-diver H-91a  [========================================] 76.8%  (+13.1 pp)  |
|     jbcontext 0.9.14  [=================================] 63.7%                    |
|                                                                                    |
|   File MRR@10:                                                                     |
|     code-diver H-91a  [====================================] 0.710  (+24.3 pp)     |
|     jbcontext 0.9.14  [=======================] 0.467                              |
|                                                                                    |
|   WHERE-78 Query Subset (Hard Structural Navigation):                              |
|     code-diver H-91a Hit@10: 87.2% (+21.8 pp over jbcontext 65.4%)                |
|     code-diver H-91a MRR@10: 0.707 (+32.1 pp over jbcontext 0.386)                |
+------------------------------------------------------------------------------------+
```

---

### The 4-Stage Cascade Architecture

The H-91a pipeline is structured as an asymmetric, multi-stage funnel designed to maximize recall at Stage 1 while progressively concentrating computational budget onto the most ambiguous candidates in Stages 2–4.

```
+------------------------------------------------------------------------------------+
|                 H-91a 4-STAGE CHAMPION RETRIEVAL CASCADE                           |
+------------------------------------------------------------------------------------+
                                    |
                                    | Natural Language Query
                                    v
+------------------------------------------------------------------------------------+
| STAGE 1: BROAD HYBRID RETRIEVAL & WEIGHTED FUSION                                  |
|                                                                                    |
|   Parallel Retrieval Probes:                                                       |
|   ├── Dense Vector ANN: Qwen3-Embedding-0.6B (MLX/Metal :8001)                     |
|   │   └── Top 360 vectors from Qdrant (file_summary: 170, file_manifest: 170)      |
|   ├── Lexical Search: In-Memory BM25 Engine (up to 1,000 matches)                  |
|   ├── Path Coverage Scorer: Tokenized file path sub-string matching                |
|   └── AST Symbol Scorer: Exact & fuzzy matching on class/method signatures         |
|                                                                                    |
|   Manual Linear Fusion Formula:                                                    |
|   score = 0.42 * Vector + 0.26 * Lexical + 0.12 * Path + 0.10 * Symbol + 0.10 * Match|
|                                                                                    |
|   Output: Top 360 Fused Candidates (preserved vector top margin 0.03)              |
+-----------------------------------------+------------------------------------------+
                                          |
                                          | Truncate to top 34 candidates
                                          v
+------------------------------------------------------------------------------------+
| STAGE 2: CROSS-ENCODER FIRST PASS (FAST ATTENTION SCREENING)                       |
|                                                                                    |
|   Model: Qwen3-Reranker-0.6B via llama.cpp / llama-server (:8081)                  |
|   - Candidate Cap: 34 candidates                                                   |
|   - Document Truncation Budget: 850 characters (file header, imports, top symbols) |
|   - Compute: Fast sequence classification over query + doc snippet                 |
|   - Latency: ~340–400 ms on Apple Silicon M3 Max                                   |
|                                                                                    |
|   Output: 34 candidates with raw cross-attention relevance scores                  |
+-----------------------------------------+------------------------------------------+
                                          |
                                          | Gated routing condition:
                                          | ce_score < 0.3 (Ambiguous / low confidence)
                                          v
+------------------------------------------------------------------------------------+
| STAGE 3: CROSS-ENCODER SELECTIVE SECOND PASS (DEEP CONTEXT EXPANSION)              |
|                                                                                    |
|   Selective Trigger:                                                               |
|   - Filter: Only candidates with Stage 1 CE score < 0.3 (score floor)              |
|   - Max Cap: Up to 24 candidates                                                   |
|   - Expanded Budget: 2,400 characters (includes full symbol signatures & bodies)   |
|                                                                                    |
|   Mechanism: Re-runs cross-encoder scoring with expanded document context.         |
|   Clear winners (score >= 0.3) bypass this stage entirely, saving ~1,500 ms.       |
|                                                                                    |
|   Output: Updated CE scores reflecting deep semantic content                       |
+-----------------------------------------+------------------------------------------+
                                          |
                                          | 16-Dimensional Feature Extraction
                                          v
+------------------------------------------------------------------------------------+
| STAGE 4: META-RANKER (LightGBM LambdaRank GBDT + GRAPH HUB PRIOR)                  |
|                                                                                    |
|   LightGBM LambdaRank Model (artifacts/ce_meta_ranker/ranker.json):                |
|   - Architecture: 200 trees, 64 leaves, learning rate 0.02                         |
|   - Trained on 856 queries, validated on 209 holdout cases (NDCG@10: 0.811)        |
|   - Inference: Native in-process C++ / Rust GBDT evaluation (< 0.5 ms)             |
|                                                                                    |
|   16 Meta-Features Fed to Model:                                                   |
|   [1] ce_score           [5] base_fused_score   [9]  path_name_length [13] file_ext_xml|
|   [2] ce_score_rank      [6] base_fused_rank    [10] is_test_path     [14] file_ext_md |
|   [3] fan_in_prior       [7] lexical_overlap    [11] file_ext_java    [15] query_terms |
|   [4] role_prior         [8] dir_depth          [12] file_ext_kt      [16] dir_prox    |
|                                                                                    |
|   Graph Hub Prior Fallback & Integration:                                          |
|   - AST Call/Import Fan-In Weight: 0.04                                            |
|   - Protected Top Candidates: Top 3 candidates protected from excessive decay      |
+-----------------------------------------+------------------------------------------+
                                          |
                                          | Final Truncation
                                          v
+------------------------------------------------------------------------------------+
| FINAL OUTPUT: TOP-10 OPTIMAL CODE CANDIDATES                                       |
+------------------------------------------------------------------------------------+
```

---

### Why the 4-Stage Cascade Outperforms Single-Pass Cloud Search (`jbcontext`)

`jbcontext 0.9.14` relies on a **single-pass bi-encoder cloud architecture**: it projects the query into a shared vector space and computes cosine similarity against pre-computed file chunks stored in JetBrains Cloud servers. While simple and low-overhead for the client, it suffers from systematic failure modes that H-91a eliminates:

#### 1. Resolution of the Bi-Encoder Vocabulary Mismatch
- **Single-Pass Cloud Flaw**: Bi-encoders compute independent representations: $sim(q, d) = \langle E(q), E(d) \rangle$. They frequently miss exact identifier tokens, internal error codes, and camelCase method names (e.g., `renameProcessor`, `PsiElementRenameHandler`) because the embeddings blend them into general semantic neighborhoods.
- **H-91a Solution**: Stage 1 combines dense embeddings with an exact BM25 index and AST symbol lookup (weighted fusion: 42% vector, 26% BM25, 12% path, 20% symbols). This guarantees that candidates matching exact identifier strings enter the top pool even if vector similarity is weak.

#### 2. Deep Full-Attention Cross-Encoding (Stage 2 & 3)
- **Single-Pass Cloud Flaw**: Single-pass cloud engines cannot afford full cross-attention between queries and thousands of repository files due to $O(N \cdot L^2)$ compute costs. They must rely entirely on bi-encoder dot products.
- **H-91a Solution**: H-91a uses `Qwen3-Reranker-0.6B` as a true cross-encoder. The query and candidate code attend to each other across all attention heads. This captures structural dependencies, parameter order, and conditional logic that bi-encoders erase.

#### 3. Selective Context Expansion (Two-Pass Economy)
- **Single-Pass Cloud Flaw**: Cloud engines enforce strict snippet truncation (typically 500–800 characters) across all documents to control bandwidth and latency. If the crucial implementation detail resides on line 120 of a class, the cloud index misses it.
- **H-91a Solution**: Stage 2 filters the top 34 candidates using a lean 850-character window. If a candidate receives a confident score ($\ge 0.3$), it passes through without additional cost. Only ambiguous candidates ($< 0.3$) trigger the Stage 3 selective second pass, which dynamically expands their text to 2,400 characters. This delivers high-recall deep inspection without paying the latency penalty on every candidate.

#### 4. GBDT Meta-Ranker with Graph Hub Priors (Stage 4)
- **Single-Pass Cloud Flaw**: Cloud retrievers frequently suffer from "utility file pollution"—generic helper files, test fixtures, or mocks that happen to contain high keyword density outrank the true architectural entry points.
- **H-91a Solution**: The LightGBM LambdaRank model synthesizes 16 heterogeneous signals simultaneously. It learns non-linear interactions: for example, if `is_test_path` is 1, the candidate requires a substantially higher `ce_score` to displace a production class. Furthermore, the `fan_in_prior` (derived from AST import and call graphs) injects topological importance, boosting central dispatchers over leaf utilities.

---

## 3. Model Fleet Summary Table

The table below summarizes all models utilized across Code Diver for both retrieval (Modes A & B) and autonomous reasoning (Mode B):

| Model Identifier | Parameter Count & Architecture | Serving Runtime & Endpoint | Memory Footprint (VRAM / RAM) | Operational Role | Operating Mode | Measured Latency / Throughput |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`Qwen3-Embedding-0.6B-4bit-DWQ`** | 0.6B Dense Transformer | MLX / Metal `:8001/v1/embeddings` | ~450 MB VRAM | Query & chunk vector embedding (Stage 1) | Mode A & Mode B | **14–25 ms** (warm) / 4.7s (cold idle) |
| **`Qwen3-Reranker-0.6B-Q4_K_M`** | 0.6B Cross-Encoder | llama.cpp / llama-server `:8081/v1/rerank` | ~520 MB VRAM | Deep cross-attention reranking (Stage 2 & 3) | Mode A & Mode B | **~176 ms** (5 docs) / **~742 ms** (20 docs) |
| **`ce_meta_ranker`** | 200 Trees, 64 Leaves LambdaRank GBDT | In-Process LightGBM (`ranker.json` / `.lgb.txt`) | < 5 MB RAM | Final 16-feature ranking & graph prior fusion (Stage 4) | Mode A & Mode B | **0.2–0.5 ms** |
| **`Qwen3.5-4B-OptiQ-4bit`** | 4.0B Dense LLM | MLX / Metal `:8012/v1/chat/completions` | ~2.6 GB VRAM | Interactive reasoning, ReAct agent loop, citations | Mode B only | **44.1 tok/s** (~7.8s closed-loop) |
| **`gemma-4-e4b-it-4bit`** | 4.0B Dense LLM | MLX / Metal `:8012/v1/chat/completions` | ~2.5 GB VRAM | Alternative local agent model (high schema adherence) | Mode B only | **43.2 tok/s** (~6.1s closed-loop) |
| **`gemini-3.5-flash-lite` / LiteLLM** | Cloud API (Google / OpenAI / Anthropic) | Remote HTTPS via LiteLLM Proxy | 0 MB (Cloud) | High-speed cloud reasoning agent for Mode B | Mode B only | **128.2 tok/s** (~1.78s closed-loop) |

---

## 4. Configuration & Deployment Blueprint

### Mode A: Serving MCP & knotgate Service Mesh

Run Code Diver as a unified microservice exposing both JSON-RPC MCP and knotgate gRPC:

```bash
# Launch unified server: HTTP MCP on 8000, knotgate gRPC MCP on 50051
code-diver serve \
  --config configs/intellij/intellij-h91a-meta-ranker.yml \
  --host 0.0.0.0 \
  --port 8000 \
  --grpc-port 50051
```

#### OpenCode Host Configuration (`~/.config/opencode/opencode.json`)
```json
{
  "mcp": {
    "code-diver": {
      "command": "code-diver",
      "args": ["mcp", "--config", "configs/intellij/intellij-h91a-meta-ranker.yml"]
    }
  }
}
```

#### Cursor Host Configuration (`.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "code-diver": {
      "command": "uv",
      "args": ["run", "code-diver", "mcp", "--config", "configs/intellij/intellij-h91a-meta-ranker.yml"]
    }
  }
}
```

---

### Mode B: Standalone Autonomous Agent CLI

```bash
# 1. Ask a single question with grounded citations
code-diver answer --config configs/intellij/intellij-h91a-meta-ranker.yml \
  "How does RenameProcessor resolve conflicts during PSI element rename?"

# 2. Start an interactive agent chat session with local 4B model
code-diver chat --config configs/intellij/intellij-h91a-meta-ranker.yml \
  --model mlx-community/Qwen3.5-4B-OptiQ-4bit
```

---

## 5. Architectural Invariants

To prevent regressions in production deployments, any modification to Code Diver must adhere to the following invariants:
1. **Mode A Zero-LLM Guarantee**: The `code_diver_search`, `code_diver_read`, and `code_diver_symbols` tool execution paths must **never** invoke an intermediate generative LLM. All transformations must be deterministic.
2. **Subsecond Latency Envelope**: Mode A search latency on a warmed system must remain under **1,000 ms** (target: 600–800 ms).
3. **Citation Line Grounding**: Every line range emitted by Mode B answers must be verified against Tree-sitter AST nodes on the local filesystem prior to output.
4. **Cascade Integrity**: Alterations to Stage 1 candidate limits (360) or Stage 2 cross-encoder limits (34) require running the full 1,065-case IntelliJ regression suite before promotion.
