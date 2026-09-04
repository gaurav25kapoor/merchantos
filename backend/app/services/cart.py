from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Cart, CartItem, Inventory, Merchant, Product, ProductVariant
from app.schemas import CartItemOut, CartOut
from app.services.audit import AuditService


class CartError(ValueError):
    pass


class CartService:
    def __init__(self, db: Session):
        self.db = db

    def create_cart(self, merchant_id: UUID, buyer_session_id: str) -> Cart:
        merchant = self.db.get(Merchant, merchant_id)
        if not merchant or not merchant.is_active:
            raise CartError("Merchant not found")
        cart = Cart(merchant_id=merchant_id, buyer_session_id=buyer_session_id, status="ACTIVE")
        self.db.add(cart)
        self.db.flush()
        AuditService(self.db).log_event(
            merchant_id,
            "cart_created",
            "cart",
            cart.id,
            actor_type="buyer",
            actor_id=buyer_session_id,
            metadata={"status": cart.status},
        )
        return cart

    def get_cart(self, cart_id: UUID, merchant_id: UUID | None = None) -> Cart:
        query = self.db.query(Cart).filter(Cart.id == cart_id)
        if merchant_id:
            query = query.filter(Cart.merchant_id == merchant_id)
        cart = query.one_or_none()
        if not cart:
            raise CartError("Cart not found")
        return cart

    def add_item(self, cart_id: UUID, product_variant_id: UUID, quantity: int) -> Cart:
        cart = self.get_cart(cart_id)
        self._ensure_active(cart)
        variant, product, _inventory = self._variant_for_cart(cart.merchant_id, product_variant_id)
        existing = (
            self.db.query(CartItem)
            .filter(CartItem.cart_id == cart.id)
            .filter(CartItem.product_variant_id == product_variant_id)
            .one_or_none()
        )
        if existing:
            existing.quantity += quantity
            existing.unit_price = variant.price
            item_id = existing.id
        else:
            item = CartItem(cart_id=cart.id, product_variant_id=variant.id, quantity=quantity, unit_price=variant.price)
            self.db.add(item)
            self.db.flush()
            item_id = item.id
        self.db.flush()
        AuditService(self.db).log_event(
            cart.merchant_id,
            "item_added_to_cart",
            "cart",
            cart.id,
            actor_type="buyer",
            actor_id=cart.buyer_session_id,
            metadata={"cart_item_id": str(item_id), "variant_id": str(variant.id), "product_id": str(product.id), "quantity": quantity},
        )
        return cart

    def update_item(self, cart_id: UUID, item_id: UUID, quantity: int) -> Cart:
        cart = self.get_cart(cart_id)
        self._ensure_active(cart)
        item = self._cart_item(cart.id, item_id)
        variant, _product, _inventory = self._variant_for_cart(cart.merchant_id, item.product_variant_id)
        item.quantity = quantity
        item.unit_price = variant.price
        self.db.flush()
        AuditService(self.db).log_event(
            cart.merchant_id,
            "cart_item_updated",
            "cart",
            cart.id,
            actor_type="buyer",
            actor_id=cart.buyer_session_id,
            metadata={"cart_item_id": str(item.id), "variant_id": str(item.product_variant_id), "quantity": quantity},
        )
        return cart

    def remove_item(self, cart_id: UUID, item_id: UUID) -> Cart:
        cart = self.get_cart(cart_id)
        self._ensure_active(cart)
        item = self._cart_item(cart.id, item_id)
        variant_id = item.product_variant_id
        self.db.delete(item)
        self.db.flush()
        AuditService(self.db).log_event(
            cart.merchant_id,
            "cart_item_removed",
            "cart",
            cart.id,
            actor_type="buyer",
            actor_id=cart.buyer_session_id,
            metadata={"cart_item_id": str(item_id), "variant_id": str(variant_id)},
        )
        return cart

    def delete_cart(self, cart_id: UUID, merchant_id: UUID | None = None) -> None:
        cart = self.get_cart(cart_id, merchant_id)
        cart.status = "ABANDONED"
        self.db.flush()
        AuditService(self.db).log_event(
            cart.merchant_id,
            "cart_abandoned",
            "cart",
            cart.id,
            actor_type="buyer",
            actor_id=cart.buyer_session_id,
            metadata={"status": cart.status},
        )

    def serialize(self, cart: Cart) -> CartOut:
        rows = (
            self.db.query(CartItem, ProductVariant, Product, Inventory)
            .join(ProductVariant, ProductVariant.id == CartItem.product_variant_id)
            .join(Product, Product.id == ProductVariant.product_id)
            .outerjoin(Inventory, Inventory.variant_id == ProductVariant.id)
            .filter(CartItem.cart_id == cart.id)
            .order_by(CartItem.created_at.asc())
            .all()
        )
        items = []
        subtotal = Decimal("0.00")
        total_count = 0
        for item, variant, product, inventory in rows:
            line_total = item.unit_price * item.quantity
            subtotal += line_total
            total_count += item.quantity
            items.append(
                CartItemOut(
                    id=item.id,
                    product_variant_id=variant.id,
                    product_id=product.id,
                    product_name=product.name,
                    sku=variant.sku,
                    attributes=variant.attributes or {},
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    line_total=line_total,
                    available_quantity=inventory.available_quantity if inventory else 0,
                )
            )
        return CartOut(
            id=cart.id,
            merchant_id=cart.merchant_id,
            buyer_session_id=cart.buyer_session_id,
            status=cart.status,
            items=items,
            subtotal=subtotal,
            total_amount=subtotal,
            total_item_count=total_count,
            created_at=cart.created_at,
            updated_at=cart.updated_at,
        )

    def _variant_for_cart(self, merchant_id: UUID, variant_id: UUID):
        row = (
            self.db.query(ProductVariant, Product, Inventory)
            .join(Product, Product.id == ProductVariant.product_id)
            .outerjoin(Inventory, Inventory.variant_id == ProductVariant.id)
            .filter(ProductVariant.id == variant_id)
            .filter(Product.merchant_id == merchant_id)
            .filter(Product.is_active.is_(True))
            .filter(ProductVariant.is_active.is_(True))
            .one_or_none()
        )
        if not row:
            raise CartError("Variant not found")
        return row

    def _cart_item(self, cart_id: UUID, item_id: UUID) -> CartItem:
        item = self.db.query(CartItem).filter(CartItem.id == item_id).filter(CartItem.cart_id == cart_id).one_or_none()
        if not item:
            raise CartError("Cart item not found")
        return item

    def _ensure_active(self, cart: Cart) -> None:
        if cart.status != "ACTIVE":
            raise CartError("Cart is not active")
