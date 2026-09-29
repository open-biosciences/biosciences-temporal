# Graph-refinement validator fixtures

## `sl_system_approach/` — structural edge cases, not scientific truth

Verbatim copies of three knowledge-graph JSON files from the `sl-system-approach` bundle in
[`biosciences-workspace-template`](https://github.com/open-biosciences/biosciences-workspace-template/tree/main/output/sl-system-approach)
(added in commit `71c8ef2`; copied at `f5801f8`). They were produced by a Claude CoWork run.
Nothing here establishes the original prompts, tool responses, reviewer identity or reproducibility.

The tests use them **only** to show that the validator catches structural defects. They are not
a gold-standard label set. No test asserts that any node, edge, trial, compound, or S′/ΔS′ value
is scientifically correct or incorrect.

| File | sha256 | Defects the tests pin |
|---|---|---|
| `sprime-sl-lung-cancer-knowledge-graph.json` | `3e40e8305d62ade6e3b86c011136db0046d7d1d48947b1d03d7cd2745779ce20` | `metadata.total_edges` 38 vs 32 edges; bare `NCT…` trial IDs; undeclared `COMPOUND:` placeholders |
| `sprime-sl-lung-cancer-knowledge-graph-v2.json` | `3aa507d5c9a03541a545ab532d781f15bd95e627151709a2f1edaf2edd6898a9` | dangling target `HGNC:9077` on the `COMPOUND:rigosertib` edge; `total_edges` 58 vs 51; `total_gene_nodes` 16 vs 15; bare trial IDs; `DISEASE:`/`COMPOUND:` placeholders |
| `sprime-sl-systemic-fragility-knowledge-graph.json` | `8759952f4f091ee1382541dff773a2b5a14251abb500277337a0e16abf2c7434` | closed graph with correct counts; undeclared `COMPOUND:`/`FRAMEWORK:` placeholders; not a refinement bundle (no claims, evidence, or revision) |

Verify the copies with `sha256sum tests/graph_refinement/fixtures/sl_system_approach/*.json`.

## `synthetic/valid_bundle.json`

Hand-written minimal bundle in the proposed contract. Identifiers match the registry syntax, but
they are placeholders (`HGNC:9999901`, `MONDO:9999901`, …) and the fixture makes no scientific
assertion. Tests change one field at a time to exercise each issue code.
