"""
Retry policies for CQ14 Temporal activities.

Defines retry behavior based on ADR-001 error codes and Temporal best practices.
Non-retryable errors are those where retry would not help (validation failures,
invalid CURIEs, etc.)
"""

from datetime import timedelta

from temporalio.common import RetryPolicy


# ADR-001 Section 9: Non-retryable error codes
# These errors indicate bad input or missing data - retrying won't help
NON_RETRYABLE_ERRORS = [
    "UNRESOLVED_ENTITY",   # Raw string passed to strict tool (use search first)
    "AMBIGUOUS_QUERY",     # Query too short or returns >100 results
    "ENTITY_NOT_FOUND",    # Valid CURIE but no record exists
    "ValidationError",     # Pydantic model validation failed
]

# Short MCP activities (resolve_gene, enrich_protein, validators)
# Expected duration: 10-60 seconds
# Retry: Quick retry for transient failures
SHORT_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=3,
    non_retryable_error_types=NON_RETRYABLE_ERRORS,
)

# Long MCP activities (expand_interactions, find_drugs, search_trials)
# Expected duration: 30-180 seconds
# Retry: More patient retry for complex queries
LONG_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=3),
    maximum_attempts=5,
    non_retryable_error_types=NON_RETRYABLE_ERRORS,
)
