# ATLAS Phase 16.2 Safe Conditional Evaluator
## Secure, Sandboxed AST Evaluation for Dynamic Process Branching

**Date:** 2026-11-17  
**Module:** `packages/atlas-process/src/atlas_process/evaluator.py`  
**Verification Suite:** `tests/unit/test_phase16_2_evaluator.py`  

---

## 1. Finding Background (REM-16.1-04)

In Phase 16.0, `ProcessExecutionEngine._evaluate_conditions(tdef, instance)` was discovered to be an empty stub:
```python
# Phase 16.0 vulnerable code:
for cond in tdef.conditions:
    pass
return True
```
Every conditional branch returned `True` regardless of the variables. A process intended to branch conditionally (e.g. `amount > 10000 -> ManualApproval` vs `amount <= 10000 -> AutoApprove`) would always branch incorrectly.

Moreover, naive fixes using Python's built-in `eval()` or `exec()` introduce Critical Remote Code Execution (RCE) vulnerabilities, allowing untrusted workflow parameters to execute arbitrary code on host systems.

---

## 2. Secure AST Architecture (`SafeExpressionEvaluator`)

Phase 16.2 introduces `SafeExpressionEvaluator`, implementing strict AST parsing and validation:

```mermaid
flowchart TD
    Expr["Expression String e.g. 'amount > 5000 and region == \"US\"'"] --> LengthCheck["Length Check (< 500 chars)"]
    LengthCheck --> ASTParse["ast.parse(mode='eval')"]
    ASTParse --> DepthCheck["AST Depth Traversal (Depth <= 10)"]
    DepthCheck --> NodeAllowlist{"Strict Node Allowlist Check"}
    
    NodeAllowlist -->|Prohibited Node e.g. Call, Import, Attribute| Reject["Raise UnsafeExpressionError"]
    NodeAllowlist -->|Allowed Nodes Only| SafeEval["Safe Tree Recursive Walk"]
    
    SafeEval --> ContextLookup["Context Variable Resolution (instance.variables)"]
    ContextLookup --> Result["Deterministic Boolean Evaluation (True / False)"]
```

### 2.1 Security Controls & Guardrails:
1. **Strict Node Allowlist:**
   - Permitted: `ast.Expression`, `ast.Compare`, `ast.UnaryOp`, `ast.BinOp`, `ast.BoolOp`, `ast.Name`, `ast.Constant`.
   - Operators allowed: `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`, `and`, `or`, `not`, `+`, `-`, `*`, `/`, `%`.
   - Strictly forbidden: `ast.Call` (no functions like `eval`, `exec`, `open`, `os.system`), `ast.Attribute` (no traversal like `__class__`, `__subclasses__`), `ast.Import` / `ast.ImportFrom`, `ast.Lambda`, comprehensions.
2. **Resource Exhaustion Defense:**
   - Maximum expression length enforced: 500 characters.
   - Maximum AST recursion depth enforced: 10 levels (prevents stack overflow attacks via deeply nested parenthesis).
3. **Identifier Sandboxing:**
   - Variable names are looked up strictly from the caller-provided context dictionary (`instance.variables`).
   - Undefined variables evaluate to `None` without raising uncaught exceptions or leaking global/builtin scopes.
4. **Integration with Engine:**
   - In `engine.py`, `_evaluate_conditions()` calls `self._evaluator.evaluate(cond.expression, instance.variables)`.
   - If evaluated to `True`, the target task ID is scheduled; if `False`, the branch is skipped deterministically.
