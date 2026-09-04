import uuid
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AgentSession, AgentToolCall, PolicyDecision, Recommendation, UpsellEvent
from app.services.experiments import GrowthExperimentService


client = TestClient(app)


def create_day5_catalog(prefix: str, negotiation_enabled: bool = True):
    merchant = client.post("/api/v1/merchants", json={"name": f"{prefix} Store", "slug": f"{prefix}-store"})
    assert merchant.status_code == 201
    merchant_id = merchant.json()["id"]
    policy = client.put(
        f"/api/v1/merchants/{merchant_id}/policy",
        json={"maximum_discount_percent": "10", "negotiation_enabled": negotiation_enabled, "return_window_days": 14},
    )
    assert policy.status_code == 200

    other = client.post("/api/v1/merchants", json={"name": f"{prefix} Other", "slug": f"{prefix}-other"})
    assert other.status_code == 201
    other_merchant_id = other.json()["id"]

    basic = create_product(merchant_id, f"{prefix} Basic Black Wireless Headphones", "Reliable wireless headphones", "headphones", f"{prefix}-BASIC", "2500.00", {"color": "black", "connectivity": "wireless", "battery_life_hours": 12}, 10)
    premium = create_product(merchant_id, f"{prefix} Premium Black Wireless Headphones", "Noise cancelling headphones", "headphones", f"{prefix}-PREMIUM", "3200.00", {"color": "black", "connectivity": "wireless", "battery_life_hours": 36, "noise_cancellation": True}, 6)
    case = create_product(merchant_id, f"{prefix} Headphone Case", "Protective accessory case", "Accessories", f"{prefix}-CASE", "399.00", {"color": "black"}, 30)
    unavailable = create_product(merchant_id, f"{prefix} Out Of Stock Headphone Stand", "Accessory stand", "Accessories", f"{prefix}-STAND", "699.00", {}, 0)
    other_product = create_product(other_merchant_id, f"{prefix} Other Premium Black Wireless Headphones", "Other merchant premium", "headphones", f"{prefix}-OTHER", "999.00", {"color": "black", "connectivity": "wireless"}, 20)
    return {"merchant_id": merchant_id, "other_merchant_id": other_merchant_id, "basic": basic, "premium": premium, "case": case, "unavailable": unavailable, "other_product": other_product}


def create_product(merchant_id: str, name: str, description: str, category: str, sku: str, price: str, attributes: dict, quantity: int):
    product = client.post("/api/v1/products", json={"merchant_id": merchant_id, "name": name, "description": description, "category": category, "brand": "Day5"})
    assert product.status_code == 201
    variant = client.post("/api/v1/variants", json={"product_id": product.json()["id"], "sku": sku, "price": price, "attributes": attributes})
    assert variant.status_code == 201
    inventory = client.post("/api/v1/inventory", json={"variant_id": variant.json()["id"], "available_quantity": quantity})
    assert inventory.status_code == 201
    return {"product_id": product.json()["id"], "variant_id": variant.json()["id"], "sku": sku}


def test_negotiation_accept_counter_reject_invalid_and_logs_policy_decisions():
    data = create_day5_catalog(uuid.uuid4().hex[:8])
    accept = client.post("/api/v1/negotiation", json={"merchant_id": data["merchant_id"], "variant_id": data["basic"]["variant_id"], "offered_price": "2400"})
    assert accept.status_code == 200
    assert accept.json()["decision"] == "ACCEPT"
    assert accept.json()["approved_price"] == "2400.00"

    counter = client.post("/api/v1/negotiation", json={"merchant_id": data["merchant_id"], "variant_id": data["basic"]["variant_id"], "offered_price": "2000"})
    assert counter.status_code == 200
    assert counter.json()["decision"] == "COUNTER_OFFER"
    assert counter.json()["counter_offer"] == "2250.00"

    disabled_data = create_day5_catalog(uuid.uuid4().hex[:8], negotiation_enabled=False)
    reject = client.post("/api/v1/negotiation", json={"merchant_id": disabled_data["merchant_id"], "variant_id": disabled_data["basic"]["variant_id"], "offered_price": "2400"})
    assert reject.status_code == 200
    assert reject.json()["decision"] == "REJECT"

    invalid = client.post("/api/v1/negotiation", json={"merchant_id": data["merchant_id"], "variant_id": data["basic"]["variant_id"], "offered_price": "0"})
    assert invalid.status_code == 422

    db = SessionLocal()
    try:
        assert db.query(PolicyDecision).filter(PolicyDecision.merchant_id == UUID(data["merchant_id"])).count() >= 2
    finally:
        db.close()


def test_negotiation_enforces_merchant_isolation():
    data = create_day5_catalog(uuid.uuid4().hex[:8])
    response = client.post("/api/v1/negotiation", json={"merchant_id": data["merchant_id"], "variant_id": data["other_product"]["variant_id"], "offered_price": "900"})
    assert response.status_code == 404


def test_upsell_recommendations_are_same_merchant_in_stock_and_not_same_product():
    data = create_day5_catalog(uuid.uuid4().hex[:8])
    response = client.get(f"/api/v1/products/{data['basic']['product_id']}/upsells", params={"merchant_id": data["merchant_id"]})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["product_id"] == data["premium"]["product_id"]
    assert result["product_id"] != data["basic"]["product_id"]
    assert "Upgrade" in result["reason"]

    db = SessionLocal()
    try:
        assert db.query(Recommendation).filter(Recommendation.recommendation_type == "upsell").count() >= 1
        assert db.query(UpsellEvent).count() >= 1
    finally:
        db.close()


def test_cross_sell_recommendations_are_complementary_same_merchant_and_in_stock():
    data = create_day5_catalog(uuid.uuid4().hex[:8])
    response = client.get(f"/api/v1/products/{data['basic']['product_id']}/cross-sells", params={"merchant_id": data["merchant_id"]})
    assert response.status_code == 200
    body = response.json()
    skus = {item["sku"] for item in body["results"]}
    assert data["case"]["sku"] in skus
    assert data["unavailable"]["sku"] not in skus
    assert data["other_product"]["sku"] not in skus
    assert all(item["product_id"] != data["basic"]["product_id"] for item in body["results"])


def test_growth_experiment_assignment_is_deterministic():
    session_id = uuid.uuid4()
    service = GrowthExperimentService()
    first = service.assign_variant(session_id, "upsell_strategy")
    second = service.assign_variant(session_id, "upsell_strategy")
    assert first == second

    data = create_day5_catalog(uuid.uuid4().hex[:8])
    response = client.get(f"/api/v1/experiments/upsell_strategy/assignment", params={"merchant_id": data["merchant_id"], "session_id": str(session_id)})
    assert response.status_code == 200
    assert response.json()["variant"] == first


def test_agent_integrates_negotiation_upsell_and_cross_sell_tools():
    data = create_day5_catalog(uuid.uuid4().hex[:8])
    negotiation = client.post(
        "/api/v1/agent/chat",
        json={"merchant_id": data["merchant_id"], "variant_id": data["basic"]["variant_id"], "message": "Can you give me this for Rs. 2000?"},
    )
    assert negotiation.status_code == 200
    assert [call["tool_name"] for call in negotiation.json()["tool_calls"]] == ["negotiate_price"]
    assert "2250.00" in negotiation.json()["response"]

    upsell = client.post(
        "/api/v1/agent/chat",
        json={"merchant_id": data["merchant_id"], "product_id": data["basic"]["product_id"], "message": "Do you have a better version?"},
    )
    assert upsell.status_code == 200
    assert "get_upsell_recommendations" in [call["tool_name"] for call in upsell.json()["tool_calls"]]
    assert upsell.json()["recommendations"][0]["sku"] == data["premium"]["sku"]

    cross_sell = client.post(
        "/api/v1/agent/chat",
        json={"merchant_id": data["merchant_id"], "product_id": data["basic"]["product_id"], "message": "What accessories go with this?"},
    )
    assert cross_sell.status_code == 200
    assert "get_cross_sell_recommendations" in [call["tool_name"] for call in cross_sell.json()["tool_calls"]]
    assert cross_sell.json()["recommendations"][0]["sku"] == data["case"]["sku"]

    db = SessionLocal()
    try:
        logged_tools = {row.tool_name for row in db.query(AgentToolCall).all()}
        assert {"negotiate_price", "get_upsell_recommendations", "get_cross_sell_recommendations"} <= logged_tools
    finally:
        db.close()
