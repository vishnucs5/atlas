# ATLAS CLI Release Process & Governance Runbook

## 1. Release Philosophy & Governance Gates

ATLAS CLI releases require explicit, multi-stage human authorization. Release candidates (RCs) are produced deterministically and held behind governance gates before physical distribution.

---

## 2. Release Preparation Checklist

Before producing a release candidate, verify the following 7 criteria:

1. **Git Provenance**: Clean working tree on `feat/atlas-cli-production-release` branched from approved ancestors.
2. **Full Monorepo Tests**: 100% green tests across all packages (`uv run pytest -v`).
3. **Static Security Scan**: Zero unapproved vulnerabilities via `python scripts/audit_dependencies.py --severity MODERATE`.
4. **Code Quality**: Clean `uv run ruff check .` and `uv run ruff format --check .`.
5. **Reproducible Build**: Wheel and source distribution built using `uv build --package atlas-cli`.
6. **SBOM & Checksums**: Software Bill of Materials and SHA-256 digests generated in `dist/`.
7. **Performance Verification**: All benchmarks meet P95 latency thresholds without memory leaks.

---

## 3. Release Candidate Packaging Commands

```bash
# 1. Clean dist directory
rm -rf dist/
mkdir -p dist/

# 2. Build Python wheels and source distributions
uv build --package atlas-cli

# 3. Generate CycloneDX SBOM and SHA-256 Checksums
uv run python scripts/generate_sbom.py

# 4. Run performance benchmark suite
uv run python scripts/benchmark_cli_performance.py

# 5. Run live dependency security audit gate
uv run python scripts/audit_dependencies.py --severity MODERATE
```

---

## 4. Final Governance Boundary

> [!CAUTION]
> The release candidate is prepared locally. **Do NOT**:
> - Push to a remote repository.
> - Publish packages to PyPI or internal registries.
> - Publish binaries or release tags.
> - Merge to `master`.
>
> Stop at the release candidate stage and wait for explicit human release authorization.
