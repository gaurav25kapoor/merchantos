import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Cart, IdempotencyRecord, Inventory, Order, OrderItem, Payment, PaymentAttempt, WebhookEvent
from app.schemas import PaymentAttemptOut, PaymentOut
from app.services.audit import AuditService
from app.services.razorpay_service import PaymentProviderError, RazorpayService


PAYMENT_TRANSITIONS = {
    "CREATED": {"PENDING", "PROCESSING", "FAILED", "CANCELLED", "SUCCESS"},
    "PENDING": {"PROCESSING", "FAILED", "CANCELLED", "SUCCESS"},
    "PROCESSING": {"SUCCESS", "FAILED"},
    "FAILED": {"PENDING", "PROCESSING"},
    "SUCCESS": set(),
    "CANCELLED": set(),
}
ORDER_TRANSITIONS = {
    "PENDING_PAYMENT": {"PAID", "PAYMENT_FAILED"},
    "PAYMENT_FAILED": {"PENDING_PAYMENT", "PAID"},
    "PAID": set(),
}


class PaymentError(ValueError):
    pass


class PaymentStateMachine:
    def transition_payment(self, payment: Payment, target: str) -> None:
        allowed = PAYMENT_TRANSITIONS.get(payment.status, set())
        if target == payment.status:
            return
        if target not in allowed:
            raise PaymentError(f"Invalid payment transition {payment.status} -> {target}")
        payment.status = target

    def transition_order(self, order: Order, target: str) -> None:
        allowed = ORDER_TRANSITIONS.get(order.status, set())
        if target == order.status:
            return
        if target not in allowed:
            raise PaymentError(f"Invalid order transition {order.status} -> {target}")
        order.status = target


class IdempotencyService:
    def __init__(self, db: Session):
        self.db = db

    def get_replay(self, key: str | None, operation: str) -> dict | None:
        if not key:
            return None
        record = self.db.query(IdempotencyRecord).filter(IdempotencyRecord.key == key).filter(IdempotencyRecord.operation == operation).one_or_none()
        return record.response_json if record else None

    def store(self, key: str | None, operation: str, request_payload: dict, response_payload: dict, resource_id: str | None = None) -> None:
        if not key:
            return
        record = IdempotencyRecord(
            key=key,
            operation=operation,
            request_hash=request_hash(request_payload),
            response_json=jsonable_encoder(response_payload),
            resource_id=resource_id,
            status="COMPLETED",
        )
        self.db.add(record)
        self.db.flush()


class PaymentService:
    def __init__(self, db: Session, razorpay: RazorpayService | None = None):
        self.db = db
        self.razorpay = razorpay or RazorpayService()
        self.machine = PaymentStateMachine()
        self.idempotency = IdempotencyService(db)

    def get_payment(self, payment_id: UUID, merchant_id: UUID) -> Payment:
        payment = (
            self.db.query(Payment)
            .join(Order, Order.id == Payment.order_id)
            .filter(Payment.id == payment_id)
            .filter(Order.merchant_id == merchant_id)
            .one_or_none()
        )
        if not payment:
            raise PaymentError("Payment not found")
        return payment

    def serialize(self, payment: Payment) -> PaymentOut:
        return PaymentOut(
            id=payment.id,
            order_id=payment.order_id,
            merchant_id=payment.order.merchant_id,
            provider=payment.provider,
            provider_order_id=payment.provider_order_id,
            provider_mode=payment.provider_mode,
            amount=payment.amount,
            amount_minor=payment.amount_minor,
            currency=payment.currency,
            status=payment.status,
            inventory_deducted=payment.inventory_deducted,
            attempts=[
                PaymentAttemptOut(
                    id=attempt.id,
                    provider=attempt.provider,
                    provider_payment_id=attempt.provider_payment_id,
                    provider_order_id=attempt.provider_order_id,
                    amount=attempt.amount,
                    amount_minor=attempt.amount_minor,
                    currency=attempt.currency,
                    status=attempt.status,
                    failure_reason=attempt.failure_reason,
                    failure_code=attempt.failure_code,
                    created_at=attempt.created_at,
                    updated_at=attempt.updated_at,
                )
                for attempt in sorted(payment.attempts, key=lambda item: item.created_at)
            ],
            created_at=payment.created_at,
            updated_at=payment.updated_at,
        )

    def verify(self, merchant_id: UUID, payment_id: UUID, provider_payment_id: str, provider_order_id: str, signature: str, idempotency_key: str | None = None) -> tuple[PaymentOut, bool]:
        replay = self.idempotency.get_replay(idempotency_key, "payments.verify")
        if replay:
            return PaymentOut.model_validate(replay["payment"]), True
        payment = self.get_payment(payment_id, merchant_id)
        if provider_order_id != payment.provider_order_id:
            raise PaymentError("Provider order ID does not match payment")
        if payment.provider_mode != "mock":
            if not self.razorpay.verify_payment_signature(provider_order_id, provider_payment_id, signature):
                self.record_failure(payment, provider_payment_id, "Invalid Razorpay signature", "INVALID_SIGNATURE")
                raise PaymentError("Invalid Razorpay signature")
        result = self.handle_payment_success(payment, provider_payment_id, {"source": "frontend_verify"})
        payload = {"payment": result.model_dump(mode="json"), "message": "Payment verified successfully"}
        self.idempotency.store(idempotency_key, "payments.verify", {"payment_id": str(payment_id), "provider_payment_id": provider_payment_id}, payload, str(payment.id))
        return result, False

    def mock_success(self, merchant_id: UUID, payment_id: UUID, provider_payment_id: str | None = None, idempotency_key: str | None = None) -> tuple[PaymentOut, bool]:
        if settings.environment == "production" or settings.payment_mode.lower() != "mock":
            raise PaymentError("Mock payment success is only available in development mock mode")
        replay = self.idempotency.get_replay(idempotency_key, "payments.mock_success")
        if replay:
            return PaymentOut.model_validate(replay["payment"]), True
        payment = self.get_payment(payment_id, merchant_id)
        result = self.handle_payment_success(payment, provider_payment_id or f"mock_pay_{payment.id}", {"source": "mock_success"})
        payload = {"payment": result.model_dump(mode="json"), "message": "Mock payment marked successful"}
        self.idempotency.store(idempotency_key, "payments.mock_success", {"payment_id": str(payment_id)}, payload, str(payment.id))
        return result, False

    def fail_payment(self, merchant_id: UUID, payment_id: UUID, reason: str, code: str | None = None, provider_payment_id: str | None = None, idempotency_key: str | None = None) -> tuple[PaymentOut, bool]:
        replay = self.idempotency.get_replay(idempotency_key, "payments.failure")
        if replay:
            return PaymentOut.model_validate(replay["payment"]), True
        payment = self.get_payment(payment_id, merchant_id)
        self.record_failure(payment, provider_payment_id, reason, code)
        result = self.serialize(payment)
        payload = {"payment": result.model_dump(mode="json"), "message": "Payment failure recorded"}
        self.idempotency.store(idempotency_key, "payments.failure", {"payment_id": str(payment_id), "reason": reason}, payload, str(payment.id))
        return result, False

    def handle_payment_success(self, payment: Payment, provider_payment_id: str, metadata: dict) -> PaymentOut:
        if payment.status == "SUCCESS":
            return self.serialize(payment)
        AuditService(self.db).log_event(
            payment.order.merchant_id,
            "payment_processing",
            "payment",
            payment.id,
            metadata={"order_id": str(payment.order_id), "source": metadata.get("source")},
        )
        self.machine.transition_payment(payment, "PROCESSING")
        self._deduct_inventory_once(payment)
        self.machine.transition_payment(payment, "SUCCESS")
        self.machine.transition_order(payment.order, "PAID")
        if payment.order.cart:
            payment.order.cart.status = "PAID"
        self.db.add(
            PaymentAttempt(
                payment_id=payment.id,
                provider=payment.provider,
                provider_payment_id=provider_payment_id,
                provider_order_id=payment.provider_order_id,
                amount=payment.amount,
                amount_minor=payment.amount_minor,
                currency=payment.currency,
                status="SUCCESS",
                metadata_json=metadata,
            )
        )
        self.db.flush()
        AuditService(self.db).log_event(
            payment.order.merchant_id,
            "payment_success",
            "payment",
            payment.id,
            metadata={"order_id": str(payment.order_id), "provider_payment_id": provider_payment_id, "source": metadata.get("source")},
        )
        return self.serialize(payment)

    def record_failure(self, payment: Payment, provider_payment_id: str | None, reason: str, code: str | None = None) -> None:
        if payment.status == "SUCCESS":
            raise PaymentError("Cannot mark a successful payment as failed")
        AuditService(self.db).log_event(
            payment.order.merchant_id,
            "payment_processing",
            "payment",
            payment.id,
            metadata={"order_id": str(payment.order_id), "target": "FAILED"},
        )
        if payment.status == "CREATED":
            self.machine.transition_payment(payment, "PENDING")
        self.machine.transition_payment(payment, "PROCESSING")
        self.machine.transition_payment(payment, "FAILED")
        if payment.order.status == "PENDING_PAYMENT":
            self.machine.transition_order(payment.order, "PAYMENT_FAILED")
        self.db.add(
            PaymentAttempt(
                payment_id=payment.id,
                provider=payment.provider,
                provider_payment_id=provider_payment_id,
                provider_order_id=payment.provider_order_id,
                amount=payment.amount,
                amount_minor=payment.amount_minor,
                currency=payment.currency,
                status="FAILED",
                failure_reason=reason,
                failure_code=code,
                metadata_json={},
            )
        )
        self.db.flush()
        AuditService(self.db).log_event(
            payment.order.merchant_id,
            "payment_failed",
            "payment",
            payment.id,
            metadata={"order_id": str(payment.order_id), "provider_payment_id": provider_payment_id, "reason": reason, "code": code},
        )

    def process_webhook(self, body: bytes, signature: str | None, idempotency_key: str | None = None) -> tuple[dict, bool]:
        replay = self.idempotency.get_replay(idempotency_key, "webhooks.razorpay")
        if replay:
            return replay, True
        if settings.payment_mode.lower() != "mock":
            if not signature or not self.razorpay.verify_webhook_signature(body, signature):
                raise PaymentProviderError("Invalid Razorpay webhook signature")
        event = json.loads(body.decode("utf-8"))
        event_id = str(event.get("id") or f"generated_{hashlib.sha256(body).hexdigest()}")
        existing = self.db.query(WebhookEvent).filter(WebhookEvent.provider == "razorpay").filter(WebhookEvent.provider_event_id == event_id).one_or_none()
        if existing:
            return {"status": "duplicate", "event_id": event_id}, True
        event_type = event.get("event", "")
        payload = event.get("payload", {}).get("payment", {}).get("entity", {})
        provider_order_id = payload.get("order_id")
        provider_payment_id = payload.get("id")
        payment = self.db.query(Payment).filter(Payment.provider_order_id == provider_order_id).one_or_none() if provider_order_id else None
        status = "IGNORED"
        if payment and event_type in {"payment.authorized", "payment.captured"}:
            self.handle_payment_success(payment, provider_payment_id or f"webhook_pay_{payment.id}", {"source": "webhook", "event_id": event_id, "event": event_type})
            status = "PROCESSED"
        elif payment and event_type == "payment.failed":
            if payment.status != "SUCCESS":
                error = payload.get("error_description") or "Payment failed"
                code = payload.get("error_code")
                self.record_failure(payment, provider_payment_id, error, code)
            status = "PROCESSED"
        webhook = WebhookEvent(provider="razorpay", provider_event_id=event_id, event_type=event_type or "unknown", payload_hash=hashlib.sha256(body).hexdigest(), status=status, processed_at=datetime.now(timezone.utc), metadata_json={"payment_id": str(payment.id) if payment else None})
        self.db.add(webhook)
        self.db.flush()
        if payment:
            AuditService(self.db).log_event(
                payment.order.merchant_id,
                "webhook_received",
                "webhook_event",
                webhook.id,
                metadata={"payment_id": str(payment.id), "event_type": event_type or "unknown", "status": status},
            )
        response = {"status": status.lower(), "event_id": event_id}
        self.idempotency.store(idempotency_key, "webhooks.razorpay", {"event_id": event_id}, response, event_id)
        return response, False

    def _deduct_inventory_once(self, payment: Payment) -> None:
        if payment.inventory_deducted:
            return
        for item in payment.order.items:
            inventory = (
                self.db.query(Inventory)
                .filter(Inventory.variant_id == item.product_variant_id)
                .with_for_update()
                .one_or_none()
            )
            if not inventory:
                raise PaymentError(f"Missing inventory for variant {item.variant_sku}")
            if inventory.available_quantity < item.quantity:
                raise PaymentError(f"Insufficient inventory for variant {item.variant_sku}. Requested: {item.quantity}, Available: {inventory.available_quantity}")
            inventory.available_quantity -= item.quantity
            AuditService(self.db).log_event(
                payment.order.merchant_id,
                "inventory_deducted",
                "inventory",
                inventory.id,
                metadata={"payment_id": str(payment.id), "order_id": str(payment.order_id), "variant_id": str(item.product_variant_id), "quantity": item.quantity},
            )
        payment.inventory_deducted = True


def request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(jsonable_encoder(payload), sort_keys=True).encode("utf-8")).hexdigest()
