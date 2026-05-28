# Container Runtime

Build the Alpine runtime image:

```bash
docker compose -f ops/runtime/docker-compose.yml build code-diver
```

Run against any mounted codebase:

```bash
CODEBASE_PATH=/absolute/path/to/repo \
ARTIFACTS_PATH=/absolute/path/to/artifacts \
docker compose -f ops/runtime/docker-compose.yml run --rm code-diver index
```

Useful commands:

```bash
docker compose -f ops/runtime/docker-compose.yml up -d qdrant clickhouse grafana
docker compose -f ops/runtime/docker-compose.yml run --rm code-diver search "where is the main entrypoint?"
docker compose -f ops/runtime/docker-compose.yml run --rm code-diver evaluate --json
docker compose -f ops/runtime/docker-compose.yml run --rm code-diver experiment
```

For the sibling `protogen` repo:

```bash
CODEBASE_PATH=/absolute/path/to/protogen \
ARTIFACTS_PATH=/absolute/path/to/code-diver/.code-diver/container-protogen \
CODE_DIVER_CONFIG=/app/configs/container-protogen.yml \
docker compose -f ops/runtime/docker-compose.yml run --rm code-diver index
```

Use absolute host paths for `CODEBASE_PATH` and `ARTIFACTS_PATH`; compose resolves relative bind paths from the compose file directory, which is easy to get wrong.

Services:

- Qdrant: `http://localhost:6333`
- ClickHouse HTTP: `http://localhost:18123`
- Grafana: `http://localhost:3000` (`admin` / `admin`)

The runtime container writes indexes and graph artifacts to `/artifacts`, and writes experiment metrics to ClickHouse over HTTP inside the compose network.
