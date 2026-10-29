# Phase 1: Component Inventory

The executable components of [`biosciences-temporal`](../../README.md): the Temporal workflow, activity wrappers, PydanticAI `AgentRunner` definitions, standalone orchestrator, models, and CLI scripts.

Names, registration, activity signatures, and `AgentRunner` metadata come from [`architecture_inventory.generated.json`](./architecture_inventory.generated.json). Connector configurations, JSON Schemas, and CLI script options come from [`docs/inspect.json`](../inspect.json). Regenerate both with `uv run python scripts/bt_diagram.py . write`.

---

## 1. Temporal workflows ([`workflows.py`](../../src/biosciences_temporal/temporal/workflows.py))

Registered in [`worker.py`](../../src/biosciences_temporal/temporal/worker.py) `main` on `TASK_QUEUE` (`biosciences-task-queue`), with `WORKFLOW_RUNNER` (`SandboxedWorkflowRunner`), and connected via [`connection.py`](../../src/biosciences_temporal/temporal/connection.py) `connect` (`plugins=[PydanticAIPlugin(), LogfirePlugin(setup_logfire=setup_logfire, metrics=False)]`).

| Workflow | Input | Activities, in order | Output | Activity configs ([`timeouts.py`](../../src/biosciences_temporal/config/timeouts.py)) |
| :--- | :--- | :--- | :--- | :--- |
| `CQ14Workflow` | `input_json: str` (parsed into `CQ14Input`) | Phase 1: `resolve_gene` (x2 parallel via `asyncio.gather`) → Phase 2: `enrich_protein` (parallel via `asyncio.gather`) → Phase 3: `expand_interactions` → Phase 4a: `find_drugs` → Phase 4b: `search_trials` → Phase 5: parallel `asyncio.gather` of `validate_gene`, `validate_mechanism`, `validate_trial`, `validate_synthetic_lethality` | `str` (`CQ14Result` serialized as JSON) | `SHORT_ACTIVITY_CONFIG` (3 min start-to-close, 10 min schedule-to-close, 3 attempts) for `resolve_gene`, `enrich_protein`, and all 4 validation activities; `LONG_ACTIVITY_CONFIG` (5 min start-to-close, 20 min schedule-to-close, 5 attempts) for `expand_interactions`, `find_drugs`, and `search_trials` |

- **Standalone non-Temporal orchestrator.** [`cq14.py`](../../src/biosciences_temporal/agents/cq14.py) defines `CQ14Orchestrator` and `CQ14Result`, which run the same 5-phase Fuzzy-to-Fact protocol directly in-process via [`run_agent.py`](../../src/biosciences_temporal/scripts/run_agent.py) without Temporal.

---

## 2. Activities ([`activities.py`](../../src/biosciences_temporal/temporal/activities.py))

All nine activities are exported in `ALL_ACTIVITIES` and registered by [`worker.py`](../../src/biosciences_temporal/temporal/worker.py). Each activity is a thin wrapper that awaits its corresponding agent function and serializes the Pydantic output with `model_dump()`.

| Activity | Phase | Input | Returns | Wrapped agent function |
| :--- | :--- | :--- | :--- | :--- |
| `resolve_gene` | 1 (Anchor) | `gene_symbol: str` | `dict` (`GeneInfo`) | [`resolve.py`](../../src/biosciences_temporal/agents/resolve.py) `resolve_gene` |
| `enrich_protein` | 2 (Enrich) | `uniprot_id: str` | `dict` (`ProteinFunction`) | [`enrich.py`](../../src/biosciences_temporal/agents/enrich.py) `enrich_protein` |
| `expand_interactions` | 3 (Expand) | `gene_symbol: str` | `dict` (`{"interactions": list[dict]}`) | [`expand.py`](../../src/biosciences_temporal/agents/expand.py) `expand_interactions` |
| `find_drugs` | 4a (Traverse) | `target_name: str` | `list[dict]` (`DrugCandidate` list) | [`drugs.py`](../../src/biosciences_temporal/agents/drugs.py) `find_drugs` |
| `search_trials` | 4b (Traverse) | `drug_name: str`, `condition: str = "cancer"` | `list[dict]` (`ClinicalTrial` list) | [`trials.py`](../../src/biosciences_temporal/agents/trials.py) `search_trials` |
| `validate_gene` | 5 (Validate) | `claim: str` | `dict` (`ValidationEvidence`) | [`validate.py`](../../src/biosciences_temporal/agents/validate.py) `validate_gene` |
| `validate_mechanism` | 5 (Validate) | `claim: str` | `dict` (`ValidationEvidence`) | [`validate.py`](../../src/biosciences_temporal/agents/validate.py) `validate_drug` |
| `validate_trial` | 5 (Validate) | `nct_id: str` | `dict` (`ValidationEvidence`) | [`validate.py`](../../src/biosciences_temporal/agents/validate.py) `validate_trial` |
| `validate_synthetic_lethality` | 5 (Validate) | `gene_a: str`, `gene_b: str` | `dict` (`ValidationEvidence`) | [`validate.py`](../../src/biosciences_temporal/agents/validate.py) `validate_synthetic_lethality` |

---

## 3. PydanticAI `AgentRunner` definitions ([`agents/`](../../src/biosciences_temporal/agents/))

[`base.py`](../../src/biosciences_temporal/agents/base.py) defines `AgentRunner[T]`, `AgentMetadata`, `create_mcp_client`, and `create_model`. Every `AgentMetadata` instance is checked against [`docs/metadata-spec.md`](../metadata-spec.md) by `bt_diagram.py check`.

| `AgentRunner` name | Module & variable | Output type | `phase` | `action` | `entity_type` | `source` |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `anchor_resolve` | [`resolve.py`](../../src/biosciences_temporal/agents/resolve.py) `_runner` | `GeneInfo` | `anchor` | `resolve` | `gene` | `HGNC` |
| `enrich_protein` | [`enrich.py`](../../src/biosciences_temporal/agents/enrich.py) `_runner` | `ProteinFunction` | `enrich` | `protein` | `protein` | `UniProt` |
| `expand_interactions` | [`expand.py`](../../src/biosciences_temporal/agents/expand.py) `_runner` | `list[GeneInteraction]` | `expand` | `interactions` | `interaction` | `STRING,BioGRID` |
| `traverse_drugs` | [`drugs.py`](../../src/biosciences_temporal/agents/drugs.py) `_runner` | `list[DrugCandidate]` | `traverse` | `drugs` | `compound` | `ChEMBL` |
| `traverse_trials` | [`trials.py`](../../src/biosciences_temporal/agents/trials.py) `_runner` | `list[ClinicalTrial]` | `traverse` | `trials` | `trial` | `ClinicalTrials.gov` |
| `validate_gene` | [`validate.py`](../../src/biosciences_temporal/agents/validate.py) `_gene_runner` | `ValidationEvidence` | `validate` | `gene` | `gene` | `HGNC` |
| `validate_drug` | [`validate.py`](../../src/biosciences_temporal/agents/validate.py) `_drug_runner` | `ValidationEvidence` | `validate` | `drug` | `compound` | `ChEMBL` |
| `validate_trial` | [`validate.py`](../../src/biosciences_temporal/agents/validate.py) `_trial_runner` | `ValidationEvidence` | `validate` | `trial` | `trial` | `ClinicalTrials.gov` |
| `validate_sl` | [`validate.py`](../../src/biosciences_temporal/agents/validate.py) `_sl_runner` | `ValidationEvidence` | `validate` | `sl` | `gene_pair` | `BioGRID` |

---

## 4. Models ([`models.py`](../../src/biosciences_temporal/agents/models.py))

| Phase | Model | Key fields |
| :--- | :--- | :--- |
| Phase 1 (Anchor) | `GeneInfo` | `hgnc_id`, `symbol`, `name`, `entrez_id`, `uniprot_id`, `ensembl_id` |
| Phase 2 (Enrich) | `ProteinFunction` | `uniprot_id`, `function_summary`, `keywords` |
| Phase 3 (Expand) | `GeneInteraction` | `partner_gene`, `interaction_type`, `evidence_source`, `score`, `pubmed_id` |
| Phase 4a (Traverse) | `DrugCandidate` | `chembl_id`, `name`, `target_name`, `mechanism`, `max_phase` |
| Phase 4b (Traverse) | `ClinicalTrial` | `nct_id`, `title`, `phase`, `status`, `conditions`, `interventions` |
| Phase 5 (Validate) | `ValidationEvidence` | `claim`, `verified`, `evidence_source`, `evidence_details`, `pubmed_ids` |

---

## 5. Entry points ([`scripts/`](../../src/biosciences_temporal/scripts/))

| Script | Module | Surface |
| :--- | :--- | :--- |
| `run_agent` | [`run_agent.py`](../../src/biosciences_temporal/scripts/run_agent.py) | Standalone execution via `CQ14Orchestrator` (`--gene-a`, `--gene-b`, `--output` / `-o`) |
| `run_worker` | [`run_worker.py`](../../src/biosciences_temporal/scripts/run_worker.py) | Configures Logfire and starts the Temporal worker ([`worker.py`](../../src/biosciences_temporal/temporal/worker.py) `main`) |
| `run_workflow` | [`run_workflow.py`](../../src/biosciences_temporal/scripts/run_workflow.py) | Starts or resumes `CQ14Workflow` via [`client.py`](../../src/biosciences_temporal/temporal/client.py) (`--gene-a`, `--gene-b`, `--target-name`, `--condition`, `-w` / `--workflow-id`, `--no-wait`) |
| `query_logfire` | [`query_logfire.py`](../../src/biosciences_temporal/scripts/query_logfire.py) | Queries Logfire spans via `LogfireQueryClient` (`--limit` / `-n`, `--sql`, `--type`, `--format`) |
