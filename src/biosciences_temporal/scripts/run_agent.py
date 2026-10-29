"""
Run CQ14 workflow standalone (no Temporal).

This script runs the PydanticAI agents directly without Temporal durability.
Useful for testing and development.

Usage:
    uv run python -m src.biosciences_temporal.scripts.run_agent
    uv run python -m src.biosciences_temporal.scripts.run_agent --gene-a BRCA1 --gene-b PARP1
"""

# Load .env first so LOGFIRE_TOKEN, OPENROUTER_API_KEY, and model overrides are set
# before Logfire and the agents see them.
# override=True: .env wins over stale shell exports.
import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
import logfire

load_dotenv(override=True)

# Configure Logfire before other imports that use Pydantic AI
if os.getenv("LOGFIRE_TOKEN"):
    logfire.configure(token=os.getenv("LOGFIRE_TOKEN"), service_name="biosciences-temporal")
else:
    logfire.configure(send_to_logfire=False, service_name="biosciences-temporal")
logfire.instrument_pydantic_ai()

# Add parent to path for relative imports when running as script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from src.biosciences_temporal.agents.cq14 import CQ14Orchestrator  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Run CQ14 workflow standalone")
    parser.add_argument("--gene-a", default="TP53", help="First gene in synthetic lethal pair")
    parser.add_argument("--gene-b", default="TYMS", help="Second gene (drug target)")
    parser.add_argument("--output", "-o", help="Output file for results (JSON)")

    args = parser.parse_args()

    # Check environment
    if not os.environ.get("OPENROUTER_API_KEY") and not os.environ.get("USE_TEST_MODEL"):
        print("Error: OPENROUTER_API_KEY not set (or set USE_TEST_MODEL=true for offline test runs)")
        sys.exit(1)

    # Run workflow
    orchestrator = CQ14Orchestrator(gene_a=args.gene_a, gene_b=args.gene_b)
    result = asyncio.run(orchestrator.run())

    # Print summary
    print("\n" + "=" * 60)
    print("CQ14 RESULT SUMMARY")
    print("=" * 60)

    result_dict = result.to_dict()
    print(json.dumps(result_dict, indent=2))

    # Save to file if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump(result_dict, f, indent=2)
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
