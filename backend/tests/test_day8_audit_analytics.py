import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AuditEvent


client = TestClient(app)


def create_day8_store(prefix: str):
    merchant = client.post("/api/v1/merchants", json={"name": f"{prefix} Audit Store", "slug": f"{prefix}-audit-store"})
    assert merchant.status_code == 201
    merchant_id = merchant.json()["id"]
    policy = client.put(f"/api/v1/merchants/{merchant_id}/policy", json={"maximum_discount_percent": "10", "negotiation_enabled": True})
    assert policy.status_code == 200

    product = client.post("/api/v1/products", json={"merchant_id": merchant_id, "name": f"{prefix} Everyday Headphones", "category": "headphones", "brand": "Day8"})
    assert product.status_code == 201
    variant = client.post("/api/v1/variants", json={"product_id": product.json()["id"], "sku": f"{prefix}-DAY8-BASE", "price": "100.00", "attributes": {"color": "black"}})
    assert variant.status_code == 201
    inventory = client.post("/api/v1/inventory", json={"variant_id": variant.json()["id"], "available_quantity": 5})
    assert inventory.status_code == 201

    upsell_product = client.post("/api/v1/products", json={"merchant_id": merchant_id, "name": f"{prefix} Premium Headphones", "category": "headphones", "brand": "Day8"})
    assert upsell_product.status_code == 201
    upsell_variant = client.post("/api/v1/variants", json={"product_id": upsell_product.json()["id"], "sku": f"{prefix}-DAY8-PREMIUM", "price": "150.00", "attributes": {"color": "black", "noise_cancellation": True}})
    assert upsell_variant.status_code == 201
    assert client.post("/api/v1/inventory", json={"variant_id": upsell_variant.json()["id"], "available_quantity": 3}).status_code == 201

    cart = client.post("/api/v1/carts", json={"merchant_id": merchant_id, "buyer_session_id": f"buyer-{prefix}"})
    assert cart.status_code == 201
    assert client.post(f"/api/v1/carts/{cart.json()['id']}/items", json={"product_variant_id": variant.json()["id"], "quantity": 2}).status_code == 201
    checkout = client.post("/api/v1/checkout", json={"cart_id": cart.json()["id"], "merchant_id": merchant_id})
    assert checkout.status_code == 200
    paid = client.post("/api/v1/payments/mock-success", json={"merchant_id": merchant_id, "payment_id": checkout.json()["payment_id"]})
    assert paid.status_code == 200

    negotiation = client.post("/api/v1/negotiation", json={"merchant_id": merchant_id, "variant_id": variant.json()["id"], "offered_price": "90"})
    assert negotiation.status_code == 200
    upsells = client.get(f"/api/v1/products/{product.json()['id']}/upsells", params={"merchant_id": merchant_id})
    assert upsells.status_code == 200
    agent = client.post("/api/v1/agent/chat", json={"merchant_id": merchant_id, "message": "show me headphones under 200", "limit": 3})
    assert agent.status_code == 200

    other = client.post("/api/v1/merchants", json={"name": f"{prefix} Other Audit Store", "slug": f"{prefix}-other-audit-store"})
    assert other.status_code == 201

    return {
        "merchant_id": merchant_id,
        "other_merchant_id": other.json()["id"],
        "product_id": product.json()["id"],
        "variant_id": variant.json()["id"],
    }


def test_audit_events_are_logged_filterable_newest_first_and_merchant_scoped():
    data = create_day8_store(uuid.uuid4().hex[:8])

    response = client.get("/api/v1/audit-events", params={"merchant_id": data["merchant_id"], "limit": 100})
    assert response.status_code == 200
    body = response.json()
    event_types = [event["event_type"] for event in body["events"]]
    assert {"merchant_created", "product_created", "cart_created", "checkout_started", "order_created", "payment_success", "inventory_deducted", "negotiation_accept", "upsell_shown", "agent_tool_called"} <= set(event_types)
    assert body["events"] == sorted(body["events"], key=lambda event: event["created_at"], reverse=True)

    filtered = client.get("/api/v1/audit-events", params={"merchant_id": data["merchant_id"], "event_type": "payment_success"})
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["events"][0]["metadata"]["source"] == "mock_success"

    entity_filtered = client.get("/api/v1/audit-events", params={"merchant_id": data["merchant_id"], "entity_type": "product", "entity_id": data["product_id"]})
    assert entity_filtered.status_code == 200
    assert any(event["event_type"] == "product_created" for event in entity_filtered.json()["events"])

    other_events = client.get("/api/v1/audit-events", params={"merchant_id": data["other_merchant_id"]})
    assert other_events.status_code == 200
    assert other_events.json()["total"] == 1
    assert other_events.json()["events"][0]["event_type"] == "merchant_created"

    db = SessionLocal()
    try:
        assert db.query(AuditEvent).filter(AuditEvent.merchant_id == data["merchant_id"]).count() >= 10
    finally:
        db.close()


def test_dashboard_endpoints_return_merchant_scoped_metrics_and_date_validation():
    data = create_day8_store(uuid.uuid4().hex[:8])
    merchant_id = data["merchant_id"]

    overview = client.get("/api/v1/dashboard/overview", params={"merchant_id": merchant_id})
    assert overview.status_code == 200
    assert overview.json()["total_revenue"] == "200.00"
    assert overview.json()["successful_payments"] == 1
    assert overview.json()["total_orders"] == 1
    assert overview.json()["total_negotiations"] == 1

    revenue = client.get("/api/v1/dashboard/revenue", params={"merchant_id": merchant_id, "grouping": "day"})
    assert revenue.status_code == 200
    assert revenue.json()["total_revenue"] == "200.00"
    assert len(revenue.json()["data"]) >= 1

    orders = client.get("/api/v1/dashboard/orders", params={"merchant_id": merchant_id})
    assert orders.status_code == 200
    assert orders.json()["orders_by_status"]["PAID"] == 1
    assert orders.json()["payment_success_rate"] == "100.00"

    products = client.get("/api/v1/dashboard/products", params={"merchant_id": merchant_id})
    assert products.status_code == 200
    assert products.json()["total_products"] == 2
    assert products.json()["top_products"][0]["units_sold"] == 2

    inventory = client.get("/api/v1/dashboard/inventory", params={"merchant_id": merchant_id, "low_stock_threshold": 3})
    assert inventory.status_code == 200
    assert inventory.json()["total_inventory_units"] == 6
    assert inventory.json()["low_stock_variants"] == 2

    agent = client.get("/api/v1/dashboard/agent-activity", params={"merchant_id": merchant_id})
    assert agent.status_code == 200
    assert agent.json()["total_tool_calls"] >= 1
    assert any(tool["tool_name"] == "search_products" for tool in agent.json()["tools"])

    negotiations = client.get("/api/v1/dashboard/negotiations", params={"merchant_id": merchant_id})
    assert negotiations.status_code == 200
    assert negotiations.json()["accepted_negotiations"] == 1
    assert negotiations.json()["acceptance_rate"] == "100.00"

    recommendations = client.get("/api/v1/dashboard/recommendations", params={"merchant_id": merchant_id})
    assert recommendations.status_code == 200
    assert recommendations.json()["upsell_recommendations"] >= 1
    assert recommendations.json()["recommendation_events"] >= 1

    invalid_range = client.get("/api/v1/dashboard/overview", params={"merchant_id": merchant_id, "start_date": "2030-01-02T00:00:00", "end_date": "2030-01-01T00:00:00"})
    assert invalid_range.status_code == 422
