"""Automated architecture & runtime contract extractor for biosciences-temporal.

Extracts:
1. pyproject.toml dependencies and optional-dependencies.
2. Temporal task queue, runner, and ADR-001 retry policy error codes.
3. Pydantic AI Gateway and biosciences-mcp MCPServerStdio connector contracts.
4. All 9 AgentRunner definitions with their AgentMetadata and Pydantic output schemas.
5. CLI scripts under src/biosciences_temporal/scripts/ and their argparse options.

Generates docs/inspect.json (machine-readable agent contract), UTF-8 and LF.

Usage (from the repo root, under `uv run` so the package imports):
    python scripts/document_architecture.py           regenerate docs/inspect.json
    python scripts/document_architecture.py --check   exit 1 when it is missing or stale
"""

from __future__ import annotations

import argparse
import ast
import json
import tomllib
from pathlib import Path

from biosciences_temporal.agents.base import (
    GATEWAY_SERVER,
    OPENROUTER_FALLBACK_MODEL,
    OPENROUTER_FREE_MODEL,
    TYPESAFE_MODEL_NAME,
    USAGE_LIMITS,
)
from biosciences_temporal.agents.drugs import _runner as drugs_runner
from biosciences_temporal.agents.enrich import _runner as enrich_runner
from biosciences_temporal.agents.expand import _runner as expand_runner
from biosciences_temporal.agents.models import (
    ClinicalTrial,
    DrugCandidate,
    GeneInfo,
    GeneInteraction,
    ProteinFunction,
    ValidationEvidence,
)
from biosciences_temporal.agents.resolve import _runner as resolve_runner
from biosciences_temporal.agents.trials import _runner as trials_runner
from biosciences_temporal.agents.validate import (
    _drug_runner,
    _gene_runner,
    _sl_runner,
    _trial_runner,
)
from biosciences_temporal.config.retry_policies import NON_RETRYABLE_ERRORS
from biosciences_temporal.config.timeouts import TASK_QUEUE

INSPECT = "docs/inspect.json"
REGENERATE = "regenerate with: uv run python scripts/bt_diagram.py . write"


def _extract_script_options(script_path: Path) -> list[str]:
    """Extract argparse add_argument flag strings from a script AST."""
    tree = ast.parse(script_path.read_text(encoding="utf-8"))
    opts: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    opts.append(arg.value)
    return opts


def _cli_scripts(root: Path) -> list[dict]:
    scripts_dir = root / "src" / "biosciences_temporal" / "scripts"
    out: list[dict] = []
    for path in sorted(scripts_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = (ast.get_docstring(tree) or "").strip()
        first_line = doc.splitlines()[0] if doc else ""
        out.append(
            {
                "script": path.stem,
                "module": f"src.biosciences_temporal.scripts.{path.stem}",
                "help": first_line,
                "options": _extract_script_options(path),
            }
        )
    return out


def manifest(root: Path) -> dict:
    pyproject_path = root / "pyproject.toml"
    pyproject_data = {}
    if pyproject_path.exists():
        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)
    project_meta = pyproject_data.get("project", {})

    runners = [
        ("resolve", resolve_runner, GeneInfo, False),
        ("enrich", enrich_runner, ProteinFunction, False),
        ("expand", expand_runner, GeneInteraction, True),
        ("drugs", drugs_runner, DrugCandidate, True),
        ("trials", trials_runner, ClinicalTrial, True),
        ("validate", _gene_runner, ValidationEvidence, False),
        ("validate", _drug_runner, ValidationEvidence, False),
        ("validate", _trial_runner, ValidationEvidence, False),
        ("validate", _sl_runner, ValidationEvidence, False),
    ]

    agents_contract = [
        {
            "name": r.name,
            "module": f"biosciences_temporal.agents.{mod}",
            "output_model": f"list[{model.__name__}]" if is_list else model.__name__,
            "model_factory": f"create_model(agent_name={r.name!r})",
            "model_override_env": f"BIOSCIENCES_MODEL_{r.name.upper()}",
            "metadata": r.metadata.to_dict(),
        }
        for mod, r, model, is_list in runners
    ]

    models_schemas = {
        m.__name__: m.model_json_schema()
        for m in (
            GeneInfo,
            ProteinFunction,
            GeneInteraction,
            DrugCandidate,
            ClinicalTrial,
            ValidationEvidence,
        )
    }

    return {
        "metadata": {
            "name": project_meta.get("name", "biosciences-temporal"),
            "version": project_meta.get("version", "0.1.0"),
            "description": project_meta.get("description", ""),
            "requires_python": project_meta.get("requires-python", ">=3.11"),
        },
        "dependencies": {
            "runtime": project_meta.get("dependencies", []),
            "optional": project_meta.get("optional-dependencies", {}),
        },
        "temporal": {
            "default_task_queue": TASK_QUEUE,
            "workflow_runner": "UnsandboxedWorkflowRunner",
            "non_retryable_error_types": NON_RETRYABLE_ERRORS,
        },
        "connectors": {
            "openrouter_and_typesafe": {
                "primary_model": OPENROUTER_FREE_MODEL,
                "fallback_model": OPENROUTER_FALLBACK_MODEL,
                "typesafe_model": TYPESAFE_MODEL_NAME,
                "offline_fallback": "TestModel",
                "env_vars": [
                    "OPENROUTER_API_KEY",
                    "OPENROUTER_FREE_MODEL",
                    "OPENROUTER_FALLBACK_MODEL",
                    "TYPESAFE_API_KEY",
                    "TYPESAFE_MODEL_NAME",
                    "LOGFIRE_TOKEN",
                    "USE_TEST_MODEL",
                ],
                "request_limit": USAGE_LIMITS.request_limit,
            },
            "mcp_stdio": {
                "id": "biosciences_mcp",
                "transport": "MCPToolset (StdioTransport)",
                "command": "uv",
                "args": ["run", "fastmcp", "run", GATEWAY_SERVER],
                "sibling_repo": "biosciences-mcp",
                "override_env_var": "BIOSCIENCES_MCP_PATH",
                "timeout_seconds": 120.0,
                "lifecycle": "one-shot per activity task",
            },
        },
        "agents": agents_contract,
        "models": models_schemas,
        "cli_scripts": _cli_scripts(root),
    }


def render(root: Path) -> str:
    return json.dumps(manifest(root), indent=2) + "\n"


def check(root: Path) -> list[str]:
    path = root / INSPECT
    if not path.exists():
        return [f"{INSPECT} is missing; {REGENERATE}"]
    if path.read_text(encoding="utf-8") != render(root):
        return [f"{INSPECT} is stale; {REGENERATE}"]
    return []


def write(root: Path) -> Path:
    path = root / INSPECT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(root), encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare, don't write")
    args = parser.parse_args(argv)
    root = Path(".")
    if args.check:
        problems = check(root)
        print("\n".join(problems) or f"{INSPECT}: ok")
        return 1 if problems else 0
    path = write(root)
    contract = json.loads(path.read_text(encoding="utf-8"))
    print(
        f"wrote {path}: {len(contract['agents'])} AgentRunner definitions, "
        f"{len(contract['models'])} Pydantic models, "
        f"{len(contract['cli_scripts'])} CLI scripts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
