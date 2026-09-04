import uuid
from uuid import UUID

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AuditEvent, Inventory, Payment


client = TestClient(app)


def create_catalog(prefix: str, stock: int = 8):
    merchant = client.post("/api/v1/merchants", json={"name": f"{prefix} Integration Store", "slug": f"{prefix}-integration-store"})
    assert merchant.status_code == 201
    merchant_id = merchant.json()["id"]
    policy = client.put(f"/api/v1/merchants/{merchant_id}/policy", json={"maximum_discount_percent": "10", "negotiation_enabled": True})
    assert policy.status_code == 200
    product = client.post("/api/v1/products", json={"merchant_id": merchant_id, "name": f"{prefix} Black Wireless Headphones", "description": "Premium wireless headphones", "category": "headphones", "brand": "Day9"})
    assert product.status_code == 201
    variant = client.post("/api/v1/variants", json={"product_id": product.json()["id"], "sku": f"{prefix}-DAY9", "price": "1000.00", "attributes": {"color": "black", "connectivity": "wireless"}})
    assert variant.status_code == 201
    inventory = client.post("/api/v1/inventory", json={"variant_id": variant.json()["id"], "available_quantity": stock})
    assert inventory.status_code == 201
    return {"merchant_id": merchant_id, "product_id": product.json()["id"], "variant_id": variant.json()["id"], "inventory_id": inventory.json()["id"]}


def test_day9_flow_merchant_catalog_search_agent_negotiation_checkout_payment_and_audit():
    data = create_catalog(uuid.uuid4().hex[:8])

    search = client.get("/api/v1/search", params={"merchant_id": data["merchant_id"], "q": "black wireless headphones"})
    assert search.status_code == 200
    assert search.json()["total"] == 1

    buyer = client.post("/api/v1/buyer/search", json={"merchant_id": data["merchant_id"], "message": "I need black wireless headphones under 1200"})
    assert buyer.status_code == 200
    assert buyer.json()["results"][0]["variant_id"] == data["variant_id"]

    agent = client.post("/api/v1/agent/chat", json={"merchant_id": data["merchant_id"], "message": "I need black wireless headphones under 1200"})
    assert agent.status_code == 200
    assert "search_products" in [call["tool_name"] for call in agent.json()["tool_calls"]]

    negotiation = client.post("/api/v1/negotiation", json={"merchant_id": data["merchant_id"], "variant_id": data["variant_id"], "offered_price": "900"})
    assert negotiation.status_code == 200
    assert negotiation.json()["decision"] == "ACCEPT"

    cart = client.post("/api/v1/carts", json={"merchant_id": data["merchant_id"], "buyer_session_id": "day9-buyer"})
    assert cart.status_code == 201
    assert client.post(f"/api/v1/carts/{cart.json()['id']}/items", json={"product_variant_id": data["variant_id"], "quantity": 2}).status_code == 201
    checkout = client.post("/api/v1/checkout", json={"merchant_id": data["merchant_id"], "cart_id": cart.json()["id"], "buyer_session_id": "day9-buyer"})
    assert checkout.status_code == 200

    first = client.post("/api/v1/payments/mock-success", headers={"Idempotency-Key": f"day9-{uuid.uuid4().hex}"}, json={"merchant_id": data["merchant_id"], "payment_id": checkout.json()["payment_id"]})
    assert first.status_code == 200
    second = client.post("/api/v1/payments/mock-success", headers={"Idempotency-Key": f"day9-replay-{uuid.uuid4().hex}"}, json={"merchant_id": data["merchant_id"], "payment_id": checkout.json()["payment_id"]})
    assert second.status_code == 200

    db = SessionLocal()
    try:
      inventory = db.get(Inventory, UUID(data["inventory_id"]))
      payment = db.get(Payment, UUID(checkout.json()["payment_id"]))
      assert inventory.available_quantity == 6
      assert payment.inventory_deducted is True
      assert db.query(AuditEvent).filter(AuditEvent.merchant_id == UUID(data["merchant_id"])).count() >= 8
    finally:
      db.close()

    orders = client.get("/api/v1/orders", params={"merchant_id": data["merchant_id"]})
    payments = client.get("/api/v1/payments", params={"merchant_id": data["merchant_id"]})
    audit = client.get("/api/v1/audit-events", params={"merchant_id": data["merchant_id"], "event_type": "payment_success"})
    assert orders.status_code == 200 and orders.json()["total"] == 1
    assert payments.status_code == 200 and payments.json()["total"] == 1
    assert audit.status_code == 200 and audit.json()["total"] == 1


def test_day9_merchant_isolation_and_public_config_are_safe():
    first = create_catalog(uuid.uuid4().hex[:8])
    second = create_catalog(uuid.uuid4().hex[:8])

    assert client.post("/api/v1/negotiation", json={"merchant_id": second["merchant_id"], "variant_id": first["variant_id"], "offered_price": "900"}).status_code == 404
    assert client.get(f"/api/v1/inventory/{first['variant_id']}").status_code == 200
    assert client.get("/api/v1/search", params={"merchant_id": second["merchant_id"], "q": "Day9"}).json()["results"][0]["merchant_id"] == second["merchant_id"]

    config = client.get("/api/v1/config/public")
    assert config.status_code == 200
    body = config.json()
    assert "razorpay_key_secret" not in body
    assert "llm_api_key" not in body
    assert "database_url" not in body

    too_large = client.post("/api/v1/buyer/intent", content=b"x" * 1_000_001, headers={"Content-Type": "application/json"})
    assert too_large.status_code == 413


def test_day10_demo_seed_endpoint_is_idempotent_and_safe():
    first = client.post("/api/v1/dev/seed-demo-data")
    assert first.status_code == 200
    body = first.json()
    assert body["merchant_slug"] == "merchantos-demo-final"
    assert body["products"] >= 18
    assert body["orders"] >= 18
    assert body["payments"] >= 18
    assert body["audit_events"] >= 10

    second = client.post("/api/v1/dev/seed-demo-data")
    assert second.status_code == 200
    assert second.json()["merchant_id"] == body["merchant_id"]
    assert second.json()["products"] == body["products"]
