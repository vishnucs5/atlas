"""CLI commands for Phase 17 Human-AI Collaboration, Steering & Compliance."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from atlas_collaboration.compliance import ComplianceEvidenceGenerator
from atlas_collaboration.models import ComplianceBundle, WorkspaceRole
from atlas_collaboration.storage import CollaborationStorage
from atlas_collaboration.workspace import CollaborativeWorkspaceHub

from atlas_cli.adapters.client import AtlasClient
from atlas_cli.config import get_atlas_dir, get_db_path
from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    RESET,
    YELLOW,
    colorize,
    render_badge,
    render_table,
)


def _get_local_storage() -> CollaborationStorage:
    atlas_dir = get_atlas_dir()
    atlas_dir.mkdir(parents=True, exist_ok=True)
    return CollaborationStorage(db_path=get_db_path())


def run_workspace_create(
    name: str,
    tenant_id: str = "default_tenant",
    client: AtlasClient | None = None,
) -> int:
    """Create a new collaborative workspace."""
    cli = client or AtlasClient()
    print(colorize(f"\n[COLLABORATION] Creating workspace: '{name}'...", BOLD + CYAN))

    if hasattr(cli, "is_server_online") and cli.is_server_online():
        res = cli.create_workspace(name=name, tenant_id=tenant_id)
        if "error" in res:
            print(colorize(f"Error: {res['error']}", RED), file=sys.stderr)
            return 1
        ws_id = res.get("workspace_id")
        created_at = res.get("created_at")
    else:
        # Local offline storage execution
        storage = _get_local_storage()
        ws_id = f"ws_{uuid.uuid4().hex[:12]}"
        created_at = time.time()
        storage.save_workspace(
            workspace_id=ws_id,
            name=name,
            tenant_id=tenant_id,
            created_at=created_at,
        )

    print(colorize(f"Workspace created successfully {render_badge('ACTIVE', 'success')}", GREEN))
    print(f"  {BOLD}ID:{RESET}         {colorize(str(ws_id), CYAN)}")
    print(f"  {BOLD}Name:{RESET}       {name}")
    print(f"  {BOLD}Tenant:{RESET}     {tenant_id}")
    print(f"  {BOLD}Created:{RESET}    {time.ctime(created_at)}")
    return 0


def run_workspace_list(
    tenant_id: str | None = None,
    client: AtlasClient | None = None,
) -> int:
    """List collaborative workspaces."""
    cli = client or AtlasClient()
    if hasattr(cli, "is_server_online") and cli.is_server_online():
        workspaces = cli.list_workspaces(tenant_id=tenant_id)
    else:
        storage = _get_local_storage()
        workspaces = storage.list_workspaces(tenant_id=tenant_id)

    if not workspaces:
        print(colorize("No collaborative workspaces found.", DIM))
        return 0

    headers = ["WORKSPACE ID", "NAME", "TENANT", "STATUS", "FENCING TOKEN"]
    rows = []
    for w in workspaces:
        ws_id = w.get("workspace_id", "")
        name = w.get("name", "")
        t_id = w.get("tenant_id", "")
        status = w.get("status", "ACTIVE")
        fencing = str(w.get("active_fencing_token", 0))
        badge = render_badge(status, "success" if status == "ACTIVE" else "warning")
        rows.append([ws_id, name, t_id, badge, fencing])

    print(colorize(f"\n[COLLABORATIVE WORKSPACES] ({len(workspaces)} total)", BOLD + CYAN))
    print(render_table(headers, rows))
    return 0


def run_workspace_inspect(
    workspace_id: str,
    client: AtlasClient | None = None,
) -> int:
    """Inspect detailed state and active turn lease of a workspace."""
    cli = client or AtlasClient()
    if hasattr(cli, "is_server_online") and cli.is_server_online():
        ws = cli.get_workspace(workspace_id)
    else:
        storage = _get_local_storage()
        ws = storage.get_workspace(workspace_id)

    if not ws:
        print(colorize(f"Error: Workspace '{workspace_id}' not found.", RED), file=sys.stderr)
        return 1

    print(colorize(f"\n[WORKSPACE] {ws.get('name')}", BOLD + CYAN))
    print(f"  {BOLD}ID:{RESET}              {colorize(ws.get('workspace_id', ''), CYAN)}")
    print(f"  {BOLD}Tenant:{RESET}          {ws.get('tenant_id', '')}")
    print(f"  {BOLD}Status:{RESET}          {render_badge(ws.get('status', 'ACTIVE'), 'success')}")
    print(f"  {BOLD}Fencing Token:{RESET}   {ws.get('active_fencing_token', 0)}")

    collabs = ws.get("collaborators", [])
    if collabs:
        print(colorize("\n  Collaborators:", BOLD))
        for c in collabs:
            ident = c.get("identity", "")
            role = c.get("role", "")
            print(f"    - {ident} ({role})")

    # Check active lease
    storage = _get_local_storage()
    lease = storage.get_active_lease(workspace_id)
    if lease and lease.is_active and not lease.is_expired():
        print(colorize("\n  Active Turn Lease:", BOLD + GREEN))
        print(f"    Holder:   {lease.holder_identity} [{lease.holder_role.value}]")
        print(f"    Fencing:  {lease.fencing_token}")
        print(f"    Expires:  {time.ctime(lease.expires_at)}")
    else:
        print(colorize("\n  Turn Lease: [NO ACTIVE LEASE / UNLOCKED]", DIM))

    return 0


def run_workspace_lease(
    workspace_id: str,
    identity: str,
    role: str = "OWNER",
    force: bool = False,
    duration: float = 300.0,
    client: AtlasClient | None = None,
) -> int:
    """Acquire or preempt a semantic turn lease for a workspace."""
    cli = client or AtlasClient()
    print(
        colorize(
            f"\n[TURN LEASE] Acquiring lease for '{identity}' ({role}) on workspace '{workspace_id}'...",
            BOLD + CYAN,
        )
    )

    if hasattr(cli, "is_server_online") and cli.is_server_online():
        res = cli.acquire_lease(
            workspace_id=workspace_id,
            identity=identity,
            role=role,
            force=force,
            duration_seconds=duration,
        )
        if "error" in res:
            print(colorize(f"Error acquiring lease: {res['error']}", RED), file=sys.stderr)
            return 1
        lease_id = res.get("lease_id")
        fencing_token = res.get("fencing_token")
    else:
        # Local execution via hub
        storage = _get_local_storage()
        hub = CollaborativeWorkspaceHub()
        try:
            r_enum = WorkspaceRole(role.upper())
        except ValueError:
            r_enum = WorkspaceRole.OWNER

        # Ensure session exists in hub
        session = hub.get_session(workspace_id)
        if not session:
            session = hub.create_session(
                tenant_id="default_tenant",
                workspace_name=workspace_id,
                owner_identity=identity,
                session_id=workspace_id,
            )
        else:
            hub.join_session(
                session_id=workspace_id,
                identity=identity,
                role=r_enum,
                is_human=True,
            )

        try:
            lease = hub.acquire_turn_lease(
                session_id=workspace_id,
                identity=identity,
                duration_seconds=duration,
            )
            lease.workspace_id = workspace_id
            storage.save_lease(lease)
            lease_id = lease.lease_id
            fencing_token = lease.fencing_token
        except Exception as e:
            print(colorize(f"Error acquiring turn lease: {e}", RED), file=sys.stderr)
            return 1

    print(
        colorize(f"Turn lease acquired successfully {render_badge('ACQUIRED', 'success')}", GREEN)
    )
    print(f"  {BOLD}Lease ID:{RESET}        {colorize(str(lease_id), CYAN)}")
    print(f"  {BOLD}Holder:{RESET}          {identity} ({role})")
    print(f"  {BOLD}Fencing Token:{RESET}   {fencing_token}")
    print(f"  {BOLD}Duration:{RESET}        {duration}s")
    return 0


def run_steering_pause(
    workspace_id: str,
    reason: str,
    operator_id: str = "operator",
    client: AtlasClient | None = None,
) -> int:
    """Pause workspace execution for in-flight human intervention."""
    cli = client or AtlasClient()
    print(colorize(f"\n[STEERING] Pausing workspace '{workspace_id}'...", BOLD + YELLOW))

    if hasattr(cli, "is_server_online") and cli.is_server_online():
        res = cli.pause_steering(workspace_id=workspace_id, reason=reason, operator_id=operator_id)
        if "error" in res:
            print(colorize(f"Error: {res['error']}", RED), file=sys.stderr)
            return 1
        st_id = res.get("steering_id")
    else:
        storage = _get_local_storage()
        ws = storage.get_workspace(workspace_id)
        if not ws:
            print(colorize(f"Workspace '{workspace_id}' not found.", RED), file=sys.stderr)
            return 1
        storage.save_workspace(
            workspace_id=workspace_id,
            name=ws["name"],
            status="PAUSED_FOR_STEERING",
        )
        st_id = f"steer_{uuid.uuid4().hex[:8]}"

    print(colorize(f"Workspace paused for steering {render_badge('PAUSED', 'warning')}", YELLOW))
    print(f"  {BOLD}Steering ID:{RESET}  {colorize(str(st_id), CYAN)}")
    print(f"  {BOLD}Reason:{RESET}       {reason}")
    print(f"  {BOLD}Operator:{RESET}     {operator_id}")
    return 0


def run_steering_resume(
    workspace_id: str,
    params_json: str | None = None,
    client: AtlasClient | None = None,
) -> int:
    """Resume execution of a paused workspace with child idempotency derivation."""
    cli = client or AtlasClient()
    print(colorize(f"\n[STEERING] Resuming workspace '{workspace_id}'...", BOLD + CYAN))

    modified_params: dict[str, Any] = {}
    if params_json:
        try:
            modified_params = json.loads(params_json)
        except json.JSONDecodeError as exc:
            print(colorize(f"Error parsing JSON parameters: {exc}", RED), file=sys.stderr)
            return 1

    if hasattr(cli, "is_server_online") and cli.is_server_online():
        res = cli.resume_steering(workspace_id=workspace_id, modified_parameters=modified_params)
        if "error" in res:
            print(colorize(f"Error: {res['error']}", RED), file=sys.stderr)
            return 1
        child_key = res.get("child_operation_key", "derived")
    else:
        from atlas_collaboration.steering import SteeringController

        storage = _get_local_storage()
        ws = storage.get_workspace(workspace_id)
        if not ws:
            print(colorize(f"Workspace '{workspace_id}' not found.", RED), file=sys.stderr)
            return 1
        controller = SteeringController()
        controller.pause_workflow(
            process_instance_id=workspace_id,
            task_instance_id="task_0",
            operator_id="operator",
            reason="CLI Steering Resume",
        )
        child_key = controller.derive_child_idempotency_key(
            parent_key=f"op_{workspace_id}",
            steering_id=f"steer_{uuid.uuid4().hex[:8]}",
            modified_params=modified_params,
        )
        storage.save_workspace(workspace_id=workspace_id, name=ws["name"], status="ACTIVE")

    print(colorize(f"Workspace execution resumed {render_badge('ACTIVE', 'success')}", GREEN))
    print(f"  {BOLD}Child Idempotency Key:{RESET} {colorize(str(child_key), CYAN)}")
    return 0


def run_compliance_export(
    workspace_id: str,
    output_path: str | None = None,
    frameworks: str | None = None,
    client: AtlasClient | None = None,
) -> int:
    """Generate and export HMAC-SHA256 signed compliance evidence bundle."""
    cli = client or AtlasClient()
    fw_list = (
        [f.strip() for f in frameworks.split(",") if f.strip()]
        if frameworks
        else ["SOC2", "EU_AI_ACT", "ISO27001", "HIPAA"]
    )
    print(
        colorize(f"\n[COMPLIANCE] Generating evidence bundle for '{workspace_id}'...", BOLD + CYAN)
    )

    if hasattr(cli, "is_server_online") and cli.is_server_online():
        bundle = cli.get_compliance_bundle(workspace_id=workspace_id, frameworks=fw_list)
        if "error" in bundle:
            print(colorize(f"Error: {bundle['error']}", RED), file=sys.stderr)
            return 1
    else:
        # Generate locally
        storage = _get_local_storage()
        gen = ComplianceEvidenceGenerator()
        primary_fw = fw_list[0] if fw_list else "SOC2"
        bundle_obj = gen.generate_bundle(
            tenant_id="default_tenant",
            framework=primary_fw,
            records=[],
        )
        bundle_obj.workspace_id = workspace_id
        bundle_obj.frameworks = fw_list
        bundle_obj.decision_merkle_root = bundle_obj.root_merkle_hash
        bundle_obj.hmac_signature = bundle_obj.signature
        storage.save_compliance_bundle(bundle_obj)
        bundle = bundle_obj.model_dump()

    dest = Path(output_path) if output_path else Path(f"compliance_bundle_{workspace_id}.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)

    print(
        colorize(
            f"Compliance bundle exported successfully {render_badge('SIGNED', 'success')}", GREEN
        )
    )
    print(f"  {BOLD}Bundle ID:{RESET}       {colorize(bundle.get('bundle_id', ''), CYAN)}")
    print(f"  {BOLD}Frameworks:{RESET}      {', '.join(bundle.get('frameworks', []))}")
    print(f"  {BOLD}Merkle Root:{RESET}     {bundle.get('decision_merkle_root', '')}")
    print(f"  {BOLD}HMAC Signature:{RESET}  {bundle.get('hmac_signature', '')}")
    print(f"  {BOLD}Saved To:{RESET}        {dest.resolve()}")
    return 0


def run_compliance_verify(bundle_path: str) -> int:
    """Verify cryptographic integrity of an exported compliance bundle."""
    path = Path(bundle_path)
    if not path.exists():
        print(colorize(f"Error: Bundle file not found: {bundle_path}", RED), file=sys.stderr)
        return 1

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(colorize(f"Error reading bundle file: {exc}", RED), file=sys.stderr)
        return 1

    bundle = ComplianceBundle(**data)
    gen = ComplianceEvidenceGenerator()
    is_valid = gen.verify_bundle(bundle)

    if is_valid:
        print(colorize("\n[COMPLIANCE VERIFICATION] PASS", BOLD + GREEN))
        print(f"  {BOLD}Bundle ID:{RESET}       {data.get('bundle_id')}")
        print(f"  {BOLD}Status:{RESET}          {render_badge('VERIFIED', 'success')}")
        print(f"  {BOLD}HMAC Proof:{RESET}      Cryptographically authentic.")
        return 0
    else:
        print(colorize("\n[COMPLIANCE VERIFICATION] FAILED", BOLD + RED))
        print(
            "  Warning: Signature does not match computed Merkle root. Possible tampering detected."
        )
        return 1
