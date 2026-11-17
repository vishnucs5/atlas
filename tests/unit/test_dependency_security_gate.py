"""Unit tests for ATLAS Dependency Security Gate and Vulnerability Gate Evaluation."""

from __future__ import annotations

import datetime
from typing import Any

import pytest

from scripts.audit_dependencies import (
    evaluate_vulnerabilities,
    sanitize_environment,
)


@pytest.fixture
def sample_vulnerable_fixture() -> list[dict[str, Any]]:
    """Controlled fixture simulating pip-audit output for a vulnerable package."""
    return [
        {
            "name": "urllib3",
            "version": "1.26.4",
            "vulns": [
                {
                    "id": "GHSA-q2x7-8rv6-6q7h",
                    "aliases": ["CVE-2021-33503"],
                    "description": "Catastrophic backtracking in URL authority parser.",
                    "fix_versions": ["1.26.5"],
                    "severity": "HIGH",
                }
            ],
        },
        {
            "name": "fastapi",
            "version": "0.115.11",
            "vulns": [],
        },
    ]


@pytest.fixture
def sample_clean_fixture() -> list[dict[str, Any]]:
    """Controlled fixture simulating pip-audit output for clean packages."""
    return [
        {"name": "pydantic", "version": "2.10.6", "vulns": []},
        {"name": "fastapi", "version": "0.115.11", "vulns": []},
        {"name": "cryptography", "version": "44.0.0", "vulns": []},
    ]


def test_clean_scan_evaluation(sample_clean_fixture: list[dict[str, Any]]) -> None:
    """A clean scan must evaluate to PASS with zero violations."""
    res = evaluate_vulnerabilities(sample_clean_fixture, exceptions=[])
    assert res["status"] == "PASS"
    assert res["violations_count"] == 0
    assert res["exempted_count"] == 0
    assert len(res["violations"]) == 0


def test_vulnerable_fixture_blocks_gate(sample_vulnerable_fixture: list[dict[str, Any]]) -> None:
    """A vulnerable fixture without exceptions must fail the security gate."""
    res = evaluate_vulnerabilities(sample_vulnerable_fixture, exceptions=[], fail_severity="HIGH")
    assert res["status"] == "FAIL"
    assert res["violations_count"] == 1
    assert res["violations"][0]["package"] == "urllib3"
    assert res["violations"][0]["vulnerability_id"] == "GHSA-q2x7-8rv6-6q7h"
    assert "CVE-2021-33503" in res["violations"][0]["aliases"]


def test_active_exemption_allows_gate(sample_vulnerable_fixture: list[dict[str, Any]]) -> None:
    """An active unexpired exemption must allow the scan to PASS with exemption logged."""
    now = datetime.datetime(2026, 11, 17, 12, 0, 0, tzinfo=datetime.UTC)
    future_expiry = "2026-12-31T23:59:59Z"

    exceptions = [
        {
            "vulnerability_id": "CVE-2021-33503",
            "package_name": "urllib3",
            "justification": "Mitigated via upstream reverse proxy URL sanitization in ingress.",
            "owner": "sec-ops@atlas.internal",
            "expiry_date": future_expiry,
        }
    ]

    res = evaluate_vulnerabilities(
        sample_vulnerable_fixture,
        exceptions=exceptions,
        fail_severity="HIGH",
        current_time=now,
    )
    assert res["status"] == "PASS"
    assert res["violations_count"] == 0
    assert res["exempted_count"] == 1
    assert res["exempted"][0]["exemption"]["owner"] == "sec-ops@atlas.internal"


def test_expired_exemption_fails_gate(sample_vulnerable_fixture: list[dict[str, Any]]) -> None:
    """An expired exemption must NOT bypass the gate and must cause a FAIL."""
    now = datetime.datetime(2026, 11, 17, 12, 0, 0, tzinfo=datetime.UTC)
    past_expiry = "2026-10-01T00:00:00Z"

    exceptions = [
        {
            "vulnerability_id": "GHSA-q2x7-8rv6-6q7h",
            "package_name": "urllib3",
            "justification": "Temporary waiver",
            "owner": "sec-ops@atlas.internal",
            "expiry_date": past_expiry,
        }
    ]

    res = evaluate_vulnerabilities(
        sample_vulnerable_fixture,
        exceptions=exceptions,
        fail_severity="HIGH",
        current_time=now,
    )
    assert res["status"] == "FAIL"
    assert res["violations_count"] == 1
    assert "expired_exemption" in res["violations"][0]


def test_severity_threshold_filtering() -> None:
    """Low severity vulnerabilities below threshold must not fail gate when threshold is HIGH."""
    vulns = [
        {
            "name": "example-pkg",
            "version": "1.0.0",
            "vulns": [
                {
                    "id": "GHSA-low-001",
                    "aliases": [],
                    "description": "Minor timing discrepancy",
                    "fix_versions": [],
                    "severity": "LOW",
                }
            ],
        }
    ]

    res = evaluate_vulnerabilities(vulns, exceptions=[], fail_severity="HIGH")
    assert res["status"] == "PASS"
    assert res["violations_count"] == 0
    assert res["ignored_low_severity_count"] == 1


def test_environment_sanitization() -> None:
    """Sanitizer must scrub tokens and secret variables from child process environment."""
    dirty_env = {
        "PATH": "/usr/bin",
        "GITHUB_TOKEN": "ghp_secret_123",
        "DATABASE_PASSWORD": "supersecretpassword",
        "AWS_SECRET_ACCESS_KEY": "AKIA...",
        "APP_ENV": "production",
        "AUTH_BEARER": "eyJ...",
    }

    clean = sanitize_environment(dirty_env)
    assert "PATH" in clean
    assert "APP_ENV" in clean
    assert "GITHUB_TOKEN" not in clean
    assert "DATABASE_PASSWORD" not in clean
    assert "AWS_SECRET_ACCESS_KEY" not in clean
    assert "AUTH_BEARER" not in clean
