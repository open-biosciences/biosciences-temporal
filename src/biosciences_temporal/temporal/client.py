"""
Temporal client for triggering CQ14 workflows.

Provides functions to start new workflows or get results from existing ones.
"""

import asyncio
import json
import uuid
from dataclasses import asdict
from typing import Optional

from temporalio.client import Client

from ..config import TASK_QUEUE
from .workflows import CQ14Input, CQ14Workflow


async def start_workflow(
    gene_a: str = "TP53",
    gene_b: str = "TYMS",
    target_name: str = "thymidylate synthase",
    condition: str = "cancer",
    workflow_id: Optional[str] = None,
) -> str:
    """Start a new CQ14 workflow.

    Args:
        gene_a: First gene in the synthetic lethal pair.
        gene_b: Second gene (target for drug discovery).
        target_name: Human-readable target name for drug search.
        condition: Disease condition for trial search.
        workflow_id: Optional workflow ID. Generated if not provided.

    Returns:
        The workflow ID.
    """
    client = await Client.connect("localhost:7233")

    if workflow_id is None:
        workflow_id = f"cq14-{gene_a}-{gene_b}-{uuid.uuid4().hex[:8]}"

    input_data = CQ14Input(
        gene_a=gene_a,
        gene_b=gene_b,
        target_name=target_name,
        condition=condition,
    )

    handle = await client.start_workflow(
        CQ14Workflow.run,
        json.dumps(asdict(input_data)),
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    print(f"Started workflow: {workflow_id}")
    print(f"Temporal UI: http://localhost:8233/namespaces/default/workflows/{workflow_id}")

    return workflow_id


async def get_result(workflow_id: str) -> str:
    """Get the result of an existing workflow.

    Args:
        workflow_id: The workflow ID to query.

    Returns:
        The workflow result as JSON.
    """
    client = await Client.connect("localhost:7233")

    handle = client.get_workflow_handle(workflow_id)
    result = await handle.result()

    return result


async def run_and_wait(
    gene_a: str = "TP53",
    gene_b: str = "TYMS",
    target_name: str = "thymidylate synthase",
    condition: str = "cancer",
) -> str:
    """Start a workflow and wait for the result.

    Args:
        gene_a: First gene in the synthetic lethal pair.
        gene_b: Second gene (target for drug discovery).
        target_name: Human-readable target name for drug search.
        condition: Disease condition for trial search.

    Returns:
        The workflow result as JSON.
    """
    workflow_id = await start_workflow(gene_a, gene_b, target_name, condition)
    return await get_result(workflow_id)
