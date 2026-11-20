"""Free-only model catalog and credential governance commands."""

from __future__ import annotations

import os
import sys
from getpass import getpass
from typing import Any

import httpx
from atlas_models.credentials import (
    PROVIDER_ENV,
    CredentialStoreUnavailable,
    get_credential,
    remove_credential,
    set_credential,
)
from atlas_models.free_inventory import load_cached_free_ids, save_cached_free_ids

from atlas_cli.configuration.manager import ConfigManager
from atlas_cli.rendering.formatters import BOLD, CYAN, GREEN, colorize, render_badge, render_table

PROVIDERS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "label": "OpenRouter Free",
        "signup": "https://openrouter.ai/keys",
        "models": ["openrouter/free"],
        "attestation": None,
    },
    "google": {
        "label": "Google AI Studio",
        "signup": "https://aistudio.google.com/app/apikey",
        "models": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
        "attestation": "ATLAS_GEMINI_FREE_TIER_ATTESTED",
    },
    "cloudflare": {
        "label": "Cloudflare Workers AI",
        "signup": "https://dash.cloudflare.com/profile/api-tokens",
        "models": ["@cf/meta/llama-3.3-70b-instruct-fp8-fast"],
        "attestation": "ATLAS_CLOUDFLARE_WORKERS_FREE_ATTESTED",
    },
}


def run_models_list() -> int:
    """List supported zero-cost routes with auth and account-attestation state."""
    cfg = ConfigManager()
    active = cfg.get("default_model", "openrouter/free")
    rows = []
    for provider_id, provider in PROVIDERS.items():
        try:
            key_present = bool(get_credential(provider_id))
        except CredentialStoreUnavailable:
            key_present = False
        attested = not provider["attestation"] or os.environ.get(provider["attestation"]) == "1"
        model_ids = list(provider["models"])
        if provider_id == "openrouter":
            try:
                model_ids.extend(load_cached_free_ids(cfg.config_dir))
            except ValueError:
                print(
                    "OpenRouter inventory cache is malformed; run 'atlas models refresh' to replace it.",
                    file=sys.stderr,
                )
        for model_id in sorted(set(model_ids)):
            status = (
                "READY"
                if key_present and attested
                else ("NEEDS_ATTESTATION" if key_present else "NEEDS_KEY")
            )
            rows.append(
                [
                    model_id,
                    provider["label"],
                    render_badge(
                        "ACTIVE" if active == model_id else status,
                        "success" if active == model_id else "dim",
                    ),
                ]
            )
        if provider_id == "cloudflare" and (
            not os.environ.get("CLOUDFLARE_ACCOUNT_ID")
            or not os.environ.get("ATLAS_CLOUDFLARE_WORKERS_FREE_ATTESTED")
        ):
            rows[-1][2] = render_badge("NEEDS_ACCOUNT_OR_ATTESTATION", "warning")
    print(colorize("\n[ATLAS ZERO-COST MODEL CATALOG]", BOLD + CYAN))
    if rows:
        print(render_table(["Exact Model ID", "Provider", "Status"], rows))
    else:
        print("No currently eligible free models are configured.")
    print(
        "\nFree route inventory is provider-specific and can change. Use 'atlas models refresh' to inspect current OpenRouter listings."
    )
    return 0


def run_models_use(model_name: str) -> int:
    """Select an exact free catalog model ID."""
    valid = {model for provider in PROVIDERS.values() for model in provider["models"]}
    if model_name.endswith(":free"):
        try:
            valid.update(load_cached_free_ids())
        except ValueError:
            print(
                "OpenRouter free inventory cache is malformed; refresh it before selecting a model.",
                file=sys.stderr,
            )
            return 2
    if model_name not in valid:
        print(f"Blocked: '{model_name}' is not an exact selectable free model ID.", file=sys.stderr)
        return 2
    cfg = ConfigManager()
    cfg.set("default_model", model_name)
    print(colorize(f"Free model set to: {model_name}", BOLD + GREEN))
    return 0


def _preflight(provider_id: str, key: str) -> tuple[str, str]:
    headers = {}
    if provider_id == "openrouter":
        url = "https://openrouter.ai/api/v1/key"
        headers["Authorization"] = f"Bearer {key}"
    elif provider_id == "google":
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash"
        headers["x-goog-api-key"] = key
    else:
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        if not account_id:
            return (
                "NEEDS_ACCOUNT_ID",
                "Set CLOUDFLARE_ACCOUNT_ID before probing Cloudflare Workers AI",
            )
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models/search?search=llama-3.3-70b-instruct-fp8-fast"
        headers["Authorization"] = f"Bearer {key}"

    try:
        response = httpx.get(url, headers=headers, timeout=10, follow_redirects=False)
    except httpx.HTTPError as exc:
        return "UNAVAILABLE", type(exc).__name__
    if response.status_code in (401, 403):
        return (
            "INVALID_KEY" if response.status_code == 401 else "FORBIDDEN"
        ), f"HTTP {response.status_code}"
    if response.status_code == 429:
        return "RATE_LIMITED", "HTTP 429"
    if response.status_code >= 500:
        return "UNAVAILABLE", f"HTTP {response.status_code}"
    if response.status_code >= 400:
        return "UNAVAILABLE", f"HTTP {response.status_code}"
    return (
        "CONFIGURED",
        "key metadata probe succeeded; inference access is checked on the first completion",
    )


def run_models_configure(provider_id: str | None = None) -> int:
    """Configure a provider key through hidden input and save it to OS keyring."""
    if not provider_id:
        cfg = ConfigManager()
        active = cfg.get("default_model", "openrouter/free")
        print(colorize("\n[ATLAS MODEL CONFIGURATION]", BOLD + CYAN))
        print(f"Active Model: {colorize(active, BOLD)}")
        print("-" * 60)
        print("Provider API Key Status:")
        for prov, info in PROVIDERS.items():
            env_var = PROVIDER_ENV[prov]
            is_set = bool(get_credential(prov))
            badge = (
                render_badge("CONFIGURED", "success")
                if is_set
                else render_badge("NEEDS_KEY", "warning")
            )
            print(f"  * {info['label']:22} ({env_var}): {badge}")
        print("-" * 60)
        print("To configure a provider key: atlas models configure <provider>")
        print("Supported providers: openrouter, google, cloudflare")
        return 0
    provider_id = provider_id.lower()
    if provider_id not in PROVIDERS:
        print("Unsupported provider. Choose openrouter, google, or cloudflare.", file=sys.stderr)
        return 2
    if os.environ.get(PROVIDER_ENV[provider_id]):
        print(f"{PROVIDER_ENV[provider_id]} is already set in the environment and is read-only.")
        return 0
    if not sys.stdin.isatty():
        try:
            line = sys.stdin.readline().strip()
        except Exception:
            line = ""
        if line:
            secret = line
        else:
            print(
                f"NEEDS_KEY: create a key at {PROVIDERS[provider_id]['signup']} and set {PROVIDER_ENV[provider_id]} in the environment."
            )
            return 0
    else:
        print(f"Create a free-tier key: {PROVIDERS[provider_id]['signup']}")
        try:
            secret = getpass(f"Paste {PROVIDER_ENV[provider_id]} (input hidden; blank to cancel): ")
        except (EOFError, KeyboardInterrupt):
            print("Credential setup cancelled.")
            return 1
    if not secret:
        print("Credential setup skipped.")
        return 0
    secret = secret.strip()
    if provider_id == "openrouter" and "sk-or-" in secret:
        for token in secret.split():
            if token.startswith("sk-or-"):
                secret = token
                break
    try:
        set_credential(provider_id, secret)
    except CredentialStoreUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    del secret
    print(
        "Credential saved to the OS keyring. Run 'atlas models test "
        + provider_id
        + "' to check connectivity."
    )
    return 0


def run_models_test(provider_id: str) -> int:
    """Perform a non-generation provider metadata request."""
    provider_id = provider_id.lower()
    if provider_id not in PROVIDERS:
        print("Unsupported provider.", file=sys.stderr)
        return 2
    try:
        key = get_credential(provider_id)
    except CredentialStoreUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not key:
        print("NEEDS_KEY. Run 'atlas models configure " + provider_id + "'.")
        return 1
    attestation_var = PROVIDERS[provider_id]["attestation"]
    if attestation_var and os.environ.get(attestation_var) != "1":
        print(
            f"Authentication probe is available, but zero-cost account eligibility requires explicit attestation ({attestation_var}=1)."
        )
    status, detail = _preflight(provider_id, key)
    del key
    print(f"{status}: {detail}")
    return 0 if status == "CONFIGURED" else 1


def run_models_remove(provider_id: str) -> int:
    """Remove a provider key from OS keyring; environment-owned keys stay untouched."""
    provider_id = provider_id.lower()
    if provider_id not in PROVIDERS:
        print("Unsupported provider.", file=sys.stderr)
        return 2
    if os.environ.get(PROVIDER_ENV[provider_id]):
        print(
            f"{PROVIDER_ENV[provider_id]} is set in the environment and is read-only; remove it from the shell configuration."
        )
    try:
        deleted = remove_credential(provider_id)
    except CredentialStoreUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print("Keyring credential removed." if deleted else "No keyring credential found.")
    return 0


def run_models_refresh() -> int:
    """Fetch OpenRouter's inventory and show entries with explicit zero token prices."""
    try:
        response = httpx.get(
            "https://openrouter.ai/api/v1/models", timeout=15, follow_redirects=False
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(
            f"Inventory unavailable ({type(exc).__name__}); existing selection was not changed.",
            file=sys.stderr,
        )
        return 1
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        print(
            "Inventory response did not contain a model list; cache was not changed.",
            file=sys.stderr,
        )
        return 1
    free_models = []
    free_model_ids = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str):
            continue
        pricing = item.get("pricing") or {}
        zero_pricing = isinstance(pricing, dict) and bool(pricing)
        if zero_pricing:
            try:
                zero_pricing = all(float(value) == 0.0 for value in pricing.values())
            except (TypeError, ValueError):
                zero_pricing = False
        if model_id == "openrouter/free" or (model_id.endswith(":free") and zero_pricing):
            free_models.append(
                [
                    item.get("id", ""),
                    item.get("name", ""),
                    "zero token price listed; account terms still apply",
                ]
            )
            if model_id.endswith(":free"):
                free_model_ids.append(model_id)
    cfg = ConfigManager()
    try:
        cache_path = save_cached_free_ids(free_model_ids, cfg.config_dir)
    except OSError as exc:
        print(f"Could not save free inventory cache ({type(exc).__name__}).", file=sys.stderr)
        return 1
    print(render_table(["Model ID", "Name", "Evidence"], free_models))
    print(
        f"Discovered {len(free_models)} OpenRouter free routes and refreshed the one-hour inventory cache at {cache_path}."
    )
    print(
        "Each selected :free model is rechecked against live zero-price metadata before inference; stale cache entries are not executable."
    )
    return 0
