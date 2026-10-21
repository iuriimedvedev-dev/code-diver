# systemd user units for local code-diver servers

Canonical defaults for the two llama-server daemons and the optional MCP HTTP
server. Install:

```bash
cp deploy/systemd-user/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now code-diver-rerank.service code-diver-embed.service
```

## `code-diver-rerank.service` — Qwen3-Reranker-0.6B on 780M iGPU (:8792)

- Binary: llama.cpp Vulkan build (`build-vk`), `--device Vulkan0` pinned to the
  780M iGPU plus `GGML_VK_VISIBLE_DEVICES=0`, so the daemon can never land on
  the training R9700 after a device reorder. Full offload (`-ngl 99`).
- Slim flags (2026-10-16, measured): `-c 8192 -b 2048 -ub 2048 -np 2`.
  A 0.6B Q8_0 model serving ≤2500-char rerank docs needs nothing more:
  RSS 5240 MB → 551 MB (−89%), rerank latency 4.38 s → 3.29 s (−25%),
  ranking margin unchanged (0.9998 vs 0.0004).
- Consumer: hars-memory MCP fusion rerank (`HARS_MEMORY_RERANK_BACKEND=http`,
  pool 20, timeout 30 s).

## `code-diver-embed.service` — embeddinggemma-300M on CPU (:8791)

- Binary: llama.cpp CPU build. Slim flags (2026-10-16, measured):
  `-t 4 -c 2048 -b 512 -ub 512 -np 2`. The model's own `n_ctx_train` is 2048,
  so anything above was pure waste.
  RSS 1686 MB → 403 MB (−76%), embed batch-32 latency 0.34 s → 0.26 s (−24%),
  768-dim vectors verified.
- Consumer: hars-memory http embedder (`HARS_MEMORY_EMBED_PROVIDER=http`,
  batch 32) + code-diver proxy.

## Rollback

Previous (fat) revisions are backed up next to the live units as
`code-diver-{rerank,embed}.service.bak-cpu-20261014` (and timestamped copies
under `/tmp/opencode/`). Restore = copy back + `daemon-reload` + restart.

## `code-diver-http@<project>.service` — MCP Streamable HTTP (:18080)

Additive unit: it does **not** replace `code-diver-daemon@<project>.service`
(the stdio shim over `$XDG_RUNTIME_DIR/code-diver/<project>.sock`). Both can run
while clients are migrated.

```bash
install -Dm644 deploy/systemd-user/code-diver-http@.service \
  ~/.config/systemd/user/code-diver-http@.service
install -Dm600 deploy/systemd-user/code-diver-http.env.example \
  ~/.config/code-diver/cortex.http.env     # optional: port/TLS/OAuth
systemctl --user daemon-reload
systemctl --user enable --now code-diver-http@cortex.service
curl -fsS http://127.0.0.1:18080/health
```

- Reads `~/.config/code-diver/<project>.yml` (same per-project config as the
  daemon) and optional `~/.config/code-diver/<project>.http.env`.
- Binds `127.0.0.1:18080` by default; override `CODE_DIVER_HTTP_PORT` /
  `CODE_DIVER_MCP_HOST` in the env file to run one unit per project.
- gRPC is disabled (`--grpc-port 0`) because it is not covered by OAuth.
- TLS and OAuth are opt-in; see [`docs/http-mcp.md`](../../docs/http-mcp.md)
  for the full env table, OAuth flow, mkcert instructions and verification.

Rollback:

```bash
systemctl --user disable --now code-diver-http@cortex.service
```

Clients return to the stdio configuration; no other unit is affected.
