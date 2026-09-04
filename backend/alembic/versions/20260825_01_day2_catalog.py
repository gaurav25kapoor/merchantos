"""Create MerchantOS Day 2 catalog tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260825_01"
down_revision = None
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)
def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]
def upgrade():
    op.create_table("merchants", sa.Column("id", uuid, primary_key=True), sa.Column("name", sa.String(160), nullable=False), sa.Column("slug", sa.String(100), nullable=False, unique=True), sa.Column("description", sa.Text()), sa.Column("email", sa.String(255)), sa.Column("contact_phone", sa.String(40)), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), *timestamps())
    op.create_index("ix_merchants_slug", "merchants", ["slug"])
    op.create_table("merchant_policies", sa.Column("id", uuid, primary_key=True), sa.Column("merchant_id", uuid, sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("return_window_days", sa.Integer(), nullable=False), sa.Column("cancellation_window_minutes", sa.Integer(), nullable=False), sa.Column("minimum_order_value", sa.Numeric(12,2), nullable=False), sa.Column("maximum_discount_percent", sa.Numeric(5,2), nullable=False), sa.Column("free_shipping_threshold", sa.Numeric(12,2)), sa.Column("rules", postgresql.JSONB(), nullable=False), *timestamps(), sa.CheckConstraint("return_window_days >= 0"), sa.CheckConstraint("cancellation_window_minutes >= 0"), sa.CheckConstraint("minimum_order_value >= 0"), sa.CheckConstraint("maximum_discount_percent BETWEEN 0 AND 100"), sa.CheckConstraint("free_shipping_threshold IS NULL OR free_shipping_threshold >= 0"))
    op.create_index("ix_merchant_policies_merchant_id", "merchant_policies", ["merchant_id"])
    op.create_table("products", sa.Column("id", uuid, primary_key=True), sa.Column("merchant_id", uuid, sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.String(200), nullable=False), sa.Column("description", sa.Text()), sa.Column("category", sa.String(100)), sa.Column("brand", sa.String(100)), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), *timestamps())
    op.create_index("ix_products_merchant_id", "products", ["merchant_id"]); op.create_index("ix_products_category", "products", ["category"])
    op.create_table("product_variants", sa.Column("id", uuid, primary_key=True), sa.Column("product_id", uuid, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False), sa.Column("sku", sa.String(100), nullable=False, unique=True), sa.Column("attributes", postgresql.JSONB(), nullable=False), sa.Column("price", sa.Numeric(12,2), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), *timestamps(), sa.CheckConstraint("price >= 0"))
    op.create_index("ix_product_variants_product_id", "product_variants", ["product_id"]); op.create_index("ix_product_variants_sku", "product_variants", ["sku"])
    op.create_table("inventory", sa.Column("id", uuid, primary_key=True), sa.Column("variant_id", uuid, sa.ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("available_quantity", sa.Integer(), nullable=False, server_default="0"), sa.Column("reserved_quantity", sa.Integer(), nullable=False, server_default="0"), sa.Column("status", sa.String(30), nullable=False, server_default="in_stock"), *timestamps(), sa.CheckConstraint("available_quantity >= 0"), sa.CheckConstraint("reserved_quantity >= 0"))
    op.create_index("ix_inventory_variant_id", "inventory", ["variant_id"])
    op.create_table("users", sa.Column("id", uuid, primary_key=True), sa.Column("merchant_id", uuid, sa.ForeignKey("merchants.id", ondelete="SET NULL")), sa.Column("name", sa.String(160), nullable=False), sa.Column("email", sa.String(255), nullable=False, unique=True), sa.Column("role", sa.String(40), nullable=False, server_default="staff"), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), *timestamps())
    op.create_index("ix_users_merchant_id", "users", ["merchant_id"]); op.create_index("ix_users_email", "users", ["email"])
def downgrade():
    op.drop_table("users"); op.drop_table("inventory"); op.drop_table("product_variants"); op.drop_table("products"); op.drop_table("merchant_policies"); op.drop_table("merchants")
