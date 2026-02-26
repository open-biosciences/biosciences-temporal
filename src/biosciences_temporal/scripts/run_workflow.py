"""
Trigger CQ14 workflow via Temporal.

This script starts a new workflow or resumes an existing one.
Requires the Temporal worker to be running.

Usage:
    # Start new workflow
    uv run python -m src.biosciences_temporal.scripts.run_workflow

    # Custom genes
    uv run python -m src.biosciences_temporal.scripts.run_workflow --gene-a BRCA1 --gene-b PARP1

    # Resume existing workflow
    uv run python -m src.biosciences_temporal.scripts.run_workflow -w <workflow-id>
"""

import argparse
import asyncio
import os
import sys

# Add parent to path for relative imports when running as script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from src.biosciences_temporal.temporal.client import start_workflow, get_result


async def main():
    parser = argparse.ArgumentParser(description="Trigger CQ14 workflow via Temporal")
    parser.add_argument("--gene-a", default="TP53", help="First gene in synthetic lethal pair")
    parser.add_argument("--gene-b", default="TYMS", help="Second gene (drug target)")
    parser.add_argument("--target-name", default="thymidylate synthase", help="Target name for drug search")
    parser.add_argument("--condition", default="cancer", help="Disease condition for trial search")
    parser.add_argument("-w", "--workflow-id", help="Resume existing workflow by ID")
    parser.add_argument("--no-wait", action="store_true", help="Start workflow but don't wait for result")

    args = parser.parse_args()

    if args.workflow_id:
        # Resume existing workflow
        print(f"Getting result for workflow: {args.workflow_id}")
        result = await get_result(args.workflow_id)
    else:
        # Start new workflow
        workflow_id = await start_workflow(
            gene_a=args.gene_a,
            gene_b=args.gene_b,
            target_name=args.target_name,
            condition=args.condition,
        )

        if args.no_wait:
            print(f"Workflow started. Check status at:")
            print(f"  http://localhost:8233/namespaces/default/workflows/{workflow_id}")
            return

        print(f"Waiting for workflow to complete...")
        result = await get_result(workflow_id)

    print("\n" + "=" * 60)
    print("WORKFLOW RESULT")
    print("=" * 60)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
