"""Add Day 4 agent session and tool-call logging."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260827_02"
down_revision = "20260827_01"
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
        "agent_sessions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("merchant_id", uuid, sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
    )
    op.create_index("ix_agent_sessions_merchant_id", "agent_sessions", ["merchant_id"])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("session_id", uuid, sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("merchant_id", uuid, sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("tool_input", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("tool_output", postgresql.JSONB()),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error", sa.Text()),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(),
    )
    op.create_index("ix_agent_tool_calls_session_id", "agent_tool_calls", ["session_id"])
    op.create_index("ix_agent_tool_calls_merchant_id", "agent_tool_calls", ["merchant_id"])
    op.create_index("ix_agent_tool_calls_tool_name", "agent_tool_calls", ["tool_name"])


def downgrade():
    op.drop_index("ix_agent_tool_calls_tool_name", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_merchant_id", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_session_id", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_agent_sessions_merchant_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")
