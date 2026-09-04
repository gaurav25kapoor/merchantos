import hmac
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from uuid import UUID

from app.config import settings


class PaymentProviderError(RuntimeError):
    pass


class RazorpayService:
    def create_order(self, order_id: UUID, amount: Decimal, currency: str = "INR") -> dict:
        amount_minor = to_minor_units(amount)
        mode = settings.payment_mode.lower()
        if mode == "mock":
            return {
                "provider_order_id": f"mock_order_{order_id}",
                "amount": amount_minor,
                "currency": currency,
                "mode": "mock",
                "key_id": settings.razorpay_key_id,
            }
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            raise PaymentProviderError("Razorpay credentials are required outside mock mode")
        try:
            import razorpay
        except ImportError as exc:
            raise PaymentProviderError("Razorpay SDK is not installed") from exc
        client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
        order = client.order.create({"amount": amount_minor, "currency": currency, "receipt": str(order_id)})
        return {
            "provider_order_id": order["id"],
            "amount": amount_minor,
            "currency": currency,
            "mode": "real",
            "key_id": settings.razorpay_key_id,
        }

    def verify_payment_signature(self, provider_order_id: str, provider_payment_id: str, signature: str) -> bool:
        if not settings.razorpay_key_secret:
            raise PaymentProviderError("Razorpay secret is required for signature verification")
        payload = f"{provider_order_id}|{provider_payment_id}".encode("utf-8")
        expected = hmac.new(settings.razorpay_key_secret.encode("utf-8"), payload, sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        if not settings.razorpay_key_secret:
            raise PaymentProviderError("Razorpay secret is required for webhook verification")
        expected = hmac.new(settings.razorpay_key_secret.encode("utf-8"), body, sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


def to_minor_units(amount: Decimal) -> int:
    return int((Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100).to_integral_value(rounding=ROUND_HALF_UP))
