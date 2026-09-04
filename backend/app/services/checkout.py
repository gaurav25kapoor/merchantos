from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Cart, CartItem, Inventory, Order, OrderItem, Payment, PaymentAttempt, Product, ProductVariant
from app.schemas import CheckoutResponse, RazorpayCheckoutOut
from app.services.audit import AuditService
from app.services.cart import CartError, CartService
from app.services.razorpay_service import PaymentProviderError, RazorpayService


class CheckoutError(ValueError):
    pass


class CheckoutService:
    def __init__(self, db: Session, payment_provider: RazorpayService | None = None):
        self.db = db
        self.payment_provider = payment_provider or RazorpayService()

    def checkout(self, cart_id: UUID, merchant_id: UUID, buyer_session_id: str | None = None) -> CheckoutResponse:
        cart = CartService(self.db).get_cart(cart_id, merchant_id)
        if cart.status != "ACTIVE":
            raise CheckoutError("Cart is not active")
        if buyer_session_id is not None and cart.buyer_session_id != buyer_session_id:
            raise CheckoutError("Cart buyer session does not match")
        rows = self._cart_rows(cart)
        if not rows:
            raise CheckoutError("Cart is empty")
        self._validate_inventory(rows)
        AuditService(self.db).log_event(
            cart.merchant_id,
            "checkout_started",
            "cart",
            cart.id,
            actor_type="buyer",
            actor_id=cart.buyer_session_id,
            metadata={"item_count": len(rows)},
        )
        subtotal = sum((item.unit_price * item.quantity for item, _variant, _product, _inventory in rows), Decimal("0.00"))
        order = Order(
            merchant_id=cart.merchant_id,
            cart_id=cart.id,
            buyer_session_id=cart.buyer_session_id,
            subtotal=subtotal,
            total_amount=subtotal,
            currency="INR",
            status="PENDING_PAYMENT",
        )
        self.db.add(order)
        self.db.flush()
        AuditService(self.db).log_event(
            cart.merchant_id,
            "order_created",
            "order",
            order.id,
            actor_type="buyer",
            actor_id=cart.buyer_session_id,
            metadata={"cart_id": str(cart.id), "amount": str(order.total_amount), "currency": order.currency},
        )
        for item, variant, product, _inventory in rows:
            self.db.add(
                OrderItem(
                    order_id=order.id,
                    product_variant_id=variant.id,
                    product_name=product.name,
                    variant_sku=variant.sku,
                    variant_attributes=variant.attributes or {},
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    line_total=item.unit_price * item.quantity,
                )
            )
        provider_order = self.payment_provider.create_order(order.id, order.total_amount, order.currency)
        payment = Payment(
            order_id=order.id,
            provider="razorpay",
            provider_order_id=provider_order["provider_order_id"],
            provider_mode=provider_order["mode"],
            amount=order.total_amount,
            amount_minor=provider_order["amount"],
            currency=order.currency,
            status="CREATED",
            metadata_json={"receipt": str(order.id)},
        )
        self.db.add(payment)
        self.db.flush()
        AuditService(self.db).log_event(
            cart.merchant_id,
            "payment_created",
            "payment",
            payment.id,
            actor_type="system",
            metadata={"order_id": str(order.id), "provider": payment.provider, "amount": str(payment.amount), "provider_order_id": payment.provider_order_id},
        )
        self.db.add(PaymentAttempt(payment_id=payment.id, provider="razorpay", provider_order_id=payment.provider_order_id, status="CREATED", metadata_json={"mode": payment.provider_mode}))
        cart.status = "CHECKED_OUT"
        self.db.flush()
        return CheckoutResponse(
            order_id=order.id,
            payment_id=payment.id,
            amount=order.total_amount,
            currency=order.currency,
            status=order.status,
            razorpay=RazorpayCheckoutOut(
                key_id=provider_order["key_id"],
                order_id=provider_order["provider_order_id"],
                amount=provider_order["amount"],
                currency=order.currency,
                mode=provider_order["mode"],
            ),
        )

    def _cart_rows(self, cart: Cart):
        return (
            self.db.query(CartItem, ProductVariant, Product, Inventory)
            .join(ProductVariant, ProductVariant.id == CartItem.product_variant_id)
            .join(Product, Product.id == ProductVariant.product_id)
            .outerjoin(Inventory, Inventory.variant_id == ProductVariant.id)
            .filter(CartItem.cart_id == cart.id)
            .filter(Product.merchant_id == cart.merchant_id)
            .filter(Product.is_active.is_(True))
            .filter(ProductVariant.is_active.is_(True))
            .all()
        )

    def _validate_inventory(self, rows) -> None:
        for item, variant, _product, inventory in rows:
            if not inventory:
                raise CheckoutError(f"Missing inventory for variant {variant.sku}")
            if inventory.available_quantity < item.quantity:
                raise CheckoutError(f"Insufficient inventory for variant {variant.sku}. Requested: {item.quantity}, Available: {inventory.available_quantity}")
