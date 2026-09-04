import uuid
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import AgentSession, AgentToolCall
from app.services.agent_tools import ToolRegistry


client = TestClient(app)


def create_agent_catalog(prefix: str):
    merchant = client.post(
        "/api/v1/merchants",
        json={"name": f"{prefix} Agent Store", "slug": f"{prefix}-agent-store"},
    )
    assert merchant.status_code == 201
    merchant_id = merchant.json()["id"]
    policy = client.put(
        f"/api/v1/merchants/{merchant_id}/policy",
        json={"return_window_days": 14, "cancellation_window_minutes": 45, "maximum_discount_percent": 10},
    )
    assert policy.status_code == 200

    other = client.post(
        "/api/v1/merchants",
        json={"name": f"{prefix} Other Agent Store", "slug": f"{prefix}-other-agent-store"},
    )
    assert other.status_code == 201
    other_merchant_id = other.json()["id"]

    main = create_agent_product(
        merchant_id=merchant_id,
        name=f"{prefix} Black Wireless Headphones",
        description="Bluetooth headphones with long battery life",
        category="headphones",
        sku=f"{prefix}-AGENT-WH",
        price="1999.00",
        attributes={"color": "black", "connectivity": "wireless"},
        quantity=8,
    )
    expensive = create_agent_product(
        merchant_id=merchant_id,
        name=f"{prefix} Premium Wireless Headphones",
        description="Premium wireless headphones",
        category="headphones",
        sku=f"{prefix}-AGENT-PRO",
        price="4999.00",
        attributes={"color": "black", "connectivity": "wireless"},
        quantity=5,
    )
    unavailable = create_agent_product(
        merchant_id=merchant_id,
        name=f"{prefix} Black Wired Headphones",
        description="Studio headphones",
        category="headphones",
        sku=f"{prefix}-AGENT-WIRED",
        price="999.00",
        attributes={"color": "black", "connectivity": "wired"},
        quantity=0,
    )
    other_product = create_agent_product(
        merchant_id=other_merchant_id,
        name=f"{prefix} Other Black Wireless Headphones",
        description="Other merchant product",
        category="headphones",
        sku=f"{prefix}-AGENT-OTHER",
        price="999.00",
        attributes={"color": "black", "connectivity": "wireless"},
        quantity=20,
    )
    inactive = create_agent_product(
        merchant_id=merchant_id,
        name=f"{prefix} Inactive Wireless Headphones",
        description="Inactive product",
        category="headphones",
        sku=f"{prefix}-AGENT-INACTIVE",
        price="899.00",
        attributes={"color": "black", "connectivity": "wireless"},
        quantity=10,
    )
    assert client.patch(f"/api/v1/products/{inactive['product_id']}", json={"is_active": False}).status_code == 200

    return {
        "merchant_id": merchant_id,
        "other_merchant_id": other_merchant_id,
        "main": main,
        "expensive": expensive,
        "unavailable": unavailable,
        "other_product": other_product,
        "inactive": inactive,
    }


def create_agent_product(merchant_id: str, name: str, description: str, category: str, sku: str, price: str, attributes: dict, quantity: int):
    product = client.post(
        "/api/v1/products",
        json={"merchant_id": merchant_id, "name": name, "description": description, "category": category, "brand": "AgentBrand"},
    )
    assert product.status_code == 201
    variant = client.post(
        "/api/v1/variants",
        json={"product_id": product.json()["id"], "sku": sku, "price": price, "attributes": attributes},
    )
    assert variant.status_code == 201
    inventory = client.post("/api/v1/inventory", json={"variant_id": variant.json()["id"], "available_quantity": quantity})
    assert inventory.status_code == 201
    return {"product_id": product.json()["id"], "variant_id": variant.json()["id"], "sku": sku}


def test_agent_accepts_valid_request_selects_tools_ranks_and_logs_calls():
    data = create_agent_catalog(uuid.uuid4().hex[:8])
    response = client.post(
        "/api/v1/agent/chat",
        json={
            "merchant_id": data["merchant_id"],
            "message": "I need black wireless headphones under Rs. 2500 that are in stock.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"]["max_price"] == "2500"
    assert body["products"][0]["sku"] == data["main"]["sku"]
    assert body["products"][0]["rank"] == 1
    assert "within budget" in body["products"][0]["reasons"]
    tool_names = [call["tool_name"] for call in body["tool_calls"]]
    assert tool_names == ["search_products", "check_inventory", "rank_products"]
    assert all(call["success"] for call in body["tool_calls"])

    db = SessionLocal()
    try:
        logged = db.query(AgentToolCall).filter(AgentToolCall.session_id == UUID(body["session_id"])).count()
        assert logged == 3
    finally:
        db.close()


def test_agent_can_execute_details_and_policy_flows():
    data = create_agent_catalog(uuid.uuid4().hex[:8])
    details = client.post(
        "/api/v1/agent/chat",
        json={"merchant_id": data["merchant_id"], "message": "Show me the details of the cheapest black headphones."},
    )
    assert details.status_code == 200
    detail_tools = [call["tool_name"] for call in details.json()["tool_calls"]]
    assert "get_product_details" in detail_tools

    policy = client.post(
        "/api/v1/agent/chat",
        json={"merchant_id": data["merchant_id"], "message": "What is the return policy for this product?"},
    )
    assert policy.status_code == 200
    body = policy.json()
    assert [call["tool_name"] for call in body["tool_calls"]] == ["get_merchant_policy"]
    assert "Returns are allowed within 14 days" in body["response"]


def test_tool_registry_rejects_unknown_tool_and_invalid_arguments():
    data = create_agent_catalog(uuid.uuid4().hex[:8])
    db = SessionLocal()
    try:
        session = AgentSession(merchant_id=UUID(data["merchant_id"]), context={})
        db.add(session)
        db.commit()
        db.refresh(session)

        registry = ToolRegistry()
        output, unknown = registry.execute(db, session.id, UUID(data["merchant_id"]), "drop_tables", {})
        assert output is None
        assert unknown.success is False
        assert unknown.error == "Unknown tool"

        output, invalid = registry.execute(db, session.id, UUID(data["merchant_id"]), "check_inventory", {"variant_id": "not-a-uuid"})
        assert output is None
        assert invalid.success is False
        db.commit()
    finally:
        db.close()


def test_tool_layer_enforces_merchant_isolation():
    data = create_agent_catalog(uuid.uuid4().hex[:8])
    db = SessionLocal()
    try:
        session = AgentSession(merchant_id=UUID(data["merchant_id"]), context={})
        db.add(session)
        db.commit()
        db.refresh(session)

        registry = ToolRegistry()
        output, call = registry.execute(
            db,
            session.id,
            UUID(data["merchant_id"]),
            "get_product_details",
            {"product_id": data["other_product"]["product_id"]},
        )
        assert output is None
        assert call.success is False
        assert call.error == "Product not found"
        db.commit()
    finally:
        db.close()


def test_llm_configuration_failure_uses_deterministic_fallback(monkeypatch):
    data = create_agent_catalog(uuid.uuid4().hex[:8])
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_api_key", "configured-for-test")

    response = client.post(
        "/api/v1/agent/chat",
        json={"merchant_id": data["merchant_id"], "message": "I need black wireless headphones under Rs. 2500 that are in stock."},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "deterministic-fallback"


def test_agent_response_schema_and_missing_merchant_error():
    missing = client.post(
        "/api/v1/agent/chat",
        json={"merchant_id": str(uuid.uuid4()), "message": "I need headphones"},
    )
    assert missing.status_code == 404

    data = create_agent_catalog(uuid.uuid4().hex[:8])
    response = client.post(
        "/api/v1/agent/chat",
        json={"merchant_id": data["merchant_id"], "message": "I need black wireless headphones under Rs. 2500"},
    )
    assert response.status_code == 200
    body = response.json()
    assert {"session_id", "intent", "response", "products", "tool_calls", "provider"} <= set(body)
    returned_skus = {product["sku"] for product in body["products"]}
    assert data["other_product"]["sku"] not in returned_skus
    assert data["inactive"]["sku"] not in returned_skus
    assert data["unavailable"]["sku"] not in returned_skus
