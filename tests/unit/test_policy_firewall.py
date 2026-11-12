"""Unit tests for ActionFirewall and policy rule evaluation."""

import pytest
from atlas_core.contracts.action import ActionTarget, ComputerAction
from atlas_core.contracts.policy import PolicyDecisionType, RiskLevel
from atlas_policy.firewall import ActionFirewall, PolicyRule


def test_firewall_allows_low_risk_action():
    """Verify low-risk read-only actions are allowed."""
    firewall = ActionFirewall()
    action = ComputerAction(
        action_id="act_1",
        task_id="t1",
        session_id="s1",
        action_type="browser.scroll",
        idempotency_key="k1",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.risk_level == RiskLevel.LOW
    assert len(decision.rules_evaluated) > 0


def test_firewall_requires_approval_for_destructive_action():
    """Verify destructive terminal execution requires approval with CRITICAL risk."""
    firewall = ActionFirewall()
    action = ComputerAction(
        action_id="act_2",
        task_id="t1",
        session_id="s1",
        action_type="terminal.execute",
        parameters={"command": "rm -rf /"},
        idempotency_key="k2",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.risk_level == RiskLevel.CRITICAL
    assert "destructive" in decision.reason.lower()


def test_firewall_allows_medium_risk_action():
    """Verify interactive browser inputs are allowed with MEDIUM risk."""
    firewall = ActionFirewall()
    action = ComputerAction(
        action_id="act_3",
        task_id="t1",
        session_id="s1",
        action_type="browser.click",
        target=ActionTarget(strategy="css", parameters={"selector": "#submit-btn"}),
        idempotency_key="k3",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.risk_level == RiskLevel.MEDIUM


def test_firewall_requires_approval_for_high_risk_action():
    """Verify file modification and standard terminal execution require approval with HIGH risk."""
    firewall = ActionFirewall()
    action = ComputerAction(
        action_id="act_4",
        task_id="t1",
        session_id="s1",
        action_type="file.write",
        parameters={"path": "/etc/hosts", "content": "127.0.0.1 localhost"},
        idempotency_key="k4",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.risk_level == RiskLevel.HIGH


def test_firewall_requires_approval_for_critical_financial_action():
    """Verify financial and account deletion actions require approval with CRITICAL risk."""
    firewall = ActionFirewall()
    action = ComputerAction(
        action_id="act_5",
        task_id="t1",
        session_id="s1",
        action_type="payment.authorize",
        parameters={"amount": 500.0, "currency": "USD"},
        idempotency_key="k5",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.risk_level == RiskLevel.CRITICAL


def test_firewall_domain_allowlist_permits_allowed_domain():
    """Verify navigation to explicitly allowed domains succeeds."""
    firewall = ActionFirewall(allowed_domains=["github.com", "python.org"])
    action = ComputerAction(
        action_id="act_6",
        task_id="t1",
        session_id="s1",
        action_type="browser.navigate",
        parameters={"url": "https://github.com/astral-sh/uv"},
        idempotency_key="k6",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.risk_level == RiskLevel.MEDIUM


def test_firewall_domain_allowlist_denies_unauthorized_domain():
    """Verify navigation to unauthorized domains is DENIED."""
    firewall = ActionFirewall(allowed_domains=["internal.company.com"])
    action = ComputerAction(
        action_id="act_7",
        task_id="t1",
        session_id="s1",
        action_type="browser.navigate",
        parameters={"url": "https://malicious-exfiltration.net/api"},
        idempotency_key="k7",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.DENY
    assert decision.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    assert "not in allowed domains" in decision.reason.lower()


def test_firewall_domain_allowlist_checks_target_parameters():
    """Verify domain allowlist checks target.parameters when url is inside target."""
    firewall = ActionFirewall(allowed_domains=["docs.python.org"])
    action = ComputerAction(
        action_id="act_8",
        task_id="t1",
        session_id="s1",
        action_type="browser.navigate",
        target=ActionTarget(strategy="url", parameters={"url": "https://unauthorized-domain.com"}),
        idempotency_key="k8",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.DENY
    assert decision.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /var/data",
        "rmdir /s /q c:\\system32",
        "del /f /s /q C:\\Users\\*",
        "format C:",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
        "Remove-Item -Recurse -Force C:\\Windows",
        "shutdown -h now",
    ],
)
def test_destructive_command_patterns_detected(command: str):
    """Verify detection of various destructive commands across OS flavors."""
    firewall = ActionFirewall()
    action = ComputerAction(
        action_id="act_dest",
        task_id="t1",
        session_id="s1",
        action_type="terminal.execute",
        parameters={"command": command},
        idempotency_key="k_dest",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.risk_level == RiskLevel.CRITICAL


def test_firewall_custom_rule_action_prefix_denial():
    """Verify custom prefix rules can deny specific actions."""
    firewall = ActionFirewall()
    custom_rule = PolicyRule(
        rule_id="deny_crypto",
        name="Block Cryptocurrency Operations",
        action_prefix="crypto.",
        decision=PolicyDecisionType.DENY,
        risk_level=RiskLevel.CRITICAL,
        description="Block all cryptocurrency and wallet interactions.",
    )
    firewall.add_rule(custom_rule)

    action = ComputerAction(
        action_id="act_crypto",
        task_id="t1",
        session_id="s1",
        action_type="crypto.wallet.transfer",
        parameters={"recipient": "0x123", "amount": 10},
        idempotency_key="k_crypto",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.DENY
    assert decision.risk_level == RiskLevel.CRITICAL
    assert "crypto" in decision.reason.lower()
    assert "deny_crypto" in decision.rules_evaluated


def test_firewall_rule_management():
    """Verify adding, removing, and listing policy rules."""
    firewall = ActionFirewall()
    initial_rule_count = len(firewall.get_rules())

    rule = PolicyRule(
        rule_id="test_custom_rule",
        name="Test Rule",
        action_prefix="test.",
        decision=PolicyDecisionType.ALLOW,
        risk_level=RiskLevel.LOW,
    )
    firewall.add_rule(rule)
    assert len(firewall.get_rules()) == initial_rule_count + 1

    removed = firewall.remove_rule("test_custom_rule")
    assert removed is True
    assert len(firewall.get_rules()) == initial_rule_count

    not_removed = firewall.remove_rule("non_existent_rule")
    assert not_removed is False


def test_firewall_benign_terminal_is_high_risk_approval():
    """Verify benign terminal commands require approval as HIGH risk."""
    firewall = ActionFirewall()
    action = ComputerAction(
        action_id="act_benign_term",
        task_id="t1",
        session_id="s1",
        action_type="terminal.execute",
        parameters={"command": "ls -la"},
        idempotency_key="k_term",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.risk_level == RiskLevel.HIGH


def test_firewall_blocked_domains_returns_deny_critical():
    """Verify explicit blocked_domains configuration returns DENY with CRITICAL risk."""
    firewall = ActionFirewall(blocked_domains=["*.malicious.com", "phishing.org"])
    action = ComputerAction(
        action_id="act_blocked",
        task_id="t1",
        session_id="s1",
        action_type="browser.navigate",
        parameters={"url": "https://sub.malicious.com/login"},
        idempotency_key="k_blocked",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.DENY
    assert decision.risk_level == RiskLevel.CRITICAL
    assert "explicitly blocked" in decision.reason.lower()


def test_firewall_wildcard_and_leading_dot_domain_normalization():
    """Verify domain matching handles wildcard (*.domain) and leading dot (.domain) syntax."""
    firewall = ActionFirewall(allowed_domains=["*.example.com", ".python.org"])

    # Matches subdomain of wildcard
    act_sub = ComputerAction(
        action_id="act_sub",
        task_id="t1",
        session_id="s1",
        action_type="browser.navigate",
        parameters={"url": "https://api.example.com"},
        idempotency_key="k_sub",
    )
    assert firewall.evaluate(act_sub).decision == PolicyDecisionType.ALLOW

    # Matches base domain of wildcard
    act_base = ComputerAction(
        action_id="act_base",
        task_id="t1",
        session_id="s1",
        action_type="browser.navigate",
        parameters={"url": "https://example.com"},
        idempotency_key="k_base",
    )
    assert firewall.evaluate(act_base).decision == PolicyDecisionType.ALLOW

    # Matches subdomain with leading dot pattern
    act_dot = ComputerAction(
        action_id="act_dot",
        task_id="t1",
        session_id="s1",
        action_type="browser.navigate",
        parameters={"url": "https://docs.python.org"},
        idempotency_key="k_dot",
    )
    assert firewall.evaluate(act_dot).decision == PolicyDecisionType.ALLOW


def test_policy_rule_exact_action_type_matching():
    """Verify PolicyRule with exact_action_type matches only identical action types."""
    firewall = ActionFirewall()
    rule = PolicyRule(
        rule_id="exact_type_rule",
        name="Exact Action Match",
        exact_action_type="custom.special_action",
        decision=PolicyDecisionType.REQUIRE_APPROVAL,
        risk_level=RiskLevel.HIGH,
    )
    firewall.add_rule(rule)

    # Identical match
    action_match = ComputerAction(
        action_id="act_exact",
        task_id="t1",
        session_id="s1",
        action_type="custom.special_action",
        idempotency_key="k_exact",
    )
    decision = firewall.evaluate(action_match)
    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.risk_level == RiskLevel.HIGH
    assert "exact_type_rule" in decision.rules_evaluated

    # Prefix variation should not match exact rule
    action_variation = ComputerAction(
        action_id="act_var",
        task_id="t1",
        session_id="s1",
        action_type="custom.special_action.extra",
        idempotency_key="k_var",
    )
    assert not rule.matches(action_variation)


def test_policy_rule_disabled_is_skipped():
    """Verify disabled policy rules (enabled=False) are ignored during evaluation."""
    firewall = ActionFirewall()
    disabled_rule = PolicyRule(
        rule_id="disabled_deny",
        name="Disabled Deny Rule",
        action_prefix="browser.scroll",
        decision=PolicyDecisionType.DENY,
        risk_level=RiskLevel.CRITICAL,
        enabled=False,
    )
    firewall.add_rule(disabled_rule)

    assert not disabled_rule.matches(
        ComputerAction(
            action_id="act_test",
            task_id="t1",
            session_id="s1",
            action_type="browser.scroll",
            idempotency_key="k_test",
        )
    )

    action = ComputerAction(
        action_id="act_scroll",
        task_id="t1",
        session_id="s1",
        action_type="browser.scroll",
        idempotency_key="k_scroll",
    )
    decision = firewall.evaluate(action)
    # Built-in scroll rule should allow it despite disabled deny rule
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.risk_level == RiskLevel.LOW


@pytest.mark.parametrize(
    "malformed_url",
    [
        "http://[invalid-ipv6",
        "http://",
        "https://",
        "://bad-url",
    ],
)
def test_firewall_fails_closed_on_malformed_url(malformed_url: str):
    """Verify malformed or unparseable URLs fail closed with DENY decision."""
    firewall = ActionFirewall(allowed_domains=["example.com"])
    action = ComputerAction(
        action_id="act_malformed",
        task_id="t1",
        session_id="s1",
        action_type="browser.navigate",
        parameters={"url": malformed_url},
        idempotency_key="k_mal",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.DENY
    assert decision.risk_level == RiskLevel.CRITICAL
    assert "malformed" in decision.reason.lower() or "unparseable" in decision.reason.lower()

