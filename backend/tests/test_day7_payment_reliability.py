import hashlib
import hmac
import json
import uuid
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import IdempotencyRecord, Inventory, Order, Payment, PaymentAttempt, WebhookEvent
from app.services.payments import PaymentError, PaymentStateMachine


client = TestClient(app)


def create_paid_ready_payment(prefix: str, quantity: int = 2, stock: int = 5):
    merchant = client.post("/api/v1/merchants", json={"name": f"{prefix} Pay Store", "slug": f"{prefix}-pay-store"})
    assert merchant.status_code == 201
    merchant_id = merchant.json()["id"]
    other = client.post("/api/v1/merchants", json={"name": f"{prefix} Other Pay Store", "slug": f"{prefix}-other-pay-store"})
    assert other.status_code == 201
    product = client.post("/api/v1/products", json={"merchant_id": merchant_id, "name": f"{prefix} Paid Headphones", "category": "headphones"})
    assert product.status_code == 201
    variant = client.post("/api/v1/variants", json={"product_id": product.json()["id"], "sku": f"{prefix}-PAY", "price": "100.00", "attributes": {}})
    assert variant.status_code == 201
    inventory = client.post("/api/v1/inventory", json={"variant_id": variant.json()["id"], "available_quantity": stock})
    assert inventory.status_code == 201
    cart = client.post("/api/v1/carts", json={"merchant_id": merchant_id, "buyer_session_id": f"buyer-{prefix}"})
    assert cart.status_code == 201
    assert client.post(f"/api/v1/carts/{cart.json()['id']}/items", json={"product_variant_id": variant.json()["id"], "quantity": quantity}).status_code == 201
    checkout = client.post("/api/v1/checkout", json={"cart_id": cart.json()["id"], "merchant_id": merchant_id})
    assert checkout.status_code == 200
    return {
        "merchant_id": merchant_id,
        "other_merchant_id": other.json()["id"],
        "variant_id": variant.json()["id"],
        "payment_id": checkout.json()["payment_id"],
        "order_id": checkout.json()["order_id"],
        "provider_order_id": checkout.json()["razorpay"]["order_id"],
        "cart_id": cart.json()["id"],
    }


def sign_payment(order_id: str, payment_id: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256).hexdigest()


def sign_webhook(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_payment_state_machine_valid_and_invalid_transitions():
    db = SessionLocal()
    try:
        data = create_paid_ready_payment(uuid.uuid4().hex[:8])
        payment = db.get(Payment, UUID(data["payment_id"]))
        machine = PaymentStateMachine()
        machine.transition_payment(payment, "PENDING")
        machine.transition_payment(payment, "PROCESSING")
        machine.transition_payment(payment, "SUCCESS")
        assert payment.status == "SUCCESS"
        try:
            machine.transition_payment(payment, "FAILED")
            raise AssertionError("SUCCESS -> FAILED should fail")
        except PaymentError:
            pass
        try:
            machine.transition_payment(payment, "PENDING")
            raise AssertionError("SUCCESS -> PENDING should fail")
        except PaymentError:
            pass
    finally:
        db.rollback()
        db.close()


def test_failure_attempt_retry_success_and_history_preserved():
    data = create_paid_ready_payment(uuid.uuid4().hex[:8])
    failed = client.post("/api/v1/payments/fail", json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"], "failure_reason": "card declined", "failure_code": "BAD_CARD"})
    assert failed.status_code == 200
    assert failed.json()["payment"]["status"] == "FAILED"
    retry = client.post("/api/v1/payments/mock-success", json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"], "provider_payment_id": "mock_retry"})
    assert retry.status_code == 200
    body = retry.json()
    assert body["payment"]["status"] == "SUCCESS"
    statuses = [attempt["status"] for attempt in body["payment"]["attempts"]]
    assert "FAILED" in statuses
    assert "SUCCESS" in statuses


def test_mock_success_deducts_inventory_once_and_duplicate_is_safe():
    data = create_paid_ready_payment(uuid.uuid4().hex[:8], quantity=2, stock=5)
    key = f"mock-once-{uuid.uuid4().hex}"
    first = client.post("/api/v1/payments/mock-success", headers={"Idempotency-Key": key}, json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"]})
    assert first.status_code == 200
    second = client.post("/api/v1/payments/mock-success", headers={"Idempotency-Key": key}, json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"]})
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True

    db = SessionLocal()
    try:
        inventory = db.query(Inventory).filter(Inventory.variant_id == UUID(data["variant_id"])).one()
        assert inventory.available_quantity == 3
        payment = db.get(Payment, UUID(data["payment_id"]))
        assert payment.inventory_deducted is True
        assert db.query(IdempotencyRecord).filter(IdempotencyRecord.key == key).count() == 1
    finally:
        db.close()


def test_mock_success_rejected_in_production(monkeypatch):
    data = create_paid_ready_payment(uuid.uuid4().hex[:8])
    monkeypatch.setattr(settings, "environment", "production")
    response = client.post("/api/v1/payments/mock-success", json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"]})
    assert response.status_code == 400
    assert "only available" in response.json()["detail"]


def test_real_signature_verification_valid_invalid_and_wrong_order(monkeypatch):
    data = create_paid_ready_payment(uuid.uuid4().hex[:8])
    monkeypatch.setattr(settings, "payment_mode", "real")
    monkeypatch.setattr(settings, "razorpay_key_secret", "test_secret")
    db = SessionLocal()
    try:
        payment = db.get(Payment, UUID(data["payment_id"]))
        payment.provider_mode = "real"
        db.commit()
    finally:
        db.close()

    wrong = client.post(
        "/api/v1/payments/verify",
        json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"], "razorpay_payment_id": "pay_bad", "razorpay_order_id": "wrong_order", "razorpay_signature": "bad"},
    )
    assert wrong.status_code == 400

    invalid = client.post(
        "/api/v1/payments/verify",
        json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"], "razorpay_payment_id": "pay_bad", "razorpay_order_id": data["provider_order_id"], "razorpay_signature": "bad"},
    )
    assert invalid.status_code == 400

    signature = sign_payment(data["provider_order_id"], "pay_good", "test_secret")
    valid = client.post(
        "/api/v1/payments/verify",
        headers={"Idempotency-Key": "verify-real"},
        json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"], "razorpay_payment_id": "pay_good", "razorpay_order_id": data["provider_order_id"], "razorpay_signature": signature, "amount": "1.00"},
    )
    assert valid.status_code == 200
    assert valid.json()["payment"]["amount"] == "200.00"
    duplicate = client.post(
        "/api/v1/payments/verify",
        headers={"Idempotency-Key": "verify-real"},
        json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"], "razorpay_payment_id": "pay_good", "razorpay_order_id": data["provider_order_id"], "razorpay_signature": signature},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["idempotent_replay"] is True


def test_webhook_valid_duplicate_after_frontend_success_and_failed_event(monkeypatch):
    data = create_paid_ready_payment(uuid.uuid4().hex[:8], quantity=1, stock=4)
    monkeypatch.setattr(settings, "payment_mode", "real")
    monkeypatch.setattr(settings, "razorpay_key_secret", "webhook_secret")
    db = SessionLocal()
    try:
        payment = db.get(Payment, UUID(data["payment_id"]))
        payment.provider_mode = "real"
        db.commit()
    finally:
        db.close()
    signature = sign_payment(data["provider_order_id"], "pay_frontend", "webhook_secret")
    assert client.post("/api/v1/payments/verify", json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"], "razorpay_payment_id": "pay_frontend", "razorpay_order_id": data["provider_order_id"], "razorpay_signature": signature}).status_code == 200

    event = {"id": f"evt_{uuid.uuid4().hex}", "event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_frontend", "order_id": data["provider_order_id"]}}}}
    body = json.dumps(event, separators=(",", ":")).encode("utf-8")
    webhook = client.post("/api/v1/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sign_webhook(body, "webhook_secret"), "Content-Type": "application/json"})
    assert webhook.status_code == 200
    duplicate = client.post("/api/v1/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sign_webhook(body, "webhook_secret"), "Content-Type": "application/json"})
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"

    monkeypatch.setattr(settings, "payment_mode", "mock")
    failed_data = create_paid_ready_payment(uuid.uuid4().hex[:8])
    monkeypatch.setattr(settings, "payment_mode", "real")
    db = SessionLocal()
    try:
        failed_payment = db.get(Payment, UUID(failed_data["payment_id"]))
        failed_payment.provider_mode = "real"
        db.commit()
    finally:
        db.close()
    failed_event = {"id": f"evt_{uuid.uuid4().hex}", "event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_failed", "order_id": failed_data["provider_order_id"], "error_description": "bank failed", "error_code": "BANK_ERROR"}}}}
    failed_body = json.dumps(failed_event, separators=(",", ":")).encode("utf-8")
    failed = client.post("/api/v1/webhooks/razorpay", content=failed_body, headers={"X-Razorpay-Signature": sign_webhook(failed_body, "webhook_secret"), "Content-Type": "application/json"})
    assert failed.status_code == 200
    assert client.get(f"/api/v1/payments/{failed_data['payment_id']}", params={"merchant_id": failed_data["merchant_id"]}).json()["status"] == "FAILED"

    bad = client.post("/api/v1/webhooks/razorpay", content=failed_body, headers={"X-Razorpay-Signature": "bad", "Content-Type": "application/json"})
    assert bad.status_code == 400

    db = SessionLocal()
    try:
        inventory = db.query(Inventory).filter(Inventory.variant_id == UUID(data["variant_id"])).one()
        assert inventory.available_quantity == 3
        assert db.query(WebhookEvent).filter(WebhookEvent.provider_event_id == event["id"]).count() == 1
    finally:
        db.close()


def test_failed_payment_does_not_deduct_inventory_and_insufficient_success_is_controlled():
    data = create_paid_ready_payment(uuid.uuid4().hex[:8], quantity=2, stock=2)
    assert client.post("/api/v1/payments/fail", json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"], "failure_reason": "failed"}).status_code == 200
    db = SessionLocal()
    try:
        inventory = db.query(Inventory).filter(Inventory.variant_id == UUID(data["variant_id"])).one()
        assert inventory.available_quantity == 2
        inventory.available_quantity = 1
        db.commit()
    finally:
        db.close()
    insufficient = client.post("/api/v1/payments/mock-success", json={"merchant_id": data["merchant_id"], "payment_id": data["payment_id"]})
    assert insufficient.status_code == 400
    assert "Insufficient inventory" in insufficient.json()["detail"]


def test_payment_merchant_isolation_and_status_endpoint():
    data = create_paid_ready_payment(uuid.uuid4().hex[:8])
    assert client.get(f"/api/v1/payments/{data['payment_id']}", params={"merchant_id": data["merchant_id"]}).status_code == 200
    assert client.get(f"/api/v1/payments/{data['payment_id']}", params={"merchant_id": data["other_merchant_id"]}).status_code == 404
    isolated = client.post("/api/v1/payments/mock-success", json={"merchant_id": data["other_merchant_id"], "payment_id": data["payment_id"]})
    assert isolated.status_code == 400


def test_idempotency_key_is_scoped_by_operation():
    first = create_paid_ready_payment(uuid.uuid4().hex[:8])
    second = create_paid_ready_payment(uuid.uuid4().hex[:8])
    key = "same-key-different-operation"
    success = client.post("/api/v1/payments/mock-success", headers={"Idempotency-Key": key}, json={"merchant_id": first["merchant_id"], "payment_id": first["payment_id"]})
    assert success.status_code == 200
    failure = client.post("/api/v1/payments/fail", headers={"Idempotency-Key": key}, json={"merchant_id": second["merchant_id"], "payment_id": second["payment_id"], "failure_reason": "declined"})
    assert failure.status_code == 200
    db = SessionLocal()
    try:
        operations = {record.operation for record in db.query(IdempotencyRecord).filter(IdempotencyRecord.key == key).all()}
        assert operations == {"payments.mock_success", "payments.failure"}
    finally:
        db.close()
