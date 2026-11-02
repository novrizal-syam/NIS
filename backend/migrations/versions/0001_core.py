"""core: doc_counters and audit_log

Revision ID: 0001_core
Revises:
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "doc_counters",
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("doc_type", "year", name=op.f("pk_doc_counters")),
    )
    op.create_table(
        "audit_log",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("changed", postgresql.JSONB(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("ix_audit_log_actor_at", "audit_log", ["actor_id", "at"])
    # The audit log is append-only: block UPDATE and DELETE at the database level.
    op.execute(
        """
        CREATE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable();")
    op.drop_index("ix_audit_log_actor_at", table_name="audit_log")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("doc_counters")
