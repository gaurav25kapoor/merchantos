"""Add Day 3 catalog search indexes."""

from alembic import op


revision = "20260827_01"
down_revision = "20260825_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_products_is_active", "products", ["is_active"])
    op.create_index("ix_product_variants_price", "product_variants", ["price"])
    op.create_index("ix_product_variants_is_active", "product_variants", ["is_active"])
    op.create_index("ix_inventory_available_quantity", "inventory", ["available_quantity"])


def downgrade():
    op.drop_index("ix_inventory_available_quantity", table_name="inventory")
    op.drop_index("ix_product_variants_is_active", table_name="product_variants")
    op.drop_index("ix_product_variants_price", table_name="product_variants")
    op.drop_index("ix_products_is_active", table_name="products")
