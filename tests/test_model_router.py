"""Tests for model router gateway system.

Tests the route_task() function that intelligently selects Claude model tiers
for token efficiency, with mandatory complexity declaration and fallback cascading.
"""
import json
import tempfile
import time
from pathlib import Path

import pytest

from cowork_to_code_bridge.model_router import (
    SCOPE_TO_FLAGS,
    TIER_TO_MODEL_ID,
    FallbackStrategy,
    ModelTier,
    PermissionScope,
    _get_cascade_order,
    _validate_model_preference,
    auto_select,
    get_routing_metadata,
    get_routing_recommendations,
    route_task,
    scope_to_flags,
    tier_to_model_id,
)

# ─────────────────────────────────────────────────────────────────────────── #
# Model Preference Validation
# ─────────────────────────────────────────────────────────────────────────── #


def test_validate_model_preference_required():
    """model_preference is MANDATORY — raises ValueError if None."""
    with pytest.raises(ValueError, match="MANDATORY"):
        _validate_model_preference(None)


def test_validate_model_preference_string():
    """Accepts string model names (case-insensitive)."""
    assert _validate_model_preference("haiku") == ModelTier.HAIKU
    assert _validate_model_preference("SONNET") == ModelTier.SONNET
    assert _validate_model_preference("OpUs") == ModelTier.OPUS
    assert _validate_model_preference("fable") == ModelTier.FABLE


def test_validate_model_preference_enum():
    """Accepts ModelTier enum directly."""
    assert _validate_model_preference(ModelTier.OPUS) == ModelTier.OPUS


def test_validate_model_preference_invalid():
    """Rejects invalid model names with clear error."""
    with pytest.raises(ValueError, match="Invalid model_preference"):
        _validate_model_preference("gpt-4")
    with pytest.raises(ValueError):
        _validate_model_preference("claude")


def test_validate_model_preference_type_error():
    """Rejects non-string, non-enum types."""
    with pytest.raises(TypeError):
        _validate_model_preference(123)
    with pytest.raises(TypeError):
        _validate_model_preference(["haiku"])


# ─────────────────────────────────────────────────────────────────────────── #
# Tier → Model ID Mapping (must stay in sync with run_claude.sh)
# ─────────────────────────────────────────────────────────────────────────── #


def test_tier_to_model_id_all_tiers():
    """Every tier resolves to its canonical concrete model ID."""
    assert tier_to_model_id("haiku") == "claude-haiku-4-5-20251001"
    assert tier_to_model_id("sonnet") == "claude-sonnet-4-6"
    assert tier_to_model_id("opus") == "claude-opus-4-8"
    assert tier_to_model_id("fable") == "claude-fable-5"


def test_tier_to_model_id_case_insensitive_and_enum():
    """Accepts uppercase strings and ModelTier enum members."""
    assert tier_to_model_id("OPUS") == "claude-opus-4-8"
    assert tier_to_model_id(ModelTier.FABLE) == "claude-fable-5"


def test_tier_to_model_id_unknown_raises():
    """An unknown tier surfaces loudly rather than silently defaulting."""
    with pytest.raises(ValueError, match="unknown model tier"):
        tier_to_model_id("gpt-4")


def test_tier_to_model_id_mapping_covers_every_tier():
    """No tier is missing from the canonical mapping."""
    assert set(TIER_TO_MODEL_ID) == set(ModelTier)


# ─────────────────────────────────────────────────────────────────────────── #
# Permission Scope (issue #47 — per-task sandboxing)
# ─────────────────────────────────────────────────────────────────────────── #


def test_scope_to_flags_all_scopes():
    """Every scope resolves to its canonical flag list."""
    assert scope_to_flags("plan") == ["--permission-mode", "plan"]
    assert scope_to_flags("readonly") == ["--allowedTools", "Read,Glob,Grep"]
    assert scope_to_flags("edit") == ["--allowedTools", "Read,Glob,Grep,Edit,Write"]
    # 'full' means "no extra restriction" → empty flag list.
    assert scope_to_flags("full") == []


def test_scope_to_flags_case_insensitive_and_enum():
    """Accepts uppercase strings and PermissionScope enum members."""
    assert scope_to_flags("PLAN") == ["--permission-mode", "plan"]
    assert scope_to_flags(PermissionScope.READONLY) == ["--allowedTools", "Read,Glob,Grep"]


def test_scope_to_flags_unknown_raises():
    """An unknown scope surfaces loudly rather than silently widening trust."""
    with pytest.raises(ValueError, match="unknown permission scope"):
        scope_to_flags("yolo")


def test_scope_to_flags_mapping_covers_every_scope():
    """No scope is missing from the canonical mapping."""
    assert set(SCOPE_TO_FLAGS) == set(PermissionScope)


def test_readonly_and_plan_scopes_grant_no_shell_or_write():
    """Sandboxed scopes must never expose shell or write tools."""
    for scope in ("plan", "readonly"):
        flags = " ".join(scope_to_flags(scope))
        assert "Bash" not in flags
        assert "Write" not in flags
        assert "Edit" not in flags


# ─────────────────────────────────────────────────────────────────────────── #
# Cascade Order Logic
# ─────────────────────────────────────────────────────────────────────────── #


def test_cascade_up_from_haiku():
    """CASCADE_UP from Haiku: Haiku → Sonnet → Opus → Fable."""
    order = _get_cascade_order(ModelTier.HAIKU, FallbackStrategy.CASCADE_UP)
    assert order == [ModelTier.HAIKU, ModelTier.SONNET, ModelTier.OPUS, ModelTier.FABLE]


def test_cascade_up_from_sonnet():
    """CASCADE_UP from Sonnet: Sonnet → Opus → Fable."""
    order = _get_cascade_order(ModelTier.SONNET, FallbackStrategy.CASCADE_UP)
    assert order == [ModelTier.SONNET, ModelTier.OPUS, ModelTier.FABLE]


def test_cascade_up_from_fable():
    """CASCADE_UP from Fable: just Fable (already at top)."""
    order = _get_cascade_order(ModelTier.FABLE, FallbackStrategy.CASCADE_UP)
    assert order == [ModelTier.FABLE]


def test_cascade_down_from_fable():
    """CASCADE_DOWN from Fable: Fable → Opus → Sonnet → Haiku."""
    order = _get_cascade_order(ModelTier.FABLE, FallbackStrategy.CASCADE_DOWN)
    assert order == [ModelTier.FABLE, ModelTier.OPUS, ModelTier.SONNET, ModelTier.HAIKU]


def test_cascade_down_from_sonnet():
    """CASCADE_DOWN from Sonnet: Sonnet → Haiku."""
    order = _get_cascade_order(ModelTier.SONNET, FallbackStrategy.CASCADE_DOWN)
    assert order == [ModelTier.SONNET, ModelTier.HAIKU]


def test_cascade_down_from_haiku():
    """CASCADE_DOWN from Haiku: just Haiku (already at bottom)."""
    order = _get_cascade_order(ModelTier.HAIKU, FallbackStrategy.CASCADE_DOWN)
    assert order == [ModelTier.HAIKU]


def test_fail_fast_strategy():
    """FAIL_FAST: only try the requested model, no fallback."""
    for tier in [ModelTier.HAIKU, ModelTier.SONNET, ModelTier.OPUS, ModelTier.FABLE]:
        order = _get_cascade_order(tier, FallbackStrategy.FAIL_FAST)
        assert order == [tier], f"FAIL_FAST should only return {tier}"


def test_cascade_with_string_strategy():
    """Cascade order accepts string strategy names."""
    order = _get_cascade_order(ModelTier.HAIKU, "cascade_up")
    assert order == [ModelTier.HAIKU, ModelTier.SONNET, ModelTier.OPUS, ModelTier.FABLE]


# ─────────────────────────────────────────────────────────────────────────── #
# route_task() Function
# ─────────────────────────────────────────────────────────────────────────── #


def test_route_task_requires_model_preference():
    """route_task() raises ValueError if model_preference is missing."""
    with pytest.raises(ValueError, match="MANDATORY"):
        route_task("scripts/test.sh", model_preference=None)


def test_route_task_accepts_valid_preference():
    """route_task() accepts valid model preferences and returns task_id."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/test.sh",
            args=["arg1"],
            model_preference="opus",
            bridge_root=bridge_root,
        )

        assert "task_id" in result
        assert result["status"] == "queued"
        assert result["requested_model"] == "opus"
        assert result["selected_model"] == "opus"
        assert result["fallback_used"] is False


def test_route_task_returns_routing_metadata():
    """route_task() return includes full routing metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/analyze.sh",
            args=["data.csv"],
            model_preference="sonnet",
            fallback_strategy="cascade_up",
            bridge_root=bridge_root,
        )

        assert "routing_metadata" in result
        routing = result["routing_metadata"]
        assert routing["requested_model"] == "sonnet"
        assert routing["selected_model"] == "sonnet"
        assert routing["fallback_strategy"] == "cascade_up"
        assert routing["fallback_used"] is False
        assert "cascade_order" in routing
        assert "ts_routed" in routing


def test_route_task_persists_routing_file():
    """route_task() stores routing metadata in routing/ folder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/test.sh",
            model_preference="haiku",
            bridge_root=bridge_root,
        )

        task_id = result["task_id"]
        routing_file = bridge_root / "routing" / f"{task_id}.json"
        assert routing_file.exists(), "Routing metadata should be persisted"

        routing_data = json.loads(routing_file.read_text())
        assert routing_data["selected_model"] == "haiku"


def test_route_task_atomic_write():
    """Routing metadata is written atomically (.tmp → rename)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/test.sh",
            model_preference="opus",
            bridge_root=bridge_root,
        )

        task_id = result["task_id"]
        routing_file = bridge_root / "routing" / f"{task_id}.json"
        tmp_file = routing_file.with_suffix(".json.tmp")

        # File should exist, temp file should not
        assert routing_file.exists()
        assert not tmp_file.exists()


def test_route_task_idempotency_key():
    """route_task() respects idempotency_key parameter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        key = "my-unique-key-123"
        result = route_task(
            "scripts/test.sh",
            model_preference="sonnet",
            idempotency_key=key,
            bridge_root=bridge_root,
        )

        # Task should be queued with the key
        assert result["status"] == "queued"


def test_route_task_cascade_up():
    """route_task() with CASCADE_UP includes full cascade in metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/test.sh",
            model_preference="haiku",
            fallback_strategy="cascade_up",
            bridge_root=bridge_root,
        )

        cascade = result["routing_metadata"]["cascade_order"]
        assert cascade == ["haiku", "sonnet", "opus", "fable"]


def test_route_task_cascade_down():
    """route_task() with CASCADE_DOWN includes full cascade in metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/test.sh",
            model_preference="fable",
            fallback_strategy="cascade_down",
            bridge_root=bridge_root,
        )

        cascade = result["routing_metadata"]["cascade_order"]
        assert cascade == ["fable", "opus", "sonnet", "haiku"]


def test_route_task_fail_fast():
    """route_task() with FAIL_FAST has single model in cascade."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/test.sh",
            model_preference="opus",
            fallback_strategy="fail_fast",
            bridge_root=bridge_root,
        )

        cascade = result["routing_metadata"]["cascade_order"]
        assert cascade == ["opus"]


# ─────────────────────────────────────────────────────────────────────────── #
# Routing Metadata Retrieval
# ─────────────────────────────────────────────────────────────────────────── #


def test_get_routing_metadata_exists():
    """get_routing_metadata() retrieves stored routing info."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/test.sh",
            model_preference="sonnet",
            bridge_root=bridge_root,
        )

        task_id = result["task_id"]
        routing_data = get_routing_metadata(task_id, bridge_root=bridge_root)

        assert routing_data is not None
        assert routing_data["selected_model"] == "sonnet"


def test_get_routing_metadata_not_found():
    """get_routing_metadata() returns None for non-existent task."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        (bridge_root / "routing").mkdir(exist_ok=True)

        result = get_routing_metadata("nonexistent_task_xyz", bridge_root=bridge_root)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────── #
# Routing Recommendations (Informational)
# ─────────────────────────────────────────────────────────────────────────── #


def test_get_routing_recommendations():
    """get_routing_recommendations() provides reference guidance."""
    recs = get_routing_recommendations("Analyze quarterly data")

    assert "recommended_tier" in recs
    assert "reasoning" in recs
    assert "can_use_cheaper" in recs
    assert "must_use_expensive" in recs
    # Default recommendation is Sonnet
    assert recs["recommended_tier"] == "sonnet"


def test_get_routing_recommendations_no_error():
    """get_routing_recommendations() doesn't fail on any input."""
    for task in [
        "",
        "x" * 1000,
        None,  # type check: our function accepts str but should handle gracefully
    ]:
        try:
            recs = get_routing_recommendations(task if task is not None else "")
            assert isinstance(recs, dict)
        except Exception as e:
            pytest.fail(f"get_routing_recommendations raised {type(e).__name__}: {e}")


# ─────────────────────────────────────────────────────────────────────────── #
# Auto-select heuristic (issue #33)
# ─────────────────────────────────────────────────────────────────────────── #


def test_auto_select_empty_defaults_to_sonnet():
    """No description → safe default of sonnet/medium, flagged as default."""
    for empty in ["", None, "   "]:
        sel = auto_select(empty)
        assert sel["tier"] == "sonnet"
        assert sel["effort"] == "medium"
        assert sel["is_default"] is True


def test_auto_select_haiku_signals():
    """Lightweight verbs route to haiku/low."""
    sel = auto_select("Summarize this changelog and classify each entry")
    assert sel["tier"] == "haiku"
    assert sel["effort"] == "low"
    assert sel["is_default"] is False
    assert "summarize" in sel["matched_signals"]["haiku"]


def test_auto_select_sonnet_signals():
    """Standard coding work routes to sonnet/medium."""
    sel = auto_select("Implement a parser and write tests for the endpoint")
    assert sel["tier"] == "sonnet"
    assert sel["effort"] == "medium"


def test_auto_select_opus_signals():
    """Architecture/design work routes to opus/high."""
    sel = auto_select("Design the cross-module architecture for the new system")
    assert sel["tier"] == "opus"
    assert sel["effort"] == "high"


def test_auto_select_fable_signals():
    """Deepest-reasoning cues route to fable/max."""
    sel = auto_select("Prove the theorem and design a novel algorithm")
    assert sel["tier"] == "fable"
    assert sel["effort"] == "max"


def test_auto_select_highest_tier_wins():
    """A task with both haiku and opus signals routes to the higher tier."""
    sel = auto_select("Summarize the design and architect the refactor")
    assert sel["tier"] == "opus"


def test_auto_select_effort_bumped_up():
    """A 'thorough' cue raises effort one step above the tier default."""
    sel = auto_select("Implement the feature thoroughly")  # sonnet → medium → high
    assert sel["tier"] == "sonnet"
    assert sel["effort"] == "high"


def test_auto_select_effort_bumped_down():
    """A 'quick' cue lowers effort one step below the tier default."""
    sel = auto_select("Just implement a quick fix")  # sonnet → medium → low
    assert sel["tier"] == "sonnet"
    assert sel["effort"] == "low"


def test_auto_select_effort_bump_clamps():
    """Effort bumps never fall off either end of the scale."""
    top = auto_select("Prove the theorem exhaustively")  # fable → max, up → clamps at max
    assert top["effort"] == "max"
    low = auto_select("Just summarize quickly")  # haiku → low, down → clamps at low
    assert low["effort"] == "low"


# ── Whole-word matching: signals must not fire as substrings of larger words ──

@pytest.mark.parametrize("text, buried_signal", [
    ("Update the address book UI", "add"),        # 'add' inside 'address'
    ("Listen for incoming webhooks", "list"),     # 'list' inside 'listen'
    ("Encode the payload as base64", "code"),      # 'code' inside 'encode'
    ("Summarize the latest logs", "test"),         # 'test' inside 'latest'
])
def test_auto_select_no_substring_false_positive(text, buried_signal):
    """A signal buried inside a larger word must NOT fire (whole-word matching)."""
    sel = auto_select(text)
    all_fired = [s for hits in sel["matched_signals"].values() for s in hits]
    assert buried_signal not in all_fired, (
        f"{buried_signal!r} wrongly fired on {text!r} (matched: {all_fired})"
    )


def test_auto_select_latest_logs_route_haiku():
    """'Summarize the latest logs' routes to haiku — 'latest' no longer bumps to sonnet."""
    sel = auto_select("Summarize the latest logs")
    assert sel["tier"] == "haiku"


def test_auto_select_adjust_does_not_trigger_just():
    """The 'just' down-signal must not fire inside 'adjust'."""
    sel = auto_select("Adjust the retry backoff and add a guard")
    assert sel["effort"] == "medium"  # sonnet default, no down-bump from 'adjust'


@pytest.mark.parametrize("text", [
    "Design it in-depth",             # hyphenated 'in depth'
    "Design it in depth",             # spaced
])
def test_auto_select_hyphen_and_space_phrases_equivalent(text):
    """Multi-word signals match both their hyphenated and spaced spellings."""
    sel = auto_select(text)
    assert sel["tier"] == "opus"
    assert sel["effort"] == "xhigh"  # opus high, bumped up by 'in depth'


@pytest.mark.parametrize("text", [
    "Refactor the cross-module imports",
    "Refactor the cross module imports",
])
def test_auto_select_cross_module_both_spellings(text):
    """'cross-module' and 'cross module' both route to opus."""
    sel = auto_select(text)
    assert sel["tier"] == "opus"


@pytest.mark.parametrize("text", ["Make it a one-liner", "Make it a one liner"])
def test_auto_select_one_liner_both_spellings_bump_down(text):
    """'one-liner'/'one liner' both drop effort a step."""
    sel = auto_select(f"Write code — {text}")  # sonnet/medium → down → low
    assert sel["effort"] == "low"


def test_get_routing_recommendations_uses_heuristic():
    """The public recommendation surface reflects the heuristic and flags cheaper/pricier."""
    recs = get_routing_recommendations("Summarize the release notes")
    assert recs["recommended_tier"] == "haiku"
    assert recs["recommended_effort"] == "low"
    assert recs["can_use_cheaper"] is True
    assert recs["must_use_expensive"] is False

    recs = get_routing_recommendations("Architect the distributed system")
    assert recs["recommended_tier"] == "opus"
    assert recs["can_use_cheaper"] is False
    assert recs["must_use_expensive"] is True


def test_get_routing_recommendations_default_still_sonnet():
    """Backwards-compat: a description with no signal still recommends sonnet."""
    recs = get_routing_recommendations("Analyze quarterly data")
    assert recs["recommended_tier"] == "sonnet"
    assert recs["can_use_cheaper"] is False
    assert recs["must_use_expensive"] is False


# ─────────────────────────────────────────────────────────────────────────── #
# Integration Tests
# ─────────────────────────────────────────────────────────────────────────── #


def test_route_task_full_workflow():
    """Full workflow: route task → retrieve metadata → verify consistency."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        # 1. Route a task
        route_result = route_task(
            "scripts/complex_analysis.sh",
            args=["large_dataset.csv"],
            model_preference="opus",
            fallback_strategy="cascade_up",
            bridge_root=bridge_root,
        )

        task_id = route_result["task_id"]

        # 2. Verify task was queued
        assert route_result["status"] == "queued"
        assert route_result["selected_model"] == "opus"

        # 3. Retrieve routing metadata
        routing_data = get_routing_metadata(task_id, bridge_root=bridge_root)
        assert routing_data is not None

        # 4. Verify consistency between route_result and stored metadata
        assert routing_data["selected_model"] == route_result["selected_model"]
        assert routing_data["requested_model"] == route_result["requested_model"]
        assert routing_data["fallback_strategy"] == "cascade_up"


def test_route_task_all_tiers():
    """route_task() works for all model tiers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        for tier in ["haiku", "sonnet", "opus", "fable"]:
            result = route_task(
                "scripts/test.sh",
                model_preference=tier,
                bridge_root=bridge_root,
            )

            assert result["selected_model"] == tier
            assert result["status"] == "queued"


# ─────────────────────────────────────────────────────────────────────────── #
# Comprehensive Audit Trail Validation
# ─────────────────────────────────────────────────────────────────────────── #


def test_audit_trail_cascade_up_full_chain():
    """Full cascade_up chain: Haiku → Sonnet → Opus → Fable all in audit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/analysis.sh",
            model_preference="haiku",
            fallback_strategy="cascade_up",
            bridge_root=bridge_root,
        )

        routing = get_routing_metadata(result["task_id"], bridge_root=bridge_root)
        assert routing["cascade_order"] == ["haiku", "sonnet", "opus", "fable"]
        assert routing["requested_model"] == "haiku"
        assert routing["selected_model"] == "haiku"
        assert routing["fallback_used"] is False


def test_audit_trail_cascade_down_full_chain():
    """Full cascade_down chain: Fable → Opus → Sonnet → Haiku all in audit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/reasoning.sh",
            model_preference="fable",
            fallback_strategy="cascade_down",
            bridge_root=bridge_root,
        )

        routing = get_routing_metadata(result["task_id"], bridge_root=bridge_root)
        assert routing["cascade_order"] == ["fable", "opus", "sonnet", "haiku"]
        assert routing["requested_model"] == "fable"


@pytest.mark.parametrize(
    "tier,strategy,expected_cascade",
    [
        # All cascade_up combos
        ("haiku", "cascade_up", ["haiku", "sonnet", "opus", "fable"]),
        ("sonnet", "cascade_up", ["sonnet", "opus", "fable"]),
        ("opus", "cascade_up", ["opus", "fable"]),
        ("fable", "cascade_up", ["fable"]),
        # All cascade_down combos
        ("fable", "cascade_down", ["fable", "opus", "sonnet", "haiku"]),
        ("opus", "cascade_down", ["opus", "sonnet", "haiku"]),
        ("sonnet", "cascade_down", ["sonnet", "haiku"]),
        ("haiku", "cascade_down", ["haiku"]),
        # All fail_fast (no cascade)
        ("haiku", "fail_fast", ["haiku"]),
        ("sonnet", "fail_fast", ["sonnet"]),
        ("opus", "fail_fast", ["opus"]),
        ("fable", "fail_fast", ["fable"]),
    ],
)
def test_audit_trail_all_combinations(tier, strategy, expected_cascade):
    """Audit trail validates every tier + strategy combination."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        result = route_task(
            "scripts/test.sh",
            model_preference=tier,
            fallback_strategy=strategy,
            bridge_root=bridge_root,
        )

        routing = get_routing_metadata(result["task_id"], bridge_root=bridge_root)
        assert routing["cascade_order"] == expected_cascade, \
            f"Cascade mismatch for {tier} + {strategy}"


def test_audit_trail_timestamp_validity():
    """Audit trail timestamps are valid Unix timestamps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        before = time.time()
        result = route_task(
            "scripts/test.sh",
            model_preference="opus",
            bridge_root=bridge_root,
        )
        after = time.time()

        routing = get_routing_metadata(result["task_id"], bridge_root=bridge_root)
        ts = routing["ts_routed"]

        # Timestamp should be between before and after
        assert before <= ts <= after


def test_audit_trail_isolation_per_task():
    """Each task has independent audit trail record."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        for sub in ("queue", "results", "routing"):
            (bridge_root / sub).mkdir(exist_ok=True)

        # Route multiple tasks
        tasks = []
        for tier in ["haiku", "sonnet", "opus", "fable"]:
            result = route_task(
                f"scripts/{tier}_task.sh",
                model_preference=tier,
                fallback_strategy="cascade_up",
                bridge_root=bridge_root,
            )
            tasks.append((result["task_id"], tier))

        # Each should have independent routing record
        for task_id, expected_tier in tasks:
            routing = get_routing_metadata(task_id, bridge_root=bridge_root)
            assert routing is not None
            assert routing["requested_model"] == expected_tier
