# Phase 6: Dependencies and Service Topology

The external services, sibling repository connectors, Docker Compose stack, and Python libraries [`biosciences-temporal`](../../README.md) runs on.

---

## 1. Service and connector topology

| Service / Connector | Protocol & Transport | Configuration Source | Role & Fail-Closed Contract |
| :--- | :--- | :--- | :--- |
| **Temporal Server** (`localhost:7233`, UI `:8233`) | gRPC via [`connection.py`](../../src/biosciences_temporal/temporal/connection.py) `connect` (`PydanticAIPlugin()`, `LogfirePlugin(metrics=False)`) | [`docker-compose.yml`](../../docker-compose.yml) (`temporalio/admin-tools:latest` running `temporal server start-dev`) | Polls task queue `biosciences-task-queue`. Isolated from other project queues on `:7233`. |
| **Sibling `biosciences-mcp` Gateway** (`src/biosciences_mcp/servers/gateway.py`) | JSON-RPC over OS `stdin`/`stdout` pipes (`MCPServerStdio`) | [`base.py`](../../src/biosciences_temporal/agents/base.py) `_find_sibling_repo`, `create_mcp_client` | Spawns `uv run fastmcp run src/biosciences_mcp/servers/gateway.py` in `BIOSCIENCES_MCP_PATH` (`../biosciences-mcp`) per activity (`timeout=120.0`). Fails fast with `FileNotFoundError` at import time if sibling checkout is missing. |
| **OpenRouter API & TypeSafe Jev** (`https://openrouter.ai/api/v1`) | HTTPS via `OpenRouterModel` / `FallbackModel` (and optional `TypeSafeModel`) | [`base.py`](../../src/biosciences_temporal/agents/base.py) `create_model` | Uses `nvidia/nemotron-3.5-lightning:free` primary and `openrouter/free` secondary (`USAGE_LIMITS = UsageLimits(request_limit=100)`), or falls back to `TestModel()` when `OPENROUTER_API_KEY` is unset. |
| **Pydantic Logfire** | OTLP HTTPS (`logfire.configure()`, `logfire.instrument_pydantic_ai()`, `LogfirePlugin(metrics=False)`) & SQL Read API (`LogfireQueryClient`) | [`connection.py`](../../src/biosciences_temporal/temporal/connection.py), [`run_agent.py`](../../src/biosciences_temporal/scripts/run_agent.py), [`run_worker.py`](../../src/biosciences_temporal/scripts/run_worker.py), [`query_logfire.py`](../../src/biosciences_temporal/scripts/query_logfire.py) | Links Temporal workflows, activities, and `AgentRunner` spans (`phase`, `action`, `entity_type`, `source`, `cq_id`) into a single trace and queries historical spans via `LOGFIRE_READ_TOKEN`. |

---

## 2. Library dependencies ([`pyproject.toml`](../../pyproject.toml))

The full list is extracted into [`docs/inspect.json`](../inspect.json) under `dependencies`.

| Package | Version Constraint | Role |
| :--- | :--- | :--- |
| `pydantic-ai[temporal]` | `>=1.42.0` | `Agent`, `MCPServerStdio`, `OpenRouterModel`, `FallbackModel`, `TestModel`, `PydanticAIPlugin`, `LogfirePlugin`, `UsageLimits` |
| `temporalio` | `>=1.5.0` | Workflow, activity, worker (`UnsandboxedWorkflowRunner`), and client runtime |
| `pydantic` | `>=2.0` | Structured output models (`agents/models.py`) |
| `logfire` | `>=4.18.0` | OpenTelemetry instrumentation and `LogfireQueryClient` |
| `httpx` | `>=0.27` | Async HTTP transport |
| `python-dotenv` | `>=1.0` | `.env` configuration loader (`load_dotenv(override=True)`) |
