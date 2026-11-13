"""Unit tests verifying MarketplaceRegistry, SemVer DependencyResolver, and installation lifecycle."""

import pytest
from atlas_core.contracts.agent import AgentCapability
from atlas_marketplace.models import (
    PackageDependency,
    PackageManifest,
    PackageType,
    PublisherIdentity,
    WorkflowGraphDefinition,
    WorkflowNodeDefinition,
)
from atlas_marketplace.package import (
    PackageSignatureError,
    build_package_archive,
)
from atlas_marketplace.registry import (
    MarketplaceRegistry,
    PackageStatus,
)
from atlas_marketplace.resolver import (
    CircularDependencyError,
    DependencyResolver,
    IncompatibleDependencyError,
    matches_constraint,
    parse_semver,
)


def _make_archive(
    pkg_id: str,
    version: str,
    deps: list[PackageDependency] | None = None,
    key: str = "test_key",
    pub_id: str = "pub_test",
) -> bytes:
    """Helper to build signed package archive for testing."""
    manifest = PackageManifest(
        package_id=pkg_id,
        package_type=PackageType.WORKFLOW if "wf" in pkg_id else PackageType.SKILL,
        name=f"Package {pkg_id}",
        description="Test description",
        version=version,
        publisher=PublisherIdentity(
            publisher_id=pub_id,
            name="Test Pub",
            email="test@atlas.org",
            public_key=key,
        ),
        required_capabilities=[AgentCapability.RESEARCH],
        dependencies=deps or [],
        tags=["test", "automation"],
    )
    wf = (
        WorkflowGraphDefinition(
            graph_id=f"wf_{pkg_id}",
            nodes=[
                WorkflowNodeDefinition(
                    node_id="n1",
                    name="Step 1",
                    required_capability=AgentCapability.RESEARCH,
                )
            ],
        )
        if "wf" in pkg_id
        else None
    )
    return build_package_archive(manifest=manifest, workflow=wf, signing_key=key)


def test_semver_constraint_matching():
    """Verify SemVer range, caret, tilde, and wildcard matching."""
    assert parse_semver("1.2.3") == (1, 2, 3)

    # Wildcard
    assert matches_constraint("1.2.3", "*") is True

    # Caret
    assert matches_constraint("1.2.5", "^1.2.0") is True
    assert matches_constraint("1.9.0", "^1.2.0") is True
    assert matches_constraint("2.0.0", "^1.2.0") is False

    # Tilde
    assert matches_constraint("1.2.5", "~1.2.0") is True
    assert matches_constraint("1.3.0", "~1.2.0") is False

    # Range
    assert matches_constraint("1.5.0", ">=1.0.0, <2.0.0") is True
    assert matches_constraint("2.0.0", ">=1.0.0, <2.0.0") is False


def test_dependency_resolver_resolution_and_cycles():
    """Verify topological resolution and cycle detection."""
    available = {
        "pkg_a": ["1.0.0"],
        "pkg_b": ["1.1.0", "1.0.0"],
        "pkg_c": ["2.0.0"],
    }
    resolver = DependencyResolver(available)

    # 1. Linear resolution: root -> B (^1.0.0) -> C (2.0.0)
    def dep_lookup(pid: str, v: str) -> list[PackageDependency]:
        if pid == "pkg_b":
            return [PackageDependency(package_id="pkg_c", version_constraint="=2.0.0")]
        return []

    order = resolver.resolve(
        root_package_id="pkg_a",
        root_dependencies=[PackageDependency(package_id="pkg_b", version_constraint="^1.0.0")],
        package_dependency_lookup=dep_lookup,
    )
    assert order == [("pkg_c", "2.0.0"), ("pkg_b", "1.1.0")]

    # 2. Cycle detection: X -> Y -> X
    available_cycle = {"pkg_x": ["1.0.0"], "pkg_y": ["1.0.0"]}
    cycle_resolver = DependencyResolver(available_cycle)

    def cycle_lookup(pid: str, v: str) -> list[PackageDependency]:
        if pid == "pkg_x":
            return [PackageDependency(package_id="pkg_y", version_constraint="*")]
        if pid == "pkg_y":
            return [PackageDependency(package_id="pkg_x", version_constraint="*")]
        return []

    with pytest.raises(CircularDependencyError):
        cycle_resolver.resolve(
            root_package_id="pkg_root",
            root_dependencies=[PackageDependency(package_id="pkg_x", version_constraint="*")],
            package_dependency_lookup=cycle_lookup,
        )

    # 3. Missing dependency
    with pytest.raises(IncompatibleDependencyError):
        resolver.find_best_version("non_existent_pkg", "*")


def test_registry_publish_search_pagination():
    """Verify package publishing, metadata indexing, search query filtering, and pagination."""
    registry = MarketplaceRegistry()

    arch1 = _make_archive("com.atlas.wf.consensus", "1.0.0")
    arch2 = _make_archive("com.atlas.skill.linter", "1.0.0")
    arch3 = _make_archive("com.atlas.wf.analytics", "1.0.0")

    registry.publish_package(arch1)
    registry.publish_package(arch2)
    registry.publish_package(arch3)

    # Search by keyword
    results, total = registry.search_packages(query="consensus")
    assert total == 1
    assert results[0].package_id == "com.atlas.wf.consensus"

    # Search by package type
    skills, s_total = registry.search_packages(package_type=PackageType.SKILL)
    assert s_total == 1
    assert skills[0].package_id == "com.atlas.skill.linter"

    # Pagination
    page1, p_total = registry.search_packages(page=1, page_size=2)
    assert p_total == 3
    assert len(page1) == 2


def test_registry_install_with_transitive_dependencies():
    """Verify installation resolves prerequisites and updates installation records."""
    registry = MarketplaceRegistry()

    # Leaf skill
    skill_arch = _make_archive("com.atlas.skill.leaf", "1.0.0")
    registry.publish_package(skill_arch)

    # Workflow depending on leaf skill
    wf_arch = _make_archive(
        "com.atlas.wf.main",
        "1.0.0",
        deps=[PackageDependency(package_id="com.atlas.skill.leaf", version_constraint="^1.0.0")],
    )
    registry.publish_package(wf_arch)

    # Install
    installed = registry.install_package("com.atlas.wf.main")
    assert len(installed) == 2
    pkg_ids = [inst.package_id for inst in installed]
    assert pkg_ids == ["com.atlas.skill.leaf", "com.atlas.wf.main"]

    installed_list = registry.list_installed()
    assert len(installed_list) == 2


def test_registry_upgrade_and_rollback():
    """Verify package upgrade records previous_version and rollback restores it."""
    registry = MarketplaceRegistry()

    arch_v1 = _make_archive("com.atlas.wf.roll", "1.0.0")
    arch_v2 = _make_archive("com.atlas.wf.roll", "1.1.0")

    registry.publish_package(arch_v1)
    registry.install_package("com.atlas.wf.roll", version_constraint="=1.0.0")

    inst_v1 = registry.list_installed()[0]
    assert inst_v1.version == "1.0.0"

    # Upgrade to v1.1.0
    registry.publish_package(arch_v2)
    registry.install_package("com.atlas.wf.roll", version_constraint="=1.1.0")

    inst_v2 = registry.list_installed()[0]
    assert inst_v2.version == "1.1.0"
    assert inst_v2.previous_version == "1.0.0"

    # Rollback
    rolled = registry.rollback_package("com.atlas.wf.roll")
    assert rolled.version == "1.0.0"
    assert rolled.previous_version == "1.1.0"


def test_registry_deprecate_and_withdraw():
    """Verify deprecation and withdrawal semantics."""
    registry = MarketplaceRegistry()
    arch = _make_archive("com.atlas.wf.dep", "1.0.0")
    registry.publish_package(arch)

    # Deprecate
    registry.deprecate_package("com.atlas.wf.dep", "1.0.0")
    assert registry.get_package("com.atlas.wf.dep").status == PackageStatus.DEPRECATED

    # Withdraw
    registry.withdraw_package("com.atlas.wf.dep", "1.0.0")
    assert registry.get_package("com.atlas.wf.dep") is None  # Active lookup excludes withdrawn

    # Installation of withdrawn package blocked
    with pytest.raises(KeyError, match="not available"):
        registry.install_package("com.atlas.wf.dep")


def test_registry_publisher_revocation():
    """Verify revoking a publisher blocks package publishing and verification."""
    registry = MarketplaceRegistry()
    registry.revoke_publisher("pub_bad")

    arch = _make_archive("com.atlas.wf.bad", "1.0.0", pub_id="pub_bad")

    with pytest.raises(PackageSignatureError, match="revoked"):
        registry.publish_package(arch)
