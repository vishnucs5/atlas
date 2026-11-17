# ATLAS Phase 16 Test Strategy

Details acceptance testing methodology, fault injection scenarios, and regression verification for Phase 16.

## 1. Test Layers
1. **Unit & Contract Tests**: Pydantic schema validation, cycle detection, state machine invariants.
2. **Acceptance Scenarios**: 45 deterministic end-to-end scenarios (`tests/acceptance/test_phase16_acceptance.py`).
3. **Fault Injection**:
   - Stale worker fencing tokens.
   - Worker lease expirations.
   - Process restart recovery.
   - External timeout during saga transactions.
   - Connector consecutive failures and circuit breaker trips.
   - Parameter tampering during approval.
4. **Monorepo Regression**: Full execution across all workspace packages (781 tests).
