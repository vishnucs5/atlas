"""SemVer parsing, constraint satisfaction, and topological dependency resolution."""

import re
from typing import Any

from atlas_marketplace.models import PackageDependency


class DependencyResolutionError(Exception):
    """Base error for package dependency resolution failures."""


class CircularDependencyError(DependencyResolutionError):
    """Raised when package dependencies form a cycle."""


class IncompatibleDependencyError(DependencyResolutionError):
    """Raised when dependency constraints cannot be satisfied."""


def parse_semver(version_str: str) -> tuple[int, int, int]:
    """Parse a Semantic Version string into (major, minor, patch) tuple."""
    clean = version_str.split("-")[0].split("+")[0].strip()
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", clean)
    if not match:
        raise ValueError(f"Cannot parse SemVer: '{version_str}'")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def matches_single_constraint(v_tuple: tuple[int, int, int], expr: str) -> bool:
    """Evaluate whether a parsed version tuple satisfies a single constraint expression."""
    expr = expr.strip()
    if expr in ("*", ""):
        return True

    # Caret compatible: ^1.2.3 -> >=1.2.3, <2.0.0
    if expr.startswith("^"):
        target = parse_semver(expr[1:])
        next_major = (target[0] + 1, 0, 0)
        return target <= v_tuple < next_major

    # Tilde: ~1.2.3 -> >=1.2.3, <1.3.0
    if expr.startswith("~"):
        target = parse_semver(expr[1:])
        next_minor = (target[0], target[1] + 1, 0)
        return target <= v_tuple < next_minor

    # Operators
    if expr.startswith(">="):
        return v_tuple >= parse_semver(expr[2:])
    elif expr.startswith("<="):
        return v_tuple <= parse_semver(expr[2:])
    elif expr.startswith(">"):
        return v_tuple > parse_semver(expr[1:])
    elif expr.startswith("<"):
        return v_tuple < parse_semver(expr[1:])
    elif expr.startswith("="):
        return v_tuple == parse_semver(expr[1:])
    else:
        # Exact match
        return v_tuple == parse_semver(expr)


def matches_constraint(version_str: str, constraint_str: str) -> bool:
    """Evaluate if a version string satisfies comma-separated SemVer constraints."""
    v_tuple = parse_semver(version_str)
    clauses = [c.strip() for c in constraint_str.split(",") if c.strip()]
    if not clauses:
        return True
    return all(matches_single_constraint(v_tuple, c) for c in clauses)


class DependencyResolver:
    """Resolves transitive dependency graphs with version constraint satisfaction and cycle detection."""

    def __init__(self, available_packages: dict[str, list[str]]) -> None:
        """available_packages: dict mapping package_id -> list of available version strings."""
        self.available_packages = available_packages

    def find_best_version(self, package_id: str, constraint: str) -> str:
        """Find the highest available version for package_id satisfying constraint."""
        versions = self.available_packages.get(package_id, [])
        if not versions:
            raise IncompatibleDependencyError(
                f"Package '{package_id}' is not available in the registry."
            )

        matching = []
        for v in versions:
            try:
                if matches_constraint(v, constraint):
                    matching.append(v)
            except ValueError:
                continue

        if not matching:
            raise IncompatibleDependencyError(
                f"No available version of '{package_id}' satisfies constraint '{constraint}'. "
                f"Available versions: {versions}"
            )

        # Sort descending by semver tuple
        matching.sort(key=parse_semver, reverse=True)
        return matching[0]

    def resolve(
        self,
        root_package_id: str,
        root_dependencies: list[PackageDependency],
        package_dependency_lookup: Any,  # Callable[[package_id, version], list[PackageDependency]]
    ) -> list[tuple[str, str]]:
        """Resolve full transitive dependency graph returning installation order (leaves first)."""
        resolved: dict[str, str] = {}  # package_id -> selected_version
        visited: set[str] = set()
        visiting: set[str] = set()
        order: list[tuple[str, str]] = []

        def _dfs(pkg_id: str, constraint: str, deps: list[PackageDependency]) -> None:
            if pkg_id in visiting:
                raise CircularDependencyError(
                    f"Circular dependency detected involving package '{pkg_id}'."
                )

            if pkg_id in visited:
                # Verify existing selection satisfies this new constraint
                existing_v = resolved[pkg_id]
                if not matches_constraint(existing_v, constraint):
                    raise IncompatibleDependencyError(
                        f"Version conflict for '{pkg_id}': resolved version '{existing_v}' "
                        f"does not satisfy constraint '{constraint}'."
                    )
                return

            visiting.add(pkg_id)

            # Select best version
            selected_v = self.find_best_version(pkg_id, constraint)
            resolved[pkg_id] = selected_v

            # Resolve transitive dependencies
            child_deps = package_dependency_lookup(pkg_id, selected_v)
            for child in child_deps:
                _dfs(child.package_id, child.version_constraint, [])

            visiting.remove(pkg_id)
            visited.add(pkg_id)
            order.append((pkg_id, selected_v))

        for dep in root_dependencies:
            _dfs(dep.package_id, dep.version_constraint, [])

        return order
