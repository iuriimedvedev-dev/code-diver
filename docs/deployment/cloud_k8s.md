# Team & Cloud Deployment Guide (Kubernetes & Docker)

Code Diver can be deployed as a shared, central code search service for development teams. This allows team members using **OpenCode**, **Claude Desktop**, **Cursor**, or **Windsurf** to share pre-indexed vector collections and graph indices across large repositories without everyone having to index gigabytes locally.

---

## Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │             Kubernetes Cluster               │
                      │                                              │
                      │   ┌──────────────────────────────────────┐   │
Developers / IDEs ───►│───► Code Diver Pods (MCP / Search API)   │   │
(OpenCode / Claude)   │   └───────────────┬──────────────────────┘   │
                      │                   │                          │
                      │        ┌──────────┴──────────┐               │
                      │        ▼                     ▼               │
                      │   ┌──────────────┐   ┌───────────────────┐   │
                      │   │ Qdrant       │   │ Embedding service │   │
                      │   │ (vectors)    │   │ llama.cpp -np N   │   │
                      │   └──────────────┘   └───────────────────┘   │
                      │                   │                          │
                      │                   ▼                          │
                      │   ┌──────────────────────────────────────┐   │
                      │   │ Shared Repo Storage (NFS / ReadOnly) │   │
                      │   └──────────────────────────────────────┘   │
                      └──────────────────────────────────────────────┘
```

The embedding service is shared by every project process and is usually the
first throughput ceiling. Size it before adding app replicas (see below).

---

## 1. Quick Docker Compose (Self-Hosted on Server)

To deploy Code Diver with Qdrant on a team server:

1. Copy configuration:
   ```bash
   cd deploy/docker
   docker compose up -d
   ```
2. Qdrant will be available at `http://<server-ip>:6333`.
3. To index a repository on the shared server:
   ```bash
   docker compose run --rm code-diver-search index
   ```

---

## 2. Kubernetes Deployment

Production manifests live in `deploy/k8s/` as a kustomize bundle with two
profiles:

| Profile | Command | OAuth | Ingress/TLS | StorageClass | Registry |
|---|---|---|---|---|---|
| Home / local | `kubectl apply -k deploy/k8s/overlays/local` | off | none | `local-path` | `registry.local/...` |
| Work / enterprise | `kubectl apply -k deploy/k8s/overlays/work` | on | nginx + cert-manager (or BYO secret) | `fast-ssd` | `registry.work.example/...` |

`kubectl apply -k deploy/k8s` is the work profile (production-safe). See
`deploy/k8s/README.md` for the four knobs (issuer host, TLS variant, storage
class, registry), secret creation, restore jobs, verification and scaling.

The old single-file manifest still exists as `deploy/k8s/code-diver-k8s.yaml`
for a self-contained, **unauthenticated** `kubectl apply -f`; it is a mirror of
the base plus the optional Qdrant StatefulSet and is not the recommended path.

The bundle sets up:
- namespace `code-diver`, ConfigMaps (app config + env), PVCs for repo/state
- an **external** Qdrant endpoint by default; `qdrant-statefulset.yaml` is
  optional for clusters that do not have one
- one Deployment (`code-diver-service`) and one ClusterIP Service on port 8080
- an Ingress for `/mcp` and all OAuth endpoints in the work profile only

First index / restore: see `deploy/k8s/README.md` ("First index", "Restore").

---

## 3. Embedder sizing: the shared bottleneck

Measured on the reference CPU-only host with llama-server at `-t 4 -np 2`:

| Load | Throughput vs 1 client |
|---|---|
| 8 concurrent embedding requests | **1.46×** |
| 8 concurrent recalls via the memory service | **1.51×** |

Those numbers are slot queueing, not code-diver CPU. One shared endpoint is the
right design, but `-np` must match the concurrency you expect.

### Concurrency model

* One `code-diver serve` process per project, one `SearchRuntime` each.
* The committed transport executes retrieval synchronously inside the async
  handler, so one project process issues ~one embedding at a time. Concurrency
  comes from **several project processes** (and indexing jobs), all sharing the
  embedding endpoint.
* One search = ~one embedding. Indexing embeds chunk/summary batches and
  competes with queries.
* Parallel: HTTP handling, embedder slots, Qdrant. Serial: everything inside
  one project process, the SQLite OAuth writer, catalog writes.

### Sizing table

| Simultaneous searches (all projects) | `-np` slots | `-t` threads | Pod CPU req/limit | Memory req/limit |
|---|---|---|---|---|
| 1–2 (home) | 2 | 4 | 1 / 2 | 1Gi / 2Gi |
| 3–4 | 4 | 4 | 2 / 4 | 1Gi / 2Gi |
| 5–8 (work default) | 8 | 6–8 | 4 / 6 | 2Gi / 4Gi |
| 9–16 | 12–16 | 8 | 6 / 8 | 2Gi / 4Gi |
| >16 | second embedder Service + split project groups, or GPU | | | |

`EMBED_THREADS` must not exceed the CPU limit. Keep `-c 2048`, `-b/-ub 512` for
300M models.

### Enabling the in-cluster embedder

The manifests ship an opt-in component that runs llama-server in embedding mode
with the values above:

```bash
# uncomment in deploy/k8s/overlays/work/kustomization.yaml (plus
# embedder-resources.patch.yaml, present for work):
#   - ../../components/embedder
#   - path: embedder-sizing.patch.yaml
#   - path: embedder-resources.patch.yaml
#   - path: embedder-storageclass.patch.yaml
# model: create Secret embedder-model/url (init container downloads it) or
# pre-seed the embedder-models volume with the GGUF before the pod starts
kubectl apply -k deploy/k8s/overlays/work
```

It switches the app to `code-diver-embedder.yml`
(`embedding.url: http://embedder:8791/v1/embeddings`), so the base config can
keep an external endpoint. The component has a 5 GiB model PVC, an init
container that downloads the GGUF when a URL is set, `/health` probes, and the
same hardening as the app.

### Measuring

```bash
kubectl -n code-diver port-forward svc/embedder 8791:8791
# compare 1 vs N concurrent POST /v1/embeddings (script in deploy/k8s/README.md)
seq 8 | xargs -P8 -I{} curl -s -o /dev/null -w '%{time_total}\n' \
  -X POST http://127.0.0.1:8080/api/v1/search \
  -H 'content-type: application/json' \
  -d '{"query":"where is retry logic","limit":10}'
curl -s http://127.0.0.1:8080/api/v1/runtime/stats | jq '.runtime_loads, .mcp_sessions'
```

### Rule

1. Scale the **embedder** (slots, then threads/CPU) before adding app replicas.
2. `replicas > 1` needs a read-only/shared catalog, a shared OAuth store
   (code-diver only has SQLite today) and a separate indexer. Not supported:
   the scale unit is one Deployment per project.
3. For more colleagues, add projects/namespaces, not replicas of one project.

---

## 4. Connecting Team Clients

Once deployed, point clients at the MCP endpoint:

```json
{
  "mcpServers": {
    "code-diver": {
      "type": "http",
      "url": "https://code-diver.work.example/mcp"
    }
  }
}
```

The client discovers the OAuth metadata from the `401` `WWW-Authenticate`
challenge, registers itself (DCR), opens `/authorize` for the operator code and
stores the refresh token.

For the local profile there is no OAuth and no Ingress:

```bash
kubectl -n code-diver port-forward svc/code-diver-service 8080:8080
# client URL: http://127.0.0.1:8080/mcp
```

Alternatively point a local `code-diver.yml` at the team Qdrant:

```yaml
storage:
  provider: qdrant
  qdrant:
    url: http://qdrant.internal.corp:6333
```

In this mode, whenever CI/CD indexes new commits into Qdrant, all developers and AI agents immediately get up-to-date semantic retrieval with zero local indexing overhead.
