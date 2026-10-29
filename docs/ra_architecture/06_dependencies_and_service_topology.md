# Phase 6: Dependencies and Service Topology

The external services, sibling repository connectors, Docker Compose stack, and Python libraries [`biosciences-temporal`](../../README.md) runs on.

---

## 1. Service and connector topology

| Service / Connector | Protocol & Transport | Configuration Source | Role & Fail-Closed Contract |
| :--- | :--- | :--- | :--- |
| **Temporal Server** (`localhost:7233`, UI `:8233`) | gRPC via [`connection.py`](../../src/biosciences_temporal/temporal/connection.py) `connect` (`PydanticAIPlugin()`, `LogfirePlugin(setup_logfire=setup_logfire, metrics=False)`) | [`docker-compose.yml`](../../docker-compose.yml) (`temporalio/admin-tools:latest` running `temporal server start-dev`) | Polls task queue `biosciences-task-queue`. Isolated from other project queues on `:7233`. |
| **Sibling `biosciences-mcp` Gateway** (`src/biosciences_mcp/servers/gateway.py`) | JSON-RPC over OS `stdin`/`stdout` pipes (`MCPToolset` with `StdioTransport`) | [`base.py`](../../src/biosciences_temporal/agents/base.py) `_find_sibling_repo`, `create_mcp_client` | Spawns `uv run fastmcp run src/biosciences_mcp/servers/gateway.py` in `BIOSCIENCES_MCP_PATH` (`../biosciences-mcp`) per activity (`init_timeout=120.0`, `read_timeout=120.0`). Skipped automatically when `AgentRunner` runs offline with `TestModel(call_tools=[])` or an injected `FunctionToolset`. |
| **OpenRouter API & TypeSafe Jev** (`https://openrouter.ai/api/v1`) | HTTPS via `OpenRouterModel` / `FallbackModel` and `TypeSafeModel` | [`base.py`](../../src/biosciences_temporal/agents/base.py) `create_model` | Uses `nvidia/nemotron-3.5-lightning:free` primary and `openrouter/free` secondary (`USAGE_LIMITS = UsageLimits(request_limit=100)`), optional `TypeSafeModel("jev-latest")` when `TYPESAFE_API_KEY` is set, or falls back to `TestModel(call_tools=[])` when neither API key is set. |
| **Pydantic Logfire** | OTLP HTTPS (`setup_logfire()`, `LogfirePlugin(setup_logfire=setup_logfire, metrics=False)`) & SQL Read API (`LogfireQueryClient`) | [`connection.py`](../../src/biosciences_temporal/temporal/connection.py), [`run_agent.py`](../../src/biosciences_temporal/scripts/run_agent.py), [`run_worker.py`](../../src/biosciences_temporal/scripts/run_worker.py), [`query_logfire.py`](../../src/biosciences_temporal/scripts/query_logfire.py) | Links Temporal workflows, activities, and `AgentRunner` spans (`phase`, `action`, `entity_type`, `source`, `cq_id`) into a single replay-safe trace and queries historical spans via `LOGFIRE_READ_TOKEN`. |

---

## 2. Library dependencies ([`pyproject.toml`](../../pyproject.toml))

The full list is extracted into [`docs/inspect.json`](../inspect.json) under `dependencies`.

| Package | Version Constraint | Role |
| :--- | :--- | :--- |
| `pydantic-ai[temporal]` | `>=2.62.0` | `Agent`, `MCPToolset`, `OpenRouterModel`, `TypeSafeModel`, `FallbackModel`, `TestModel`, `FunctionToolset`, `PydanticAIPlugin`, `LogfirePlugin`, `UsageLimits` |
| `fastmcp` | `>=3.0,<4.0` | `StdioTransport` client speaking MCP SDK v1 wire protocol compatible with `biosciences-mcp` (`fastmcp 2.14.x`) |
| `typesafe-sdk` | `>=0.7.5` | TypeSafe (`jev-latest`) client SDK backing `pydantic_ai.models.typesafe.TypeSafeModel` |
| `temporalio` | `>=1.34.0` | Workflow, activity, worker (`WORKFLOW_RUNNER` / `SandboxedWorkflowRunner`), and client runtime |
| `pydantic` | `>=2.14.0` | Structured output models (`agents/models.py`) |
| `logfire` | `>=5.4.0` | OpenTelemetry instrumentation and `LogfireQueryClient` |
| `httpx` | `>=0.28.0` | Async HTTP transport |
| `python-dotenv` | `>=1.2.0` | `.env` configuration loader (`load_dotenv(override=True)`) |
