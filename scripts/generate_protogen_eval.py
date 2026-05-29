from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from code_diver.services import CodeSymbolExtractor


@dataclass(slots=True)
class EvalCaseDraft:
    case_id: str
    query: str
    expected: list[str]
    priority: int


class ProtogenEvalGenerator:
    def __init__(self, root: Path, limit: int):
        self.root = root.resolve()
        self.limit = limit
        self.symbol_extractor = CodeSymbolExtractor()

    def build(self) -> list[EvalCaseDraft]:
        groups = [
            self._intent_cases(),
            self._api_route_cases(),
            self._config_cases(),
            self._eval_yaml_cases(),
            self._python_symbol_cases(),
        ]
        drafts: list[EvalCaseDraft] = []
        while any(groups):
            next_groups: list[list[EvalCaseDraft]] = []
            for group in groups:
                if not group:
                    continue
                drafts.append(group.pop(0))
                next_groups.append(group)
            groups = next_groups
        return self._dedupe(drafts)[: self.limit]

    def _intent_cases(self) -> list[EvalCaseDraft]:
        specs = [
            ("where-authorization", "where is authorization authentication user permissions tokens handled", ["src/config/settings.py", "src/api/routes/settings.py", "src/operators/models_config.py"]),
            ("where-command-created", "where is a generation command created from cli user input", ["src/cli/commands_click/generate.py", "src/cli/commands/generate.py"]),
            ("where-command-dispatched", "where does the CLI route commands to handlers", ["src/cli/cli.py", "src/cli/app.py"]),
            ("where-strategy-created", "where is an arena strategy experiment created", ["src/arena/service.py", "src/arena/models.py"]),
            ("where-strategy-run", "where are arena strategies run and compared", ["src/arena/runner.py", "src/arena/evaluator.py"]),
            ("where-session-starts", "where is a generation session created and started", ["src/sessions/service.py", "src/api/routes/sessions.py"]),
            ("where-session-cancel", "where is session cancellation implemented", ["src/sessions/service.py", "src/cli/commands_click/session.py"]),
            ("where-session-cleanup", "where are old sessions cleaned up", ["src/sessions/cleanup.py", "src/sessions/service.py"]),
            ("where-live-updates", "where are live websocket progress updates sent", ["src/websocket/manager.py", "src/services/pipeline_service.py"]),
            ("where-events-stored", "where are websocket or protocol events stored", ["src/websocket/event_store.py", "src/protocol/models.py"]),
            ("where-pipeline-built", "where is the feature generation pipeline assembled", ["src/pipeline/builder.py", "src/pipeline/graph.py"]),
            ("where-pipeline-run", "where does pipeline execution happen", ["src/pipeline/runner.py", "src/pipeline/orchestrator.py"]),
            ("where-feature-loop", "where is the feature iteration loop controlled", ["src/pipeline/feature_loop.py", "src/pipeline/feature_partitioner.py"]),
            ("where-team-pipeline", "where is team based pipeline execution implemented", ["src/services/team_pipeline_executor.py", "src/agents/team_agent_runner.py"]),
            ("where-agent-registry", "where are agents registered and resolved", ["src/agents/registry.py", "src/agents/base/registry.py"]),
            ("where-agent-factory", "where are agent objects constructed", ["src/agents/factory.py", "src/agents/base/factory.py"]),
            ("where-operator-registry", "where are coding operators registered", ["src/operators/registry.py", "src/operators/process_registry.py"]),
            ("where-gemini-operator", "where does Gemini operator call the SDK or CLI", ["src/operators/gemini_sdk.py", "src/operators/gemini_cli.py"]),
            ("where-openai-operator", "where does OpenAI Codex or SDK operator run", ["src/operators/openai_sdk.py", "src/operators/openai_codex.py"]),
            ("where-claude-operator", "where does Claude Code operator run", ["src/operators/claude_code.py", "src/operators/claude_code_sdk.py"]),
            ("where-operator-config", "where are operator models and provider settings configured", ["src/operators/models_config.py", "src/config/provider.py"]),
            ("where-tool-registry", "where are agent tools registered", ["src/tools/registry.py", "src/agents/tools/registry.py"]),
            ("where-file-tools", "where are read write edit file tools implemented", ["src/tools/infrastructure/read_file_tool.py", "src/tools/infrastructure/write_file_tool.py"]),
            ("where-codegen-tools", "where are code generation tools implemented", ["src/tools/codegen/codegen_tool.py", "src/agents/tools/codegen.py"]),
            ("where-openapi-generation", "where is OpenAPI parsing or extraction done", ["src/agents/backend/openapi_parser.py", "src/operators/openapi_extractor.py"]),
            ("where-backend-agent", "where is backend generation agent behavior defined", ["src/agents/backend/agent.py", "src/agents/developer/backend.py"]),
            ("where-frontend-agent", "where is frontend generation agent behavior defined", ["src/agents/frontend/agent.py", "src/agents/developer/frontend.py"]),
            ("where-infra-agent", "where is infrastructure docker generation agent behavior defined", ["src/agents/infrastructure/agent.py", "src/agents/developer/infrastructure.py"]),
            ("where-architecture-agent", "where is architecture design agent implemented", ["src/agents/architecture/agent.py", "src/agents/architect/agent.py"]),
            ("where-product-manager", "where does product manager coordinate features", ["src/agents/product_manager/coordinator.py", "src/agents/product_manager/agent.py"]),
            ("where-supervisor", "where does supervisor orchestrate agent graph", ["src/agents/supervisor/graph.py", "src/agents/supervisor/agent.py"]),
            ("where-direct-agents", "where are direct non langchain agents implemented", ["src/agents/direct/base.py", "src/agents/direct/operator_agent.py"]),
            ("where-reviewer", "where is code review agent service implemented", ["src/review/service.py", "src/review/reviewer_agent.py"]),
            ("where-changes-analyzed", "where are incremental change requests analyzed", ["src/changes/analyzer.py", "src/changes/service.py"]),
            ("where-changes-decomposed", "where are changes decomposed into implementation steps", ["src/changes/decomposer.py", "src/changes/models.py"]),
            ("where-artifacts", "where are generated artifacts stored and served", ["src/artifacts/service.py", "src/api/routes/artifacts.py"]),
            ("where-containers", "where are docker containers created and monitored", ["src/containers/service.py", "src/containers/docker_client.py"]),
            ("where-compose", "where is docker compose generated or managed", ["src/containers/compose.py", "src/tools/infrastructure/compose_tool.py"]),
            ("where-health-checks", "where are container health checks implemented", ["src/containers/health.py", "src/api/routes/health.py"]),
            ("where-database-session", "where is database session setup", ["src/database/session.py", "src/config/settings.py"]),
            ("where-session-repository", "where are sessions persisted in postgres", ["src/sessions/postgres_repository.py", "src/sessions/repository.py"]),
            ("where-metrics-collector", "where are LLM tokens cost cache usage collected", ["src/metrics/collector.py", "src/metrics/callbacks.py"]),
            ("where-metrics-api", "where are metrics exposed through API routes", ["src/api/routes/metrics.py", "src/cli/commands_click/metrics.py"]),
            ("where-pricing", "where is OpenRouter pricing calculated", ["src/metrics/openrouter_pricing.py", "src/metrics/models.py"]),
            ("where-eval-runner", "where are evaluation datasets executed", ["src/eval/runner.py", "src/eval/service.py"]),
            ("where-eval-import", "where are eval yaml datasets imported", ["src/eval/dataset_importer.py", "src/cli/commands_click/evals.py"]),
            ("where-eval-judge", "where is generated app quality judged", ["src/eval/judge.py", "src/arena/evaluator.py"]),
            ("where-ailoop", "where does autonomous improvement loop orchestrate analysis optimization", ["src/ailoop/orchestrator.py", "src/ailoop/service.py"]),
            ("where-ailoop-analysis", "where does ailoop analyze failures and metrics", ["src/ailoop/analyzer.py", "src/ailoop/deep_analyzer.py"]),
            ("where-ailoop-optimize", "where does ailoop optimize generator prompts or config", ["src/ailoop/optimizer.py", "src/ailoop/models.py"]),
            ("where-team-builder", "where are teams built from yaml definitions", ["src/team_builder/service.py", "src/team_builder/yaml_validator.py"]),
            ("where-team-db", "where are teams persisted in database", ["src/teams_db/service.py", "src/teams_db/repository.py"]),
            ("where-prompt-parts", "where are prompt parts stored and resolved", ["src/teams_db/prompt_part_resolver.py", "src/api/routes/prompt_parts.py"]),
            ("where-platform-module", "where is platform module registry handled", ["src/platform/registry.py", "src/tools/platform/module_details_tool.py"]),
            ("where-memory", "where is cross feature memory or registry implemented", ["src/memory/cross_feature_registry.py", "src/memory/tools.py"]),
            ("where-scaffolding", "where are model repository schema service generators", ["src/scaffolding/generators/model_generator.py", "src/scaffolding/generators/service_generator.py"]),
            ("where-frontend-package", "where are frontend dependencies and npm scripts configured", ["frontend/package.json"]),
            ("where-dev-compose", "where are postgres redis backend frontend dev services configured", ["docker-compose.dev.yml"]),
            ("where-monitoring-compose", "where are prometheus grafana monitoring services configured", ["docker-compose.monitoring.yml"]),
            ("where-python-package", "where are python dependencies and console scripts configured", ["pyproject.toml"]),
            ("where-sample-apps", "where are sample app definitions configured", ["scripts/sample_apps.yaml"]),
            ("where-api-router-wiring", "where are FastAPI routers included in the app", ["src/main.py", "src/app.py"]),
            ("where-settings-api", "where can UI fetch or update provider settings", ["src/api/routes/settings.py"]),
            ("where-operators-api", "where does API expose operator management", ["src/api/routes/operators.py"]),
            ("where-teams-api", "where does API expose team builder and teams", ["src/api/routes/teams.py", "src/api/routes/team_builder.py"]),
            ("where-tools-api", "where does API expose available generation tools", ["src/api/routes/tools.py"]),
            ("where-monitor-api", "where does API expose monitoring endpoints", ["src/api/routes/monitor.py"]),
            ("where-blog-api", "where is the example blog API implemented", ["src/api/routes/blog.py", "src/api/schemas/blog.py"]),
            ("where-calculator-api", "where is the calculator route and service implemented", ["src/api/routes/calculator.py", "src/api/services/calculator.py"]),
            ("where-todo-api", "where are todo endpoints and schemas implemented", ["src/api/routes/todos.py", "src/api/schemas/todo.py"]),
            ("where-root-health", "where is root health check endpoint implemented", ["src/api/routes/root_health.py", "src/api/routes/health.py"]),
            ("where-prompt-templates", "where are agent prompt templates defined", ["src/agents/base/prompts.py", "src/codegen/templates/prompts.py"]),
            ("where-backend-prompts", "where are backend generation prompts stored", ["src/agents/backend/prompts.py", "src/agents/backend/prompts_improved.py"]),
            ("where-frontend-prompts", "where are frontend generation prompts stored", ["src/agents/frontend/prompts.py"]),
            ("where-infra-prompts", "where are infrastructure generation prompts stored", ["src/agents/infrastructure/prompts.py"]),
            ("where-api-prompts", "where are API generation prompts and templates stored", ["src/agents/api/prompts.py", "src/agents/api/templates.py"]),
            ("where-architecture-models", "where are architecture output models defined", ["src/agents/architecture/models.py"]),
            ("where-backend-models", "where are backend generation models defined", ["src/agents/backend/models.py"]),
            ("where-frontend-models", "where are frontend generation models defined", ["src/agents/frontend/models.py"]),
            ("where-infra-models", "where are docker infrastructure models defined", ["src/agents/infrastructure/models.py"]),
            ("where-agent-runtime", "where is agent runtime execution managed", ["src/agents/runtime/executor.py", "src/agents/runtime/session_map.py"]),
            ("where-subagents", "where are subagents spawned for work", ["src/agents/subagent_spawner.py"]),
            ("where-team-graph", "where is the multi agent team graph built", ["src/agents/team_graph_builder.py", "src/agents/team_factory.py"]),
            ("where-team-config-yaml", "where are team yaml configs validated and serialized", ["src/team_builder/yaml_validator.py", "src/team_builder/serialization.py"]),
            ("where-team-state", "where is team execution state stored", ["src/teams/state.py", "src/teams/builder.py"]),
            ("where-generated-code-service", "where is generated code produced from specifications", ["src/codegen/service.py"]),
            ("where-codegen-models", "where are code generation request and response models", ["src/codegen/models.py"]),
            ("where-codegen-prompts", "where are code generation prompts defined", ["src/codegen/prompts.py"]),
            ("where-static-files", "where are static files registered for generated apps", ["src/automation/static_files/registry.py"]),
            ("where-angular-cli", "where does the app wrap Angular CLI commands", ["src/automation/cli_tools/angular_cli_tool.py"]),
            ("where-npm-tool", "where does the app run npm commands", ["src/automation/cli_tools/npm_tool.py"]),
            ("where-uv-tool", "where does the app run uv python commands", ["src/automation/cli_tools/uv_tool.py"]),
            ("where-mcp-config", "where is MCP server configuration loaded", ["src/config/mcp_config.py"]),
            ("where-feature-flags", "where are feature flags configured", ["src/config/feature_flags.py"]),
            ("where-logfire", "where is Logfire observability configured", ["src/observability/logfire_config.py", "src/config/src/observability/logfire_config.py"]),
            ("where-logging", "where is structured logging configured", ["src/logging_config.py"]),
            ("where-analytics-report", "where are arena analytics reports generated", ["src/analytics/arena_reporter.py", "src/analytics/report_generator.py"]),
            ("where-session-analysis", "where are generation sessions analyzed", ["src/analytics/session_analyzer.py"]),
            ("where-arena-aggregation", "where are arena results aggregated", ["src/arena/aggregator.py", "src/arena/statistics.py"]),
            ("where-arena-quality", "where is arena quality runner implemented", ["src/arena/quality_runner.py"]),
            ("where-arena-repository", "where are arena runs persisted", ["src/arena/repository.py"]),
            ("where-eval-repository", "where are evaluation runs persisted", ["src/eval/repository.py"]),
            ("where-batch-eval", "where are batch eval jobs orchestrated", ["src/eval/batch_orchestrator.py"]),
            ("where-eval-config-loader", "where are evaluation yaml configs loaded", ["src/eval/config_loader.py"]),
            ("where-app-host-client", "where does the system call generated app host", ["src/services/app_host_client.py"]),
            ("where-team-service", "where is team CRUD service implemented", ["src/services/team_service.py"]),
            ("where-workspace", "where are session workspaces managed", ["src/sessions/workspace.py"]),
            ("where-session-ports", "where are session service ports or interfaces defined", ["src/sessions/ports.py"]),
            ("where-protocol-models", "where are protocol event models defined", ["src/protocol/models.py"]),
            ("where-websocket-events", "where are websocket event types defined", ["src/websocket/events.py"]),
            ("where-websocket-handlers", "where are websocket handlers implemented", ["src/websocket/handlers.py"]),
            ("where-model-generator", "where does scaffolding generate models", ["src/scaffolding/generators/model_generator.py"]),
            ("where-repository-generator", "where does scaffolding generate repositories", ["src/scaffolding/generators/repository_generator.py"]),
            ("where-schema-generator", "where does scaffolding generate schemas", ["src/scaffolding/generators/schema_generator.py"]),
            ("where-service-generator", "where does scaffolding generate services", ["src/scaffolding/generators/service_generator.py"]),
            ("where-platform-tools", "where are platform module tools implemented", ["src/tools/platform/module_details_tool.py"]),
            ("where-taiga-tools", "where are Taiga UI docs and theme tools implemented", ["src/tools/ui/taiga_docs_tool.py", "src/tools/ui/taiga_theme_tool.py"]),
            ("where-testing-tools", "where are unit integration api testing tools implemented", ["src/tools/testing/unit_tests_tool.py", "src/tools/testing/integration_tests_tool.py", "src/tools/testing/api_tests_tool.py"]),
        ]
        return [
            self._case(case_id, query, [path for path in expected if (self.root / path).exists()], 0)
            for case_id, query, expected in specs
            if any((self.root / path).exists() for path in expected)
        ]

    def _python_symbol_cases(self) -> list[EvalCaseDraft]:
        drafts: list[EvalCaseDraft] = []
        by_area: dict[str, list[EvalCaseDraft]] = {}
        for path in sorted((self.root / "src").rglob("*.py")):
            rel_path = path.relative_to(self.root).as_posix()
            if self._skip_path(rel_path):
                continue
            area = "/".join(rel_path.split("/")[:3])
            text = path.read_text(encoding="utf-8", errors="replace")
            for symbol in self.symbol_extractor.extract(rel_path, text):
                if symbol.kind == "method" and "." in symbol.name:
                    words = self._words(symbol.name.replace(".", " "))
                    query = f"{rel_path} method {' '.join(words)} {symbol.signature}"
                    priority = 3
                else:
                    words = self._words(symbol.name)
                    query = f"{rel_path} {symbol.kind} {' '.join(words)} {symbol.signature}"
                    priority = 2
                by_area.setdefault(area, []).append(
                    self._case(f"symbol-{rel_path}-{symbol.name}", query, [rel_path], priority)
                )
        groups = [values for _, values in sorted(by_area.items())]
        while any(groups):
            next_groups: list[list[EvalCaseDraft]] = []
            for group in groups:
                if not group:
                    continue
                drafts.append(group.pop(0))
                next_groups.append(group)
            groups = next_groups
        return drafts

    def _api_route_cases(self) -> list[EvalCaseDraft]:
        drafts: list[EvalCaseDraft] = []
        for path in sorted((self.root / "src" / "api" / "routes").glob("*.py")):
            rel_path = path.relative_to(self.root).as_posix()
            stem_words = " ".join(self._words(path.stem))
            drafts.append(self._case(f"api-route-{path.stem}", f"API route router endpoints {stem_words}", [rel_path], 1))
        return drafts

    def _config_cases(self) -> list[EvalCaseDraft]:
        paths = [
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.dev.yml",
            "docker-compose.prod.yml",
            "docker-compose.monitoring.yml",
            "frontend/Dockerfile",
            "frontend/package.json",
            "scripts/sample_apps.yaml",
        ]
        return [
            self._case(f"config-{Path(path).stem}", f"configuration file {' '.join(self._words(path))}", [path], 1)
            for path in paths
            if (self.root / path).exists()
        ]

    def _eval_yaml_cases(self) -> list[EvalCaseDraft]:
        drafts: list[EvalCaseDraft] = []
        for path in sorted((self.root / "evals").glob("*.yaml")):
            rel_path = path.relative_to(self.root).as_posix()
            words = " ".join(self._words(path.stem.replace("_dataset", "")))
            drafts.append(self._case(f"eval-{path.stem}", f"evaluation dataset yaml generated app task {words}", [rel_path], 4))
        return drafts

    def _case(self, case_id: str, query: str, expected: list[str], priority: int) -> EvalCaseDraft:
        clean_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", case_id).strip("-").lower()
        clean_query = re.sub(r"\s+", " ", query).strip()
        return EvalCaseDraft(clean_id, clean_query, expected, priority)

    def _dedupe(self, drafts: list[EvalCaseDraft]) -> list[EvalCaseDraft]:
        seen: set[str] = set()
        deduped: list[EvalCaseDraft] = []
        for draft in sorted(drafts, key=lambda value: (value.priority, value.case_id)):
            key = draft.case_id
            if key in seen or not all((self.root / expected).exists() for expected in draft.expected):
                continue
            seen.add(key)
            deduped.append(draft)
        return deduped

    def _skip_path(self, rel_path: str) -> bool:
        return any(
            rel_path.startswith(prefix)
            for prefix in [
                "src/app/",
                "src/templates/",
                "src/tests/",
                "src/themes/",
            ]
        )

    def _words(self, text: str) -> list[str]:
        spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        return [word.lower() for word in re.split(r"[^A-Za-z0-9]+", spaced) if len(word) > 1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("../protogen"))
    parser.add_argument("--output", type=Path, default=Path("datasets/protogen_eval_100.jsonl"))
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    cases = ProtogenEvalGenerator(args.root, args.limit).build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(
            json.dumps({"id": case.case_id, "query": case.query, "expected": case.expected}) + "\n"
            for case in cases
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(cases)} cases -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
