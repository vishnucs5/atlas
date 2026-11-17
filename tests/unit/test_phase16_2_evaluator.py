"""Tests for SafeExpressionEvaluator in atlas_process."""

import pytest
from atlas_process.evaluator import (
    SafeExpressionEvaluator,
    UnsafeExpressionError,
)


def test_evaluator_comparisons_and_literals():
    evaluator = SafeExpressionEvaluator()

    assert evaluator.evaluate("amount > 100", {"amount": 250}) is True
    assert evaluator.evaluate("amount > 100", {"amount": 50}) is False
    assert evaluator.evaluate("amount >= 100", {"amount": 100}) is True
    assert evaluator.evaluate("status == 'APPROVED'", {"status": "APPROVED"}) is True
    assert evaluator.evaluate("status != 'REJECTED'", {"status": "APPROVED"}) is True
    assert evaluator.evaluate("priority in ['HIGH', 'CRITICAL']", {"priority": "CRITICAL"}) is True
    assert evaluator.evaluate("priority in ['HIGH', 'CRITICAL']", {"priority": "LOW"}) is False


def test_evaluator_boolean_and_arithmetic():
    evaluator = SafeExpressionEvaluator()

    assert (
        evaluator.evaluate("amount * 2 > 150 and approved", {"amount": 100, "approved": True})
        is True
    )
    assert (
        evaluator.evaluate("amount * 2 > 150 and approved", {"amount": 100, "approved": False})
        is False
    )
    assert evaluator.evaluate("not flagged or score >= 80", {"flagged": True, "score": 85}) is True
    assert evaluator.evaluate("not flagged or score >= 80", {"flagged": True, "score": 70}) is False


def test_evaluator_subscript_and_none():
    evaluator = SafeExpressionEvaluator()

    assert evaluator.evaluate("metadata['tier'] == 'gold'", {"metadata": {"tier": "gold"}}) is True
    assert evaluator.evaluate("missing_var is None", {}) is True
    assert evaluator.evaluate("existing_var is not None", {"existing_var": 123}) is True


def test_evaluator_blocks_arbitrary_function_calls():
    evaluator = SafeExpressionEvaluator()

    with pytest.raises(UnsafeExpressionError):
        evaluator.evaluate("__import__('os').system('dir')")

    with pytest.raises(UnsafeExpressionError):
        evaluator.evaluate("print('hello')")


def test_evaluator_blocks_attribute_access():
    evaluator = SafeExpressionEvaluator()

    with pytest.raises(UnsafeExpressionError):
        evaluator.evaluate("obj.__class__.__mro__", {"obj": "test"})


def test_evaluator_length_and_depth_limits():
    evaluator = SafeExpressionEvaluator()

    oversized = "a == " + "b and " * 120 + "c"
    with pytest.raises(UnsafeExpressionError):
        evaluator.evaluate(oversized)

    nested = "(1 + (2 + (3 + (4 + (5 + (6 + (7 + (8 + (9 + (10 + (11 + 12)))))))))))"
    with pytest.raises(UnsafeExpressionError):
        evaluator.evaluate(nested)
