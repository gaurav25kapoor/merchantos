from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Inventory, Product, ProductVariant, Recommendation, UpsellEvent
from app.schemas import RecommendationOut
from app.services.audit import AuditService
from app.services.search import normalize_text


CROSS_SELL_KEYWORDS = {
    "headphones": ("case", "adapter", "cable", "charger", "stand", "accessory", "accessories"),
    "Apparel": ("bag", "cap", "accessory", "accessories"),
    "Accessories": ("shirt", "t-shirt", "tee"),
}


class RecommendationError(ValueError):
    pass


class RecommendationService:
    def __init__(self, db: Session):
        self.db = db

    def upsells(self, merchant_id: UUID, product_id: UUID, limit: int = 3, session_id: UUID | None = None) -> list[dict]:
        source, source_variant = self._source(merchant_id, product_id)
        candidates = self._candidates(merchant_id, product_id)
        ranked = []
        for product, variant, inventory in candidates:
            if normalize_text(product.category) != normalize_text(source.category):
                continue
            if variant.price <= source_variant.price:
                continue
            score = 50 + min(40, int((variant.price - source_variant.price) / max(source_variant.price, Decimal("1")) * 100))
            reason = self._upsell_reason(source_variant.attributes or {}, variant.attributes or {})
            ranked.append((score, product, variant, inventory, reason))
        ranked.sort(key=lambda item: (-item[0], item[2].price, item[1].name.lower()))
        results = [self._to_recommendation(merchant_id, product_id, item, "upsell", session_id) for item in ranked[:limit]]
        return results

    def cross_sells(self, merchant_id: UUID, product_id: UUID, limit: int = 3) -> list[dict]:
        source, _source_variant = self._source(merchant_id, product_id)
        keywords = CROSS_SELL_KEYWORDS.get(source.category or "", ())
        candidates = self._candidates(merchant_id, product_id)
        ranked = []
        for product, variant, inventory in candidates:
            haystack = normalize_text(f"{product.name} {product.description} {product.category} {' '.join(str(value) for value in (variant.attributes or {}).values())}")
            keyword_matches = sum(1 for keyword in keywords if normalize_text(keyword) in haystack)
            category_differs = normalize_text(product.category) != normalize_text(source.category)
            if keyword_matches == 0 and not category_differs:
                continue
            score = 40 + keyword_matches * 20 + (10 if category_differs else 0)
            reason = f"Useful accessory to complement your {source.category or 'product'}."
            ranked.append((score, product, variant, inventory, reason))
        ranked.sort(key=lambda item: (-item[0], item[2].price, item[1].name.lower()))
        return [self._to_recommendation(merchant_id, product_id, item, "cross_sell", None) for item in ranked[:limit]]

    def _source(self, merchant_id: UUID, product_id: UUID) -> tuple[Product, ProductVariant]:
        row = (
            self.db.query(Product, ProductVariant)
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .filter(Product.id == product_id)
            .filter(Product.merchant_id == merchant_id)
            .filter(Product.is_active.is_(True))
            .filter(ProductVariant.is_active.is_(True))
            .order_by(ProductVariant.price.asc())
            .first()
        )
        if not row:
            raise RecommendationError("Product not found")
        return row

    def _candidates(self, merchant_id: UUID, source_product_id: UUID):
        return (
            self.db.query(Product, ProductVariant, Inventory)
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .join(Inventory, Inventory.variant_id == ProductVariant.id)
            .filter(Product.merchant_id == merchant_id)
            .filter(Product.id != source_product_id)
            .filter(Product.is_active.is_(True))
            .filter(ProductVariant.is_active.is_(True))
            .filter(Inventory.available_quantity > 0)
            .all()
        )

    def _to_recommendation(self, merchant_id: UUID, source_product_id: UUID, item: tuple, recommendation_type: str, session_id: UUID | None) -> dict:
        score, product, variant, inventory, reason = item
        recommendation = Recommendation(
            merchant_id=merchant_id,
            source_product_id=source_product_id,
            recommended_product_id=product.id,
            recommendation_type=recommendation_type,
            reason=reason,
            score=score,
            metadata_json={"variant_id": str(variant.id), "sku": variant.sku},
        )
        self.db.add(recommendation)
        if recommendation_type == "upsell":
            self.db.add(UpsellEvent(merchant_id=merchant_id, session_id=session_id, source_product_id=source_product_id, recommended_product_id=product.id, event_type="shown", reason=reason, metadata_json={"variant_id": str(variant.id)}))
        self.db.flush()
        AuditService(self.db).log_event(
            merchant_id,
            f"{recommendation_type}_shown",
            "recommendation",
            recommendation.id,
            actor_type="agent" if session_id else "system",
            actor_id=session_id,
            metadata={"source_product_id": str(source_product_id), "recommended_product_id": str(product.id), "variant_id": str(variant.id), "score": score},
        )
        return RecommendationOut(
            product_id=product.id,
            variant_id=variant.id,
            name=product.name,
            description=product.description,
            category=product.category,
            sku=variant.sku,
            price=variant.price,
            available_quantity=inventory.available_quantity,
            score=score,
            reason=reason,
        ).model_dump(mode="json")

    def _upsell_reason(self, source_attrs: dict, candidate_attrs: dict) -> str:
        candidate_battery = candidate_attrs.get("battery_life_hours")
        source_battery = source_attrs.get("battery_life_hours", 0)
        if isinstance(candidate_battery, int) and isinstance(source_battery, int) and candidate_battery > source_battery:
            return "Upgrade for better battery life."
        if candidate_attrs.get("noise_cancellation"):
            return "Upgrade for noise cancellation and higher-value features."
        return "Upgrade to a higher-value option in the same category."
