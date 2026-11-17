"""Safe, deterministic, AST-based conditional expression evaluator for ATLAS enterprise processes.

Enforces strict expression safety:
- Prohibits eval, exec, arbitrary function execution, attribute traversal, and OS/network imports.
- Supports comparisons (==, !=, <, <=, >, >=, in, not in, is, is not), boolean operations (and, or, not),
  basic arithmetic (+, -, *, /, %), literals, and context variable resolution.
- Enforces strict length and AST complexity bounds.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Any


class ExpressionError(Exception):
    """Base exception for expression parsing and evaluation errors."""


class UnsafeExpressionError(ExpressionError):
    """Raised when an expression contains disallowed AST constructs, attribute access, or functions."""


class ExpressionEvaluationError(ExpressionError):
    """Raised when expression evaluation encounters a runtime error (e.g., type mismatch, division by zero)."""


class SafeExpressionEvaluator:
    """Deterministic, bounded expression evaluator using Python AST validation."""

    MAX_EXPRESSION_LENGTH = 500
    MAX_NODE_COUNT = 50
    MAX_DEPTH = 10

    # Whitelist of allowed comparison operators
    _CMP_OPS: dict[type, Callable[[Any, Any], Any]] = {
        ast.Eq: lambda a, b: a == b,
        ast.NotEq: lambda a, b: a != b,
        ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b,
        ast.Gt: lambda a, b: a > b,
        ast.GtE: lambda a, b: a >= b,
        ast.In: lambda a, b: a in b,
        ast.NotIn: lambda a, b: a not in b,
        ast.Is: lambda a, b: a is b,
        ast.IsNot: lambda a, b: a is not b,
    }

    # Whitelist of allowed binary operators
    _BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b if b != 0 else float("inf"),
        ast.Mod: lambda a, b: a % b if b != 0 else 0,
    }

    # Whitelist of allowed unary operators
    _UNARY_OPS: dict[type, Callable[[Any], Any]] = {
        ast.Not: lambda a: not a,
        ast.USub: lambda a: -a,
        ast.UAdd: lambda a: +a,
    }

    def evaluate(self, expression: str, context: dict[str, Any] | None = None) -> bool:
        """Parse, validate, and evaluate an expression against the supplied variable context.

        Returns True if the expression evaluates to truthy, False otherwise.
        """
        expr = expression.strip()
        if not expr:
            return True

        if len(expr) > self.MAX_EXPRESSION_LENGTH:
            raise UnsafeExpressionError(
                f"Expression length {len(expr)} exceeds maximum permitted length of {self.MAX_EXPRESSION_LENGTH}"
            )

        try:
            parsed = ast.parse(expr, mode="eval")
        except SyntaxError as exc:
            raise ExpressionEvaluationError(f"Malformed expression syntax: {exc}") from exc

        # Validate AST safety
        node_count = sum(1 for _ in ast.walk(parsed))
        if node_count > self.MAX_NODE_COUNT:
            raise UnsafeExpressionError(
                f"Expression complexity {node_count} nodes exceeds maximum limit of {self.MAX_NODE_COUNT}"
            )

        ctx = context or {}
        result = self._eval_node(parsed.body, ctx, depth=0)
        return bool(result)

    def _eval_node(self, node: ast.AST, context: dict[str, Any], depth: int) -> Any:
        if depth > self.MAX_DEPTH:
            raise UnsafeExpressionError(
                f"Expression nesting depth exceeds limit of {self.MAX_DEPTH}"
            )

        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            # Resolve variable name from context
            if node.id in ("True", "true"):
                return True
            if node.id in ("False", "false"):
                return False
            if node.id in ("None", "null", "nil"):
                return None
            return context.get(node.id)

        if isinstance(node, ast.UnaryOp):
            unary_fn = self._UNARY_OPS.get(type(node.op))
            if not unary_fn:
                raise UnsafeExpressionError(f"Disallowed unary operator: {type(node.op).__name__}")
            operand = self._eval_node(node.operand, context, depth + 1)
            try:
                return unary_fn(operand)
            except Exception as exc:
                raise ExpressionEvaluationError(f"Error evaluating unary operation: {exc}") from exc

        if isinstance(node, ast.BinOp):
            bin_fn = self._BIN_OPS.get(type(node.op))
            if not bin_fn:
                raise UnsafeExpressionError(f"Disallowed binary operator: {type(node.op).__name__}")
            left = self._eval_node(node.left, context, depth + 1)
            right = self._eval_node(node.right, context, depth + 1)
            try:
                return bin_fn(left, right)
            except Exception as exc:
                raise ExpressionEvaluationError(
                    f"Error evaluating binary operation: {exc}"
                ) from exc

        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for val_node in node.values:
                    val = self._eval_node(val_node, context, depth + 1)
                    if not val:
                        return False
                return True
            if isinstance(node.op, ast.Or):
                for val_node in node.values:
                    val = self._eval_node(val_node, context, depth + 1)
                    if val:
                        return True
                return False
            raise UnsafeExpressionError(f"Disallowed boolean operator: {type(node.op).__name__}")

        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, context, depth + 1)
            for op, comparator_node in zip(node.ops, node.comparators, strict=False):
                cmp_fn = self._CMP_OPS.get(type(op))
                if not cmp_fn:
                    raise UnsafeExpressionError(
                        f"Disallowed comparison operator: {type(op).__name__}"
                    )
                right = self._eval_node(comparator_node, context, depth + 1)
                try:
                    if left is None or right is None:
                        # Allow equality checks with None
                        if type(op) in (ast.Eq, ast.Is):
                            matched = left is right
                        elif type(op) in (ast.NotEq, ast.IsNot):
                            matched = left is not right
                        else:
                            matched = False
                    else:
                        matched = cmp_fn(left, right)
                except TypeError:
                    matched = False
                if not matched:
                    return False
                left = right
            return True

        if isinstance(node, ast.List):
            return [self._eval_node(elt, context, depth + 1) for elt in node.elts]

        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(elt, context, depth + 1) for elt in node.elts)

        if isinstance(node, ast.Subscript):
            target = self._eval_node(node.value, context, depth + 1)
            slice_val = self._eval_node(node.slice, context, depth + 1)
            if isinstance(target, dict):
                return target.get(slice_val)
            if isinstance(target, (list, tuple)) and isinstance(slice_val, int):
                if 0 <= slice_val < len(target):
                    return target[slice_val]
                return None
            return None

        # Any other AST node (Call, Attribute, Import, Lambda, Yield, etc.) is strictly prohibited
        raise UnsafeExpressionError(
            f"Disallowed AST expression construct: '{type(node).__name__}'. "
            "Arbitrary function calls, attribute access, and code execution are strictly blocked."
        )
