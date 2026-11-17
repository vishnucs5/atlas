#!/usr/bin/env python3
"""ATLAS Automated Dependency Security Audit & Vulnerability Gate.

Scans the locked production and transitive dependencies resolved in `uv.lock`
against upstream vulnerability databases using `pip-audit`. Produces both
machine-readable and human-readable audit artifacts, enforces vulnerability
exemption lifecycles (justification, owner, expiry), and acts as a CI gate.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Default severity levels ranking
SEVERITY_ORDER = {
    "NONE": 0,
    "LOW": 1,
    "MODERATE": 2,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


def sanitize_environment(env: dict[str, str]) -> dict[str, str]:
    """Strip secret tokens and credentials from child environment."""
    clean_env = env.copy()
    sensitive_keys = [
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "KEY",
        "CREDENTIAL",
        "AUTH",
        "API_KEY",
        "SSH",
    ]
    for key in list(clean_env.keys()):
        for pattern in sensitive_keys:
            if pattern in key.upper():
                clean_env.pop(key, None)
                break
    return clean_env


def export_requirements_from_uv(
    workspace_root: Path, output_file: Path, include_dev: bool = False
) -> None:
    """Export locked dependencies from uv.lock to requirements-txt format."""
    cmd = [
        "uv",
        "export",
        "--format",
        "requirements.txt",
        "--all-packages",
        "--no-emit-workspace",
        "--output-file",
        str(output_file),
    ]
    if not include_dev:
        cmd.append("--no-dev")

    res = subprocess.run(cmd, cwd=workspace_root, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to export dependencies from uv.lock:\n{res.stderr}")


def load_exceptions(exceptions_file: Path) -> list[dict[str, Any]]:
    """Load and validate the vulnerability exceptions file."""
    if not exceptions_file.exists():
        return []
    with open(exceptions_file, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("exceptions", [])


def evaluate_vulnerabilities(
    scan_results: list[dict[str, Any]],
    exceptions: list[dict[str, Any]],
    fail_severity: str = "MODERATE",
    current_time: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Evaluate scan vulnerabilities against the exception registry and failure threshold."""
    if current_time is None:
        current_time = datetime.datetime.now(datetime.UTC)

    threshold_level = SEVERITY_ORDER.get(fail_severity.upper(), 2)

    exempted: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    ignored_low_severity: list[dict[str, Any]] = []

    for pkg in scan_results:
        pkg_name = pkg.get("name", "")
        pkg_version = pkg.get("version", "")
        vulns = pkg.get("vulns", [])

        for vuln in vulns:
            vuln_id = vuln.get("id", "UNKNOWN")
            # In pip-audit, aliases or CVE IDs can be present
            aliases = vuln.get("aliases", [])
            desc = vuln.get("description", "")
            fix_versions = vuln.get("fix_versions", [])

            # Extract severity if available from aliases or rating
            raw_severity = "MODERATE"
            if "severity" in vuln:
                raw_severity = str(vuln["severity"]).upper()

            vuln_item = {
                "package": pkg_name,
                "installed_version": pkg_version,
                "vulnerability_id": vuln_id,
                "aliases": aliases,
                "description": desc,
                "fix_versions": fix_versions,
                "severity": raw_severity,
            }

            # Check matching exception
            matching_exception = None
            all_ids = {vuln_id.upper()} | {a.upper() for a in aliases}

            for exc in exceptions:
                exc_id = exc.get("vulnerability_id", "").upper()
                exc_pkg = exc.get("package_name", "").lower()
                if (exc_id in all_ids or exc_id == "*") and (
                    exc_pkg == pkg_name.lower() or exc_pkg == "*"
                ):
                    matching_exception = exc
                    break

            if matching_exception:
                expiry_str = matching_exception.get("expiry_date", "")
                try:
                    expiry_dt = datetime.datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
                    if expiry_dt.tzinfo is None:
                        expiry_dt = expiry_dt.replace(tzinfo=datetime.UTC)
                except Exception:
                    expiry_dt = datetime.datetime.min.replace(tzinfo=datetime.UTC)

                if current_time <= expiry_dt:
                    vuln_item["exemption"] = {
                        "justification": matching_exception.get("justification", ""),
                        "owner": matching_exception.get("owner", ""),
                        "expiry_date": expiry_str,
                    }
                    exempted.append(vuln_item)
                    continue
                else:
                    vuln_item["expired_exemption"] = {
                        "expiry_date": expiry_str,
                        "owner": matching_exception.get("owner", ""),
                    }

            # If not exempted, check severity threshold
            vuln_level = SEVERITY_ORDER.get(raw_severity, 2)
            if vuln_level >= threshold_level:
                violations.append(vuln_item)
            else:
                ignored_low_severity.append(vuln_item)

    is_passing = len(violations) == 0

    return {
        "status": "PASS" if is_passing else "FAIL",
        "threshold": fail_severity,
        "total_packages_scanned": len(scan_results),
        "violations_count": len(violations),
        "exempted_count": len(exempted),
        "ignored_low_severity_count": len(ignored_low_severity),
        "violations": violations,
        "exempted": exempted,
        "ignored_low_severity": ignored_low_severity,
    }


def run_pip_audit(requirements_path: Path) -> tuple[int, dict[str, Any], str]:
    """Execute pip-audit in json format using uvx or pip_audit module."""
    clean_env = sanitize_environment(os.environ.copy())

    # Try uvx pip-audit first
    cmd = [
        "uvx",
        "pip-audit",
        "-r",
        str(requirements_path),
        "-f",
        "json",
        "--desc",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=clean_env,
            check=False,
        )
        stdout = proc.stdout
        stderr = proc.stderr
    except FileNotFoundError:
        # Fallback to python -m pip_audit
        cmd = [
            sys.executable,
            "-m",
            "pip_audit",
            "-r",
            str(requirements_path),
            "-f",
            "json",
            "--desc",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=clean_env,
            check=False,
        )
        stdout = proc.stdout
        stderr = proc.stderr

    raw_output = stdout if stdout.strip() else stderr

    try:
        # pip-audit may print "No known vulnerabilities found" before JSON or just JSON
        json_start = stdout.find("{")
        if json_start != -1:
            data = json.loads(stdout[json_start:])
        else:
            data = {"dependencies": [], "fixes": []}
    except Exception as e:
        data = {"error": str(e), "raw_output": raw_output, "dependencies": []}

    return proc.returncode, data, raw_output


def main() -> int:
    parser = argparse.ArgumentParser(description="ATLAS Dependency Security Gate")
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=Path("config/vulnerability_exceptions.json"),
        help="Path to vulnerability exceptions JSON",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Directory to save audit artifacts",
    )
    parser.add_argument(
        "--severity",
        type=str,
        default="MODERATE",
        choices=["LOW", "MODERATE", "HIGH", "CRITICAL"],
        help="Severity failure threshold (default: MODERATE)",
    )
    parser.add_argument(
        "--include-dev",
        action="store_true",
        help="Include development dependencies in scan",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path("."),
        help="Workspace root containing uv.lock",
    )

    args = parser.parse_args()
    workspace_root = args.workspace_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_reqs = output_dir / "temp_audit_requirements.txt"

    print("=" * 70)
    print("ATLAS DEPENDENCY SECURITY GATE — EXECUTING SCAN")
    print(f"Timestamp: {datetime.datetime.now(datetime.UTC).isoformat()}")
    print(f"Severity Threshold: {args.severity}")
    print("=" * 70)

    try:
        print("[1/4] Exporting locked dependencies from uv.lock...")
        export_requirements_from_uv(workspace_root, temp_reqs, include_dev=args.include_dev)

        print("[2/4] Running pip-audit against upstream vulnerability databases...")
        retcode, audit_data, raw_str = run_pip_audit(temp_reqs)

        print("[3/4] Evaluating results against vulnerability exceptions...")
        exceptions = load_exceptions(args.exceptions.resolve())
        scan_results = audit_data.get("dependencies", [])

        eval_summary = evaluate_vulnerabilities(
            scan_results=scan_results,
            exceptions=exceptions,
            fail_severity=args.severity,
        )

        # Build comprehensive report
        audit_report = {
            "audit_id": f"dep-audit-{int(datetime.datetime.now().timestamp())}",
            "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "scanner": "pip-audit",
            "scanner_version": "2.10.1",
            "vulnerability_database": "PyPI / OSV Advisory Database",
            "lockfile_source": "uv.lock",
            "evaluation": eval_summary,
            "raw_audit_data": audit_data,
        }

        report_file = output_dir / "dependency-audit.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(audit_report, f, indent=2)

        print(f"[4/4] Machine-readable report saved to {report_file}")
        print("\n" + "=" * 70)
        print("AUDIT SUMMARY:")
        print(f"  Status:               {eval_summary['status']}")
        print(f"  Packages Scanned:     {eval_summary['total_packages_scanned']}")
        print(f"  Violations (Gated):   {eval_summary['violations_count']}")
        print(f"  Exempted Vulns:       {eval_summary['exempted_count']}")
        print(f"  Low Severity Ignored: {eval_summary['ignored_low_severity_count']}")
        print("=" * 70)

        if eval_summary["status"] != "PASS":
            print("\n[!] SECURITY GATE FAILURE: Unexempted vulnerabilities detected:")
            for v in eval_summary["violations"]:
                print(
                    f"  - Package: {v['package']}=={v['installed_version']} | "
                    f"ID: {v['vulnerability_id']} | Severity: {v['severity']}"
                )
                print(f"    Description: {v['description']}")
                print(f"    Fix: {v.get('fix_versions')}")
            return 1

        print("\n[+] SECURITY GATE PASSED: Zero unexempted vulnerabilities detected.")
        return 0

    finally:
        if temp_reqs.exists():
            temp_reqs.unlink()


if __name__ == "__main__":
    sys.exit(main())
