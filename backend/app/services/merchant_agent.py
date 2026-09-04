import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AgentSession, Merchant
from app.schemas import AgentChatResponse, BuyerIntent, RankedProductOut, RecommendationOut, ToolCallOut
from app.services.audit import AuditService
from app.services.agent_tools import ToolRegistry
from app.services.intent import IntentExtractor
from app.services.llm import DeterministicLLMProvider, ToolPlan, get_llm_provider


class MerchantAgent:
    def __init__(self, db: Session, registry: ToolRegistry | None = None):
        self.db = db
        self.registry = registry or ToolRegistry()
        self.intent_extractor = IntentExtractor()
        self.provider = get_llm_provider()

    def chat(self, merchant_id: UUID, message: str, session_id: UUID | None = None, limit: int = 20, cart_id: UUID | None = None, product_id: UUID | None = None, variant_id: UUID | None = None, quantity: int | None = None) -> AgentChatResponse:
        merchant = self.db.get(Merchant, merchant_id)
        if not merchant or not merchant.is_active:
            raise ValueError("Merchant not found")
        is_new_session = session_id is None
        session = self._get_or_create_session(merchant_id, session_id)
        if is_new_session:
            AuditService(self.db).log_event(merchant_id, "agent_session_started", "agent_session", session.id, actor_type="agent", actor_id=session.id, metadata={})
        intent = self.intent_extractor.extract(message)
        plan = self._plan(message, intent)
        plan = self._optimize_plan(plan, product_id, variant_id)

        products: list[dict] = []
        recommendations: list[dict] = []
        cart: dict | None = None
        checkout: dict | None = None
        policy: dict | None = None
        negotiation: dict | None = None
        calls = []
        context = {
            "cart_id": str(cart_id) if cart_id else None,
            "product_id": str(product_id) if product_id else None,
            "variant_id": str(variant_id) if variant_id else None,
            "quantity": quantity or extract_quantity_hint(message) or 1,
            "offered_price": str(extract_offer_price(message)) if extract_offer_price(message) is not None else None,
        }

        for tool_name in self._dedupe(plan.tools):
            tool_input = self._build_tool_input(tool_name, intent, products, policy, limit, session.id, context)
            if tool_input is None:
                continue
            output, call = self.registry.execute(self.db, session.id, merchant_id, tool_name, tool_input)
            calls.append(call)
            if output is None:
                continue
            if tool_name == "search_products":
                products = output["results"]
            elif tool_name == "rank_products":
                products = output["products"]
            elif tool_name == "get_merchant_policy":
                policy = output["policy"]
            elif tool_name == "get_product_details" and products:
                products[0]["details"] = output["product"]
            elif tool_name == "negotiate_price":
                negotiation = output
            elif tool_name in ("get_upsell_recommendations", "get_cross_sell_recommendations"):
                recommendations = output["results"]
            elif tool_name in ("add_to_cart", "view_cart"):
                cart = output
            elif tool_name == "checkout_cart":
                checkout = output

        self.db.commit()
        self.db.refresh(session)
        response_products = [RankedProductOut.model_validate(product) for product in products if "rank" in product]
        response_recommendations = [RecommendationOut.model_validate(item) for item in recommendations]
        response = self._response_message(intent, response_products, policy, negotiation, response_recommendations, cart, checkout)
        AuditService(self.db).log_event(
            merchant_id,
            "agent_response_generated",
            "agent_session",
            session.id,
            actor_type="agent",
            actor_id=session.id,
            metadata={"tool_call_count": len(calls), "provider": self.provider.name},
        )
        self.db.commit()
        return AgentChatResponse(
            session_id=session.id,
            intent=intent,
            response=response,
            products=response_products,
            recommendations=response_recommendations,
            cart=cart,
            checkout=checkout,
            tool_calls=[
                ToolCallOut(
                    id=call.id,
                    tool_name=call.tool_name,
                    tool_input=call.tool_input,
                    tool_output=call.tool_output,
                    success=call.success,
                    error=call.error,
                    duration_ms=call.duration_ms,
                )
                for call in calls
            ],
            provider=self.provider.name,
        )

    def _get_or_create_session(self, merchant_id: UUID, session_id: UUID | None) -> AgentSession:
        if session_id:
            session = (
                self.db.query(AgentSession)
                .filter(AgentSession.id == session_id)
                .filter(AgentSession.merchant_id == merchant_id)
                .one_or_none()
            )
            if not session:
                raise ValueError("Agent session not found")
            return session
        session = AgentSession(merchant_id=merchant_id, context={})
        self.db.add(session)
        self.db.flush()
        return session

    def _plan(self, message: str, intent: BuyerIntent) -> ToolPlan:
        try:
            return self.provider.plan_tools(message, intent)
        except Exception:
            self.provider = DeterministicLLMProvider()
            return self.provider.plan_tools(message, intent)

    def _optimize_plan(self, plan: ToolPlan, product_id: UUID | None, variant_id: UUID | None) -> ToolPlan:
        tools = plan.tools
        if variant_id and "negotiate_price" in tools:
            tools = [tool for tool in tools if tool != "search_products"]
        if product_id and any(tool in tools for tool in ("get_upsell_recommendations", "get_cross_sell_recommendations")):
            tools = [tool for tool in tools if tool != "search_products"]
        return ToolPlan(tools=tools, needs_policy=plan.needs_policy, needs_details=plan.needs_details)

    def _build_tool_input(self, tool_name: str, intent: BuyerIntent, products: list[dict], policy: dict | None, limit: int, session_id: UUID, context: dict) -> dict | None:
        if tool_name == "search_products":
            return {
                "query": intent.query,
                "category": intent.category,
                "brand": intent.brand,
                "min_price": str(intent.min_price) if intent.min_price is not None else None,
                "max_price": str(intent.max_price) if intent.max_price is not None else None,
                "in_stock": intent.requires_in_stock,
                "attributes": intent.attributes,
                "limit": limit,
            }
        if tool_name == "check_inventory":
            if not products:
                return None
            return {"variant_id": products[0]["variant_id"]}
        if tool_name == "get_product_details":
            if not products:
                return None
            return {"product_id": products[0]["product_id"]}
        if tool_name == "get_merchant_policy":
            return {"policy_type": None}
        if tool_name == "rank_products":
            return {"products": products, "intent": intent.model_dump(mode="json"), "policy": policy}
        if tool_name == "negotiate_price":
            offered_price = context.get("offered_price")
            variant_id = context.get("variant_id") or (products[0]["variant_id"] if products else None)
            if not offered_price or not variant_id:
                return None
            return {"variant_id": variant_id, "offered_price": offered_price, "session_id": str(session_id)}
        if tool_name in ("get_upsell_recommendations", "get_cross_sell_recommendations"):
            product_id = context.get("product_id") or (products[0]["product_id"] if products else None)
            if not product_id:
                return None
            return {"product_id": product_id, "session_id": str(session_id), "limit": min(limit, 3)}
        if tool_name == "get_growth_experiment_variant":
            return {"session_id": str(session_id), "experiment_name": "upsell_strategy"}
        if tool_name == "add_to_cart":
            if not context.get("cart_id") or not context.get("variant_id"):
                return None
            return {"cart_id": context["cart_id"], "product_variant_id": context["variant_id"], "quantity": context["quantity"]}
        if tool_name == "view_cart":
            if not context.get("cart_id"):
                return None
            return {"cart_id": context["cart_id"]}
        if tool_name == "checkout_cart":
            if not context.get("cart_id"):
                return None
            return {"cart_id": context["cart_id"]}
        return {}

    def _response_message(self, intent: BuyerIntent, products: list[RankedProductOut], policy: dict | None, negotiation: dict | None, recommendations: list[RecommendationOut], cart: dict | None, checkout: dict | None) -> str:
        if policy:
            return f"Returns are allowed within {policy['return_window_days']} days. Cancellation window is {policy['cancellation_window_minutes']} minutes."
        if checkout:
            return f"Checkout is ready for Rs. {checkout['amount']}."
        if cart:
            return f"Cart has {cart['total_item_count']} item(s), total Rs. {cart['total_amount']}."
        if negotiation:
            if negotiation["decision"] == "ACCEPT":
                return f"I can accept Rs. {negotiation['approved_price']} for this item."
            if negotiation["decision"] == "COUNTER_OFFER":
                return f"I can't accept that offer, but I can do Rs. {negotiation['counter_offer']}."
            return negotiation["reason"]
        if recommendations:
            return f"I found {len(recommendations)} recommendation for you. Top pick: {recommendations[0].name}."
        if not products:
            descriptor = intent.query or intent.category or "matching products"
            return f"I couldn't find {descriptor} for those filters."
        descriptor = intent.query or intent.category or "matching products"
        price_part = f" under Rs. {intent.max_price}" if intent.max_price is not None else ""
        stock_part = " that are in stock" if intent.requires_in_stock else ""
        return f"I found {len(products)} {descriptor}{price_part}{stock_part}. The top match is {products[0].name}."

    def _dedupe(self, tools: list[str]) -> list[str]:
        seen = set()
        deduped = []
        for tool in tools:
            if tool not in seen:
                seen.add(tool)
                deduped.append(tool)
        return deduped


def extract_offer_price(message: str) -> Decimal | None:
    match = re.search(r"(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", message.lower())
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def extract_quantity_hint(message: str) -> int | None:
    match = re.search(r"\b([1-9][0-9]*)\s*(?:items?|pieces?|pcs?|units?)\b", message.lower())
    return int(match.group(1)) if match else None
