"""Model Provider Adapters."""

from atlas_models.adapters.anthropic import AnthropicAdapter
from atlas_models.adapters.gemini import GeminiAdapter
from atlas_models.adapters.ollama import OllamaAdapter
from atlas_models.adapters.openai import OpenAIAdapter
from atlas_models.adapters.openai_compatible import OpenAICompatibleAdapter

__all__ = [
    "AnthropicAdapter",
    "GeminiAdapter",
    "OllamaAdapter",
    "OpenAIAdapter",
    "OpenAICompatibleAdapter",
]
