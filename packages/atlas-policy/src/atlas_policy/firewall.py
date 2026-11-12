"""Action Firewall and Policy Engine for the ATLAS computer-use runtime."""

import re
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

from atlas_core.contracts.action import ComputerAction
from atlas_core.contracts.policy import PolicyDecision, PolicyDecisionType, RiskLevel
from pydantic import BaseModel, ConfigDict

# Compiled regular expressions for detecting destructive system commands
DESTRUCTIVE_COMMAND_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+-[rfRF]{1,3}\b"),
    re.compile(r"\brmdir\s+/[sS]\b", re.IGNORECASE),
    re.compile(r"\brd\s+/[sS]\b", re.IGNORECASE),
    re.compile(r"\bdel\s+/[fFqQsS]{1,4}\b", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE),
    re.compile(r"\bmkfs(\.\w+)?\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
    re.compile(r"\b(shutdown|reboot|poweroff)\b", re.IGNORECASE),
    re.compile(r"\bdrop\s+(database|table)\b", re.IGNORECASE),
    re.compile(r"\bRemove-Item\b.*(-Recurse|-Force)", re.IGNORECASE),
    re.compile(r"\bchmod\s+(-R\s+)?777\s+/"),
]


class PolicyRule(BaseModel):
    """Declarative policy rule for action evaluation and risk classification."""

    model_config = ConfigDict(validate_assignment=True)

    rule_id: str
    name: str
    action_prefix: str = ""
    decision: PolicyDecisionType = PolicyDecisionType.ALLOW
    risk_level: RiskLevel = RiskLevel.LOW
    description: str = ""
    exact_action_type: str | None = None
    enabled: bool = True
    priority: int = 100

    def matches(self, action: ComputerAction) -> bool:
        """Determine whether this rule applies to the specified action."""
        if not self.enabled:
            return False

        if self.exact_action_type is not None:
            return action.action_type == self.exact_action_type

        if self.action_prefix:
            if self.action_prefix == "*":
                return True
            return action.action_type.startswith(self.action_prefix)

        return False


MALFORMED_DOMAIN_TOKEN_PREFIX = "<malformed:"


def _extract_domains_from_action(action: ComputerAction) -> list[str]:
    """Extract hostnames/domains referenced in action parameters and target.

    Fails closed by returning a malformed token if a candidate URL cannot be parsed.
    """
    candidates: list[str] = []

    # Check direct parameters
    for key in ("url", "domain", "target_url", "host"):
        val = action.parameters.get(key)
        if isinstance(val, str) and val.strip():
            candidates.append(val.strip())

    # Check target parameters if present
    if action.target and action.target.parameters:
        for key in ("url", "domain", "target_url", "host"):
            val = action.target.parameters.get(key)
            if isinstance(val, str) and val.strip():
                candidates.append(val.strip())

    domains: list[str] = []
    for cand in candidates:
        to_parse = cand
        if "://" not in to_parse and not to_parse.startswith("//"):
            to_parse = f"http://{to_parse}"
        try:
            parsed = urlparse(to_parse)
            host = parsed.hostname
            if host:
                domains.append(host.lower())
            else:
                # No valid hostname extracted from candidate URL; fail closed
                domains.append(f"{MALFORMED_DOMAIN_TOKEN_PREFIX}{cand}>")
        except Exception:
            # Constitution Rule 5: No swallowing exceptions; fail closed on malformed URLs
            domains.append(f"{MALFORMED_DOMAIN_TOKEN_PREFIX}{cand}>")

    return domains


def _is_domain_allowed(domain: str, allowed_domains: Sequence[str] | set[str]) -> bool:
    """Check if domain matches an allowed domain or is a subdomain of an allowed domain.

    Normalizes wildcards (e.g. `*.example.com`) and leading dots (`.example.com`).
    """
    norm_domain = domain.lower().strip()
    for allowed in allowed_domains:
        raw_allowed = allowed.lower().strip()
        if raw_allowed == "*":
            return True
        norm_allowed = raw_allowed.lstrip("*").lstrip(".")
        if not norm_allowed:
            continue
        if norm_domain == norm_allowed or norm_domain.endswith(f".{norm_allowed}"):
            return True
    return False


def _find_destructive_command(action: ComputerAction) -> str | None:
    """Inspect action parameters for destructive shell commands."""
    strings_to_check: list[str] = []

    def _collect_strings(data: Any) -> None:
        if isinstance(data, str):
            strings_to_check.append(data)
        elif isinstance(data, dict):
            for v in data.values():
                _collect_strings(v)
        elif isinstance(data, list | tuple | set):
            for item in data:
                _collect_strings(item)

    _collect_strings(action.parameters)
    if action.target and action.target.parameters:
        _collect_strings(action.target.parameters)

    for text in strings_to_check:
        for pattern in DESTRUCTIVE_COMMAND_PATTERNS:
            if pattern.search(text):
                return text

    return None


class ActionFirewall:
    """Action Firewall evaluates ComputerAction objects before dispatch to drivers.

    Implements:
    - Domain allowlisting and explicit blocking
    - Destructive shell command detection
    - Action prefix and category risk classification
    - Custom user-defined PolicyRule evaluation
    """

    def __init__(
        self,
        allowed_domains: Sequence[str] | None = None,
        blocked_domains: Sequence[str] | None = None,
        rules: list[PolicyRule] | None = None,
        default_decision: PolicyDecisionType = PolicyDecisionType.ALLOW,
        default_risk_level: RiskLevel = RiskLevel.LOW,
    ) -> None:
        self._allowed_domains: list[str] = list(allowed_domains) if allowed_domains else []
        self._blocked_domains: list[str] = list(blocked_domains) if blocked_domains else []
        self._rules: list[PolicyRule] = list(rules) if rules else []
        self._default_decision = default_decision
        self._default_risk_level = default_risk_level

        self._build_default_category_rules()

    def _build_default_category_rules(self) -> None:
        """Register built-in risk classification rules."""
        self._builtin_rules: list[PolicyRule] = [
            # Critical operations
            PolicyRule(
                rule_id="builtin_payment",
                name="Payment Authorization Gating",
                action_prefix="payment.",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.CRITICAL,
                description="Financial transactions require strict human approval.",
                priority=90,
            ),
            PolicyRule(
                rule_id="builtin_billing",
                name="Billing Operations Gating",
                action_prefix="billing.",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.CRITICAL,
                description="Billing changes require strict human approval.",
                priority=90,
            ),
            PolicyRule(
                rule_id="builtin_account_delete",
                name="Account Deletion Gating",
                action_prefix="account.delete",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.CRITICAL,
                description="Account deletion operations require strict human approval.",
                priority=90,
            ),
            PolicyRule(
                rule_id="builtin_credentials",
                name="Credential Access Gating",
                action_prefix="credentials.",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.CRITICAL,
                description="Access to sensitive credentials requires approval.",
                priority=90,
            ),
            # High risk operations
            PolicyRule(
                rule_id="builtin_file_modification",
                name="File Modification Gating",
                action_prefix="file.",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.HIGH,
                description="Modifying or deleting files requires approval.",
                priority=80,
            ),
            PolicyRule(
                rule_id="builtin_terminal_execution",
                name="Terminal Execution Gating",
                action_prefix="terminal.",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.HIGH,
                description="Arbitrary terminal execution requires approval.",
                priority=80,
            ),
            PolicyRule(
                rule_id="builtin_system_alteration",
                name="System State Alteration Gating",
                action_prefix="system.",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.HIGH,
                description="System level state changes require approval.",
                priority=80,
            ),
            PolicyRule(
                rule_id="builtin_download",
                name="File Download Gating",
                action_prefix="browser.download",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.HIGH,
                description="External file downloads require approval.",
                priority=80,
            ),
            # Medium risk operations
            PolicyRule(
                rule_id="builtin_browser_interaction",
                name="Interactive Browser Operations",
                action_prefix="browser.click",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.MEDIUM,
                description="Interactive clicks on authorized pages.",
                priority=70,
            ),
            PolicyRule(
                rule_id="builtin_browser_type",
                name="Browser Input Typing",
                action_prefix="browser.type",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.MEDIUM,
                description="Typing input into form fields.",
                priority=70,
            ),
            PolicyRule(
                rule_id="builtin_browser_navigate",
                name="Browser Navigation",
                action_prefix="browser.navigate",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.MEDIUM,
                description="Navigating to web pages.",
                priority=70,
            ),
            PolicyRule(
                rule_id="builtin_keyboard_input",
                name="Keyboard Input Operations",
                action_prefix="keyboard.",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.MEDIUM,
                description="Keyboard typing and key presses.",
                priority=70,
            ),
            PolicyRule(
                rule_id="builtin_mouse_interaction",
                name="Mouse Interactive Operations",
                action_prefix="mouse.click",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.MEDIUM,
                description="Mouse clicks and interactions.",
                priority=70,
            ),
            PolicyRule(
                rule_id="builtin_general_input",
                name="Generic Input Operations",
                action_prefix="input.",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.MEDIUM,
                description="Generic user input simulations.",
                priority=70,
            ),
            # Low risk operations
            PolicyRule(
                rule_id="builtin_browser_scroll",
                name="Browser Scroll Operations",
                action_prefix="browser.scroll",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.LOW,
                description="Passive viewport scrolling.",
                priority=60,
            ),
            PolicyRule(
                rule_id="builtin_browser_inspect",
                name="Browser Inspection Operations",
                action_prefix="browser.inspect",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.LOW,
                description="Read-only DOM inspection.",
                priority=60,
            ),
            PolicyRule(
                rule_id="builtin_browser_read",
                name="Browser Read Operations",
                action_prefix="browser.read",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.LOW,
                description="Read-only page text extraction.",
                priority=60,
            ),
            PolicyRule(
                rule_id="builtin_browser_query",
                name="Browser Query Operations",
                action_prefix="browser.query",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.LOW,
                description="Read-only DOM element queries.",
                priority=60,
            ),
            PolicyRule(
                rule_id="builtin_observation",
                name="Observation Capture",
                action_prefix="observation.",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.LOW,
                description="Capturing screenshots or accessibility tree state.",
                priority=60,
            ),
            PolicyRule(
                rule_id="builtin_mouse_move",
                name="Mouse Passive Move",
                action_prefix="mouse.move",
                decision=PolicyDecisionType.ALLOW,
                risk_level=RiskLevel.LOW,
                description="Passive mouse cursor movement.",
                priority=60,
            ),
        ]

    def add_rule(self, rule: PolicyRule) -> None:
        """Add a custom PolicyRule to the firewall."""
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a custom PolicyRule by its rule_id."""
        initial_len = len(self._rules)
        self._rules = [r for r in self._rules if r.rule_id != rule_id]
        return len(self._rules) < initial_len

    def get_rules(self) -> list[PolicyRule]:
        """Return all user-defined policy rules."""
        return list(self._rules)

    def evaluate(self, action: ComputerAction) -> PolicyDecision:
        """Evaluate a proposed ComputerAction through security gates and policy rules."""
        rules_evaluated: list[str] = []

        # Gate 1: Domain Allowlist and Blocklist Enforcement
        domains = _extract_domains_from_action(action)
        if domains:
            rules_evaluated.append("domain_security_check")
            for domain in domains:
                if domain.startswith(MALFORMED_DOMAIN_TOKEN_PREFIX):
                    raw_target = domain.removeprefix(MALFORMED_DOMAIN_TOKEN_PREFIX).removesuffix(
                        ">"
                    )
                    return PolicyDecision(
                        decision=PolicyDecisionType.DENY,
                        risk_level=RiskLevel.CRITICAL,
                        reason=f"Action contains malformed or unparseable target URL: '{raw_target}'. Failing closed.",
                        rules_evaluated=rules_evaluated,
                    )
                # Check explicit blocklist
                if self._blocked_domains and _is_domain_allowed(domain, self._blocked_domains):
                    return PolicyDecision(
                        decision=PolicyDecisionType.DENY,
                        risk_level=RiskLevel.CRITICAL,
                        reason=f"Target domain '{domain}' is explicitly blocked by policy.",
                        rules_evaluated=rules_evaluated,
                    )
                # Check allowlist if configured
                if self._allowed_domains and not _is_domain_allowed(domain, self._allowed_domains):
                    return PolicyDecision(
                        decision=PolicyDecisionType.DENY,
                        risk_level=RiskLevel.HIGH,
                        reason=f"Target domain '{domain}' is not in allowed domains list.",
                        rules_evaluated=rules_evaluated,
                    )

        # Gate 2: Destructive Command Detection
        rules_evaluated.append("destructive_command_protection")
        destructive_cmd = _find_destructive_command(action)
        if destructive_cmd:
            return PolicyDecision(
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.CRITICAL,
                reason=f"Destructive command detected in parameters: '{destructive_cmd}'. Requires explicit approval.",
                rules_evaluated=rules_evaluated,
            )

        # Gate 3: Custom User-Defined Policy Rules (sorted by priority descending)
        sorted_custom_rules = sorted(self._rules, key=lambda r: r.priority, reverse=True)
        for rule in sorted_custom_rules:
            rules_evaluated.append(rule.rule_id)
            if rule.matches(action):
                return PolicyDecision(
                    decision=rule.decision,
                    risk_level=rule.risk_level,
                    reason=f"Matched custom policy rule '{rule.name}' ({rule.rule_id}).",
                    rules_evaluated=rules_evaluated,
                )

        # Gate 4: Built-in Risk Classification Rules (sorted by priority descending)
        sorted_builtin_rules = sorted(self._builtin_rules, key=lambda r: r.priority, reverse=True)
        for rule in sorted_builtin_rules:
            rules_evaluated.append(rule.rule_id)
            if rule.matches(action):
                return PolicyDecision(
                    decision=rule.decision,
                    risk_level=rule.risk_level,
                    reason=f"Matched built-in category rule '{rule.name}'.",
                    rules_evaluated=rules_evaluated,
                )

        # Fallback default decision
        rules_evaluated.append("default_fallback")
        return PolicyDecision(
            decision=self._default_decision,
            risk_level=self._default_risk_level,
            reason="No specific policy rule matched; evaluated with default policy.",
            rules_evaluated=rules_evaluated,
        )
