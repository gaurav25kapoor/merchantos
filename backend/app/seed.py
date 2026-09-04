from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AgentSession,
    AgentToolCall,
    AuditEvent,
    Cart,
    CartItem,
    Inventory,
    Merchant,
    MerchantPolicy,
    Order,
    OrderItem,
    Payment,
    PaymentAttempt,
    PolicyDecision,
    Product,
    ProductVariant,
    Recommendation,
    UpsellEvent,
    User,
)


DEMO_SLUG = "merchantos-demo-final"


PRODUCTS = [
    ("Wireless Headphones Pro", "headphones", "Auralite", "DEMO-HP-PRO", Decimal("2499.00"), 17, {"color": "black", "connectivity": "wireless", "noise_cancellation": True, "battery_life_hours": 40}),
    ("Wireless Headphones Lite", "headphones", "Auralite", "DEMO-HP-LITE", Decimal("1999.00"), 26, {"color": "black", "connectivity": "wireless", "battery_life_hours": 24}),
    ("Studio Headphones Max", "headphones", "Auralite", "DEMO-HP-MAX", Decimal("3299.00"), 8, {"color": "black", "connectivity": "wireless", "noise_cancellation": True}),
    ("Protective Headphone Case", "Accessories", "Auralite", "DEMO-CASE", Decimal("299.00"), 41, {"color": "black"}),
    ("USB-C Fast Charger", "Accessories", "Volt", "DEMO-CHARGER", Decimal("899.00"), 13, {"watts": 45}),
    ("USB-C Braided Cable", "Accessories", "Volt", "DEMO-CABLE", Decimal("349.00"), 34, {"length": "1.5m"}),
    ("Bluetooth Speaker Mini", "Audio", "Auralite", "DEMO-SPK-MINI", Decimal("1499.00"), 19, {"color": "midnight"}),
    ("Bluetooth Speaker Studio", "Audio", "Auralite", "DEMO-SPK-STUDIO", Decimal("2899.00"), 9, {"color": "graphite"}),
    ("Smart Fitness Band", "Wearables", "Pulse", "DEMO-BAND", Decimal("2199.00"), 12, {"color": "black"}),
    ("Smart Watch SE", "Wearables", "Pulse", "DEMO-WATCH-SE", Decimal("4999.00"), 7, {"color": "black"}),
    ("Smart Watch Pro", "Wearables", "Pulse", "DEMO-WATCH-PRO", Decimal("7999.00"), 4, {"color": "graphite"}),
    ("Laptop Sleeve 14", "Accessories", "Carry", "DEMO-SLEEVE-14", Decimal("799.00"), 22, {"size": "14-inch"}),
    ("Wireless Mouse", "Accessories", "Click", "DEMO-MOUSE", Decimal("1199.00"), 16, {"color": "black"}),
    ("Mechanical Keyboard Mini", "Accessories", "Click", "DEMO-KEYBOARD", Decimal("3499.00"), 5, {"layout": "65%"}),
    ("Travel Power Bank", "Accessories", "Volt", "DEMO-POWERBANK", Decimal("1799.00"), 11, {"capacity": "10000mAh"}),
    ("Creator Microphone", "Audio", "Auralite", "DEMO-MIC", Decimal("2599.00"), 6, {"connection": "usb-c"}),
    ("Noise Isolating Earbuds", "headphones", "Auralite", "DEMO-EARBUDS", Decimal("2299.00"), 21, {"color": "black", "connectivity": "wireless"}),
    ("Phone Tripod Stand", "Accessories", "Frame", "DEMO-TRIPOD", Decimal("699.00"), 0, {"height": "desktop"}),
]


def seed(db: Session) -> dict:
    merchant = db.query(Merchant).filter_by(slug=DEMO_SLUG).one_or_none()
    if not merchant:
        merchant = Merchant(
            name="MerchantOS Demo Store",
            slug=DEMO_SLUG,
            description="Deterministic demo workspace for Razorpay Track 01 - AI Growth & Agentic Commerce.",
            email="demo@merchantos.local",
            contact_phone="+91-90000-00000",
        )
        db.add(merchant)
        db.flush()

    policy = db.query(MerchantPolicy).filter_by(merchant_id=merchant.id).one_or_none()
    if not policy:
        policy = MerchantPolicy(
            merchant_id=merchant.id,
            return_window_days=14,
            cancellation_window_minutes=45,
            minimum_order_value=Decimal("299.00"),
            maximum_discount_percent=Decimal("10.00"),
            negotiation_enabled=True,
            free_shipping_threshold=Decimal("2499.00"),
            rules={"ai_actions": "policy_gated", "money_changing_actions": "confirmation_required"},
        )
        db.add(policy)

    if not db.query(User).filter_by(email="demo@merchantos.local").one_or_none():
        db.add(User(merchant_id=merchant.id, name="Demo Merchant", email="demo@merchantos.local", role="owner"))

    product_map: dict[str, tuple[Product, ProductVariant, Inventory]] = {}
    for name, category, brand, sku, price, stock, attrs in PRODUCTS:
        product = db.query(Product).filter_by(merchant_id=merchant.id, name=name).one_or_none()
        if not product:
            product = Product(merchant_id=merchant.id, name=name, description=f"{name} optimized for AI-assisted commerce demos.", category=category, brand=brand)
            db.add(product)
            db.flush()
        variant = db.query(ProductVariant).filter_by(sku=sku).one_or_none()
        if not variant:
            variant = ProductVariant(product_id=product.id, sku=sku, price=price, attributes=attrs)
            db.add(variant)
            db.flush()
        inventory = db.query(Inventory).filter_by(variant_id=variant.id).one_or_none()
        if not inventory:
            inventory = Inventory(variant_id=variant.id, available_quantity=stock, reserved_quantity=min(3, max(stock // 8, 0)), status="out_of_stock" if stock == 0 else "in_stock")
            db.add(inventory)
        product_map[sku] = (product, variant, inventory)

    existing_orders = db.query(Order).filter(Order.merchant_id == merchant.id).filter(Order.buyer_session_id.like("demo-buyer-%")).count()
    if existing_orders < 18:
        _create_demo_activity(db, merchant.id, product_map)

    _ensure_audit(db, merchant.id, "demo_data_seeded", "merchant", merchant.id, {"mode": "demo", "products": len(PRODUCTS)})
    db.commit()
    return {
        "merchant_id": str(merchant.id),
        "merchant_slug": merchant.slug,
        "products": len(PRODUCTS),
        "orders": db.query(Order).filter(Order.merchant_id == merchant.id).count(),
        "payments": db.query(Payment).join(Order, Order.id == Payment.order_id).filter(Order.merchant_id == merchant.id).count(),
        "audit_events": db.query(AuditEvent).filter(AuditEvent.merchant_id == merchant.id).count(),
    }


def _create_demo_activity(db: Session, merchant_id: UUID, product_map: dict[str, tuple[Product, ProductVariant, Inventory]]) -> None:
    now = datetime.now(timezone.utc)
    carts = [
        ("DEMO-HP-PRO", 2, "SUCCESS", 0),
        ("DEMO-HP-LITE", 1, "SUCCESS", 1),
        ("DEMO-CASE", 3, "SUCCESS", 2),
        ("DEMO-HP-PRO", 1, "SUCCESS", 3),
        ("DEMO-EARBUDS", 2, "SUCCESS", 4),
        ("DEMO-WATCH-SE", 1, "SUCCESS", 5),
        ("DEMO-CHARGER", 2, "SUCCESS", 6),
        ("DEMO-SPK-STUDIO", 1, "SUCCESS", 7),
        ("DEMO-POWERBANK", 2, "SUCCESS", 8),
        ("DEMO-HP-MAX", 1, "SUCCESS", 9),
        ("DEMO-MOUSE", 2, "SUCCESS", 10),
        ("DEMO-KEYBOARD", 1, "SUCCESS", 11),
        ("DEMO-SLEEVE-14", 2, "SUCCESS", 12),
        ("DEMO-BAND", 1, "FAILED", 13),
        ("DEMO-MIC", 1, "FAILED", 14),
        ("DEMO-HP-LITE", 1, "CREATED", 15),
        ("DEMO-TRIPOD", 1, "CREATED", 16),
        ("DEMO-CABLE", 4, "SUCCESS", 17),
        ("DEMO-CASE", 2, "SUCCESS", 18),
        ("DEMO-EARBUDS", 1, "SUCCESS", 19),
    ]
    for index, (sku, quantity, payment_status, days_ago) in enumerate(carts, start=1):
        product, variant, inventory = product_map[sku]
        created = now - timedelta(days=days_ago, hours=index)
        cart = Cart(merchant_id=merchant_id, buyer_session_id=f"demo-buyer-{index:02d}", status="PAID" if payment_status == "SUCCESS" else "CHECKED_OUT", created_at=created, updated_at=created)
        db.add(cart)
        db.flush()
        db.add(CartItem(cart_id=cart.id, product_variant_id=variant.id, quantity=quantity, unit_price=variant.price, created_at=created, updated_at=created))
        total = variant.price * quantity
        order = Order(
            merchant_id=merchant_id,
            cart_id=cart.id,
            buyer_session_id=cart.buyer_session_id,
            subtotal=total,
            total_amount=total,
            currency="INR",
            status="PAID" if payment_status == "SUCCESS" else "PAYMENT_FAILED" if payment_status == "FAILED" else "PENDING_PAYMENT",
            created_at=created,
            updated_at=created,
        )
        db.add(order)
        db.flush()
        db.add(OrderItem(order_id=order.id, product_variant_id=variant.id, product_name=product.name, variant_sku=variant.sku, variant_attributes=variant.attributes, quantity=quantity, unit_price=variant.price, line_total=total, created_at=created, updated_at=created))
        payment = Payment(
            order_id=order.id,
            provider="razorpay",
            provider_order_id=f"mock_order_demo_{index:02d}",
            provider_mode="mock",
            amount=total,
            amount_minor=int(total * 100),
            currency="INR",
            status=payment_status,
            inventory_deducted=payment_status == "SUCCESS",
            metadata_json={"demo": True, "ai_assisted": index % 3 != 0},
            created_at=created,
            updated_at=created,
        )
        db.add(payment)
        db.flush()
        attempt_statuses = ["CREATED"] if payment_status == "CREATED" else ["CREATED", payment_status]
        for attempt_status in attempt_statuses:
            db.add(PaymentAttempt(payment_id=payment.id, provider="razorpay", provider_payment_id=f"mock_pay_demo_{index:02d}" if attempt_status == "SUCCESS" else None, provider_order_id=payment.provider_order_id, amount=total if attempt_status != "CREATED" else None, amount_minor=int(total * 100) if attempt_status != "CREATED" else None, currency="INR" if attempt_status != "CREATED" else None, status=attempt_status, failure_reason="Card declined in demo flow" if attempt_status == "FAILED" else None, metadata_json={"demo": True}, created_at=created, updated_at=created))
        if payment_status == "SUCCESS" and inventory.available_quantity >= quantity:
            inventory.available_quantity -= quantity
        _ensure_audit(db, merchant_id, "cart_created", "cart", cart.id, {"buyer_session_id": cart.buyer_session_id}, created)
        _ensure_audit(db, merchant_id, "order_created", "order", order.id, {"amount": str(total), "demo": True}, created)
        _ensure_audit(db, merchant_id, "payment_success" if payment_status == "SUCCESS" else "payment_failed" if payment_status == "FAILED" else "payment_created", "payment", payment.id, {"amount": str(total), "ai_assisted": index % 3 != 0}, created)

    sessions = []
    for index in range(1, 9):
        created = now - timedelta(hours=index * 4)
        session = AgentSession(merchant_id=merchant_id, context={"demo": True, "buyer_intent": "black wireless headphones under 2500"}, created_at=created, updated_at=created)
        db.add(session)
        db.flush()
        sessions.append(session)
        for tool_index, tool_name in enumerate(["search_products", "check_inventory", "rank_products", "get_merchant_policy", "get_upsell_recommendations"][: 3 + (index % 3)]):
            db.add(AgentToolCall(session_id=session.id, merchant_id=merchant_id, tool_name=tool_name, tool_input={"demo": True}, tool_output={"results": 3, "variant": "ai_recommended" if tool_name == "get_growth_experiment_variant" else None}, success=True, duration_ms=32 + tool_index * 19, created_at=created + timedelta(seconds=tool_index), updated_at=created + timedelta(seconds=tool_index)))
        _ensure_audit(db, merchant_id, "agent_session_started", "agent_session", session.id, {"demo": True}, created)

    base_product, base_variant, _ = product_map["DEMO-HP-PRO"]
    case_product, _, _ = product_map["DEMO-CASE"]
    premium_product, _, _ = product_map["DEMO-HP-MAX"]
    for index, decision in enumerate(["COUNTER_OFFER", "ACCEPT", "ACCEPT", "REJECT", "COUNTER_OFFER", "ACCEPT"], start=1):
        created = now - timedelta(days=index)
        db.add(PolicyDecision(merchant_id=merchant_id, session_id=sessions[index % len(sessions)].id, product_id=base_product.id, variant_id=base_variant.id, decision_type="negotiation", decision=decision, original_price=base_variant.price, offered_price=Decimal("2000.00"), approved_price=Decimal("2250.00") if decision == "ACCEPT" else None, counter_offer=Decimal("2250.00") if decision == "COUNTER_OFFER" else None, reason="Demo policy: maximum discount is 10%, so offers below the limit are countered.", metadata_json={"demo": True}, created_at=created, updated_at=created))
        _ensure_audit(db, merchant_id, f"negotiation_{decision.lower()}", "product_variant", base_variant.id, {"offered_price": "2000.00", "policy_limit": "10%"}, created)

    for product in [case_product, premium_product]:
        created = now - timedelta(hours=6)
        recommendation = Recommendation(merchant_id=merchant_id, source_product_id=base_product.id, recommended_product_id=product.id, recommendation_type="upsell" if product.id == premium_product.id else "cross_sell", reason="Demo AI recommendation based on buyer intent and merchant catalog.", score=88, metadata_json={"demo": True}, created_at=created, updated_at=created)
        db.add(recommendation)
        db.flush()
        db.add(UpsellEvent(merchant_id=merchant_id, session_id=sessions[0].id, source_product_id=base_product.id, recommended_product_id=product.id, event_type="shown", reason=recommendation.reason, metadata_json={"demo": True}, created_at=created, updated_at=created))
        _ensure_audit(db, merchant_id, f"{recommendation.recommendation_type}_shown", "recommendation", recommendation.id, {"score": recommendation.score}, created)


def _ensure_audit(db: Session, merchant_id: UUID, event_type: str, entity_type: str, entity_id, metadata: dict, created_at: datetime | None = None) -> None:
    exists = db.query(AuditEvent).filter_by(merchant_id=merchant_id, event_type=event_type, entity_type=entity_type, entity_id=str(entity_id)).first()
    if exists:
        return
    db.add(AuditEvent(merchant_id=merchant_id, event_type=event_type, entity_type=entity_type, entity_id=str(entity_id), actor_type="system", metadata_json=metadata, created_at=created_at or datetime.now(timezone.utc)))


if __name__ == "__main__":
    db = SessionLocal()
    try:
        result = seed(db)
        print(f"Demo data is ready: {result}")
    finally:
        db.close()
