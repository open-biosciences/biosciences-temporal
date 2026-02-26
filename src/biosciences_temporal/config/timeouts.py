"""
Activity timeout configuration for CQ14 Temporal workflow.

Defines timeout settings for different activity types.
These configs are passed to workflow.execute_activity() calls.
"""

from datetime import timedelta

from .retry_policies import (
    LONG_ACTIVITY_RETRY,
    SHORT_ACTIVITY_RETRY,
)


# Short MCP activities (resolve_gene, enrich_protein, validators)
# 3 min execution timeout, 10 min total including retries
SHORT_ACTIVITY_CONFIG = {
    "start_to_close_timeout": timedelta(minutes=3),
    "schedule_to_close_timeout": timedelta(minutes=10),
    "retry_policy": SHORT_ACTIVITY_RETRY,
}

# Long MCP activities (expand_interactions, find_drugs, search_trials)
# 5 min execution timeout, 20 min total including retries
# Note: No heartbeat timeout - activities wait for MCP/LLM response
LONG_ACTIVITY_CONFIG = {
    "start_to_close_timeout": timedelta(minutes=5),
    "schedule_to_close_timeout": timedelta(minutes=20),
    "retry_policy": LONG_ACTIVITY_RETRY,
}

# Task queue name
TASK_QUEUE = "biosciences-task-queue"
