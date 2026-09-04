import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services.intent import AIProvider, IntentExtractor


client = TestClient(app)


def create_catalog(prefix: str):
    merchant = client.post(
        "/api/v1/merchants",
        json={"name": f"{prefix} Audio Store", "slug": f"{prefix}-audio-store"},
    )
    assert merchant.status_code == 201
    merchant_id = merchant.json()["id"]

    other_merchant = client.post(
        "/api/v1/merchants",
        json={"name": f"{prefix} Other Store", "slug": f"{prefix}-other-store"},
    )
    assert other_merchant.status_code == 201
    other_merchant_id = other_merchant.json()["id"]

    wireless = create_product_variant(
        prefix=prefix,
        merchant_id=merchant_id,
        name="Wireless Headphones",
        description="Bluetooth headphones with long battery life",
        category="headphones",
        brand="SoundMax",
        sku=f"{prefix}-WH-BLK",
        price="1999.00",
        attributes={"color": "black", "connectivity": "wireless", "battery_life_hours": 24},
        quantity=25,
    )
    expensive = create_product_variant(
        prefix=prefix,
        merchant_id=merchant_id,
        name="Premium Wireless Headphones",
        description="Noise cancelling wireless headphones",
        category="headphones",
        brand="SoundMax",
        sku=f"{prefix}-WH-PRO",
        price="4999.00",
        attributes={"color": "black", "connectivity": "wireless", "battery_life_hours": 40},
        quantity=10,
    )
    wired = create_product_variant(
        prefix=prefix,
        merchant_id=merchant_id,
        name="Wired Studio Headphones",
        description="Studio monitor headphones",
        category="headphones",
        brand="StudioCo",
        sku=f"{prefix}-STUDIO",
        price="1499.00",
        attributes={"color": "white", "connectivity": "wired"},
        quantity=0,
    )
    tote = create_product_variant(
        prefix=prefix,
        merchant_id=merchant_id,
        name="Canvas Tote",
        description="Durable everyday tote bag",
        category="Accessories",
        brand="MerchantOS",
        sku=f"{prefix}-TOTE",
        price="499.00",
        attributes={"color": "natural"},
        quantity=40,
    )
    other_store_item = create_product_variant(
        prefix=prefix,
        merchant_id=other_merchant_id,
        name="Wireless Headphones",
        description="Bluetooth headphones from another merchant",
        category="headphones",
        brand="OtherBrand",
        sku=f"{prefix}-OTHER-WH",
        price="999.00",
        attributes={"color": "black", "connectivity": "wireless"},
        quantity=50,
    )
    inactive = create_product_variant(
        prefix=prefix,
        merchant_id=merchant_id,
        name="Inactive Wireless Headphones",
        description="This product should not be searchable",
        category="headphones",
        brand="SoundMax",
        sku=f"{prefix}-INACTIVE",
        price="999.00",
        attributes={"connectivity": "wireless"},
        quantity=5,
    )
    assert client.patch(f"/api/v1/products/{inactive['product_id']}", json={"is_active": False}).status_code == 200

    return {
        "merchant_id": merchant_id,
        "other_merchant_id": other_merchant_id,
        "wireless": wireless,
        "expensive": expensive,
        "wired": wired,
        "tote": tote,
        "other_store_item": other_store_item,
        "inactive": inactive,
    }


def create_product_variant(prefix: str, merchant_id: str, name: str, description: str, category: str, brand: str, sku: str, price: str, attributes: dict, quantity: int):
    product = client.post(
        "/api/v1/products",
        json={"merchant_id": merchant_id, "name": f"{prefix} {name}", "description": description, "category": category, "brand": brand},
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    variant = client.post(
        "/api/v1/variants",
        json={"product_id": product_id, "sku": sku, "price": price, "attributes": attributes},
    )
    assert variant.status_code == 201
    inventory = client.post("/api/v1/inventory", json={"variant_id": variant.json()["id"], "available_quantity": quantity})
    assert inventory.status_code == 201
    return {"product_id": product_id, "variant_id": variant.json()["id"], "sku": sku}


def test_search_keyword_name_category_price_stock_and_merchant_filters():
    data = create_catalog(uuid.uuid4().hex[:8])
    response = client.get(
        "/api/v1/search",
        params={
            "q": "wireless headphones",
            "merchant_id": data["merchant_id"],
            "category": "headphones",
            "max_price": "2500",
            "in_stock": "true",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["sku"] == data["wireless"]["sku"]
    assert result["price"] == "1999.00"
    assert result["available_quantity"] == 25


def test_search_min_price_range_and_no_results():
    data = create_catalog(uuid.uuid4().hex[:8])
    response = client.get(
        "/api/v1/search",
        params={"merchant_id": data["merchant_id"], "category": "headphones", "min_price": "3000", "max_price": "6000"},
    )
    assert response.status_code == 200
    assert [item["sku"] for item in response.json()["results"]] == [data["expensive"]["sku"]]

    no_results = client.get("/api/v1/search", params={"merchant_id": data["merchant_id"], "q": "does-not-exist"})
    assert no_results.status_code == 200
    assert no_results.json()["results"] == []


def test_search_excludes_unavailable_and_inactive_items():
    data = create_catalog(uuid.uuid4().hex[:8])
    response = client.get(
        "/api/v1/search",
        params={"merchant_id": data["merchant_id"], "q": "headphones", "in_stock": "true"},
    )
    assert response.status_code == 200
    skus = {item["sku"] for item in response.json()["results"]}
    assert data["wired"]["sku"] not in skus
    assert data["inactive"]["sku"] not in skus


def test_search_respects_merchant_boundaries():
    data = create_catalog(uuid.uuid4().hex[:8])
    response = client.get("/api/v1/search", params={"merchant_id": data["merchant_id"], "q": "wireless headphones"})
    assert response.status_code == 200
    merchant_ids = {item["merchant_id"] for item in response.json()["results"]}
    assert merchant_ids == {data["merchant_id"]}


def test_intent_extraction_price_category_quantity_and_attributes():
    response = client.post(
        "/api/v1/buyer/intent",
        json={"message": "I want 2 black wireless headphones under ₹2500 with at least 20 hours battery."},
    )
    assert response.status_code == 200
    intent = response.json()["intent"]
    assert intent["intent"] == "product_search"
    assert intent["category"] == "headphones"
    assert intent["max_price"] == "2500"
    assert intent["quantity"] == 2
    assert intent["requires_in_stock"] is True
    assert intent["attributes"]["color"] == "black"
    assert intent["attributes"]["connectivity"] == "wireless"
    assert intent["attributes"]["battery_life_hours_min"] == 20


def test_intent_validation_and_provider_fallback_behavior():
    assert client.post("/api/v1/buyer/intent", json={"message": ""}).status_code == 422

    class BrokenProvider(AIProvider):
        def extract_intent(self, message: str):
            raise RuntimeError("provider failed")

    intent = IntentExtractor(provider=BrokenProvider()).extract("wireless headphones under 2500")
    assert intent.query == "wireless headphones"
    assert intent.requires_in_stock is True


def test_buyer_search_natural_language_flow():
    data = create_catalog(uuid.uuid4().hex[:8])
    response = client.post(
        "/api/v1/buyer/search",
        json={
            "message": "I need black wireless headphones under ₹2500 that are in stock.",
            "merchant_id": data["merchant_id"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"]["max_price"] == "2500"
    assert body["intent"]["category"] == "headphones"
    assert body["total"] == 1
    assert body["results"][0]["sku"] == data["wireless"]["sku"]
    assert "I found 1" in body["message"]
