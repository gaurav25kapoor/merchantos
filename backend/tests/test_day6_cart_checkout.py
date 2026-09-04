import uuid
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Order, OrderItem, Payment, PaymentAttempt
from app.services.razorpay_service import to_minor_units


client = TestClient(app)


def create_day6_catalog(prefix: str):
    merchant = client.post("/api/v1/merchants", json={"name": f"{prefix} Checkout Store", "slug": f"{prefix}-checkout-store"})
    assert merchant.status_code == 201
    merchant_id = merchant.json()["id"]
    other = client.post("/api/v1/merchants", json={"name": f"{prefix} Other Checkout Store", "slug": f"{prefix}-other-checkout-store"})
    assert other.status_code == 201
    other_merchant_id = other.json()["id"]
    first = create_variant(merchant_id, f"{prefix} Wireless Headphones", f"{prefix}-WH", "1299.50", 5)
    second = create_variant(merchant_id, f"{prefix} Headphone Case", f"{prefix}-CASE", "299.00", 2)
    low_stock = create_variant(merchant_id, f"{prefix} Low Stock Cable", f"{prefix}-LOW", "199.00", 1)
    missing_inventory = create_variant(merchant_id, f"{prefix} Missing Inventory Stand", f"{prefix}-MISS", "399.00", None)
    inactive_product = create_variant(merchant_id, f"{prefix} Inactive Product", f"{prefix}-INACTIVE-P", "100.00", 3)
    assert client.patch(f"/api/v1/products/{inactive_product['product_id']}", json={"is_active": False}).status_code == 200
    inactive_variant = create_variant(merchant_id, f"{prefix} Inactive Variant", f"{prefix}-INACTIVE-V", "100.00", 3)
    assert client.patch(f"/api/v1/variants/{inactive_variant['variant_id']}", json={"is_active": False}).status_code == 200
    other_variant = create_variant(other_merchant_id, f"{prefix} Other Product", f"{prefix}-OTHER", "99.00", 10)
    return {
        "merchant_id": merchant_id,
        "other_merchant_id": other_merchant_id,
        "first": first,
        "second": second,
        "low_stock": low_stock,
        "missing_inventory": missing_inventory,
        "inactive_product": inactive_product,
        "inactive_variant": inactive_variant,
        "other_variant": other_variant,
    }


def create_variant(merchant_id: str, name: str, sku: str, price: str, stock: int | None):
    product = client.post("/api/v1/products", json={"merchant_id": merchant_id, "name": name, "description": name, "category": "headphones", "brand": "Day6"})
    assert product.status_code == 201
    variant = client.post("/api/v1/variants", json={"product_id": product.json()["id"], "sku": sku, "price": price, "attributes": {"color": "black"}})
    assert variant.status_code == 201
    if stock is not None:
        inventory = client.post("/api/v1/inventory", json={"variant_id": variant.json()["id"], "available_quantity": stock})
        assert inventory.status_code == 201
    return {"product_id": product.json()["id"], "variant_id": variant.json()["id"], "sku": sku}


def create_cart(merchant_id: str, buyer_session_id: str | None = None):
    buyer_session_id = buyer_session_id or uuid.uuid4().hex
    response = client.post("/api/v1/carts", json={"merchant_id": merchant_id, "buyer_session_id": buyer_session_id})
    assert response.status_code == 201
    return response.json()


def test_cart_create_add_duplicate_update_remove_get_totals_and_delete():
    data = create_day6_catalog(uuid.uuid4().hex[:8])
    cart = create_cart(data["merchant_id"])
    assert cart["status"] == "ACTIVE"
    assert cart["total_item_count"] == 0

    added = client.post(f"/api/v1/carts/{cart['id']}/items", json={"product_variant_id": data["first"]["variant_id"], "quantity": 2})
    assert added.status_code == 201
    assert added.json()["total_item_count"] == 2
    assert added.json()["subtotal"] == "2599.00"
    item_id = added.json()["items"][0]["id"]

    duplicate = client.post(f"/api/v1/carts/{cart['id']}/items", json={"product_variant_id": data["first"]["variant_id"], "quantity": 1})
    assert duplicate.status_code == 201
    assert len(duplicate.json()["items"]) == 1
    assert duplicate.json()["items"][0]["quantity"] == 3

    updated = client.patch(f"/api/v1/carts/{cart['id']}/items/{item_id}", json={"quantity": 1})
    assert updated.status_code == 200
    assert updated.json()["subtotal"] == "1299.50"

    got = client.get(f"/api/v1/carts/{cart['id']}", params={"merchant_id": data["merchant_id"]})
    assert got.status_code == 200
    assert got.json()["items"][0]["line_total"] == "1299.50"

    removed = client.delete(f"/api/v1/carts/{cart['id']}/items/{item_id}")
    assert removed.status_code == 200
    assert removed.json()["total_item_count"] == 0

    deleted = client.delete(f"/api/v1/carts/{cart['id']}", params={"merchant_id": data["merchant_id"]})
    assert deleted.status_code == 204


def test_cart_rejects_invalid_quantity_nonexistent_inactive_and_cross_merchant_variants():
    data = create_day6_catalog(uuid.uuid4().hex[:8])
    cart = create_cart(data["merchant_id"])
    assert client.post(f"/api/v1/carts/{cart['id']}/items", json={"product_variant_id": data["first"]["variant_id"], "quantity": 0}).status_code == 422
    assert client.post(f"/api/v1/carts/{cart['id']}/items", json={"product_variant_id": str(uuid.uuid4()), "quantity": 1}).status_code == 404
    assert client.post(f"/api/v1/carts/{cart['id']}/items", json={"product_variant_id": data["inactive_product"]["variant_id"], "quantity": 1}).status_code == 404
    assert client.post(f"/api/v1/carts/{cart['id']}/items", json={"product_variant_id": data["inactive_variant"]["variant_id"], "quantity": 1}).status_code == 404
    assert client.post(f"/api/v1/carts/{cart['id']}/items", json={"product_variant_id": data["other_variant"]["variant_id"], "quantity": 1}).status_code == 404


def test_checkout_creates_order_snapshot_payment_and_mock_razorpay_order():
    data = create_day6_catalog(uuid.uuid4().hex[:8])
    cart = create_cart(data["merchant_id"], "buyer-day6")
    assert client.post(f"/api/v1/carts/{cart['id']}/items", json={"product_variant_id": data["first"]["variant_id"], "quantity": 2}).status_code == 201
    assert client.post(f"/api/v1/carts/{cart['id']}/items", json={"product_variant_id": data["second"]["variant_id"], "quantity": 1}).status_code == 201

    checkout = client.post("/api/v1/checkout", json={"cart_id": cart["id"], "merchant_id": data["merchant_id"], "buyer_session_id": "buyer-day6"})
    assert checkout.status_code == 200
    body = checkout.json()
    assert body["amount"] == "2898.00"
    assert body["currency"] == "INR"
    assert body["status"] == "PENDING_PAYMENT"
    assert body["razorpay"]["amount"] == 289800
    assert body["razorpay"]["mode"] == "mock"
    assert body["razorpay"]["order_id"].startswith("mock_order_")
    assert "key_secret" not in body["razorpay"]

    order = client.get(f"/api/v1/orders/{body['order_id']}", params={"merchant_id": data["merchant_id"]})
    assert order.status_code == 200
    assert any(item["product_name"].endswith("Wireless Headphones") for item in order.json()["items"])
    assert order.json()["status"] == "PENDING_PAYMENT"

    db = SessionLocal()
    try:
        order_row = db.get(Order, UUID(body["order_id"]))
        assert order_row is not None and order_row.total_amount == Decimal("2898.00")
        assert db.query(OrderItem).filter(OrderItem.order_id == order_row.id).count() == 2
        payment = db.query(Payment).filter(Payment.order_id == order_row.id).one()
        assert payment.status == "CREATED"
        assert payment.amount_minor == 289800
        assert db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment.id).count() == 1
    finally:
        db.close()


def test_checkout_rejects_empty_insufficient_missing_inventory_and_revalidates():
    data = create_day6_catalog(uuid.uuid4().hex[:8])
    empty_cart = create_cart(data["merchant_id"])
    assert client.post("/api/v1/checkout", json={"cart_id": empty_cart["id"], "merchant_id": data["merchant_id"]}).status_code == 409

    low_cart = create_cart(data["merchant_id"])
    assert client.post(f"/api/v1/carts/{low_cart['id']}/items", json={"product_variant_id": data["low_stock"]["variant_id"], "quantity": 2}).status_code == 201
    low_checkout = client.post("/api/v1/checkout", json={"cart_id": low_cart["id"], "merchant_id": data["merchant_id"]})
    assert low_checkout.status_code == 409
    assert "Insufficient inventory" in low_checkout.json()["detail"]

    missing_cart = create_cart(data["merchant_id"])
    assert client.post(f"/api/v1/carts/{missing_cart['id']}/items", json={"product_variant_id": data["missing_inventory"]["variant_id"], "quantity": 1}).status_code == 201
    missing_checkout = client.post("/api/v1/checkout", json={"cart_id": missing_cart["id"], "merchant_id": data["merchant_id"]})
    assert missing_checkout.status_code == 409
    assert "Missing inventory" in missing_checkout.json()["detail"]


def test_checkout_and_cart_access_enforce_merchant_isolation():
    data = create_day6_catalog(uuid.uuid4().hex[:8])
    cart = create_cart(data["merchant_id"])
    assert client.get(f"/api/v1/carts/{cart['id']}", params={"merchant_id": data["other_merchant_id"]}).status_code == 404
    assert client.post("/api/v1/checkout", json={"cart_id": cart["id"], "merchant_id": data["other_merchant_id"]}).status_code == 409


def test_minor_unit_conversion_and_development_mode_are_safe():
    assert to_minor_units(Decimal("2500.00")) == 250000
    assert to_minor_units(Decimal("1299.50")) == 129950


def test_agent_cart_tools_add_view_and_checkout():
    data = create_day6_catalog(uuid.uuid4().hex[:8])
    cart = create_cart(data["merchant_id"])
    add = client.post(
        "/api/v1/agent/chat",
        json={"merchant_id": data["merchant_id"], "cart_id": cart["id"], "variant_id": data["first"]["variant_id"], "quantity": 2, "message": "Add this to cart"},
    )
    assert add.status_code == 200
    assert [call["tool_name"] for call in add.json()["tool_calls"]] == ["add_to_cart"]
    assert add.json()["cart"]["total_item_count"] == 2

    view = client.post("/api/v1/agent/chat", json={"merchant_id": data["merchant_id"], "cart_id": cart["id"], "message": "View cart"})
    assert view.status_code == 200
    assert view.json()["cart"]["total_amount"] == "2599.00"

    checkout = client.post("/api/v1/agent/chat", json={"merchant_id": data["merchant_id"], "cart_id": cart["id"], "message": "Checkout"})
    assert checkout.status_code == 200
    assert checkout.json()["checkout"]["razorpay"]["mode"] == "mock"
