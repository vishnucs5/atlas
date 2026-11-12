# ATLAS Engineering Constitution

Mandatory rules for every contributor, subagent, and model operating in this repository:

1. **Architecture Ownership**: Core owns orchestration, lifecycle, and tool contracts. Low-level drivers implement interfaces; they never own planning or planning state.
2. **Action Firewall**: The model makes decisions; ATLAS controls execution. No model adapter or execution worker may execute an action without authorization.
3. **Zero-Dependency Core**: `packages/atlas-core` must NEVER import external drivers, OS-specific APIs, or database engines.
4. **No Placeholders**: Never write dummy or placeholder implementations in production code paths.
5. **No Swallowing Exceptions**: Errors must be structured, logged with context, and handled via recovery or failure transitions.
6. **No Secret Leaks**: Credentials, keys, and tokens must never appear in logs, prompts, or screenshots.
7. **Verification Invariant**: An action is never reported as successful without deterministic post-condition verification.
8. **Durable Continuity**: Record all progress and blockers in `docs/PROJECT_STATUS.md` and `docs/IMPLEMENTATION_PLAN.md`.
