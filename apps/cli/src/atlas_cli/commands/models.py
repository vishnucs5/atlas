"""Model management commands for ATLAS CLI."""

from atlas_cli.configuration.manager import ConfigManager
from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    colorize,
    render_badge,
    render_table,
)

AVAILABLE_MODELS = [
    {
        "name": "atlas:hermetic-default",
        "provider": "atlas",
        "context": "32k",
        "vision": "Yes",
        "tools": "Yes",
        "status": "active",
    },
    {
        "name": "openai/gpt-4o",
        "provider": "openai",
        "context": "128k",
        "vision": "Yes",
        "tools": "Yes",
        "status": "ready",
    },
    {
        "name": "anthropic/claude-3-5-sonnet",
        "provider": "anthropic",
        "context": "200k",
        "vision": "Yes",
        "tools": "Yes",
        "status": "ready",
    },
    {
        "name": "gemini/gemini-2.5-pro",
        "provider": "gemini",
        "context": "1M+",
        "vision": "Yes",
        "tools": "Yes",
        "status": "ready",
    },
    {
        "name": "ollama/llama3",
        "provider": "ollama (local)",
        "context": "8k",
        "vision": "No",
        "tools": "Yes",
        "status": "local",
    },
]


def run_models_list() -> int:
    """List available and registered model adapters."""
    cfg = ConfigManager()
    active_model = cfg.get("default_model", "atlas:hermetic-default")

    print(colorize("\n[ATLAS MODEL REGISTRY]", BOLD + CYAN))
    headers = ["Model Identifier", "Provider", "Context", "Vision", "Tool Calling", "Selection"]
    rows = []
    for m in AVAILABLE_MODELS:
        is_active = m["name"] == active_model
        sel = render_badge("ACTIVE", "success") if is_active else render_badge(m["status"], "dim")
        rows.append(
            [
                m["name"],
                m["provider"],
                m["context"],
                m["vision"],
                m["tools"],
                sel,
            ]
        )

    print(render_table(headers, rows))
    print(colorize(f"\nCurrent active model: {active_model}", BOLD + GREEN))
    return 0


def run_models_use(model_name: str) -> int:
    """Switch the default active model."""
    cfg = ConfigManager()
    valid_names = [m["name"] for m in AVAILABLE_MODELS]
    # Allow partial prefix match
    matched = None
    for name in valid_names:
        if model_name.lower() in name.lower():
            matched = name
            break

    target = matched or model_name
    cfg.set("default_model", target)
    print(colorize(f"✓ Active model set to: '{target}'", BOLD + GREEN))
    return 0


def run_models_configure() -> int:
    """Display model configuration guides and environment key status."""
    import os

    cfg = ConfigManager()
    active = cfg.get("default_model", "atlas:hermetic-default")

    print(colorize("\n[ATLAS MODEL CONFIGURATION]", BOLD + CYAN))
    print(f"Active Model: {colorize(active, BOLD)}")
    print("-" * 60)
    print("Provider API Key Status:")
    for key, prov in [
        ("OPENAI_API_KEY", "OpenAI"),
        ("ANTHROPIC_API_KEY", "Anthropic"),
        ("GEMINI_API_KEY", "Gemini"),
    ]:
        is_set = key in os.environ
        badge = (
            render_badge("CONFIGURED", "success")
            if is_set
            else render_badge("UNSET (Using Hermetic Fallback)", "warning")
        )
        print(f"  * {prov:12} ({key:20}): {badge}")
    print("-" * 60)
    print(
        colorize("Set keys via environment variables or run 'atlas config set <key> <val>'.", DIM)
    )
    return 0
