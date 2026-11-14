"""Unit tests for Enterprise Integration Hub, Verified Connectors, and Webhooks (Milestone 4)."""

import hashlib
import hmac

import pytest
from atlas_enterprise import (
    ConnectorStatus,
    ConnectorType,
    ConnectorUnverifiedError,
    CrossTenantAccessViolationError,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
    IntegrationHubManager,
    IntegrationSecretStore,
    RateLimitExceededError,
)


@pytest.fixture
def org_manager() -> EnterpriseOrganizationManager:
    return EnterpriseOrganizationManager()


@pytest.fixture
def iam_engine(org_manager: EnterpriseOrganizationManager) -> EnterpriseIAMEngine:
    return EnterpriseIAMEngine(org_manager=org_manager)


@pytest.fixture
def secret_store() -> IntegrationSecretStore:
    return IntegrationSecretStore()


@pytest.fixture
def hub_manager(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
    secret_store: IntegrationSecretStore,
) -> IntegrationHubManager:
    return IntegrationHubManager(
        org_manager=org_manager,
        iam_engine=iam_engine,
        secret_store=secret_store,
    )


def test_connector_registration_and_secret_vaulting(
    org_manager: EnterpriseOrganizationManager,
    hub_manager: IntegrationHubManager,
    secret_store: IntegrationSecretStore,
) -> None:
    """Verify connectors register in UNVERIFIED state and credentials are vaulted separately."""
    org, owner, _ = org_manager.create_organization(
        name="GlobalCorp", slug="globalcorp", owner_email="admin@globalcorp.com", owner_name="Admin"
    )

    raw_credentials = {"api_key": "salesforce_secret_oauth_token_xyz"}
    connector = hub_manager.register_connector(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="Salesforce-Production",
        connector_type=ConnectorType.CRM,
        provider="salesforce",
        config={"instance_url": "https://globalcorp.my.salesforce.com"},
        secrets=raw_credentials,
    )

    assert connector.connector_id.startswith("conn_")
    assert connector.status == ConnectorStatus.UNVERIFIED
    assert "api_key" not in connector.config  # Secrets must not be stored in plain config

    # Secret is accessible only through secret store with matching org_id
    vaulted = secret_store.get_secret(org.org_id, connector.secret_id)
    assert vaulted["api_key"] == "salesforce_secret_oauth_token_xyz"


def test_connector_verification_handshake(
    org_manager: EnterpriseOrganizationManager,
    hub_manager: IntegrationHubManager,
) -> None:
    """Verify connectors cannot be invoked until passing deterministic handshake."""
    org, owner, _ = org_manager.create_organization(
        name="TechCorp", slug="techcorp", owner_email="lead@techcorp.com", owner_name="Lead"
    )

    # 1. Invalid credentials connector
    conn_bad = hub_manager.register_connector(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="Broken-Jira",
        connector_type=ConnectorType.PROJECT_MANAGEMENT,
        provider="jira",
        config={"domain": "techcorp.atlassian.net"},
        secrets={"api_token": "invalid_token_123"},
    )

    # Invocation before verification fails
    with pytest.raises(ConnectorUnverifiedError):
        hub_manager.invoke_connector(
            caller_id=owner.user_id,
            connector_id=conn_bad.connector_id,
            action_name="get_issue",
            parameters={"issue_key": "TECH-10"},
        )

    # Handshake fails
    success, reason = hub_manager.verify_connector(owner.user_id, conn_bad.connector_id)
    assert success is False
    assert "rejected" in reason
    assert conn_bad.status == ConnectorStatus.FAILED

    # 2. Valid credentials connector
    conn_good = hub_manager.register_connector(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="Good-Slack",
        connector_type=ConnectorType.COMMUNICATION,
        provider="slack",
        config={"default_channel": "#dev-alerts"},
        secrets={"bot_token": "xoxb-valid-slack-bot-token"},
    )

    success, reason = hub_manager.verify_connector(owner.user_id, conn_good.connector_id)
    assert success is True
    assert reason is None
    assert conn_good.status == ConnectorStatus.ACTIVE
    assert conn_good.last_verified_at is not None

    # Invocation succeeds
    res = hub_manager.invoke_connector(
        caller_id=owner.user_id,
        connector_id=conn_good.connector_id,
        action_name="post_message",
        parameters={"message": "Deployment succeeded!"},
    )
    assert res["status"] == "delivered"


def test_cross_tenant_connector_isolation(
    org_manager: EnterpriseOrganizationManager,
    hub_manager: IntegrationHubManager,
    secret_store: IntegrationSecretStore,
) -> None:
    """Verify tenant boundaries prevent cross-tenant invocation and credential extraction."""
    org_a, owner_a, _ = org_manager.create_organization(
        name="Tenant A", slug="ta", owner_email="a@ta.com", owner_name="Owner A"
    )
    org_b, owner_b, _ = org_manager.create_organization(
        name="Tenant B", slug="tb", owner_email="b@tb.com", owner_name="Owner B"
    )

    conn_a = hub_manager.register_connector(
        caller_user_id=owner_a.user_id,
        org_id=org_a.org_id,
        name="Tenant-A-CRM",
        connector_type=ConnectorType.CRM,
        provider="salesforce",
        config={},
        secrets={"api_key": "secret_a"},
    )

    # Tenant B tries to inspect Tenant A's connector
    with pytest.raises(CrossTenantAccessViolationError):
        hub_manager.get_connector(conn_a.connector_id, caller_org_id=org_b.org_id)

    # Tenant B tries to steal Tenant A's vaulted secret
    with pytest.raises(CrossTenantAccessViolationError):
        secret_store.get_secret(org_b.org_id, conn_a.secret_id)


def test_cryptographic_webhook_hmac_verification(
    org_manager: EnterpriseOrganizationManager,
    hub_manager: IntegrationHubManager,
) -> None:
    """Verify HMAC signature verification rejects forged or unsigned webhook payloads."""
    org, owner, _ = org_manager.create_organization(
        name="WebhookCo", slug="whco", owner_email="admin@whco.com", owner_name="Admin"
    )

    webhook_signing_secret = "whsec_super_secret_cryptographic_key_999"
    conn = hub_manager.register_connector(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="GitHub-Inbound-Webhook",
        connector_type=ConnectorType.WEBHOOK,
        provider="generic_webhook",
        config={"url": "https://api.github.com/webhook"},
        secrets={"signing_secret": webhook_signing_secret},
    )

    payload = b'{"event":"pull_request.merged","pr_number":42,"actor":"developer"}'

    # Legitimate signature
    valid_hmac = hmac.new(webhook_signing_secret.encode(), payload, hashlib.sha256).hexdigest()
    assert (
        hub_manager.verify_inbound_webhook(
            connector_id=conn.connector_id,
            payload_bytes=payload,
            signature_header=f"sha256={valid_hmac}",
        )
        is True
    )

    # Forged signature fails
    forged_hmac = "badbeefcafe1234567890abcdef1234567890abcdef1234567890abcdef12345"
    assert (
        hub_manager.verify_inbound_webhook(
            connector_id=conn.connector_id,
            payload_bytes=payload,
            signature_header=f"sha256={forged_hmac}",
        )
        is False
    )

    # Tampered payload fails
    tampered_payload = b'{"event":"pull_request.merged","pr_number":42,"actor":"attacker"}'
    assert (
        hub_manager.verify_inbound_webhook(
            connector_id=conn.connector_id,
            payload_bytes=tampered_payload,
            signature_header=f"sha256={valid_hmac}",
        )
        is False
    )


def test_connector_rate_limiting(
    org_manager: EnterpriseOrganizationManager,
    hub_manager: IntegrationHubManager,
) -> None:
    """Verify rate limits enforce execution throttling."""
    org, owner, _ = org_manager.create_organization(
        name="RateLimitOrg", slug="rlo", owner_email="owner@rlo.com", owner_name="Owner"
    )

    conn = hub_manager.register_connector(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="Throttled-CRM",
        connector_type=ConnectorType.CRM,
        provider="salesforce",
        config={},
        secrets={"api_key": "salesforce_token_abc"},
        rate_limit_rpm=3,  # Strict 3 RPM limit for testing
    )
    hub_manager.verify_connector(owner.user_id, conn.connector_id)

    # First 3 requests succeed
    for _ in range(3):
        res = hub_manager.invoke_connector(
            caller_id=owner.user_id,
            connector_id=conn.connector_id,
            action_name="query_account",
            parameters={},
        )
        assert res["status"] == "Active"

    # 4th request exceeds rate limit and raises RateLimitExceededError
    with pytest.raises(RateLimitExceededError):
        hub_manager.invoke_connector(
            caller_id=owner.user_id,
            connector_id=conn.connector_id,
            action_name="query_account",
            parameters={},
        )
