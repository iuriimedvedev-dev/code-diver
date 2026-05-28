# Metrics Stack

Start local metrics storage and dashboards:

```bash
docker compose -f ops/metrics/docker-compose.yml up -d
uv run code-diver --config configs/protogen.yml experiment
```

Services:

- Grafana: `http://localhost:3000` (`admin` / `admin`)
- ClickHouse HTTP: `http://localhost:18123`

The experiment command writes aggregate rows to `code_diver.rag_eval_metrics` and per-case rows to `code_diver.rag_eval_cases`. Both tables use a TTL from `metrics.retention_days`; the compose file also caps ClickHouse memory and CPU for local runs.

For the local compose stack, `configs/protogen.yml` uses `metrics.docker_container: code-diver-clickhouse`, so writes go through `docker exec clickhouse-client`. Remove that field to write through the ClickHouse HTTP URL instead.
