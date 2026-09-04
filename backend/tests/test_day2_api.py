import uuid
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_day2_catalog_and_inventory_flow():
    token = uuid.uuid4().hex[:8]
    merchant = client.post("/api/v1/merchants", json={"name": "Test Store", "slug": f"test-store-{token}", "email": "test@example.com"})
    assert merchant.status_code == 201
    merchant_id = merchant.json()["id"]
    assert client.post("/api/v1/merchants", json={"name": "Duplicate", "slug": f"test-store-{token}"}).status_code == 409
    policy = client.put(f"/api/v1/merchants/{merchant_id}/policy", json={"return_window_days": 14, "maximum_discount_percent": 15, "rules": {"returns": "unused"}})
    assert policy.status_code == 200 and policy.json()["return_window_days"] == 14
    product = client.post("/api/v1/products", json={"merchant_id": merchant_id, "name": "Test Product", "category": "Test"})
    assert product.status_code == 201
    variant = client.post("/api/v1/variants", json={"product_id": product.json()["id"], "sku": f"TEST-{token}", "price": "99.99", "attributes": {"size": "M"}})
    assert variant.status_code == 201
    assert client.post("/api/v1/variants", json={"product_id": product.json()["id"], "sku": f"TEST-{token}", "price": "99.99"}).status_code == 409
    inventory = client.post("/api/v1/inventory", json={"variant_id": variant.json()["id"], "available_quantity": 10})
    assert inventory.status_code == 201
    assert client.post(f"/api/v1/inventory/{variant.json()['id']}/reserve", json={"quantity": 4}).json()["available_quantity"] == 6
    assert client.post(f"/api/v1/inventory/{variant.json()['id']}/release", json={"quantity": 2}).json()["reserved_quantity"] == 2
    assert client.post(f"/api/v1/inventory/{variant.json()['id']}/reserve", json={"quantity": 99}).status_code == 409
    assert client.patch(f"/api/v1/inventory/{variant.json()['id']}", json={"available_quantity": -1}).status_code == 422

def test_foreign_keys_and_user_endpoints():
    unknown = str(uuid.uuid4())
    assert client.post("/api/v1/products", json={"merchant_id": unknown, "name": "No Merchant"}).status_code == 404
    assert client.post("/api/v1/users", json={"merchant_id": unknown, "name": "No Merchant", "email": f"{uuid.uuid4().hex}@example.com"}).status_code == 404
