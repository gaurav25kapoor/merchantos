import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Merchant(TimestampMixin, Base):
    __tablename__ = "merchants"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    policy: Mapped["MerchantPolicy | None"] = relationship(back_populates="merchant", cascade="all, delete-orphan", uselist=False)
    products: Mapped[list["Product"]] = relationship(back_populates="merchant", cascade="all, delete-orphan")
    users: Mapped[list["User"]] = relationship(back_populates="merchant", cascade="all, delete-orphan")


class MerchantPolicy(TimestampMixin, Base):
    __tablename__ = "merchant_policies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    return_window_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    cancellation_window_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    minimum_order_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    maximum_discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), nullable=False)
    negotiation_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    free_shipping_threshold: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rules: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    merchant: Mapped[Merchant] = relationship(back_populates="policy")
    __table_args__ = (CheckConstraint("return_window_days >= 0"), CheckConstraint("cancellation_window_minutes >= 0"), CheckConstraint("minimum_order_value >= 0"), CheckConstraint("maximum_discount_percent BETWEEN 0 AND 100"), CheckConstraint("free_shipping_threshold IS NULL OR free_shipping_threshold >= 0"))


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    brand: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    merchant: Mapped[Merchant] = relationship(back_populates="products")
    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class ProductVariant(TimestampMixin, Base):
    __tablename__ = "product_variants"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    product: Mapped[Product] = relationship(back_populates="variants")
    inventory: Mapped["Inventory | None"] = relationship(back_populates="variant", cascade="all, delete-orphan", uselist=False)
    __table_args__ = (CheckConstraint("price >= 0"),)


class Inventory(TimestampMixin, Base):
    __tablename__ = "inventory"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_variants.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    available_quantity: Mapped[int] = mapped_column(Integer, default=0, index=True, nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="in_stock", nullable=False)
    variant: Mapped[ProductVariant] = relationship(back_populates="inventory")
    __table_args__ = (CheckConstraint("available_quantity >= 0"), CheckConstraint("reserved_quantity >= 0"))


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("merchants.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(40), default="staff", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    merchant: Mapped[Merchant | None] = relationship(back_populates="users")


class AgentSession(TimestampMixin, Base):
    __tablename__ = "agent_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    merchant: Mapped[Merchant] = relationship()
    tool_calls: Mapped[list["AgentToolCall"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class AgentToolCall(TimestampMixin, Base):
    __tablename__ = "agent_tool_calls"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    tool_input: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    tool_output: Mapped[dict | None] = mapped_column(JSONB)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    session: Mapped[AgentSession] = relationship(back_populates="tool_calls")
    merchant: Mapped[Merchant] = relationship()


class PolicyDecision(TimestampMixin, Base):
    __tablename__ = "policy_decisions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_sessions.id", ondelete="SET NULL"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product_variants.id", ondelete="SET NULL"), index=True)
    decision_type: Mapped[str] = mapped_column(String(80), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    offered_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    approved_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    counter_offer: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    merchant: Mapped[Merchant] = relationship()


class Recommendation(TimestampMixin, Base):
    __tablename__ = "recommendations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    source_product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False)
    recommended_product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False)
    recommendation_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    merchant: Mapped[Merchant] = relationship()
    source_product: Mapped[Product] = relationship(foreign_keys=[source_product_id])
    recommended_product: Mapped[Product] = relationship(foreign_keys=[recommended_product_id])


class UpsellEvent(TimestampMixin, Base):
    __tablename__ = "upsell_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_sessions.id", ondelete="SET NULL"), index=True)
    source_product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False)
    recommended_product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), default="shown", nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    merchant: Mapped[Merchant] = relationship()


class Cart(TimestampMixin, Base):
    __tablename__ = "carts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    buyer_session_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE", index=True, nullable=False)
    merchant: Mapped[Merchant] = relationship()
    items: Mapped[list["CartItem"]] = relationship(back_populates="cart", cascade="all, delete-orphan")


class CartItem(TimestampMixin, Base):
    __tablename__ = "cart_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cart_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), index=True, nullable=False)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_variants.id", ondelete="CASCADE"), index=True, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cart: Mapped[Cart] = relationship(back_populates="items")
    variant: Mapped[ProductVariant] = relationship()
    __table_args__ = (CheckConstraint("quantity > 0"), UniqueConstraint("cart_id", "product_variant_id", name="uq_cart_items_cart_variant"))


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    cart_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("carts.id", ondelete="SET NULL"), index=True)
    buyer_session_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="PENDING_PAYMENT", index=True, nullable=False)
    merchant: Mapped[Merchant] = relationship()
    cart: Mapped[Cart | None] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    payment: Mapped["Payment | None"] = relationship(back_populates="order", cascade="all, delete-orphan", uselist=False)
    __table_args__ = (CheckConstraint("subtotal >= 0"), CheckConstraint("total_amount >= 0"))


class OrderItem(TimestampMixin, Base):
    __tablename__ = "order_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product_variants.id", ondelete="SET NULL"), index=True)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    variant_sku: Mapped[str] = mapped_column(String(100), nullable=False)
    variant_attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    order: Mapped[Order] = relationship(back_populates="items")
    variant: Mapped[ProductVariant | None] = relationship()
    __table_args__ = (CheckConstraint("quantity > 0"), CheckConstraint("unit_price >= 0"), CheckConstraint("line_total >= 0"))


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="razorpay", nullable=False)
    provider_order_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    provider_mode: Mapped[str] = mapped_column(String(20), default="mock", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="CREATED", index=True, nullable=False)
    inventory_deducted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    order: Mapped[Order] = relationship(back_populates="payment")
    attempts: Mapped[list["PaymentAttempt"]] = relationship(back_populates="payment", cascade="all, delete-orphan")
    __table_args__ = (CheckConstraint("amount >= 0"), CheckConstraint("amount_minor >= 0"))


class PaymentAttempt(TimestampMixin, Base):
    __tablename__ = "payment_attempts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="razorpay", nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(120), index=True)
    provider_order_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    amount_minor: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(40), default="CREATED", nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    payment: Mapped[Payment] = relationship(back_populates="attempts")


class IdempotencyRecord(TimestampMixin, Base):
    __tablename__ = "idempotency_records"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="COMPLETED", nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(120), index=True)
    response_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    __table_args__ = (UniqueConstraint("key", "operation", name="uq_idempotency_key_operation"),)


class WebhookEvent(TimestampMixin, Base):
    __tablename__ = "webhook_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(40), default="razorpay", nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="PROCESSED", nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_webhook_provider_event"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    actor_type: Mapped[str] = mapped_column(String(40), default="system", nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)
    merchant: Mapped[Merchant] = relationship()
