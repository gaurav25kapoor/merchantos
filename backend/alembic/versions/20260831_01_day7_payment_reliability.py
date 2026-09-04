"""Add Day 7 payment reliability records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260831_01"
down_revision = "20260830_02"
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade():
    op.add_column("payments", sa.Column("inventory_deducted", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("payment_attempts", sa.Column("provider_payment_id", sa.String(120)))
    op.add_column("payment_attempts", sa.Column("amount", sa.Numeric(12, 2)))
    op.add_column("payment_attempts", sa.Column("amount_minor", sa.Integer()))
    op.add_column("payment_attempts", sa.Column("currency", sa.String(3)))
    op.add_column("payment_attempts", sa.Column("failure_reason", sa.Text()))
    op.add_column("payment_attempts", sa.Column("failure_code", sa.String(80)))
    op.create_index("ix_payment_attempts_provider_payment_id", "payment_attempts", ["provider_payment_id"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("operation", sa.String(120), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="COMPLETED"),
        sa.Column("resource_id", sa.String(120)),
        sa.Column("response_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
        sa.UniqueConstraint("key", "operation", name="uq_idempotency_key_operation"),
    )
    op.create_index("ix_idempotency_records_resource_id", "idempotency_records", ["resource_id"])

    op.create_table(
        "webhook_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False, server_default="razorpay"),
        sa.Column("provider_event_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="PROCESSED"),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_webhook_provider_event"),
    )
    op.create_index("ix_webhook_events_event_type", "webhook_events", ["event_type"])


def downgrade():
    op.drop_index("ix_webhook_events_event_type", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index("ix_idempotency_records_resource_id", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_payment_attempts_provider_payment_id", table_name="payment_attempts")
    op.drop_column("payment_attempts", "failure_code")
    op.drop_column("payment_attempts", "failure_reason")
    op.drop_column("payment_attempts", "currency")
    op.drop_column("payment_attempts", "amount_minor")
    op.drop_column("payment_attempts", "amount")
    op.drop_column("payment_attempts", "provider_payment_id")
    op.drop_column("payments", "inventory_deducted")
