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

Production Kubernetes manifests are located in `deploy/k8s/code-diver-k8s.yaml`:

### Applying Manifests:
```bash
kubectl apply -f deploy/k8s/code-diver-k8s.yaml
```

This sets up:
- **`code-diver` namespace**
- **Qdrant Deployment & Stateful PersistentVolumeClaim** (stores neural vector embeddings)
- **ConfigMap** (`code-diver.yml`) pointing to the cluster Qdrant service
- **Code Diver Service & Deployment** running scaled search/MCP pods

---

## 3. Connecting Team Clients

Once deployed, colleagues configure their MCP host (e.g. OpenCode or Claude) to connect to the shared instance via SSH stdio forwarding or SSE:

```json
{
  "mcp": {
    "team-code-diver": {
      "command": "ssh",
      "args": ["-T", "search.internal.corp", "code-diver", "mcp"]
    }
  }
}
```
Or pointing directly to the team's shared Qdrant cluster in their local `code-diver.yml`:
```yaml
storage:
  provider: qdrant
  url: http://qdrant.internal.corp:6333
```
In this mode, whenever CI/CD indexes new commits into Qdrant, all developers and AI agents immediately get up-to-date semantic retrieval with zero local indexing overhead!
