"""Unit tests for SafetyEngine, action idempotency, and budget limits."""

import pytest
from atlas_agent.safety import (
    ActionLoopDetectedError,
    BudgetExhaustedError,
    SafetyEngine,
)


def test_action_idempotency_loop_detection():
    """Verify SafetyEngine detects repeating duplicate actions and breaks infinite loops."""
    safety = SafetyEngine(consecutive_duplicate_threshold=3)

    # First and second identical actions should pass
    safety.check_and_record_action("browser.click", {"strategy": "css", "value": "#btn"}, {})
    safety.check_and_record_action("browser.click", {"strategy": "css", "value": "#btn"}, {})

    # Third consecutive identical action triggers ActionLoopDetectedError
    with pytest.raises(ActionLoopDetectedError):
        safety.check_and_record_action("browser.click", {"strategy": "css", "value": "#btn"}, {})


def test_action_idempotency_resets_on_distinct_action():
    """Verify performing a different action resets consecutive duplicate count."""
    safety = SafetyEngine(consecutive_duplicate_threshold=3)

    safety.check_and_record_action("browser.click", "#btn", {})
    safety.check_and_record_action("browser.click", "#btn", {})
    # Different action resets
    safety.check_and_record_action("browser.type", "#input", {"text": "hello"})
    # Allowed again
    safety.check_and_record_action("browser.click", "#btn", {})


def test_budget_exhaustion_checks():
    """Verify SafetyEngine raises BudgetExhaustedError when hard ceilings are exceeded."""
    safety = SafetyEngine()

    # Normal budget passes
    safety.check_budget(
        current_step=5,
        max_steps=10,
        total_tokens=5000,
        max_tokens=100000,
        total_cost=0.05,
        max_cost=1.0,
        elapsed_seconds=30.0,
        timeout_seconds=300.0,
    )

    # Step ceiling exceeded
    with pytest.raises(BudgetExhaustedError) as exc_step:
        safety.check_budget(
            current_step=11,
            max_steps=10,
            total_tokens=1000,
            max_tokens=100000,
            total_cost=0.01,
            max_cost=1.0,
            elapsed_seconds=10.0,
            timeout_seconds=300.0,
        )
    assert "Step limit exceeded" in str(exc_step.value)

    # Cost ceiling exceeded
    with pytest.raises(BudgetExhaustedError) as exc_cost:
        safety.check_budget(
            current_step=5,
            max_steps=10,
            total_tokens=1000,
            max_tokens=100000,
            total_cost=1.50,
            max_cost=1.0,
            elapsed_seconds=10.0,
            timeout_seconds=300.0,
        )
    assert "Cost budget exceeded" in str(exc_cost.value)

    # Timeout exceeded
    with pytest.raises(BudgetExhaustedError) as exc_time:
        safety.check_budget(
            current_step=5,
            max_steps=10,
            total_tokens=1000,
            max_tokens=100000,
            total_cost=0.05,
            max_cost=1.0,
            elapsed_seconds=305.0,
            timeout_seconds=300.0,
        )
    assert "Timeout exceeded" in str(exc_time.value)
