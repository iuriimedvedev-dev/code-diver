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
                      │                   ▼                          │
                      │   ┌──────────────────────────────────────┐   │
                      │   │ Central Qdrant Vector DB (Cluster)   │   │
                      │   └──────────────────────────────────────┘   │
                      │                   │                          │
                      │                   ▼                          │
                      │   ┌──────────────────────────────────────┐   │
                      │   │ Shared Repo Storage (NFS / ReadOnly) │   │
                      │   └──────────────────────────────────────┘   │
                      └──────────────────────────────────────────────┘
```

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

## 3. Connecting Team Clients

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
