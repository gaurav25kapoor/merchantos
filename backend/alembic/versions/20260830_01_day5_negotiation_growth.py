"""Add Day 5 negotiation and recommendation records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260830_01"
down_revision = "20260827_02"
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade():
    op.add_column("merchant_policies", sa.Column("negotiation_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "policy_decisions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("merchant_id", uuid, sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", uuid, sa.ForeignKey("agent_sessions.id", ondelete="SET NULL")),
        sa.Column("product_id", uuid, sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("variant_id", uuid, sa.ForeignKey("product_variants.id", ondelete="SET NULL")),
        sa.Column("decision_type", sa.String(80), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("original_price", sa.Numeric(12, 2)),
        sa.Column("offered_price", sa.Numeric(12, 2)),
        sa.Column("approved_price", sa.Numeric(12, 2)),
        sa.Column("counter_offer", sa.Numeric(12, 2)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
    )
    op.create_index("ix_policy_decisions_merchant_id", "policy_decisions", ["merchant_id"])
    op.create_index("ix_policy_decisions_session_id", "policy_decisions", ["session_id"])
    op.create_index("ix_policy_decisions_product_id", "policy_decisions", ["product_id"])
    op.create_index("ix_policy_decisions_variant_id", "policy_decisions", ["variant_id"])

    op.create_table(
        "recommendations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("merchant_id", uuid, sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_product_id", uuid, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommended_product_id", uuid, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommendation_type", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
    )
    op.create_index("ix_recommendations_merchant_id", "recommendations", ["merchant_id"])
    op.create_index("ix_recommendations_source_product_id", "recommendations", ["source_product_id"])
    op.create_index("ix_recommendations_recommended_product_id", "recommendations", ["recommended_product_id"])
    op.create_index("ix_recommendations_recommendation_type", "recommendations", ["recommendation_type"])

    op.create_table(
        "upsell_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("merchant_id", uuid, sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", uuid, sa.ForeignKey("agent_sessions.id", ondelete="SET NULL")),
        sa.Column("source_product_id", uuid, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommended_product_id", uuid, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False, server_default="shown"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
    )
    op.create_index("ix_upsell_events_merchant_id", "upsell_events", ["merchant_id"])
    op.create_index("ix_upsell_events_session_id", "upsell_events", ["session_id"])
    op.create_index("ix_upsell_events_source_product_id", "upsell_events", ["source_product_id"])
    op.create_index("ix_upsell_events_recommended_product_id", "upsell_events", ["recommended_product_id"])


def downgrade():
    op.drop_index("ix_upsell_events_recommended_product_id", table_name="upsell_events")
    op.drop_index("ix_upsell_events_source_product_id", table_name="upsell_events")
    op.drop_index("ix_upsell_events_session_id", table_name="upsell_events")
    op.drop_index("ix_upsell_events_merchant_id", table_name="upsell_events")
    op.drop_table("upsell_events")
    op.drop_index("ix_recommendations_recommendation_type", table_name="recommendations")
    op.drop_index("ix_recommendations_recommended_product_id", table_name="recommendations")
    op.drop_index("ix_recommendations_source_product_id", table_name="recommendations")
    op.drop_index("ix_recommendations_merchant_id", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_policy_decisions_variant_id", table_name="policy_decisions")
    op.drop_index("ix_policy_decisions_product_id", table_name="policy_decisions")
    op.drop_index("ix_policy_decisions_session_id", table_name="policy_decisions")
    op.drop_index("ix_policy_decisions_merchant_id", table_name="policy_decisions")
    op.drop_table("policy_decisions")
    op.drop_column("merchant_policies", "negotiation_enabled")
