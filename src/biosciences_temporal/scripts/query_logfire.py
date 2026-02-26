"""
Query Logfire traces for CQ14 workflow analysis.

This script demonstrates how to query trace data from Logfire using the Query API.
You need a READ token (different from write token) to use this.

Usage:
    # Get a read token from Logfire web UI (Project Settings > Read Tokens)
    export LOGFIRE_READ_TOKEN=your_read_token

    uv run python -m src.biosciences_temporal.scripts.query_logfire
    uv run python -m src.biosciences_temporal.scripts.query_logfire --limit 20
    uv run python -m src.biosciences_temporal.scripts.query_logfire --sql "SELECT * FROM records WHERE span_name LIKE '%agent%' LIMIT 5"
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv
from logfire.query_client import LogfireQueryClient

load_dotenv()


def get_recent_traces(client: LogfireQueryClient, limit: int = 10) -> list:
    """Get most recent traces."""
    query = f"""
    SELECT
        start_timestamp,
        span_name,
        kind,
        duration,
        attributes
    FROM records
    ORDER BY start_timestamp DESC
    LIMIT {limit}
    """
    return client.query_json_rows(sql=query)


def get_llm_calls(client: LogfireQueryClient, limit: int = 10) -> list:
    """Get recent LLM/model calls."""
    query = f"""
    SELECT
        start_timestamp,
        span_name,
        duration,
        attributes
    FROM records
    WHERE span_name LIKE '%chat%'
       OR span_name LIKE '%model%'
       OR span_name LIKE '%openai%'
    ORDER BY start_timestamp DESC
    LIMIT {limit}
    """
    return client.query_json_rows(sql=query)


def get_agent_runs(client: LogfireQueryClient, limit: int = 10) -> list:
    """Get recent agent execution runs."""
    query = f"""
    SELECT
        start_timestamp,
        span_name,
        duration,
        attributes
    FROM records
    WHERE span_name LIKE '%agent%'
       OR span_name LIKE '%Agent%'
    ORDER BY start_timestamp DESC
    LIMIT {limit}
    """
    return client.query_json_rows(sql=query)


def custom_query(client: LogfireQueryClient, sql: str) -> list:
    """Run a custom SQL query."""
    return client.query_json_rows(sql=sql)


def main():
    parser = argparse.ArgumentParser(description="Query Logfire traces")
    parser.add_argument("--limit", "-n", type=int, default=10, help="Number of records to fetch")
    parser.add_argument("--sql", help="Custom SQL query to execute")
    parser.add_argument("--type", choices=["recent", "llm", "agent"], default="recent",
                        help="Type of query: recent traces, llm calls, or agent runs")
    parser.add_argument("--format", choices=["json", "table"], default="table",
                        help="Output format")

    args = parser.parse_args()

    # Check for read token
    read_token = os.environ.get("LOGFIRE_READ_TOKEN")
    if not read_token:
        print("Error: LOGFIRE_READ_TOKEN environment variable not set.")
        print("Get a read token from Logfire web UI: Project Settings > Read Tokens")
        sys.exit(1)

    with LogfireQueryClient(read_token=read_token) as client:
        if args.sql:
            results = custom_query(client, args.sql)
        elif args.type == "llm":
            results = get_llm_calls(client, args.limit)
        elif args.type == "agent":
            results = get_agent_runs(client, args.limit)
        else:
            results = get_recent_traces(client, args.limit)

        if args.format == "json":
            print(json.dumps(results, indent=2, default=str))
        else:
            # Simple table format - handle RowQueryResults structure
            rows = results.get("rows", results) if isinstance(results, dict) else results
            if not rows:
                print("No results found.")
                return

            print(f"\nFound {len(rows)} records:\n")
            print("-" * 80)

            for i, record in enumerate(rows, 1):
                if isinstance(record, dict):
                    print(f"[{i}] {record.get('span_name', 'N/A')}")
                    print(f"    Timestamp: {record.get('start_timestamp', 'N/A')}")
                    if 'duration' in record and record['duration']:
                        duration_s = record['duration']
                        print(f"    Duration: {duration_s:.3f}s")
                    print("-" * 80)
                else:
                    print(f"[{i}] {record}")
                    print("-" * 80)


if __name__ == "__main__":
    main()
