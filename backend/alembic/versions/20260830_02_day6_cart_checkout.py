"""Add Day 6 carts, orders, and payment foundation."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260830_02"
down_revision = "20260830_01"
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "carts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("merchant_id", uuid, sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("buyer_session_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="ACTIVE"),
        *timestamps(),
    )
    op.create_index("ix_carts_merchant_id", "carts", ["merchant_id"])
    op.create_index("ix_carts_buyer_session_id", "carts", ["buyer_session_id"])
    op.create_index("ix_carts_status", "carts", ["status"])

    op.create_table(
        "cart_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("cart_id", uuid, sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_variant_id", uuid, sa.ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        *timestamps(),
        sa.CheckConstraint("quantity > 0"),
        sa.UniqueConstraint("cart_id", "product_variant_id", name="uq_cart_items_cart_variant"),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])
    op.create_index("ix_cart_items_product_variant_id", "cart_items", ["product_variant_id"])

    op.create_table(
        "orders",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("merchant_id", uuid, sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cart_id", uuid, sa.ForeignKey("carts.id", ondelete="SET NULL")),
        sa.Column("buyer_session_id", sa.String(120), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(40), nullable=False, server_default="PENDING_PAYMENT"),
        *timestamps(),
        sa.CheckConstraint("subtotal >= 0"),
        sa.CheckConstraint("total_amount >= 0"),
    )
    op.create_index("ix_orders_merchant_id", "orders", ["merchant_id"])
    op.create_index("ix_orders_cart_id", "orders", ["cart_id"])
    op.create_index("ix_orders_buyer_session_id", "orders", ["buyer_session_id"])
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "order_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("order_id", uuid, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_variant_id", uuid, sa.ForeignKey("product_variants.id", ondelete="SET NULL")),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("variant_sku", sa.String(100), nullable=False),
        sa.Column("variant_attributes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        *timestamps(),
        sa.CheckConstraint("quantity > 0"),
        sa.CheckConstraint("unit_price >= 0"),
        sa.CheckConstraint("line_total >= 0"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_variant_id", "order_items", ["product_variant_id"])

    op.create_table(
        "payments",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("order_id", uuid, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("provider", sa.String(40), nullable=False, server_default="razorpay"),
        sa.Column("provider_order_id", sa.String(120), nullable=False),
        sa.Column("provider_mode", sa.String(20), nullable=False, server_default="mock"),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(40), nullable=False, server_default="CREATED"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
        sa.CheckConstraint("amount >= 0"),
        sa.CheckConstraint("amount_minor >= 0"),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index("ix_payments_provider_order_id", "payments", ["provider_order_id"])
    op.create_index("ix_payments_status", "payments", ["status"])

    op.create_table(
        "payment_attempts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("payment_id", uuid, sa.ForeignKey("payments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False, server_default="razorpay"),
        sa.Column("provider_order_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="CREATED"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
    )
    op.create_index("ix_payment_attempts_payment_id", "payment_attempts", ["payment_id"])
    op.create_index("ix_payment_attempts_provider_order_id", "payment_attempts", ["provider_order_id"])


def downgrade():
    op.drop_index("ix_payment_attempts_provider_order_id", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_payment_id", table_name="payment_attempts")
    op.drop_table("payment_attempts")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_provider_order_id", table_name="payments")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_order_items_product_variant_id", table_name="order_items")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_buyer_session_id", table_name="orders")
    op.drop_index("ix_orders_cart_id", table_name="orders")
    op.drop_index("ix_orders_merchant_id", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_cart_items_product_variant_id", table_name="cart_items")
    op.drop_index("ix_cart_items_cart_id", table_name="cart_items")
    op.drop_table("cart_items")
    op.drop_index("ix_carts_status", table_name="carts")
    op.drop_index("ix_carts_buyer_session_id", table_name="carts")
    op.drop_index("ix_carts_merchant_id", table_name="carts")
    op.drop_table("carts")
