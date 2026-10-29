# Phase 2: Architecture Diagrams

The system topology of [`biosciences-temporal`](../../README.md), and the flow and sequence diagram of `CQ14Workflow`.

- **§1 is written by hand.** Its names are checked by `bt_diagram.py drift`'s coverage check.
- **§2 is generated.** [`scripts/bt_diagram.py`](../../scripts/bt_diagram.py) reverse-engineers it from the source with `ast`; `write` refills it and `drift` fails when it is stale. Don't edit between the markers.

---

## 1. System topology and process boundaries

```mermaid
flowchart TD
    subgraph CLI ["Operator Entry Points (scripts/)"]
        RA["run_agent<br/>(standalone CQ14Orchestrator)"]
        RWF["run_workflow<br/>(start_workflow / get_result)"]
        RWK["run_worker<br/>(Logfire + Temporal Worker)"]
        QL["query_logfire<br/>(LogfireQueryClient)"]
    end

    subgraph Temporal ["Temporal Server (:7233, UI :8233)"]
        TQ["Task Queue: biosciences-task-queue"]
    end

    subgraph Worker ["Temporal Worker (SandboxedWorkflowRunner)"]
        WF["CQ14Workflow<br/>(5-Phase Fuzzy-to-Fact Protocol)"]
        ACT["ALL_ACTIVITIES<br/>(resolve_gene, enrich_protein, expand_interactions,<br/>find_drugs, search_trials, validate_gene,<br/>validate_mechanism, validate_trial,<br/>validate_synthetic_lethality)"]
        RUN["AgentRunner[T] (agents/base.py)<br/>(anchor_resolve, enrich_protein, expand_interactions,<br/>traverse_drugs, traverse_trials, validate_gene,<br/>validate_drug, validate_trial, validate_sl)"]
        WF --> ACT
        ACT --> RUN
    end

    subgraph Connectors ["External & Sibling Connectors"]
        OR["OpenRouter Free Tier & TypeSafe<br/>(nvidia/nemotron-3.5-lightning:free<br/>fallback: openrouter/free / TestModel)"]
        MCP["Sibling biosciences-mcp<br/>(MCPServerStdio: uv run fastmcp run<br/>src/biosciences_mcp/servers/gateway.py)"]
        APIS["Upstream Biological Databases<br/>(HGNC, UniProt, STRING, BioGRID,<br/>ChEMBL, ClinicalTrials.gov)"]
        LF["Pydantic Logfire<br/>(LogfirePlugin + AgentMetadata: phase, action, entity_type, source, cq_id)"]
    end

    RWF -->|start / resume| TQ
    RWK --> Worker
    TQ <-->|poll tasks & record events| Worker
    RA -->|in-process| RUN
    RUN -->|OpenRouterModel / FallbackModel| OR
    RUN -->|one-shot stdio subprocess per activity| MCP
    MCP --> APIS
    RUN -->|instrument_pydantic_ai spans| LF
    QL -->|SQL query API| LF
```

---

## 2. Workflow diagrams (generated)

<!-- BEGIN GENERATED: scripts/bt_diagram.py write; do not edit by hand -->
### `CQ14Workflow`

```mermaid
flowchart TD
    start(["CQ14Workflow.run(input_json: str)"])
    s0["Phase 1: Anchor<br/><b>resolve_gene</b><br/>timeout timedelta(minutes=3)<br/><i>asyncio.gather · agent:resolve_gene · model:create_model() · fault-tolerant</i>"]:::fanout
    start --> s0
    s1["Phase 2: Enrich<br/><b>enrich_protein</b><br/>timeout timedelta(minutes=3)<br/><i>asyncio.gather · agent:enrich_protein · model:create_model() · fault-tolerant</i>"]:::fanout
    s0 --> s1
    s2["Phase 3: Expand<br/><b>expand_interactions</b><br/>timeout timedelta(minutes=5)<br/><i>agent:expand_interactions · model:create_model() · fault-tolerant</i>"]:::activity
    s1 --> s2
    s3["Phase 4a: Traverse<br/><b>find_drugs</b><br/>timeout timedelta(minutes=5)<br/><i>agent:find_drugs · model:create_model() · fault-tolerant</i>"]:::activity
    s2 --> s3
    s4["Phase 4b: Traverse<br/><b>search_trials</b><br/>timeout timedelta(minutes=5)<br/><i>agent:search_trials · model:create_model() · fault-tolerant</i>"]:::activity
    s3 --> s4
    s5["Phase 5: Validate<br/><b>validate_gene</b><br/>timeout timedelta(minutes=3)<br/><i>asyncio.gather · agent:validate_gene · model:create_model() · fault-tolerant</i>"]:::fanout
    s4 --> s5
    s6["Phase 5: Validate<br/><b>validate_mechanism</b><br/>timeout timedelta(minutes=3)<br/><i>asyncio.gather · agent:validate_drug · model:create_model() · fault-tolerant</i>"]:::fanout
    s5 --> s6
    s7["Phase 5: Validate<br/><b>validate_trial</b><br/>timeout timedelta(minutes=3)<br/><i>asyncio.gather · agent:validate_trial · model:create_model() · fault-tolerant</i>"]:::fanout
    s6 --> s7
    s8["Phase 5: Validate<br/><b>validate_synthetic_lethality</b><br/>timeout timedelta(minutes=3)<br/><i>asyncio.gather · agent:validate_synthetic_lethality · model:create_model() · fault-tolerant</i>"]:::fanout
    s7 --> s8
    done(["return CQ14Result JSON"])
    s8 -->|complete| done
    classDef activity fill:#e8f0fe,stroke:#3b6fd8
    classDef fanout fill:#e6f4ea,stroke:#137333,stroke-width:2px
```

```mermaid
sequenceDiagram
    participant C as run_workflow / Client
    participant W as CQ14Workflow
    participant A as Activities (one-shot MCP)
    participant AG as PydanticAI AgentRunner (OpenRouter / TypeSafe)
    participant MCP as biosciences-mcp (stdio)
    C->>W: run(input_json: str)
    Note over W: Phase 1: Anchor - Resolve both genes in parallel
    par asyncio.gather(resolve_gene)
        W->>A: resolve_gene(input_data.gene_a)
        A->>AG: resolve_gene(...)
        AG->>MCP: MCPServerStdio tool calls
        MCP-->>AG: CURIE / Biolink records
        A-->>W: dict
    end
    Note over W: Phase 2: Enrich - Get protein context
    par asyncio.gather(enrich_protein)
        W->>A: enrich_protein(result.gene_a_resolution['uniprot_id'])
        A->>AG: enrich_protein(...)
        AG->>MCP: MCPServerStdio tool calls
        MCP-->>AG: CURIE / Biolink records
        A-->>W: dict
    end
    Note over W: Phase 3: Expand - Get interactions for target gene
    W->>A: expand_interactions(input_data.gene_b)
    A->>AG: expand_interactions(...)
    AG->>MCP: MCPServerStdio tool calls
    MCP-->>AG: CURIE / Biolink records
    A-->>W: dict
    Note over W: Phase 4a: Traverse - Find drugs targeting the protein
    W->>A: find_drugs(input_data.target_name)
    A->>AG: find_drugs(...)
    AG->>MCP: MCPServerStdio tool calls
    MCP-->>AG: CURIE / Biolink records
    A-->>W: list[dict]
    Note over W: Phase 4b: Traverse - Search clinical trials using discovered drug names
    W->>A: search_trials(drug_name, input_data.condition)
    A->>AG: search_trials(...)
    AG->>MCP: MCPServerStdio tool calls
    MCP-->>AG: CURIE / Biolink records
    A-->>W: list[dict]
    Note over W: Phase 5: Validate - Run validators in parallel
    par asyncio.gather(validate_gene)
        W->>A: validate_gene(claim)
        A->>AG: validate_gene(...)
        AG->>MCP: MCPServerStdio tool calls
        MCP-->>AG: CURIE / Biolink records
        A-->>W: dict
    end
    par asyncio.gather(validate_mechanism)
        W->>A: validate_mechanism(claim)
        A->>AG: validate_drug(...)
        AG->>MCP: MCPServerStdio tool calls
        MCP-->>AG: CURIE / Biolink records
        A-->>W: dict
    end
    par asyncio.gather(validate_trial)
        W->>A: validate_trial(result.trials[0].get('nct_id', ''))
        A->>AG: validate_trial(...)
        AG->>MCP: MCPServerStdio tool calls
        MCP-->>AG: CURIE / Biolink records
        A-->>W: dict
    end
    par asyncio.gather(validate_synthetic_lethality)
        W->>A: validate_synthetic_lethality(input_data.gene_a, input_data.gene_b)
        A->>AG: validate_synthetic_lethality(...)
        AG->>MCP: MCPServerStdio tool calls
        MCP-->>AG: CURIE / Biolink records
        A-->>W: dict
    end
    W-->>C: CQ14Result JSON
```
<!-- END GENERATED -->
