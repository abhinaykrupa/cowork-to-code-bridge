"""
Model Router Gateway — intelligent model selection for token efficiency.

Routes tasks to appropriate Claude model tier based on complexity:
  - Opus/Fable: Complex reasoning, planning, analysis
  - Sonnet: Standard work, moderate complexity
  - Haiku: Simple lookups, formatting, lightweight tasks

Mandatory complexity declaration on every route_task() call ensures
token efficiency and provides audit trail of routing decisions.

Model selection is explicit (requester-provided), not heuristic-based,
with intelligent fallback cascading both up and down the model tier.
"""
from __future__ import annotations

import json
import time
from enum import Enum
from pathlib import Path
from typing import Any

from cowork_to_code_bridge.client import queue_task as _queue_task


class ModelTier(str, Enum):
    """Available Claude model tiers, in cost/capability order."""
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"
    FABLE = "fable"  # High-capability reasoning model


class FallbackStrategy(str, Enum):
    """How to handle model unavailability."""
    CASCADE_UP = "cascade_up"      # Haiku → Sonnet → Opus → Fable
    CASCADE_DOWN = "cascade_down"  # Fable → Opus → Sonnet → Haiku
    FAIL_FAST = "fail_fast"        # No fallback, error immediately


# Model tier hierarchy (bottom to top)
TIER_HIERARCHY = [ModelTier.HAIKU, ModelTier.SONNET, ModelTier.OPUS, ModelTier.FABLE]

# Canonical tier → concrete Claude model ID. This is the single source of truth
# the daemon and run_claude.sh rely on to turn a routing tier (e.g. "opus") into
# the `--model` flag the claude CLI expects. Keep in sync with run_claude.sh's
# tier_to_model_id() — the shell copy exists so the script stays standalone.
TIER_TO_MODEL_ID: dict[ModelTier, str] = {
    ModelTier.HAIKU: "claude-haiku-4-5-20251001",
    ModelTier.SONNET: "claude-sonnet-4-6",
    ModelTier.OPUS: "claude-opus-4-8",
    ModelTier.FABLE: "claude-fable-5",
}


class PermissionScope(str, Enum):
    """Per-task permission scope a caller may request (issue #47).

    Rather than letting a caller pass arbitrary ``CLAUDE_FLAGS`` (a privilege-
    escalation risk — the bridge token would then grant full shell), the caller
    picks from a fixed, safe allowlist of named scopes. Each scope maps to a
    concrete, vetted set of ``claude`` CLI flags. An owner-set ``CLAUDE_FLAGS``
    always wins, exactly like model tier and budget.
    """
    PLAN = "plan"          # read + reason only; no edits, no shell
    READONLY = "readonly"  # read-only file inspection, no edits/exec
    EDIT = "edit"          # edit files, no shell
    FULL = "full"          # default trust scope (no extra restriction)


# Canonical scope → concrete `claude` CLI flag list. Single source of truth the
# daemon and run_claude.sh rely on. Keep in sync with run_claude.sh's
# scope_to_flags() — the shell copy exists so the script stays standalone.
# FULL maps to no flags: it means "apply no extra restriction", deferring to the
# owner's global CLAUDE_FLAGS (or the CLI default) rather than widening trust.
SCOPE_TO_FLAGS: dict[PermissionScope, list[str]] = {
    PermissionScope.PLAN: ["--permission-mode", "plan"],
    PermissionScope.READONLY: ["--allowedTools", "Read,Glob,Grep"],
    PermissionScope.EDIT: ["--allowedTools", "Read,Glob,Grep,Edit,Write"],
    PermissionScope.FULL: [],
}


def scope_to_flags(scope: str | PermissionScope) -> list[str]:
    """Resolve a permission scope to its `claude` CLI flag list.

    Raises ValueError for an unknown scope so a typo surfaces loudly rather than
    silently dispatching with the wrong (or no) restriction.
    """
    if isinstance(scope, str):
        try:
            scope = PermissionScope(scope.lower())
        except ValueError:
            valid = ", ".join(s.value for s in PermissionScope)
            raise ValueError(
                f"unknown permission scope {scope!r}; expected one of: {valid}"
            ) from None
    return SCOPE_TO_FLAGS[scope]


def tier_to_model_id(tier: str | ModelTier) -> str:
    """Resolve a routing tier ('haiku'|'sonnet'|'opus'|'fable') to a model ID.

    Raises ValueError for an unknown tier so a typo surfaces loudly rather than
    silently dispatching to the wrong (or default) model.
    """
    if isinstance(tier, str):
        try:
            tier = ModelTier(tier.lower())
        except ValueError:
            valid = ", ".join(t.value for t in TIER_HIERARCHY)
            raise ValueError(
                f"unknown model tier {tier!r}; expected one of: {valid}"
            ) from None
    return TIER_TO_MODEL_ID[tier]


def _validate_model_preference(model_preference: str | ModelTier | None) -> ModelTier:
    """Validate and normalize model preference.

    Raises ValueError if model_preference is invalid.
    """
    if model_preference is None:
        raise ValueError(
            "model_preference is MANDATORY. Specify 'haiku', 'sonnet', 'opus', or 'fable'. "
            "See BRIDGE_INIT.md for routing requirements."
        )

    if isinstance(model_preference, ModelTier):
        return model_preference

    if isinstance(model_preference, str):
        try:
            return ModelTier(model_preference.lower())
        except ValueError:
            raise ValueError(
                f"Invalid model_preference '{model_preference}'. "
                f"Must be one of: {', '.join(t.value for t in ModelTier)}"
            ) from None

    raise TypeError(f"model_preference must be str or ModelTier, got {type(model_preference)}")


def _get_cascade_order(
    initial_tier: ModelTier,
    strategy: FallbackStrategy | str,
) -> list[ModelTier]:
    """Get the order of models to try for fallback.

    For CASCADE_UP: start at initial_tier, go up to Fable.
    For CASCADE_DOWN: start at initial_tier, go down to Haiku.
    For FAIL_FAST: only try initial_tier.
    """
    if isinstance(strategy, str):
        strategy = FallbackStrategy(strategy)

    if strategy == FallbackStrategy.FAIL_FAST:
        return [initial_tier]

    start_idx = TIER_HIERARCHY.index(initial_tier)

    if strategy == FallbackStrategy.CASCADE_UP:
        # Try initial tier and all higher tiers
        return TIER_HIERARCHY[start_idx:]

    if strategy == FallbackStrategy.CASCADE_DOWN:
        # Try initial tier and all lower tiers (reversed)
        return list(reversed(TIER_HIERARCHY[:start_idx + 1]))

    raise ValueError(f"Unknown fallback strategy: {strategy}")


def route_task(
    script: str,
    args: list[str] | None = None,
    model_preference: str | ModelTier | None = None,
    fallback_strategy: str | FallbackStrategy = FallbackStrategy.CASCADE_UP,
    bridge_root: Path | str | None = None,
    timeout: int = 300,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Route a task to appropriate Claude model tier.

    This is the primary entry point for token-efficient task execution.
    Model selection is explicit (requester-provided), ensuring clear
    intent and enabling audit trails of routing decisions.

    Args:
        script: Path to script to run (e.g., "scripts/analyze.sh")
        args: Script arguments (default: [])
        model_preference: MANDATORY. One of "haiku", "sonnet", "opus", "fable".
                         Raises ValueError if missing or invalid.
        fallback_strategy: How to handle model unavailability.
                          CASCADE_UP (default): try higher tiers if unavailable.
                          CASCADE_DOWN: try lower tiers if unavailable.
                          FAIL_FAST: error if preferred model unavailable.
        bridge_root: Override auto-detected bridge root directory
        timeout: Task timeout in seconds (default: 300)
        cwd: Working directory for task execution
        env: Environment variables to pass
        idempotency_key: Unique key for idempotent execution. Required for
                        state-changing work to prevent double-execution on retry.

    Returns:
        dict with keys:
          - task_id: Unique task identifier
          - status: "queued"
          - requested_model: User's requested model tier
          - selected_model: Actual model tier selected (may differ if fallback used)
          - timestamp: Unix timestamp of routing decision
          - fallback_used: bool (True if different from requested_model)

    Raises:
        ValueError: If model_preference is missing or invalid
        TimeoutError: If task execution times out

    Example:
        >>> result = route_task(
        ...     "scripts/analyze.sh",
        ...     args=["data.csv"],
        ...     model_preference="opus",  # MANDATORY
        ...     fallback_strategy="cascade_up"
        ... )
        >>> task_id = result["task_id"]
        >>> print(f"Routed to {result['selected_model']} (requested: {result['requested_model']})")
    """
    # Validate and normalize inputs
    requested_tier = _validate_model_preference(model_preference)
    if isinstance(fallback_strategy, str):
        fallback_strategy = FallbackStrategy(fallback_strategy)

    cascade_order = _get_cascade_order(requested_tier, fallback_strategy)

    # Simulate model availability check (in production, check actual API availability)
    # For now, always use the requested model (first in cascade order)
    selected_tier = cascade_order[0]
    attempted_models = [selected_tier.value]
    fallback_used = selected_tier != requested_tier

    # Add routing metadata to the task
    routing_metadata = {
        "requested_model": requested_tier.value,
        "selected_model": selected_tier.value,
        "fallback_strategy": fallback_strategy.value,
        "cascade_order": [t.value for t in cascade_order],
        "attempted_models": attempted_models,
        "fallback_used": fallback_used,
        "ts_routed": time.time(),
    }

    # Queue the task via standard bridge mechanism. model_tier is the payload
    # key the daemon reads to inject CLAUDE_MODEL_TIER into the child env
    # (run_claude.sh maps it to a concrete --model ID).
    result = _queue_task(
        script=script,
        args=args or [],
        timeout=timeout,
        bridge_root=bridge_root,
        cwd=cwd,
        env=env,
        idempotency_key=idempotency_key,
        model_tier=selected_tier.value,
    )

    # Enhance result with routing information
    result.update({
        "requested_model": requested_tier.value,
        "selected_model": selected_tier.value,
        "fallback_used": fallback_used,
        "routing_metadata": routing_metadata,
    })

    # Also persist routing metadata alongside the queue for post-hoc audit.
    from cowork_to_code_bridge.client import _resolve_bridge_root

    _persist_routing_metadata(
        Path(bridge_root) if bridge_root else _resolve_bridge_root(),
        result["task_id"],
        routing_metadata,
    )

    return result


def _persist_routing_metadata(
    bridge_root: str | Path,
    task_id: str,
    routing_metadata: dict[str, Any],
) -> None:
    """Store routing metadata alongside the queued task.

    This allows the daemon and post-execution audit to see which model was
    selected and how the decision was made.
    """
    bridge_root = Path(bridge_root)
    routing_dir = bridge_root / "routing"
    routing_dir.mkdir(parents=True, exist_ok=True)

    routing_file = routing_dir / f"{task_id}.json"
    tmp_file = routing_file.with_suffix(".json.tmp")

    tmp_file.write_text(json.dumps(routing_metadata, indent=2))
    tmp_file.rename(routing_file)


def get_routing_metadata(
    task_id: str,
    bridge_root: Path | str | None = None,
) -> dict[str, Any] | None:
    """Retrieve routing metadata for a task.

    Returns None if task has no routing metadata (was queued without routing).
    """
    from cowork_to_code_bridge.client import _resolve_bridge_root

    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    routing_file = root / "routing" / f"{task_id}.json"

    if not routing_file.exists():
        return None

    try:
        return json.loads(routing_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def get_routing_recommendations(
    task_description: str,
    fallback_on_error: bool = True,
) -> dict[str, Any]:
    """Get recommended model tier for a task (informational only).

    This is for reference/logging. Actual decisions are made by the requester
    via the mandatory model_preference parameter.

    Args:
        task_description: Brief description of the task
        fallback_on_error: If True, return sensible default on any error

    Returns:
        dict with keys:
          - recommended_tier: Suggested ModelTier
          - reasoning: Brief explanation
          - can_use_cheaper: Whether the task could use a cheaper model
          - must_use_expensive: Whether the task requires a higher tier
    """
    # For now, this is a placeholder that always recommends Sonnet
    # In production, this could integrate with:
    # - Task history (what worked before?)
    # - Cost tracking (budget constraints?)
    # - ML-based complexity estimation
    # - User patterns (this user always overspecifies?)

    return {
        "recommended_tier": "sonnet",
        "reasoning": "Default recommendation. Actual selection via mandatory model_preference.",
        "can_use_cheaper": True,
        "must_use_expensive": False,
        "note": "Model selection is determined by requester via model_preference parameter.",
    }
