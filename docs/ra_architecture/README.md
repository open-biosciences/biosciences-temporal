# Reverse Architecture (RA) Suite: `biosciences-temporal`

Reverse-architecture documentation for [`biosciences-temporal`](../../README.md), grounded in the source code.

Scripts extract the facts; the prose here is written from them. `bt_diagram.py drift` fails when a generated file is stale, or when this suite doesn't mention a workflow, activity, `AgentRunner` name, or CLI script the code defines. `bt_diagram.py check` also verifies every `AgentMetadata` declaration against [`docs/metadata-spec.md`](../metadata-spec.md).

---

## Generated files

Regenerate them all with `uv run python scripts/bt_diagram.py . write`. Never edit them by hand.

| File | Produced by | Contents |
| :--- | :--- | :--- |
| [`architecture_inventory.generated.json`](./architecture_inventory.generated.json) | [`scripts/bt_diagram.py`](../../scripts/bt_diagram.py) `inventory` (stdlib `ast` and text parsing; imports nothing from the package) | Workflows, worker registration (`ALL_ACTIVITIES`), activities, and `AgentRunner` / `AgentMetadata` definitions |
| [`docs/inspect.json`](../inspect.json) | [`scripts/document_architecture.py`](../../scripts/document_architecture.py) (imports the package and introspects `AgentRunner`, Pydantic models, and CLI scripts) | All 9 `AgentRunner` contracts, Pydantic JSON Schemas, Pydantic AI Gateway & `MCPServerStdio` connector settings, ADR-001 retry error codes, and CLI scripts |
| [`02_architecture_diagrams.md`](./02_architecture_diagrams.md) §2 | `bt_diagram.py write`, between the generated markers | Flow and sequence diagram of `CQ14Workflow` |

---

## Document index

1. [**`01_component_inventory.md`**](./01_component_inventory.md): workflows, activities, `AgentRunner` definitions, standalone orchestrator (`CQ14Orchestrator`), models, and CLI entry points.
2. [**`02_architecture_diagrams.md`**](./02_architecture_diagrams.md): system topology, and the generated `CQ14Workflow` diagrams.
3. [**`03_data_flows.md`**](./03_data_flows.md): 5-phase Fuzzy-to-Fact data flow, one-shot `MCPServerStdio` lifecycle, Pydantic AI Gateway routing, and `AgentMetadata` Logfire attribution.
4. [**`04_api_reference.md`**](./04_api_reference.md): CLI scripts, Temporal client helpers, Pydantic output schemas, and environment variables.
5. [**`05_control_and_data_plane_phases.md`**](./05_control_and_data_plane_phases.md): architectural invariants, ADR-001 retry policies, `anyio` cancel-scope isolation, and trace-linking gap analysis.
6. [**`06_dependencies_and_service_topology.md`**](./06_dependencies_and_service_topology.md): sibling `biosciences-mcp` gateway server, Pydantic AI Gateway, Logfire, Docker Compose stack, and library dependencies.
7. [**`AGENTS.md`**](./AGENTS.md): the protocol for updating this suite.
