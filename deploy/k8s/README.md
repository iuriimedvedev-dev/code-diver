# code-diver on Kubernetes

Kustomize bundle for the native MCP Streamable HTTP server
(`code-diver serve`, TLS + OAuth 2.1 in `feat/http-mcp-oauth`).

Topology, in one sentence: **one** `code-diver serve` process per project
behind a ClusterIP Service, TLS-terminated at ingress-nginx in the work
profile, vectors in an **external** Qdrant, the repo checkout and the local
catalog/OAuth SQLite on **ReadWriteOnce** PVCs.

```
client ──https──> ingress-nginx ──http──> Service:8080 ──> Pod (1 replica/project)
                                                             ├─ /workspace (PVC): repo checkout
                                                             ├─ /data (PVC): catalog, graph, traces, OAuth SQLite
                                                             ├─ Qdrant (external, one collection/project)
                                                             └─ embedding / rerank (external)
```

## Files

| Path | Purpose |
|---|---|
| `base/` | shared resources: Namespace, 2 ConfigMaps, 2 PVCs, Deployment, Service. **OAuth off, no Ingress.** |
| `base/kustomization.yaml` | base entry point (not applied directly) |
| `components/ingress/` | Ingress for `/mcp` + all OAuth endpoints (work only) |
| `components/embedder/` | optional shared llama.cpp embedding server (`-np`/`-t` from `embedder-config`) |
| `components/app-tls/` | optional app-terminated TLS (topology W2) |
| `components/image-pull-secret/` | work profile `imagePullSecrets: registry-credentials` |
| `overlays/local/` | home profile: no OAuth, no Ingress, `local-path`, local registry |
| `overlays/work/` | enterprise profile: OAuth, Ingress, TLS (A/B), `fast-ssd`, private registry |
| `overlays/project-example/` | a second project stamped from the same base |
| `jobs/restore-catalog/` | optional first-run catalog restore Job |
| `qdrant-statefulset.yaml` | optional single-replica Qdrant (external by default) |
| `secret.example.yaml` | placeholders only (JWT/consent, Qdrant, restore, TLS) |
| `kustomization.yaml` | default = `overlays/work` |

## Prerequisites

* Kubernetes >= 1.25 (Pod Security Admission `restricted` is enforced).
* `kubectl` >= 1.25 (bundles a kustomize new enough for `components`/`patches`).
* An ingress controller for the work profile (annotations target
  **ingress-nginx**). The local profile needs none.
* A StorageClass: `local-path` for home, `fast-ssd` placeholder for work.
* An external Qdrant, **or** apply the optional `qdrant-statefulset.yaml`.
* Repository content in the `repo-shared-pvc` volume: code-diver reads (and can
  ingest into) `/workspace`. See "Populate the repo volume" below.
* An OpenAI-compatible **embedding** endpoint; the model/dimension must match
  the Qdrant collection -- **or** enable `components/embedder` (see
  "Embedder sizing").
* Optional: a **rerank** endpoint, only for `graph_file_cross_encoder` /
  `hybrid_rerank` strategies (the default `hybrid` does not use it).
* TLS: cert-manager **or** a pre-created `kubernetes.io/tls` secret (work).

## Image build and push

```bash
# from the repo root; the repo Dockerfile already installs the console script
docker build -t code-diver:0.6.5 .
docker tag  code-diver:0.6.5 registry.local/code-diver:0.6.5
docker push registry.local/code-diver:0.6.5

# work registry
docker tag  code-diver:0.6.5 registry.work.example/code-diver/code-diver:0.6.5
docker push registry.work.example/code-diver/code-diver:0.6.5
```

The tag is consumed by the `images:` entry of each overlay — that is knob 4.
`imagePullPolicy` is `IfNotPresent` in base/local and `Always` in work.

## Where Qdrant sits

The default is an **external** Qdrant (`http://qdrant.qdrant.svc.cluster.local:6333`,
namespace `qdrant`), not a sidecar: several projects share it with distinct
collections, it survives code-diver rollouts, and vectors stay out of the
catalog PVC.

`qdrant-statefulset.yaml` is optional for clusters without Qdrant and creates
the exact Service name the ConfigMap expects. The deprecated single file
`code-diver-k8s.yaml` still embeds its own Qdrant Deployment — **do not apply it
and the external/StatefulSet path in the same cluster**. Pick one:

* existing shared Qdrant -> keep the ConfigMap URL, apply nothing extra;
* no Qdrant -> `kubectl apply -f deploy/k8s/qdrant-statefulset.yaml`;
* legacy self-contained file -> only that file, never the overlays.

## Embedder: a first-class, sized dependency

The shared embedding server is the first throughput ceiling, not code-diver
itself. On the reference CPU-only host with llama-server at `-t 4 -np 2`:

* 8 concurrent embedding requests reached only **1.46×** the single-client
  throughput;
* 8 concurrent recalls through the memory service reached only **1.51×**.

Both are queueing on two slots. For a deployment shared by several colleagues
(or several project processes) size the embedder **before** anything else.

### Concurrency model (what is parallel, what is serial)

1. **One process per project**, one `SearchRuntime` each, no child processes.
2. **The committed transport runs retrieval synchronously inside the async
   request handler**, so one project process issues roughly one embedding at a
   time; concurrency comes from *several project processes* and from indexing
   jobs, not from parallel calls inside one process.
3. **One search ≈ one embedding request** (query). Indexing embeds every
   chunk/summary in batches and competes with queries — schedule indexing off
   peak hours or give the embedder headroom.
4. **Parallel:** HTTP handling, embedder slots, Qdrant queries, BM25/graph
   work in separate processes. **Serial:** everything inside one project
   process (single event loop), the OAuth SQLite writer, catalog writes.
5. **Do not add app replicas to fix latency.** Two replicas of the same
   project would both open the catalog and the SQLite OAuth DB; the fix is
   embedder slots, then a faster node.

### Sizing table

`-np` = slots (concurrent embedding requests), `-t` = CPU threads, `-c` =
per-slot context, `-b`/`-ub` = logical/physical batch.

| Simultaneous searches (all projects) | `EMBED_SLOTS` (`-np`) | `EMBED_THREADS` (`-t`) | Pod CPU req/limit | Memory req/limit |
|---|---|---|---|---|
| 1–2 (home) | 2 | 4 | 1 / 2 | 1Gi / 2Gi |
| 3–4 | 4 | 4 | 2 / 4 | 1Gi / 2Gi |
| 5–8 (work default) | 8 | 6–8 | 4 / 6 | 2Gi / 4Gi |
| 9–16 | 12–16 | 8 | 6 / 8 | 2Gi / 4Gi |
| >16 | second embedder Service + split project groups, or GPU | | | |

Rules of thumb:

* `EMBED_SLOTS >= simultaneous searches`; extra slots only cost RAM/context.
* `EMBED_THREADS <= pod CPU limit`; a lower limit throttles every slot.
* Keep `-c 2048`, `-b/-ub 512` for 300M embedding models; code chunks are
  short enough that larger batches mostly add latency.
* One 300M Q8 model is ~0.4–1 GiB; the rest is per-slot context.

### Enable the in-cluster embedder (opt-in)

```bash
# 1. uncomment the component + its sizing/storage patches in the chosen overlay
#    (work also has embedder-resources.patch.yaml for its 6-CPU default):
#      - ../../components/embedder
#      - path: embedder-sizing.patch.yaml
#      - path: embedder-resources.patch.yaml
#      - path: embedder-storageclass.patch.yaml

# 2. provide the model (either)
#    a) recommended: a URL the init container downloads on first start
kubectl -n code-diver create secret generic embedder-model \
  --from-literal=url='https://models.example.com/embeddinggemma-300M-Q8_0.gguf'
#       (or set EMBED_MODEL_URL in components/embedder/configmap.yaml)
#    b) offline: pre-seed the embedder-models volume with
#       /models/embeddinggemma-300M-Q8_0.gguf before the pod starts; for a
#       local-path StorageClass that is a directory on the node.

# 3. apply; the component switches the app to a config whose
#    embedding.url is http://embedder:8791/v1/embeddings
kubectl apply -k deploy/k8s/overlays/work
kubectl -n code-diver rollout status deploy/embedder
```

The component ships `code-diver-embedder.yml` (same as the base config, only
`embedding.*` differs) and a Deployment patch that points `--config` at it, so
the base config keeps the external URL. Sizing lives in
`components/embedder/configmap.yaml`; overlays patch it.

### Use an external embedder instead

The base `code-diver.yml` points at
`http://embedding.embedding.svc.cluster.local:8000/v1/embeddings`. Change
`embedding.url` / `embedding.model` / `embedding.dimensions` there (one block in
`base/configmap.yaml`, or the same block in the embedder config when the
component is enabled). The model and dimension must match the Qdrant
collection.

### Measure it

```bash
# 1. embedder throughput: 1 vs N concurrent requests
kubectl -n code-diver port-forward svc/embedder 8791:8791 &
python3 - <<'PY'
import concurrent.futures, json, time, urllib.request
URL = "http://127.0.0.1:8791/v1/embeddings"
BODY = json.dumps({"model": "google/embeddinggemma-300m", "input": ["def search(): pass"]}).encode()

def one():
    req = urllib.request.Request(URL, BODY, {"content-type": "application/json"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()
    return time.perf_counter() - t

for n in (1, 8):
    t = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(n) as ex:
        list(ex.map(lambda _: one(), range(n * 5)))
    total = time.perf_counter() - t
    print(f"{n} concurrent: {n*5/total:.2f} req/s")
PY

# 2. concurrent searches through the app (local profile: no OAuth on /api)
seq 8 | xargs -P8 -I{} curl -s -o /dev/null -w '%{time_total}\n' \
  -X POST http://127.0.0.1:8080/api/v1/search \
  -H 'content-type: application/json' \
  -d '{"query":"where is retry logic","limit":10}'

# 3. shared-runtime proof (always 1 load, N sessions)
curl -s http://127.0.0.1:8080/api/v1/runtime/stats | jq '.runtime_loads, .mcp_sessions'
```

If N-concurrent req/s is far below 1-concurrent × N (e.g. 1.46× at N=8), add
slots; when `-t` already equals the CPU limit, add CPU or a second embedder.

## Profiles

| | `overlays/local` | `overlays/work` |
|---|---|---|
| OAuth | **off** (`CODE_DIVER_OAUTH_ENABLED=0`) | **on**, issuer = public host |
| Exposure | ClusterIP only, plain HTTP, no Ingress | ingress-nginx + TLS |
| TLS | none (app plain HTTP) | ingress terminates TLS (W1, default) or app TLS + passthrough (W2) |
| StorageClass | `local-path` | `fast-ssd` (placeholder) |
| Registry | `registry.local/code-diver:0.6.5` | `registry.work.example/...` + pull secret |
| Secrets | **none required** | `code-diver-oauth`, plus TLS (unless cert-manager) |
| Embedder | external URL (or optional in-cluster component) | external URL **or** in-cluster component (opt-in) |
| Resources | 0.5 CPU / 1 Gi request | 1 CPU / 2 Gi request |

## The four knobs (never edit `base/`)

| Knob | Where | Local value | Work value |
|---|---|---|---|
| 1. Issuer / public host | `overlays/work/configmap.patch.yaml` + `overlays/work/kustomization.yaml` (JSON6902) | n/a (OAuth off) | `code-diver.work.example` |
| 2. TLS | `overlays/work/kustomization.yaml` -> variant A `ingress-cert-manager.patch.yaml` (active) or B `ingress-external-secret.patch.yaml` | no Ingress | A or B |
| 3. StorageClass | `overlays/*/pvc.patch.yaml` (both PVCs) | `local-path` | `fast-ssd` |
| 4. Registry | `images:` in `overlays/*/kustomization.yaml` | `registry.local/...` | `registry.work.example/...` |

## Human decisions (the four knobs, plus dependencies)

| Decision | Default in this bundle | Where |
|---|---|---|
| **Issuer / public host** | work: `code-diver.work.example`; local: none (OAuth off) | work `configmap.patch.yaml` + `kustomization.yaml` |
| **TLS: cert-manager vs BYO secret** | work variant A (cert-manager `letsencrypt-prod`), variant B present but inactive | work `kustomization.yaml` + `ingress-*.patch.yaml` |
| **StorageClass** | local `local-path`, work `fast-ssd` (both PVCs) | `overlays/*/pvc.patch.yaml` |
| **Image registry** | `registry.local/...`, `registry.work.example/...` (+ `registry-credentials` pull secret) | `overlays/*/kustomization.yaml`, `components/image-pull-secret` |
| **Qdrant endpoint / collection** | external `qdrant.qdrant.svc.cluster.local:6333`, collection `code_diver` | `base/configmap.yaml` |
| **Embedding endpoint/model** | `embedding.embedding.svc...` (placeholder model) | `base/configmap.yaml` |
| **Embedder sizing** (if in-cluster) | `EMBED_SLOTS=8`, `EMBED_THREADS=8` | `overlays/work/embedder-sizing.patch.yaml` |
| **Rerank endpoint** | unused by default (`strategy: hybrid`) | `base/configmap.yaml` (`cross_encoder_rerank`) |
| **TLS topology** | W1 ingress termination (W2 app termination available) | `components/app-tls` + work overlay |

Everything else (probes, resources, securityContext, `Recreate`, guards) is in
`base/` and should not change per cluster.

Everything else (probes, securityContext, Recreate, guards) is in `base/` and
is not meant to change per cluster.

## Deploy locally in 5 commands

```bash
# 1. (optional) point at a local registry and storage class
sed -i 's#registry.local/code-diver#registry.home.lan/code-diver#' deploy/k8s/overlays/local/kustomization.yaml
sed -i 's/local-path/my-storage-class/' deploy/k8s/overlays/local/pvc.patch.yaml
# kind/minikube with no registry: use newName: code-diver (no host) and
# `kind load docker-image code-diver:0.6.5`; base is IfNotPresent.

# 2. make sure Qdrant is reachable (external) or apply the optional one once
kubectl apply -f deploy/k8s/qdrant-statefulset.yaml   # skip if you have Qdrant

# 3. apply the local profile (no secrets, no Ingress, OAuth off)
kubectl apply -k deploy/k8s/overlays/local

# 4. wait for the pod
kubectl -n code-diver rollout status deploy/code-diver-service --timeout=3m

# 5. expose it on localhost (keep this on a trusted machine / tailnet)
kubectl -n code-diver port-forward svc/code-diver-service 8080:8080
```

Verify (in another shell):

```bash
curl -s http://127.0.0.1:8080/health
# {"status":"ok",...}
curl -s -X POST http://127.0.0.1:8080/api/v1/runtime/stats | jq '.runtime_loads, .mcp_sessions'
```

Client config: `{"mcpServers":{"code-diver":{"type":"http","url":"http://127.0.0.1:8080/mcp"}}}`.

The local profile is **unauthenticated**. Never expose it beyond the cluster
network, a WireGuard/tailnet interface, or the port-forward above. To publish
it on a LAN, enable the optional NodePort patch in
`overlays/local/kustomization.yaml` — only on a single-user cluster.

## Deploy at work in 5 commands

```bash
# 1. set the four knobs (issuer host appears in two files; registry/tls/storage)
sed -i 's/code-diver\.work\.example/code-diver.acme.internal/g' \
  deploy/k8s/overlays/work/configmap.patch.yaml deploy/k8s/overlays/work/kustomization.yaml
sed -i 's#registry\.work\.example/code-diver/code-diver#registry.acme.internal/code-diver#' \
  deploy/k8s/overlays/work/kustomization.yaml
sed -i 's/fast-ssd/gp3/' deploy/k8s/overlays/work/pvc.patch.yaml
sed -i 's/letsencrypt-prod/acme-prod/' deploy/k8s/overlays/work/ingress-cert-manager.patch.yaml

# 2. create the namespace + OAuth secret (JWT >= 32 chars)
kubectl create namespace code-diver
kubectl -n code-diver create secret generic code-diver-oauth \
  --from-literal=jwt-secret="$(openssl rand -hex 32)" \
  --from-literal=consent-secret="$(openssl rand -hex 16)"

# 2b. variant B only: bring your own certificate instead of cert-manager
#     (edit kustomization.yaml first: comment A, uncomment B -- see "TLS")
# kubectl -n code-diver create secret tls code-diver-tls --cert=fullchain.pem --key=privkey.pem

# 3. (optional) pull secret for the private registry
kubectl -n code-diver create secret docker-registry registry-credentials \
  --docker-server=registry.acme.internal \
  --docker-username='...' --docker-password='...'

# 4. apply
kubectl apply -k deploy/k8s/overlays/work

# 5. wait, then verify discovery through the real host
kubectl -n code-diver rollout status deploy/code-diver-service --timeout=5m
curl -s https://code-diver.acme.internal/.well-known/oauth-protected-resource | jq
curl -s https://code-diver.acme.internal/.well-known/oauth-authorization-server | jq
```

The OAuth issuer in the ConfigMap and the Ingress host **must be identical**;
if they differ, clients reject the metadata. Both are patched from the same
`sed` in step 1.

## Secrets

| Secret | Keys | Required by |
|---|---|---|
| `code-diver-oauth` | `jwt-secret` (>=32 chars), `consent-secret` | work/project profiles |
| `code-diver-qdrant` | `api-key` | only if Qdrant needs auth |
| `code-diver-tls` | `tls.crt`, `tls.key` | TLS variant B |
| `code-diver-mcp-tls` | `tls.crt`, `tls.key` | topology W2 (app TLS) |
| `code-diver-restore` | `catalog-url`, `catalog-sha256` | restore Job |
| `registry-credentials` | dockerconfigjson | private registry |

`secret.example.yaml` contains **placeholders only**. Create the real objects
with `kubectl create secret ...` as above; never commit or `kubectl apply` the
example file.

Rotating `jwt-secret` invalidates every access/refresh token. Deleting
`/data/oauth/oauth.sqlite3` on the state PVC revokes every client and forces
re-registration.

## TLS topologies

**W1 (default, active):** ingress-nginx terminates TLS, the pod speaks HTTP.
* Variant A: `ingress-cert-manager.patch.yaml` adds
  `cert-manager.io/cluster-issuer: letsencrypt-prod`; cert-manager creates
  `code-diver-tls`.
* Variant B: comment A, uncomment `ingress-external-secret.patch.yaml`, create
  `code-diver-tls` yourself; the `null` annotation prevents cert-manager from
  touching it.

**W2 (optional):** the app terminates TLS; the ingress passes the stream
through.
1. uncomment `- ../../components/app-tls` in `overlays/work/kustomization.yaml`
2. uncomment `- path: ingress-passthrough.patch.yaml`
3. create `code-diver-mcp-tls` (same cert/key)
4. ingress-nginx must run with `--enable-ssl-passthrough`
The component also flips the three probes to `scheme: HTTPS`.

**Local:** no TLS anywhere. If you need HTTPS on a home network, use a
self-signed certificate with variant W2 and the same `app-tls` component.

`X-Forwarded-Proto`: ingress-nginx sets it; the app trusts it only from
`FORWARDED_ALLOW_IPS` (`base/configmap.yaml`, default `"*"` because the pod is
ClusterIP-only). Narrow it to the ingress controller's pod CIDR when the
cluster network is not fully trusted.

## External dependencies (deliberately not Deployments here)

| Dependency | Why external by default | Knob |
|---|---|---|
| **Qdrant** | shared across projects, survives rollouts | `base/configmap.yaml` -> `storage.qdrant.url` / `collection` |
| **Embedding daemon** | often already GPU-backed/shared; the component is opt-in | `components/embedder/` or `embedding.url` in `base/configmap.yaml` |
| **Rerank daemon** | optional: the default `search.strategy: hybrid` does not use it | add `cross_encoder_rerank.url` and switch strategy to `graph_file_cross_encoder` |

The app pod itself is CPU-only. The optional embedder component runs a CPU
llama-server with the right `-np`/`-t` for the expected concurrency; GPU model
servers are intentionally not baked into these manifests. Point the ConfigMap
at yours, or enable the component.

## Populate the repo volume

The repo PVC starts empty. Give it a checkout before indexing, either from CI
(git-sync/rsync into the claim) or with a one-off Job. Clone into the mount
root so `root: /workspace` in `code-diver.yml` stays correct:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: code-diver-repo-sync
  namespace: code-diver
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        fsGroup: 10001
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: clone
          image: alpine/git:2.45.2
          command: ["git", "clone", "--depth", "1", "https://git.example.com/org/repo.git", "/workspace"]
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: [ALL]}
          volumeMounts:
            - {name: repo, mountPath: /workspace}
            - {name: tmp, mountPath: /tmp}
      volumes:
        - name: repo
          persistentVolumeClaim: {claimName: repo-shared-pvc}
        - name: tmp
          emptyDir: {sizeLimit: 256Mi}
```

Scale the Deployment to 0 while the clone runs (single writer + RWO volume).
For private repositories, use a Secret with a read-only deploy key or a token
URL; never put the credential in the Job manifest. To index a subdirectory
instead, clone there and set `CODE_DIVER_ROOT=/workspace/<dir>` on the
Deployment (overrides `root`), or change `root` in the ConfigMap.

## First index and restore

Fresh Qdrant collection (index once, in the running pod):

```bash
kubectl -n code-diver exec deploy/code-diver-service -- \
  code-diver --config /etc/code-diver/code-diver.yml index
```

This writes vectors to Qdrant and the catalog/graph to `/data/catalog`.
Alternatively call the `code_diver_index_trigger` tool with a `code:write`
token.

Restoring a catalog snapshot (vectors must already exist, or be restored via a
Qdrant snapshot). Apply the overlay first so the namespace and PVCs exist with
the final StorageClass, then stop the engine — the Job clears
`/data/catalog` before extracting:

```bash
kubectl apply -k deploy/k8s/overlays/work          # or overlays/local
kubectl -n code-diver scale deploy/code-diver-service --replicas=0

kubectl -n code-diver create secret generic code-diver-restore \
  --from-literal=catalog-url='https://artifacts.example.com/code-diver/catalog.tar.gz' \
  --from-literal=catalog-sha256='<sha256>'
kubectl -n code-diver apply -k deploy/k8s/jobs/restore-catalog
kubectl -n code-diver wait --for=condition=complete job/code-diver-restore-catalog --timeout=30m

kubectl -n code-diver scale deploy/code-diver-service --replicas=1
```

The tarball must contain `index.json`, `graph.json` and `traces/` at its root.
`/data/oauth` is never touched by the Job.

Qdrant snapshot restore (documented, not automated):

```bash
# upload a snapshot to an existing collection
curl -X POST "$QDRANT/collections/code_diver/snapshots/upload?priority=snapshot" \
  -F 'snapshot=@code_diver.snapshot'
```

## Verify

```bash
curl -s https://code-diver.acme.internal/.well-known/oauth-protected-resource | jq
curl -s https://code-diver.acme.internal/.well-known/oauth-authorization-server | jq

# 401 challenge on /mcp (expected without a token)
curl -si -X POST https://code-diver.acme.internal/mcp \
  -H 'accept: application/json, text/event-stream' \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | head -5

# shared runtime proof (in-cluster; /api is not published by default)
kubectl -n code-diver exec deploy/code-diver-service -- \
  sh -c 'wget -qO- http://127.0.0.1:8080/api/v1/runtime/stats' | jq '.runtime_loads, .mcp_sessions'
```

A real tool call: complete the browser `/authorize` flow (operator consent
code from the secret), then POST `initialize` + `tools/list` +
`code_diver_search` to `/mcp` with the bearer token, exactly as in
`docs/http-mcp.md` ("Manual walk-through with `curl`").

Note: the app exposes `/health`, not `/healthz`; the probes target the real
endpoint.

## Per-project pattern

One Deployment + Service **per project** — not one Deployment with a `PROJECT`
env var. Reasons:

* `code-diver serve` loads exactly one config file and one `root` per process;
* each project needs its own Qdrant collection, catalog PVC and OAuth issuer;
* a second process in the same process group would still share one
  `SearchRuntime`, so the env-var variant would need app changes.

Use `overlays/project-example` as the template; it adds `namePrefix: cortex-`
and `namespace: cortex-code-diver`, so all objects (including the Namespace)
are isolated. Give it a distinct host, collection and `code-diver-oauth`
secret. Secrets are namespaced but not part of the bundle, so their names are
not prefixed: create `code-diver-oauth`, `code-diver-qdrant` and
`registry-credentials` again inside `cortex-code-diver`.

## Scaling

**Do not set `replicas: 2`.** The blocker is local state and the shared
embedder, not Qdrant:

1. **Scale the embedder first.** Measured: 8 concurrent recalls on 2 slots
   reached only 1.51× single-client throughput. Two app replicas against the
   same endpoint only queue longer (see "Embedder sizing" above).
2. the catalog (`index.json`, `graph.json`, traces) is single-writer on a RWO
   PVC, and `code_diver_index_trigger` spawns a child that writes it;
3. the OAuth store is SQLite on the state PVC — two pods would corrupt it;
4. `strategy: Recreate` guarantees both RWO volumes are released before the
   replacement pod starts.

`replicas: 2` would therefore need a read-only/shared catalog, a shared OAuth
store (not implemented — code-diver only has SQLite), and a separate indexer.
None of that is in this bundle, so the scale unit is **one Deployment per
project**. Scale vertically (CPU/RAM) and add projects rather than replicas.

## Switching profiles

Applying one overlay over the other leaves objects the new profile no longer
declares (typically the Ingress). Switch explicitly:

```bash
# work -> local: remove the Ingress
kubectl -n code-diver delete ingress code-diver --ignore-not-found
kubectl apply -k deploy/k8s/overlays/local

# local -> work
kubectl apply -k deploy/k8s/overlays/work
```

Secrets and PVCs are never deleted by a profile switch. The ConfigMaps are
updated in place, so a rollout follows (`kubectl rollout restart`).

## Rollback

```bash
kubectl -n code-diver rollout undo deploy/code-diver-service
kubectl -n code-diver rollout status deploy/code-diver-service
```

The PVCs have no owner reference and survive deleting the Deployment or the
namespace. Rolling back a bad *index* means restoring the catalog snapshot and
the Qdrant collection snapshot.

## Legacy single file

`code-diver-k8s.yaml` is a generated mirror of `base/` plus the optional Qdrant
StatefulSet, for a self-contained `kubectl apply -f` on a trusted cluster. It
has **no Ingress and no OAuth** and is not the recommended path. After editing
`base/`, regenerate it by concatenating `base/*.yaml` and
`qdrant-statefulset.yaml` in the documented order.

## Validation status

Validated on the build host:

* every YAML file parses with `yaml.safe_load_all`;
* required fields (`apiVersion`/`kind`/`metadata.name`), probes, resources,
  securityContext and PVC references were asserted by script;
* kustomization resource/component paths and patch targets were resolved and
  checked (including prefix/suffix and namespace rewrites);
* the bundle was grepped for real secrets, private IPs and host-specific paths.

**Not** validated: `kubectl apply --dry-run`, `kubectl kustomize`, schema
validation against a live API server, and runtime behaviour. Neither `kubectl`
nor `kustomize` is installed on the machine that produced these files, so no
cluster-side dry run was performed. Run
`kubectl apply -k deploy/k8s/overlays/work --dry-run=server` before the first
real apply.
