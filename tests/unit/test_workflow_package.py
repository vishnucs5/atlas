"""Unit tests verifying WorkflowPackage schemas, checksum integrity, and cryptographic signing."""

import io
import tarfile

import pytest
from atlas_core.contracts.agent import AgentCapability
from atlas_marketplace.models import (
    PackageManifest,
    PackageType,
    PermissionDeclaration,
    PermissionScope,
    PublisherIdentity,
    WorkflowGraphDefinition,
    WorkflowNodeDefinition,
)
from atlas_marketplace.package import (
    PackageIntegrityError,
    PackageSignatureError,
    PackageValidationError,
    build_package_archive,
    unpack_and_validate_package,
    validate_workflow_dag_cycles,
)


@pytest.fixture
def valid_manifest() -> PackageManifest:
    """Fixture providing a valid package manifest."""
    return PackageManifest(
        package_id="com.atlas.consensus.audit",
        package_type=PackageType.WORKFLOW,
        name="Consensus Audit Workflow",
        description="Autonomous verification of Raft consensus.",
        version="1.2.0",
        publisher=PublisherIdentity(
            publisher_id="pub_atlas_security",
            name="ATLAS Security",
            email="sec@atlas.org",
            public_key="test_signing_key_secret_123",
        ),
        permissions=[
            PermissionDeclaration(
                scope=PermissionScope.NETWORK,
                access="domain_allowlist",
                domains=["github.com"],
            )
        ],
    )


@pytest.fixture
def valid_workflow() -> WorkflowGraphDefinition:
    """Fixture providing a valid 3-node workflow DAG."""
    return WorkflowGraphDefinition(
        graph_id="wf_consensus_dag",
        nodes=[
            WorkflowNodeDefinition(
                node_id="step_res",
                name="Research",
                required_capability=AgentCapability.RESEARCH,
                parameters={"query": "raft consensus"},
            ),
            WorkflowNodeDefinition(
                node_id="step_code",
                name="Code",
                required_capability=AgentCapability.CODE,
                parameters={"filepath": "out.py"},
                dependencies=["step_res"],
            ),
            WorkflowNodeDefinition(
                node_id="step_qa",
                name="QA",
                required_capability=AgentCapability.QUALITY_ASSURANCE,
                parameters={"target": "consensus"},
                dependencies=["step_code"],
            ),
        ],
    )


def test_manifest_validation(valid_manifest):
    """Verify package manifest schema validation and serialization."""
    assert valid_manifest.package_id == "com.atlas.consensus.audit"
    assert valid_manifest.version == "1.2.0"

    # Invalid SemVer
    with pytest.raises(ValueError, match="Semantic Versioning"):
        PackageManifest(
            package_id="com.atlas.test",
            package_type=PackageType.WORKFLOW,
            name="Test",
            description="desc",
            version="1.2",  # Missing patch
            publisher=valid_manifest.publisher,
        )

    # Invalid Package ID
    with pytest.raises(ValueError, match="package_id"):
        PackageManifest(
            package_id="INVALID_UPPERCASE_ID!",
            package_type=PackageType.WORKFLOW,
            name="Test",
            description="desc",
            version="1.0.0",
            publisher=valid_manifest.publisher,
        )


def test_workflow_dag_cycle_detection():
    """Verify Kahn's algorithm cycle detection rejects cyclic dependencies."""
    # Cyclic: A -> B -> A
    cyclic_wf = WorkflowGraphDefinition(
        graph_id="wf_cycle",
        nodes=[
            WorkflowNodeDefinition(
                node_id="node_a",
                name="A",
                required_capability=AgentCapability.RESEARCH,
                dependencies=["node_b"],
            ),
            WorkflowNodeDefinition(
                node_id="node_b",
                name="B",
                required_capability=AgentCapability.CODE,
                dependencies=["node_a"],
            ),
        ],
    )
    with pytest.raises(PackageValidationError, match="cyclic"):
        validate_workflow_dag_cycles(cyclic_wf)

    # Missing dependency
    missing_dep_wf = WorkflowGraphDefinition(
        graph_id="wf_missing",
        nodes=[
            WorkflowNodeDefinition(
                node_id="node_x",
                name="X",
                required_capability=AgentCapability.RESEARCH,
                dependencies=["non_existent_node"],
            )
        ],
    )
    with pytest.raises(PackageValidationError, match="non-existent"):
        validate_workflow_dag_cycles(missing_dep_wf)


def test_build_and_unpack_package_archive(valid_manifest, valid_workflow):
    """Verify end-to-end archive bundling, checksum calculation, signature, and unpacking."""
    extra_files = {"skill.py": b"# custom skill logic\nprint('hello world')\n"}
    archive_bytes = build_package_archive(
        manifest=valid_manifest,
        workflow=valid_workflow,
        extra_files=extra_files,
        signing_key="test_signing_key_secret_123",
    )

    assert len(archive_bytes) > 0

    # Unpack and validate
    pkg = unpack_and_validate_package(
        archive_bytes=archive_bytes,
        signing_key="test_signing_key_secret_123",
    )

    assert pkg.manifest.package_id == "com.atlas.consensus.audit"
    assert pkg.workflow is not None
    assert len(pkg.workflow.nodes) == 3
    assert "skill.py" in pkg.checksums
    assert pkg.signature is not None


def test_package_tamper_checksum_mismatch(valid_manifest, valid_workflow):
    """Verify modifying archive contents triggers PackageIntegrityError."""
    archive_bytes = build_package_archive(
        manifest=valid_manifest,
        workflow=valid_workflow,
        signing_key="test_signing_key_secret_123",
    )

    # Decompress archive, alter manifest.json, and re-tar without updating checksums
    in_buf = io.BytesIO(archive_bytes)
    out_buf = io.BytesIO()
    with (
        tarfile.open(fileobj=in_buf, mode="r:gz") as src_tar,
        tarfile.open(fileobj=out_buf, mode="w:gz") as dst_tar,
    ):
        for member in src_tar.getmembers():
            f = src_tar.extractfile(member)
            content = f.read() if f else b""
            if member.name == "manifest.json":
                # Tamper with content!
                content = content.replace(b"Consensus Audit Workflow", b"Hacked Workflow")
            tarinfo = tarfile.TarInfo(name=member.name)
            tarinfo.size = len(content)
            dst_tar.addfile(tarinfo, io.BytesIO(content))

    tampered_bytes = out_buf.getvalue()

    with pytest.raises(PackageIntegrityError, match="checksum mismatch"):
        unpack_and_validate_package(
            archive_bytes=tampered_bytes,
            signing_key="test_signing_key_secret_123",
        )


def test_package_signature_verification_failure(valid_manifest, valid_workflow):
    """Verify wrong signing key triggers PackageSignatureError."""
    archive_bytes = build_package_archive(
        manifest=valid_manifest,
        workflow=valid_workflow,
        signing_key="correct_key_456",
    )

    # Verification with wrong key
    with pytest.raises(PackageSignatureError, match="Invalid package signature"):
        unpack_and_validate_package(
            archive_bytes=archive_bytes,
            signing_key="wrong_key_789",
        )


def test_package_revoked_publisher_rejected(valid_manifest, valid_workflow):
    """Verify packages from revoked publishers are rejected."""
    archive_bytes = build_package_archive(
        manifest=valid_manifest,
        workflow=valid_workflow,
        signing_key="test_signing_key_secret_123",
    )

    with pytest.raises(PackageSignatureError, match="revoked"):
        unpack_and_validate_package(
            archive_bytes=archive_bytes,
            signing_key="test_signing_key_secret_123",
            revoked_publishers={"pub_atlas_security"},
        )


def test_package_path_traversal_attack_blocked(valid_manifest):
    """Verify archives attempting directory traversal are rejected."""
    out_buf = io.BytesIO()
    with tarfile.open(fileobj=out_buf, mode="w:gz") as tar:
        # Add malicious member path
        payload = b"malicious"
        tarinfo = tarfile.TarInfo(name="../../etc/passwd")
        tarinfo.size = len(payload)
        tar.addfile(tarinfo, io.BytesIO(payload))

    evil_archive = out_buf.getvalue()

    with pytest.raises(PackageValidationError, match="Malicious archive member path"):
        unpack_and_validate_package(evil_archive)
