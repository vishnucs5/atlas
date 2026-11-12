# atlas-policy

Action Firewall and Policy Engine for the ATLAS computer-use runtime.
Intercepts and evaluates every proposed `ComputerAction` before execution to ensure strict risk classification, human-in-the-loop authorization, domain allowlisting, and destructive command detection.
Zero external runtime dependencies beyond `atlas-core` and `pydantic`.
