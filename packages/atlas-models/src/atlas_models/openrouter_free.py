"""OpenRouter adapter that revalidates free model pricing before every inference."""

from __future__ import annotations

from atlas_core.contracts.model import ModelRequest

from atlas_models.adapters.openai_compatible import OpenAICompatibleAdapter

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


class FreeModelPriceChangedError(RuntimeError):
    """Raised when an OpenRouter model is no longer explicitly priced at zero."""


class OpenRouterFreeAdapter(OpenAICompatibleAdapter):
    """OpenAI-compatible adapter with live zero-price validation for exact `:free` IDs."""

    async def complete(self, request: ModelRequest):
        model_id = request.model_name or self.get_capabilities().model_name
        if model_id == "openrouter/free":
            return await super().complete(request)
        if not model_id.endswith(":free"):
            raise FreeModelPriceChangedError("Only OpenRouter's exact free model IDs are allowed.")
        try:
            inventory = await self._client.get(
                OPENROUTER_MODELS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except Exception as exc:
            raise FreeModelPriceChangedError(
                f"Could not revalidate free model pricing ({type(exc).__name__}); inference was blocked."
            ) from exc
        if inventory.status_code != 200:
            raise FreeModelPriceChangedError(
                f"Could not revalidate free model pricing (HTTP {inventory.status_code}); inference was blocked."
            )
        try:
            payload = inventory.json()
            data = payload.get("data")
        except (ValueError, AttributeError) as exc:
            raise FreeModelPriceChangedError(
                "Provider inventory response was invalid; inference was blocked."
            ) from exc
        if not isinstance(data, list):
            raise FreeModelPriceChangedError(
                "Provider inventory did not contain a model list; inference was blocked."
            )
        record = next(
            (item for item in data if isinstance(item, dict) and item.get("id") == model_id),
            None,
        )
        pricing = (record or {}).get("pricing")
        if not isinstance(pricing, dict) or not pricing:
            raise FreeModelPriceChangedError(
                "Provider did not return complete price evidence; inference was blocked."
            )
        try:
            zero_price = all(float(value) == 0.0 for value in pricing.values())
        except (TypeError, ValueError):
            zero_price = False
        if not zero_price:
            raise FreeModelPriceChangedError(
                "Provider price is nonzero or unknown; inference was blocked."
            )
        return await super().complete(request)
