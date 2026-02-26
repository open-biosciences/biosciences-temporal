"""
CQ14 Temporal Module: Durable execution of synthetic lethality validation.

This module implements the 5-phase Fuzzy-to-Fact protocol for validating
synthetic lethality claims using PydanticAI agents with MCP toolsets.

## Package Structure

```
biosciences_temporal/
├── agents/         # PydanticAI agents (can run standalone)
│   ├── models.py   # Shared Pydantic models
│   ├── resolve.py  # Gene resolution agent
│   ├── enrich.py   # Protein enrichment agent
│   ├── expand.py   # Interaction network agent
│   ├── drugs.py    # Drug discovery agent
│   ├── trials.py   # Clinical trials agent
│   ├── validate.py # Validation agents
│   └── cq14.py     # Orchestrated workflow
│
├── temporal/       # Temporal-specific code
│   ├── activities.py  # Thin wrappers around agents
│   ├── workflows.py   # Workflow definitions
│   ├── worker.py      # Worker configuration
│   └── client.py      # Workflow trigger/resume
│
├── config/         # Configuration
│   ├── timeouts.py    # Activity timeouts
│   └── retry_policies.py  # Retry configuration
│
└── scripts/        # Entry points
    ├── run_agent.py   # Run standalone (no Temporal)
    ├── run_worker.py  # Start Temporal worker
    └── run_workflow.py  # Trigger Temporal workflow
```

## Usage

### Standalone (no Temporal)
```bash
uv run python -m src.biosciences_temporal.scripts.run_agent
```

### With Temporal
```bash
# Terminal 1: Start worker
uv run python -m src.biosciences_temporal.scripts.run_worker

# Terminal 2: Trigger workflow
uv run python -m src.biosciences_temporal.scripts.run_workflow
```

IMPORTANT: Do not add imports here - they trigger Temporal sandbox restrictions.
Import directly from the specific module you need.
"""

# No imports here to avoid Temporal sandbox conflicts with pydantic_ai/anyio
# Import directly from the specific modules:
#
# Agents (standalone):
#   from src.biosciences_temporal.agents.cq14 import CQ14Orchestrator
#   from src.biosciences_temporal.agents import GeneInfo, DrugCandidate, ...
#
# Temporal:
#   from src.biosciences_temporal.temporal.workflows import CQ14Workflow
#   from src.biosciences_temporal.temporal.activities import ALL_ACTIVITIES

__all__: list[str] = []  # Explicit empty exports to encourage direct imports
