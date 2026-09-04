from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.models import AgentToolCall, Inventory, MerchantPolicy, Product, ProductVariant
from app.schemas import BuyerIntent, SearchResultOut
from app.services.audit import AuditService
from app.services.cart import CartService
from app.services.checkout import CheckoutService
from app.services.experiments import GrowthExperimentService
from app.services.negotiation import NegotiationService
from app.services.recommendations import RecommendationService
from app.services.search import SearchCriteria, SearchService, normalize_text


class SearchProductsInput(BaseModel):
    query: str | None = None
    category: str | None = None
    brand: str | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    in_stock: bool | None = None
    attributes: dict | None = None
    limit: int = Field(default=20, ge=1, le=50)


class ProductDetailsInput(BaseModel):
    product_id: UUID


class InventoryInput(BaseModel):
    variant_id: UUID


class MerchantPolicyInput(BaseModel):
    policy_type: str | None = Field(default=None, max_length=80)


class RankProductsInput(BaseModel):
    products: list[dict]
    intent: BuyerIntent
    policy: dict | None = None


class NegotiatePriceInput(BaseModel):
    variant_id: UUID
    offered_price: Decimal = Field(gt=0)
    session_id: UUID | None = None


class ProductRecommendationsInput(BaseModel):
    product_id: UUID
    session_id: UUID | None = None
    limit: int = Field(default=3, ge=1, le=10)


class GrowthExperimentInput(BaseModel):
    session_id: UUID
    experiment_name: str = Field(min_length=1, max_length=120)


class AddToCartInput(BaseModel):
    cart_id: UUID
    product_variant_id: UUID
    quantity: int = Field(gt=0)


class ViewCartInput(BaseModel):
    cart_id: UUID


class CheckoutCartInput(BaseModel):
    cart_id: UUID
    buyer_session_id: str | None = Field(default=None, max_length=120)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    input_model: type[BaseModel]
    handler: Callable[[Session, UUID, BaseModel], dict]


class ToolExecutionError(ValueError):
    pass


def search_products(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    args = payload if isinstance(payload, SearchProductsInput) else SearchProductsInput.model_validate(payload)
    results = SearchService(db).search(
        SearchCriteria(
            query=args.query,
            merchant_id=merchant_id,
            category=args.category,
            brand=args.brand,
            min_price=args.min_price,
            max_price=args.max_price,
            in_stock=args.in_stock,
            attributes=args.attributes,
            limit=args.limit,
        )
    )
    return {"results": [SearchResultOut(**result.__dict__).model_dump(mode="json") for result in results], "total": len(results)}


def get_product_details(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    args = payload if isinstance(payload, ProductDetailsInput) else ProductDetailsInput.model_validate(payload)
    product = (
        db.query(Product)
        .filter(Product.id == args.product_id)
        .filter(Product.merchant_id == merchant_id)
        .filter(Product.is_active.is_(True))
        .one_or_none()
    )
    if not product:
        raise ToolExecutionError("Product not found")
    variants = (
        db.query(ProductVariant, Inventory)
        .outerjoin(Inventory, Inventory.variant_id == ProductVariant.id)
        .filter(ProductVariant.product_id == product.id)
        .filter(ProductVariant.is_active.is_(True))
        .order_by(ProductVariant.price.asc(), ProductVariant.sku.asc())
        .all()
    )
    return {
        "product": {
            "product_id": str(product.id),
            "merchant_id": str(product.merchant_id),
            "name": product.name,
            "description": product.description,
            "category": product.category,
            "brand": product.brand,
            "variants": [
                {
                    "variant_id": str(variant.id),
                    "sku": variant.sku,
                    "attributes": variant.attributes or {},
                    "price": str(variant.price),
                    "available_quantity": inventory.available_quantity if inventory else 0,
                    "available": bool(inventory and inventory.available_quantity > 0),
                }
                for variant, inventory in variants
            ],
        }
    }


def check_inventory(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    args = payload if isinstance(payload, InventoryInput) else InventoryInput.model_validate(payload)
    row = (
        db.query(ProductVariant, Product, Inventory)
        .join(Product, Product.id == ProductVariant.product_id)
        .outerjoin(Inventory, Inventory.variant_id == ProductVariant.id)
        .filter(ProductVariant.id == args.variant_id)
        .filter(Product.merchant_id == merchant_id)
        .filter(Product.is_active.is_(True))
        .filter(ProductVariant.is_active.is_(True))
        .one_or_none()
    )
    if not row:
        raise ToolExecutionError("Variant not found")
    variant, product, inventory = row
    available_quantity = inventory.available_quantity if inventory else 0
    return {
        "variant_id": str(variant.id),
        "product_id": str(product.id),
        "sku": variant.sku,
        "available_quantity": available_quantity,
        "available": available_quantity > 0,
        "status": inventory.status if inventory else "unknown",
    }


def get_merchant_policy(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.merchant_id == merchant_id).one_or_none()
    if not policy:
        raise ToolExecutionError("Merchant policy not found")
    return {
        "policy": {
            "merchant_id": str(policy.merchant_id),
            "return_window_days": policy.return_window_days,
            "cancellation_window_minutes": policy.cancellation_window_minutes,
            "minimum_order_value": str(policy.minimum_order_value),
            "maximum_discount_percent": str(policy.maximum_discount_percent),
            "free_shipping_threshold": str(policy.free_shipping_threshold) if policy.free_shipping_threshold is not None else None,
            "rules": policy.rules or {},
        }
    }


def rank_products(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    del db, merchant_id
    args = payload if isinstance(payload, RankProductsInput) else RankProductsInput.model_validate(payload)
    ranked = []
    for item in args.products:
        product = SearchResultOut.model_validate(item)
        score, reasons = explain_score(product, args.intent)
        ranked.append({**product.model_dump(mode="json"), "score": score, "reasons": reasons})
    ranked.sort(key=lambda product: (-product["score"], Decimal(product["price"]), product["name"].lower(), product["sku"].lower()))
    return {"products": [{**product, "rank": index + 1} for index, product in enumerate(ranked)], "total": len(ranked)}


def explain_score(product: SearchResultOut, intent: BuyerIntent) -> tuple[int, list[str]]:
    score = product.score
    reasons: list[str] = []
    if intent.category and normalize_text(product.category) == normalize_text(intent.category):
        score += 20
        reasons.append("matches requested category")
    if intent.max_price is not None and product.price <= intent.max_price:
        score += 15
        reasons.append("within budget")
    if intent.min_price is not None and product.price >= intent.min_price:
        score += 5
        reasons.append("above minimum price")
    if product.available:
        score += 10
        reasons.append("currently in stock")
    attributes = intent.attributes or {}
    for key, value in attributes.items():
        if key == "features" or value is None:
            continue
        if normalize_text(product.attributes.get(key)) == normalize_text(value):
            score += 15
            reasons.append(f"matches requested {key}")
    if not reasons:
        reasons.append("matches the search request")
    return score, reasons


def negotiate_price(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    args = payload if isinstance(payload, NegotiatePriceInput) else NegotiatePriceInput.model_validate(payload)
    return NegotiationService(db).negotiate(merchant_id, args.variant_id, args.offered_price, args.session_id)


def get_upsell_recommendations(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    args = payload if isinstance(payload, ProductRecommendationsInput) else ProductRecommendationsInput.model_validate(payload)
    results = RecommendationService(db).upsells(merchant_id, args.product_id, args.limit, args.session_id)
    return {"results": results, "total": len(results)}


def get_cross_sell_recommendations(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    args = payload if isinstance(payload, ProductRecommendationsInput) else ProductRecommendationsInput.model_validate(payload)
    results = RecommendationService(db).cross_sells(merchant_id, args.product_id, args.limit)
    return {"results": results, "total": len(results)}


def get_growth_experiment_variant(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    del db, merchant_id
    args = payload if isinstance(payload, GrowthExperimentInput) else GrowthExperimentInput.model_validate(payload)
    service = GrowthExperimentService()
    variant = service.assign_variant(args.session_id, args.experiment_name)
    return {
        "experiment_name": args.experiment_name,
        "session_id": str(args.session_id),
        "variant": variant,
        "enabled": service.is_feature_enabled(args.session_id, args.experiment_name),
        "config": service.get_experiment_config(args.experiment_name),
    }


def add_to_cart(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    args = payload if isinstance(payload, AddToCartInput) else AddToCartInput.model_validate(payload)
    service = CartService(db)
    service.get_cart(args.cart_id, merchant_id)
    cart = service.add_item(args.cart_id, args.product_variant_id, args.quantity)
    return service.serialize(cart).model_dump(mode="json")


def view_cart(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    args = payload if isinstance(payload, ViewCartInput) else ViewCartInput.model_validate(payload)
    service = CartService(db)
    cart = service.get_cart(args.cart_id, merchant_id)
    return service.serialize(cart).model_dump(mode="json")


def checkout_cart(db: Session, merchant_id: UUID, payload: BaseModel) -> dict:
    args = payload if isinstance(payload, CheckoutCartInput) else CheckoutCartInput.model_validate(payload)
    return CheckoutService(db).checkout(args.cart_id, merchant_id, args.buyer_session_id).model_dump(mode="json")


TOOLS: dict[str, ToolSpec] = {
    "search_products": ToolSpec("search_products", SearchProductsInput, search_products),
    "get_product_details": ToolSpec("get_product_details", ProductDetailsInput, get_product_details),
    "check_inventory": ToolSpec("check_inventory", InventoryInput, check_inventory),
    "get_merchant_policy": ToolSpec("get_merchant_policy", MerchantPolicyInput, get_merchant_policy),
    "rank_products": ToolSpec("rank_products", RankProductsInput, rank_products),
    "negotiate_price": ToolSpec("negotiate_price", NegotiatePriceInput, negotiate_price),
    "get_upsell_recommendations": ToolSpec("get_upsell_recommendations", ProductRecommendationsInput, get_upsell_recommendations),
    "get_cross_sell_recommendations": ToolSpec("get_cross_sell_recommendations", ProductRecommendationsInput, get_cross_sell_recommendations),
    "get_growth_experiment_variant": ToolSpec("get_growth_experiment_variant", GrowthExperimentInput, get_growth_experiment_variant),
    "add_to_cart": ToolSpec("add_to_cart", AddToCartInput, add_to_cart),
    "view_cart": ToolSpec("view_cart", ViewCartInput, view_cart),
    "checkout_cart": ToolSpec("checkout_cart", CheckoutCartInput, checkout_cart),
}


class ToolRegistry:
    def __init__(self, tools: dict[str, ToolSpec] | None = None):
        self.tools = tools or TOOLS

    def execute(self, db: Session, session_id: UUID, merchant_id: UUID, tool_name: str, tool_input: dict) -> tuple[dict | None, AgentToolCall]:
        started = perf_counter()
        output: dict | None = None
        error: str | None = None
        success = False
        try:
            spec = self.tools.get(tool_name)
            if spec is None:
                raise ToolExecutionError("Unknown tool")
            validated = spec.input_model.model_validate(tool_input)
            output = spec.handler(db, merchant_id, validated)
            success = True
            return output, self._log(db, session_id, merchant_id, tool_name, tool_input, output, success, error, started)
        except (ValidationError, ToolExecutionError, ValueError) as exc:
            error = str(exc)
            return None, self._log(db, session_id, merchant_id, tool_name, tool_input, output, success, error, started)

    def _log(self, db: Session, session_id: UUID, merchant_id: UUID, tool_name: str, tool_input: dict, output: dict | None, success: bool, error: str | None, started: float) -> AgentToolCall:
        call = AgentToolCall(
            session_id=session_id,
            merchant_id=merchant_id,
            tool_name=tool_name,
            tool_input=jsonable_encoder(tool_input),
            tool_output=jsonable_encoder(output) if output is not None else None,
            success=success,
            error=error,
            duration_ms=max(0, round((perf_counter() - started) * 1000)),
        )
        db.add(call)
        db.flush()
        AuditService(db).log_event(
            merchant_id,
            "agent_tool_called",
            "agent_tool_call",
            call.id,
            actor_type="agent",
            actor_id=session_id,
            metadata={"tool_name": tool_name, "success": success, "duration_ms": call.duration_ms, "error": error},
        )
        return call
