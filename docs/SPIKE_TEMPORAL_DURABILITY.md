# Spike: Pydantic AI `TemporalDurability` (2026-10-21)

**Question:** Can the anchor/resolve agent run as a durable agent inside the
workflow (each model request and each MCP call its own activity) without the
MCP cancel-scope bug documented in `docs/TEMPORAL_MCP_STATUS.md`?

**Answer:** Yes, for the resolve agent on pydantic-ai 2.59.0 / temporalio 1.34.0.

## What changed on this branch

| File | Change |
|------|--------|
| `pyproject.toml` | `pydantic-ai[temporal]>=2.59.0`; `anthropic>=1.12.1,<2` (see below) |
| `agents/base.py` | `MCPServerStdio` (removed in 2.x) → `MCPToolset` + FastMCP `StdioTransport`; `create_model(max_retries=...)`; drops `VIRTUAL_ENV` from the MCP subprocess env |
| `spike/durable_resolve.py` | Agent with `TemporalDurability`, `DurableResolveWorkflow(PydanticAIWorkflow)` |
| `scripts/run_spike.py` | In-process worker (`PydanticAIPlugin` + `LogfirePlugin`, default **sandboxed** runner), runs the workflow, summarizes activity history |

Built on the uncommitted `feat/pydantic-ai-gateway` work (gateway model, dotenv loading).

## Results

Local Temporal (`localhost:7233`), Claude Sonnet 5 through the Pydantic AI Gateway.

| Run | Genes | MCP subprocess | Activities (model / get_tools / call_tool) | Failures | Wall |
|-----|-------|----------------|---------------------------------------------|----------|------|
| 1 | TP53, TYMS | fresh per activity | 6 / 2 / 4 | 0 | — |
| 2 | TP53, TYMS, BRCA1 | fresh per activity (9 starts) | 9 / 3 / 6 | 0 | 49s |
| 3 | TP53, TYMS, BRCA1 | `--keep-alive` (1 start) | 9 / 3 / 6 | 0 | 26s |

No `cancel scope` errors in any run. The default sandboxed workflow runner worked;
`UnsandboxedWorkflowRunner` was not needed. The existing one-shot path
(`resolve_gene` via `AgentRunner`) still works on 2.x with the ported `create_mcp_client()`.

## Crash and resume

`scripts/spike_crash_resume.py` runs the worker as a separate process, SIGKILLs its
process group mid-workflow, keeps it down 10s, starts a fresh worker, then checks
the history and replays it with `Replayer` (pattern from temporalio/samples-python
`replay/`). Model requests and MCP tool calls are counted per HTTP attempt
(`spike/call_log.py`). Baseline: `spike/oneshot_resolve.py`, the current pattern
(one `resolve_gene` activity per gene, repo `SHORT_ACTIVITY_CONFIG`), same branch
and library versions.

Five runs in parallel (own task queues), genes TP53/TYMS/BRCA1, killed when the
5th model request was sent (TYMS's 2nd request in flight; TP53 done):

| Run | Recovery after kill | Activities | Model requests (uncrashed: 9) | MCP calls (uncrashed: 6) | Replay |
|-----|--------------------:|-----------:|------------------------------:|-------------------------:|--------|
| durable, fresh subprocess ×2 | 53s, 53s | 18 | 10 (1 repeated) | 6 (0 repeated) | OK |
| durable, keep-alive | 43s | 18 | 10 (1 repeated) | 6 (0 repeated) | OK |
| one-shot ×2 | 193s, 195s | 3 | 11 (2 repeated) | 7 (1 repeated) | OK |

All runs: no progress while the worker was down, all three genes correct, no
orphaned MCP processes.

- Durable repeats only the request that was in flight. One-shot repeats the whole
  in-flight agent run (here TYMS's first request and tool call, plus the in-flight
  request); the cost grows with how far that run had progressed.
- Recovery time is mostly timeout config, not the pattern: the durable model
  activity has a 30s heartbeat timeout, the one-shot activity has none, so the
  crash is detected only at `start_to_close` (3 min).

Kill-point variants on the durable pattern (sequential runs, 3 genes):

| Kill during | Tool activity heartbeat timeout | Recovery | Retried |
|-------------|--------------------------------|---------:|---------|
| model request | (model default 30s) | 60s | 1 model_request |
| MCP tool call | none (Pydantic AI default) | 148s | 1 call_tool |
| MCP tool call | 30s (set in `activity_config`) | 54s | 1 call_tool |

## Anchor and Enrich without an LLM

`deterministic/` calls biosciences-mcp tools directly and returns the same models
as the agents. Anchor: `hgnc_search_genes` → `hgnc_get_gene`, choosing by HGNC's
symbol-checker precedence (approved → previous → alias symbol); a tie raises
`AmbiguousGeneSymbol`. Enrich: `uniprot_get_protein`, FUNCTION text verbatim minus
PubMed citations. `spike/plain_anchor_enrich.py` runs them as plain Temporal
activities and falls back to the resolve agent only for an ambiguous symbol.

Agent vs plain, 12 queries, run once each (`scripts/spike_compare_anchor_enrich.py`):

| | Agent (resolve + enrich) | Plain |
|---|---|---|
| IDs (hgnc, symbol, entrez, uniprot, ensembl) | — | identical on all 11 real genes, incl. aliases (p53, HER2, ALL1) and previous symbols (MLL, SEPT9) |
| Time per gene | 18.6–26.3s | 6.9–9.8s (mostly two MCP subprocess starts) |
| Model requests per gene | 5 | 0 |
| Unknown symbol (XYZNOTAGENE) | returned `GeneInfo(hgnc_id="NOT_FOUND", ...)`: schema-valid, reads as success | raises `GeneNotFound` |
| Function summary | paraphrase (similarity to UniProt text 0.09–0.47) | UniProt text verbatim |
| Keywords | 5 per gene, model-generated (the tool returns none) | empty |

Temporal run (`--temporal`), 8 queries in parallel: 20s total. TP53/TYMS approved,
p53/HER2 alias, MLL/MSF previous symbol, XYZNOTAGENE failed as `GeneNotFound`, and
CAP was ambiguous at the alias tier so it went to the agent, which picked CAP1
(HGNC:20040); that choice depends on context and was not checked.

The agent's `NOT_FOUND` result for an unknown symbol is tracked as Linear AGE-743.

## Phase 3 EXPAND loop and the pre-emit gate (no LLM)

Mapped to the canonical ladder in
`biosciences-program/docs/diagrams/ob-research-graph-build.md` and the
graph-builder skill (Phase 3 + secondary enrichment, Phase 6a gate).

- `GeneInfo.location` added (the gate requires it); plain Anchor now LOCATEs with
  `slim=true, page_size=5` as the skill specifies.
- `deterministic/expand.py`: `expand_gene` (STRING partners at score ≥ 0.7, ranked,
  top N; BioGRID Negative Genetic / Synthetic Lethality edges) and
  `enrich_gene_node` (hgnc_search_genes → hgnc_get_gene → wikipathways_get_pathways_for_gene).
- `spike/plain_expand.py`: `ExpandWorkflow` expands seeds one at a time (STRING
  1 req/s), enriches every node in parallel (worker `max_concurrent_activities=8`),
  keeps BioGRID SL edges only between existing nodes, and runs the gate.

CQ14 pair (`--seeds TP53 TYMS`, top 25 STRING partners each):

| | Result |
|---|---|
| Run | 52s, 2 expand + 52 enrich activities, 0 model requests |
| Graph | 52 Gene nodes, 50 STRING edges, 2 BioGRID annotation edges |
| Pre-emit gate | PASS: every node has symbol, name, Ensembl, UniProt, location; 50/52 have WikiPathways membership |
| Key evidence | TP53–TYMS Negative Genetic (PMID:35559673), TYMS–CHEK1 (PMID:28319113) |
| TP53 partners kept | ATM, ATR, CHEK1, CHEK2, MDM2, MDM4, CDKN1A, EP300, USP7, … |
| vs `cq14edgefix` KG (7 partners) | 3 found (ATR, CHEK1, MDM2); PLK1 (0.992), PPM1D (0.999), WEE1 (0.822) are STRING ≥ 0.7 but outside the top 25; POLQ is below 0.7 |

Earlier run with BioGRID SL partners added as nodes: 208 nodes, 155s, gate FAIL on
FAM47E-STBD1 (readthrough locus, no UniProt), 3 unresolvable BioGRID symbols
(LOC554223, PRO1596, C18ORF21), and 0/7 reference partners.

What this shows: fetching, enrichment, the loop and the gate are mechanical.
Choosing *which* partners matter for a hub gene is not: STRING ≥ 0.7 admits 872
TP53 partners, BioGRID SL evidence is mostly screen data (216 edges for the two
seeds), and the reference KG's partners came from CRISPR screens and literature.
`ExpandInput.include` is where a question-specific or agent-chosen partner list
enters. Node-selection and gate rules are an open question: open-biosciences-plugins#32.

## Both MCP servers, and deterministic edges

The bio-research plugin connects to two servers (`bio-research/.mcp.json`):
`biosciences-mcp` (12-database gateway) and `biosciences-mcp-edge` (BioGRID ORCS
essentiality, ChEMBL mechanism of action). `agents/base.py` now knows both
(`MCP_SERVERS`), and `BIOSCIENCES_MCP_TRANSPORT` picks `stdio` (local repos,
default; `BIOSCIENCES_MCP_EDGE_PATH` for the edge repo) or `http` (the plugin's
hosted endpoints, `BIOSCIENCES_API_KEY`). Both transports tested against both
servers; hosted was slower in a single test (10.2s / 5.4s, possibly cold start).

**ORCS is node evidence, not a selection rule.** WEE1 is a hit in 882 screens, the
exact figure the `cq14edgefix` KG cites. But GAPDH has 670 and TYMS 352: hit
counts measure how broadly a gene is essential, and `cell_line`/`phenotype` come
back null, so TP53-mutant specificity can't be read from this tool.

**Edges among a known node set are one deterministic call.** BioGRID REST
`/interactions` with `geneList=A|B|…`, `includeInteractors=false`, and
`evidenceList` + `includeEvidence=true` (without the latter, `evidenceList`
*excludes* the listed systems) returns only interactions among the listed genes,
each with experimental system, throughput and PMID. For the `cq14edgefix` genes
plus TYMS (9 genes): 725 interaction records across 15 of 36 pairs; filtered to
Negative Genetic / Synthetic Lethality, 4 pairs:

| Pair | System | PMID |
|------|--------|------|
| TP53–TYMS | Negative Genetic (HTP) | 35559673 |
| CHEK1–TYMS | Negative Genetic (HTP) | 28319113 |
| CHEK1–WEE1 | Synthetic Lethality (HTP) | 27453043 |
| CHEK1–ATR | Synthetic Lethality (HTP) | 27453043 |

The KG's LLM-built `TP53 –SYNTHETIC_LETHAL–` WEE1 / CHEK1 / PLK1 / POLQ / ATR edges
have no BioGRID genetic-interaction record (they cite Feng 2022 and ORCS; the
pairs have physical-interaction records only, POLQ none). The deterministic
query keeps that distinction: each edge says what kind of evidence backs it.
The `biogrid_get_interactions` MCP tool takes one gene and doesn't pass
`geneList`/`includeInteractors`/`evidenceList` through, so this needs a new
tool (for example in biosciences-mcp-edge). Tracked as Linear AGE-742.

## Gold-standard baseline (CQ dataset)

`scripts/spike_gold_baseline.py` scores the deterministic phases against
`open-biosciences/biosciences-competency-questions-sample` (revision
`4fd7a86d`, 15 CQs). Labels: the 21 distinct gene entities (`key_entities`
with an HGNC CURIE) and the 9 gene-gene `biolink_edges`.

**Anchor (plain resolver): 21/21 EXACT.** 20 by approved symbol; `hERG/KCNH2`
resolved after splitting the name, via the `hERG` alias.

**Expand (retrieval of the gold partner from either end):**

| Metric | STRING order | Evidence tie-break |
|---|---:|---:|
| recall@pool (STRING >= 0.7) | 8/9 | 8/9 |
| recall@10 | 3/9 | 4/9 |
| recall@25 | 4/9 | 4/9 |
| recall@100 | 7/9 | 7/9 |

| CQ | Gold edge | Predicate | Rank (STRING / evidence) | BioGRID systems for the pair |
|---|---|---|---|---|
| cq1 | RARG → ACVR1 | regulates | not in pool | none |
| cq3 | APP → PSEN1 | interacts_with | 2 / 6 | Affinity Capture-Western, FRET, Two-hybrid |
| cq4 | BACE1 → APP | affects | 1 / 1 | Affinity Capture-Western, Biochemical Activity |
| cq6 | E2F1 → BRCA1 | positively_regulates | 50 / 50 | Affinity Capture-Western |
| cq6 | SP1 → BRCA1 | positively_regulates | 70 / 70 | Affinity Capture-Western, Reconstituted Complex |
| cq6 | BRCA1 → RAD51 | regulates | 11 / 1 | physical only (RAD51's own BioGRID call failed) |
| cq8 | ARID1A → EZH2 | genetically_interacts_with | 33 / 33 | physical only |
| cq11 | MDM2 → TP53 | negatively_regulates | 5 / 5 | physical only |
| cq14 | TP53 → TYMS | genetically_interacts_with | 101 / 101 | Negative Genetic |

What the features show:

- **Anchor needs no LLM on the gold set.** Name normalization (`hERG/KCNH2`) is the only rule beyond HGNC precedence.
- **The STRING pool has high recall (8/9); a top-25 budget does not (4/9).** Gold partners sit anywhere from rank 1 to 101. The one pool miss (cq1, a DrugMechDB regulatory edge) has no STRING or BioGRID record at all: it needs a different source, not a better ranker.
- **The evidence tie-break helps only where ties decide** (BRCA1-RAD51: 11 → 1); elsewhere the two orders agree.
- **Predicates aren't in the pool data.** STRING and BioGRID give undirected association; the gold `regulates` / `positively_regulates` / `negatively_regulates` direction comes from elsewhere. The genetic predicate is supported by BioGRID for cq14 (Negative Genetic) but not cq8 (physical records only).
- **Tool defect found:** `biogrid_get_interactions("RAD51")` fails entirely (`UPSTREAM_ERROR`) because one upstream record's symbol (`BRCA2(IV)`) fails the server's symbol validation. Tracked as Linear AGE-745.
- **Gold-data wording:** cq14's workflow text says "1,446 screens confirm TYMS essentiality"; ORCS reports 1,446 screens in total (`hit_only=False`) and 352 hits. Tracked as
  open-biosciences/biosciences-research#9.

Caveats: 9 edges is a small label set, and this measures retrieving a known pair
from one end, not open discovery. Results were written to a scratch directory,
not the CQ runner's `.ob-cq/` layout.

## Reranking experiment (feature ablation)

`scripts/spike_rerank_experiment.py`: same 9 gold edges and STRING pools as the
baseline (pool sizes 14 to 872), each candidate carrying STRING sub-scores and
BioGRID record counts with the seed. No weights fitted to the labels. Best of
either end, as in the baseline.

| Ranker | recall@10 | recall@25 |
|---|---:|---:|
| STRING order (baseline) | 3/9 | 4/9 |
| Evidence tie-break (baseline) | 4/9 | 4/9 |
| Experimental score (`escore`) | 4/9 | 5/9 |
| Database score (`dscore`) | 3/9 | 3/9 |
| Text-mining score (`tscore`) | 4/9 | 4/9 |
| BioGRID record count with the seed | 5/9 | **6/9** |
| BioGRID low-throughput count | 4/9 | 5/9 |
| LLM, anonymized (features only, opaque IDs) | 4/9 | 5/9 |
| LLM, named (symbols + features + CQ question) | **7/9** | **7/9** |

Reading it:

- **Best single deterministic feature: BioGRID record count** (6/9 at 25), then the
  experimental score (5/9). Both beat STRING's combined score (4/9), which mixes in
  text mining and co-expression. TP53-TYMS moves from rank 101 to 9 (BioGRID) or 11
  (`escore`).
- **The LLM given only features doesn't beat one deterministic feature** (5/9 vs 6/9).
- **The named LLM's 7/9 is confounded.** In cq6, cq8, cq11 and cq14 the question
  names one gene of the pair (BRCA1, ARID1A, MDM2, TP53), and the model can recover
  the pair from the other end by ranking the named gene first (e.g. TP53 at #1 in
  TYMS's pool). Its two hits on unflagged edges (cq3, cq4) were already rank 1-2 by
  STRING. It missed BRCA1-RAD51, which the evidence tie-break ranks #1.
- **The gold set measures connecting named entities, not discovery.** Every gold
  gene-gene edge joins two of the CQ's own `key_entities`. A deterministic
  "other anchored entity" feature (or the among-set edge query, AGE-742) would put
  the 8 pooled partners in the top 10 by construction, with no LLM. Evaluating
  partner *discovery* needs labels outside the question, e.g. the Feng et al. SL
  pairs the cq14 catalog entry cites (`dwb2023/sl_gene_pairs`, 209 pairs).

## Discovery benchmark (Feng et al. SL pairs), AGE-746

`scripts/spike_discovery_benchmark.py`. Labels: `dwb2023/sl_gene_pairs` (revision
`2e47c9d0`), 209 synthetic-lethal pairs across 13 knocked-out tumour suppressors
(LKB1 resolved to STK11). Question per seed: "Which genes are synthetic lethal with
loss of {seed}?" Pool: the seed's STRING partners at ≥ 0.7 (40 to 872 candidates).
BioGRID features exclude PMID 35559673 (the Feng paper).

| | Labels |
|---|---:|
| Total | 209 |
| In the seed's STRING ≥ 0.7 pool | **4** |
| With a BioGRID record from the Feng paper itself (PMID 35559673) | 205 |
| With SL-type BioGRID evidence from any other paper | **1** |
| With any BioGRID record from another paper | 11 |

| Ranker (pooled over 13 seeds) | recall@25 | recall@100 |
|---|---:|---:|
| Random ordering of the pool (expected) | 0.3 | 1.1 |
| STRING order | 0 | 1 |
| Best held-out feature (`dscore`) | 0 | 2 |
| LLM, named | 0 | 2 |
| LLM, anonymized | 0 | 0 |
| BioGRID including the Feng PMID (leaky, not valid) | 0 | 3 |

What it shows:

- **The STRING pool is the wrong retriever for synthetic lethality: 4/209 labels
  (1.9%).** SL partners are functional (genetic) relationships, not physical
  interactors. No reranker can recover what the pool doesn't contain.
- **The rerankers can't be compared on this set.** With 4 labels in the pools, every
  ranker sits within noise of random (0-2 at 100 vs 1.1 expected).
- **Outside the Feng screen there is almost no public evidence for these pairs in
  these sources** (1/209 SL evidence, 11/209 any record). In production that is fine:
  retrieving BioGRID genetic interactions would surface the published Feng pairs
  (205/209). For evaluation it means a benchmark built from one public screen can't
  be scored without that screen leaking into the tools.
- **Implications.** Retrieval has to depend on the question type: physical and
  regulatory questions use STRING/BioGRID physical; SL questions retrieve from genetic
  sources (BioGRID genetic, ORCS, DepMap per AGE-680 item 1). Benchmarks need label
  sources independent of tool data: a temporal holdout (screens published after the
  data snapshot) or leave-one-screen-out across several SL screens. Whether an LLM
  reranker helps remains open.

## Full CQ validation (all 15 CQs), plain path

`scripts/spike_cq_validation.py --no-agents`: every gold `key_entity` and
`biolink_edge` in the CQ dataset (revision `4fd7a86d`), checked with MCP tools only.
The agent path ran too, but the Anthropic account behind the gateway hit its usage
limit during the run ("You have reached your specified API usage limits. You will
regain access on 2026-11-01", request `req_011CgGmEVcqFZzd1ZfhxY9bo`); agent results
are valid for cq1-cq6 only.

| Phase / item | Plain pass / scorable | Not scorable | Notes |
|---|---:|---|---|
| Gene resolution (HGNC) | **24/24** | | agent 14/14 where valid (cq1-cq6) |
| Ensembl gene, trials (NCT), STRING proteins | 7/8 | | RAF1 STRING search missed |
| Compound resolution (ChEMBL) | 6/8 | 3 target IDs (no tool), 3 gold errors | misses: 5-fluorouracil (no synonym search), Nutlin-3 (ChEMBL timeout after retries) |
| Pathway resolution (WikiPathways) | 0/2 | | WP2760 not found in WikiPathways; WP5078 not found by name |
| Disease resolution (MONDO) | | 4 (no disease-search tool) | |
| gene-gene and STRING edges | **10/11** | | miss: cq1 RARG → ACVR1 (no STRING/BioGRID record); agent 5/6 where valid |
| drug → target (mechanism) | 4/6 | 2 no mechanism data, 1 gold error | misses are off-target edges (dasatinib → DDR2, hERG) that mechanism data doesn't cover; agent missed palovarotene → RARG, which plain found |
| drug → trial | **2/2** | | needs the "gene drug" query for pemetrexed |
| gene ↔ disease | 1/3 | 2 tool failures | APP, APOE: `opentargets_get_associations` fails for the whole gene; NGLY1 deficiency and HTT's disease not in associations |
| gene → pathway, pathway → drug | 0/3 | | WikiPathways gold IDs (see above) |

Gold-data errors (gold ID names a different compound in ChEMBL): cq2 LDN-193189 =
`CHEMBL:405130` (WHI-P131), cq2 Dorsomorphin = `CHEMBL:495727` (AT-9283; Dorsomorphin is
`CHEMBL:478629`), cq4 Lecanemab = `CHEMBL:4594344` (tisotumab; Lecanemab is
`CHEMBL:3833321`). cq2's `WP:WP2760` returns ENTITY_NOT_FOUND from WikiPathways. Tracked as
open-biosciences/biosciences-research#10. The APP/APOE Open Targets failure is Linear
AGE-747 (GO-term rows fail the output validator); the drug agent's prompt hard-codes
cq14's answers (fluorouracil, pemetrexed): Linear AGE-748.

What it shows for `main`: gene resolution, gene-gene edges and drug → trial are ready for
plain code; compound resolution needs synonym search; drug → target needs bioactivity data
for off-target edges; disease and pathway steps are blocked by tool gaps
(no disease search, Open Targets failure for APP/APOE) and gold drift, not by the
plain-vs-agent choice. Wherever both paths had valid results, plain matched or beat the
agent.

## Findings

1. **anthropic 2.x breaks pydantic-ai 2.59.0.** `pydantic_ai/models/anthropic.py`
   calls `BetaMessageParam(...)`, which anthropic 2.1.0 changed to a `Union`
   → `TypeError: Cannot instantiate typing.Union` on every model request
   (reproduced without Temporal). pydantic-ai declares `anthropic>=1.12.1` with no
   upper bound, so the resolver picks 2.x. Pinned `<2`. Tracked upstream as
   [pydantic/pydantic-ai#10923](https://github.com/pydantic/pydantic-ai/issues/10923)
   (open, filed 2026-10-21; maintainers deciding between a code fix and an `anthropic<2` cap).
   Drop the pin once that ships.
2. **`MCPServerStdio` no longer exists in 2.x.** `MCPToolset` wraps a FastMCP
   client; stdio goes through `fastmcp.client.transports.StdioTransport`, as in the
   [v2 MCP client docs](https://github.com/pydantic/pydantic-ai/blob/v2.0.0/docs/mcp/client.md).
   Stdio subprocess cleanup on cancellation was fixed in
   [#8548](https://github.com/pydantic/pydantic-ai/issues/8548) (closed 2026-09-21).
3. **Subprocess cost dominates with stdio.** `keep_alive=False` starts
   `uv run fastmcp` once per MCP activity (~2–3s each). `keep_alive=True` reused one
   subprocess across activities on different tasks without errors and halved wall
   time. A hosted HTTP MCP endpoint would avoid the subprocess entirely.
4. **Worktrees can't find `biosciences-mcp` as a sibling.** `_find_sibling_repo()`
   resolves relative to `.worktrees/`; set `BIOSCIENCES_MCP_PATH`.
5. Structured output varied between runs (`entrez_id='7298'` vs `'NCBIGene:7298'`),
   independent of durability.
6. **MCP tool activities have no heartbeat timeout by default** (only model
   activities get 30s; `_durability.py`). A crash mid-tool-call then waits for
   `start_to_close`. Every activity already heartbeats, so set `heartbeat_timeout`
   in `activity_config` (done in `durable_resolve.py`).
7. **MCP version skew logs a warning per connection.** The mcp 2.3 client sends
   `server/discover` first; biosciences-mcp (mcp 1.26) rejects it and the client
   falls back to `initialize`. Harmless, but noisy in worker logs.
8. **Every Anthropic request enters the SDK twice.** For claude-sonnet-5 at the default
   `max_tokens`, Pydantic AI calls `messages.create` non-streaming, the SDK refuses it
   locally ("Streaming is required", nothing sent), and Pydantic AI retries streaming
   (`models/anthropic.py`). One HTTP request either way; it only matters for
   instrumentation, and setting `max_tokens` avoids it.
9. **biosciences-mcp `string_get_interactions` drops the query protein's own edges.**
   It calls STRING `/json/network` (all edges among the seed and its partners) and
   truncates to `limit` in API order (`clients/string.py:318`). TP53 at `limit=400`:
   16 seed partners, no MDM2. STRING's `interaction_partners` endpoint returns the
   seed's partners ranked by score. Workaround here: `limit=10000`, filter, rank. Tracked as Linear AGE-741.
10. **Graph-builder skill examples don't match the live tools.** `string_get_interactions`
    takes no `species` argument (the documented call fails validation) and needs the
    `STRING:` prefix; `opentargets_get_associations` takes `target_id`, not `ensembl_id`. Tracked as
    Linear AGE-737 (open-biosciences-plugins#31 closed as its duplicate).
11. **Slim projections drop the fields callers filter on.** TP53: BioGRID full is 6125
    records / 1.91 MB, slim 0.38 MB but keeps only `symbol_b` and
    `experimental_system_type` (no `experimental_system`, so SL can't be filtered);
    STRING has no slim mode (2.95 MB at `limit=10000`, above Temporal's 2 MB default
    payload limit if returned raw from an activity); HGNC search slim is identical to
    full and doesn't say what matched. Filter inside the activity; send only slim
    records across into an LLM or workflow history. Tracked as Linear AGE-744.

## Sources

- Pydantic AI Temporal guide ([current](https://pydantic.dev/docs/ai/integrations/durable_execution/temporal/),
  [v2.0.0](https://github.com/pydantic/pydantic-ai/blob/v2.0.0/docs/durable_execution/temporal.md)):
  `TemporalDurability` preferred, `TemporalAgent` deprecated; MCP calls always run in
  activities; stable agent `name` and toolset `id` required; set `max_retries=0` on the
  provider client because Temporal retries.
- `PydanticAIPlugin` sandbox passthroughs (`pydantic_ai`, `anyio`, `sniffio`, `httpx`, ...):
  read from the installed source (`durable_exec/temporal/__init__.py`), not stated in the docs.
- Temporal: [Child Workflows](https://docs.temporal.io/child-workflows) — start with one
  Workflow calling Activities; add Child Workflows only for a concrete reason.

## Not tested

- Uncrashed wall time of one-shot vs durable (durable adds ~15 activities and their
  history events for 3 genes).
- One-shot with heartbeats added (would close most of the recovery-time gap, not the
  repeated work).
- Other CQ14 phases, HTTP MCP transport, `non_retryable_model_errors` behavior.

## Reproduce

```bash
cd .worktrees/spike-temporal-durability
export BIOSCIENCES_MCP_PATH=/path/to/biosciences-mcp
uv sync --extra dev
uv run python -m src.biosciences_temporal.scripts.run_spike --genes TP53 TYMS BRCA1 [--keep-alive]

# Crash and resume (SPIKE_TASK_QUEUE isolates concurrent runs)
uv run python -m src.biosciences_temporal.scripts.spike_crash_resume --pattern durable --kill-at-model-call 5
uv run python -m src.biosciences_temporal.scripts.spike_crash_resume --pattern oneshot --kill-at-model-call 5
uv run python -m src.biosciences_temporal.scripts.spike_crash_resume --kill-after 7 --kill-during tool
```
