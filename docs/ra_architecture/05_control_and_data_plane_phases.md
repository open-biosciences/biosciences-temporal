# Phase 5: Control and Data Plane Invariants

The architectural invariants, ADR-001 retry policies, and verification checks of [`biosciences-temporal`](../../README.md).

---

## 1. Core architectural invariants

| # | Invariant | Enforcement Mechanism |
| :--- | :--- | :--- |
| **1** | **PydanticAI First, Temporal Second** | All 9 `AgentRunner` agents ([`agents/`](../../src/biosciences_temporal/agents/)) have zero Temporal imports and can execute standalone via [`CQ14Orchestrator`](../../src/biosciences_temporal/agents/cq14.py) (`run_agent`). Temporal activities ([`activities.py`](../../src/biosciences_temporal/temporal/activities.py)) are thin wrappers that await the agent function and call `model_dump()`. |
| **2** | **One-Shot Activity-Scoped MCP Lifecycle** | [`base.py`](../../src/biosciences_temporal/agents/base.py) `AgentRunner.run` creates a fresh `MCPServerStdio` instance and enters/exits `async with mcp:` inside a single activity call, preventing `anyio` cancel-scope cross-task violations (`RuntimeError: Attempted to exit cancel scope in a different task`). |
| **3** | **ADR-001 Fail-Fast Retry Policy** | [`retry_policies.py`](../../src/biosciences_temporal/config/retry_policies.py) configures `NON_RETRYABLE_ERRORS = ["UNRESOLVED_ENTITY", "AMBIGUOUS_QUERY", "ENTITY_NOT_FOUND", "ValidationError"]` on both `SHORT_ACTIVITY_RETRY` (3 attempts, 2 s→1 min) and `LONG_ACTIVITY_RETRY` (5 attempts, 5 s→3 min) so Fuzzy-to-Fact protocol violations fail immediately without wasted retries. |
| **4** | **Zero-Token-Spend OpenRouter Free Tier & Offline Fallback** | [`base.py`](../../src/biosciences_temporal/agents/base.py) `create_model` chains `OpenRouterModel(OPENROUTER_FREE_MODEL)` (`nvidia/nemotron-3.5-lightning:free`) and `OpenRouterModel(OPENROUTER_FALLBACK_MODEL)` (`openrouter/free`) behind `FallbackModel` (with optional `TypeSafeModel` when `TYPESAFE_API_KEY` is set) and falls back to `TestModel()` when offline. |
| **5** | **Logfire Metadata Taxonomy Compliance** | [`scripts/bt_diagram.py`](../../scripts/bt_diagram.py) `check` parses [`docs/metadata-spec.md`](../metadata-spec.md) and verifies that every `AgentRunner`'s `AgentMetadata` (`phase`, `action`, `entity_type`, `source`) uses only valid taxonomy values. |
| **6** | **Architecture & AST Drift Ratchet** | [`scripts/bt_diagram.py`](../../scripts/bt_diagram.py) `check` and `drift` and [`scripts/document_architecture.py`](../../scripts/document_architecture.py) `--check` verify that `ALL_ACTIVITIES` matches workflow calls and `@activity.defn` definitions, every activity call has a timeout, generated diagrams and JSON contracts are fresh, and every component/CLI script is documented in `docs/ra_architecture/`. |

---

## 2. Single-trace Logfire observability across Temporal and PydanticAI ([`connection.py`](../../src/biosciences_temporal/temporal/connection.py))

[`connection.py`](../../src/biosciences_temporal/temporal/connection.py) `connect` attaches `plugins=[PydanticAIPlugin(), LogfirePlugin(metrics=False)]` to `Client.connect(address)`, shared by [`worker.py`](../../src/biosciences_temporal/temporal/worker.py) and [`client.py`](../../src/biosciences_temporal/temporal/client.py). Combined with `logfire.configure(...)` and `logfire.instrument_pydantic_ai()` in [`run_worker.py`](../../src/biosciences_temporal/scripts/run_worker.py) and [`run_workflow.py`](../../src/biosciences_temporal/scripts/run_workflow.py), all 5 CQ14 workflow phases, activity executions, and `AgentRunner` runs nest under a single unified Logfire trace without requiring the Logfire AI Gateway proxy.

---

## 3. Deterministic workflow sandboxing (`SandboxedWorkflowRunner`) ([`worker.py`](../../src/biosciences_temporal/temporal/worker.py))

[`worker.py`](../../src/biosciences_temporal/temporal/worker.py) defines `WORKFLOW_RUNNER = SandboxedWorkflowRunner(restrictions=SandboxRestrictions.default.with_passthrough_modules("biosciences_temporal.config", "beartype"))` and passes `workflow_runner=WORKFLOW_RUNNER` to `Worker(...)`:
- **Package isolation**: [`__init__.py`](../../src/biosciences_temporal/__init__.py) and [`temporal/__init__.py`](../../src/biosciences_temporal/temporal/__init__.py) have empty `__all__: list[str] = []` so importing `biosciences_temporal.temporal.workflows` inside the sandbox never triggers eager agent/MCP imports.
- **Explicit passthroughs**: [`workflows.py`](../../src/biosciences_temporal/temporal/workflows.py) wraps `from ..config import LONG_ACTIVITY_CONFIG, SHORT_ACTIVITY_CONFIG` in `with workflow.unsafe.imports_passed_through():`, and `PydanticAIPlugin` (`connection.py`) automatically adds passthroughs for `pydantic_ai`, `pydantic`, `logfire`, `httpx`, `anyio`, `sniffio`, `fastmcp`, `mcp`, and `beartype`.
- **Verification**: [`tests/test_model_and_runner.py`](../../tests/test_model_and_runner.py) verifies `WORKFLOW_RUNNER.prepare_workflow` on `CQ14Workflow` in the unit test suite.
