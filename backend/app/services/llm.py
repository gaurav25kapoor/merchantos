from dataclasses import dataclass

from app.config import settings
from app.schemas import BuyerIntent


@dataclass
class ToolPlan:
    tools: list[str]
    needs_policy: bool = False
    needs_details: bool = False


class LLMProvider:
    name = "fallback"

    def plan_tools(self, message: str, intent: BuyerIntent) -> ToolPlan:
        raise NotImplementedError


class DeterministicLLMProvider(LLMProvider):
    name = "deterministic-fallback"

    def plan_tools(self, message: str, intent: BuyerIntent) -> ToolPlan:
        normalized = message.lower()
        if any(word in normalized for word in ("return", "refund", "cancel", "cancellation", "policy")):
            return ToolPlan(tools=["get_merchant_policy"], needs_policy=True)
        if any(phrase in normalized for phrase in ("better version", "upgrade", "better option", "premium")):
            return ToolPlan(tools=["search_products", "get_growth_experiment_variant", "get_upsell_recommendations"])
        if any(phrase in normalized for phrase in ("accessories", "accessory", "go with", "complement", "compatible")):
            return ToolPlan(tools=["search_products", "get_cross_sell_recommendations"])
        if any(phrase in normalized for phrase in ("give me this for", "can you give me", "offer", "negotiate", "discount")):
            return ToolPlan(tools=["search_products", "negotiate_price"])
        if any(phrase in normalized for phrase in ("checkout", "place order", "pay now")):
            return ToolPlan(tools=["checkout_cart"])
        if any(phrase in normalized for phrase in ("view cart", "show cart", "cart total")):
            return ToolPlan(tools=["view_cart"])
        if any(phrase in normalized for phrase in ("add to cart", "add this", "put this in cart")):
            return ToolPlan(tools=["add_to_cart"])
        tools = ["search_products"]
        if intent.requires_in_stock:
            tools.append("check_inventory")
        tools.append("rank_products")
        if "detail" in normalized or "cheapest" in normalized:
            tools.append("get_product_details")
        return ToolPlan(tools=tools, needs_details="detail" in normalized or "cheapest" in normalized)


class ConfiguredLLMProvider(LLMProvider):
    name = "configured-unavailable"

    def plan_tools(self, message: str, intent: BuyerIntent) -> ToolPlan:
        raise RuntimeError("Configured LLM provider is unavailable in this environment")


def get_llm_provider() -> LLMProvider:
    if settings.llm_api_key and settings.llm_provider.lower() != "fallback":
        return ConfiguredLLMProvider()
    return DeterministicLLMProvider()
