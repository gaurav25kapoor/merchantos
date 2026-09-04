from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import MerchantPolicy, PolicyDecision, Product, ProductVariant
from app.services.audit import AuditService


class NegotiationError(ValueError):
    pass


class NegotiationService:
    def __init__(self, db: Session):
        self.db = db

    def negotiate(self, merchant_id: UUID, variant_id: UUID, offered_price: Decimal, session_id: UUID | None = None) -> dict:
        if offered_price <= 0:
            raise NegotiationError("Offer must be greater than zero")
        row = (
            self.db.query(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.product_id)
            .filter(ProductVariant.id == variant_id)
            .filter(Product.merchant_id == merchant_id)
            .filter(Product.is_active.is_(True))
            .filter(ProductVariant.is_active.is_(True))
            .one_or_none()
        )
        if not row:
            raise NegotiationError("Variant not found")
        variant, product = row
        AuditService(self.db).log_event(
            merchant_id,
            "negotiation_started",
            "product_variant",
            variant.id,
            actor_type="agent" if session_id else "buyer",
            actor_id=session_id,
            metadata={"product_id": str(product.id), "offered_price": str(offered_price)},
        )
        policy = self.db.query(MerchantPolicy).filter(MerchantPolicy.merchant_id == merchant_id).one_or_none()
        original_price = money(variant.price)
        max_discount = money(policy.maximum_discount_percent if policy else Decimal("0"))
        minimum_allowed = money(original_price * (Decimal("1") - (max_discount / Decimal("100"))))

        if not policy or not policy.negotiation_enabled:
            result = self._decision(merchant_id, session_id, product.id, variant.id, "REJECT", original_price, offered_price, None, None, "Negotiation is disabled for this merchant.")
            return result
        if offered_price >= original_price:
            result = self._decision(merchant_id, session_id, product.id, variant.id, "ACCEPT", original_price, offered_price, original_price, None, "Offer meets or exceeds the listed price.")
            return result
        if offered_price >= minimum_allowed:
            result = self._decision(merchant_id, session_id, product.id, variant.id, "ACCEPT", original_price, offered_price, money(offered_price), None, "Offer is within the merchant's approved discount policy.")
            return result
        result = self._decision(merchant_id, session_id, product.id, variant.id, "COUNTER_OFFER", original_price, offered_price, None, minimum_allowed, "Offer is below the merchant's maximum allowed discount.")
        return result

    def _decision(self, merchant_id: UUID, session_id: UUID | None, product_id: UUID, variant_id: UUID, decision: str, original_price: Decimal, offered_price: Decimal, approved_price: Decimal | None, counter_offer: Decimal | None, reason: str) -> dict:
        record = PolicyDecision(
            merchant_id=merchant_id,
            session_id=session_id,
            product_id=product_id,
            variant_id=variant_id,
            decision_type="negotiation",
            decision=decision,
            original_price=original_price,
            offered_price=money(offered_price),
            approved_price=approved_price,
            counter_offer=counter_offer,
            reason=reason,
            metadata_json={},
        )
        self.db.add(record)
        self.db.flush()
        AuditService(self.db).log_event(
            merchant_id,
            f"negotiation_{decision.lower()}",
            "policy_decision",
            record.id,
            actor_type="agent" if session_id else "system",
            actor_id=session_id,
            metadata={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "original_price": str(original_price),
                "offered_price": str(money(offered_price)),
                "approved_price": str(approved_price) if approved_price is not None else None,
                "counter_offer": str(counter_offer) if counter_offer is not None else None,
            },
        )
        return {
            "decision": decision,
            "original_price": original_price,
            "offered_price": money(offered_price),
            "approved_price": approved_price,
            "counter_offer": counter_offer,
            "reason": reason,
            "policy_decision_id": record.id,
        }


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
