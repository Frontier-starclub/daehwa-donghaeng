"""Consent, report access, durable schedules and registration requests.

Revision ID: 20260922_0002
Revises: 20260901_0001
"""

import sqlalchemy as sa

from alembic import op

revision = "20260922_0002"
down_revision = "20260901_0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "chat_reminder_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(
            sa.Column("chat_reminder_at", sa.Time(), nullable=False, server_default="19:00:00")
        )
    with op.batch_alter_table("consents") as batch:
        for name in ("share_medication", "share_mood", "share_language", "onboarding_completed"):
            batch.add_column(
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
            )
    with op.batch_alter_table("medication_schedules") as batch:
        batch.drop_constraint("uq_schedule_medication_time", type_="unique")
        batch.add_column(sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE medication_schedules SET ended_at = updated_at WHERE active = false")
    op.create_table(
        "medication_batch_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("medication_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scan_id"], ["medication_scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_id", name="uq_batch_scan"),
        sa.UniqueConstraint("user_id", "request_id", name="uq_batch_user_request"),
    )
    op.create_table(
        "session_analyses",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        op.f("ix_session_analyses_user_id"), "session_analyses", ["user_id"], unique=False
    )
    op.create_table(
        "consent_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_consent_history_user_id"), "consent_history", ["user_id"], unique=False
    )
    op.create_table(
        "caregiver_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_caregiver_invitations_owner_id"),
        "caregiver_invitations",
        ["owner_id"],
        unique=False,
    )
    op.create_table(
        "caregiver_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("caregiver_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["caregiver_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "caregiver_id", name="uq_caregiver_pair"),
    )
    op.create_index(
        op.f("ix_caregiver_links_caregiver_id"), "caregiver_links", ["caregiver_id"], unique=False
    )
    op.create_index(
        op.f("ix_caregiver_links_owner_id"), "caregiver_links", ["owner_id"], unique=False
    )
    # ### end Alembic commands ###


def downgrade():
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT medication_id FROM medication_schedules "
                "GROUP BY medication_id, remind_at HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicates:
        raise RuntimeError(
            "Downgrade would discard schedule history. Restore a pre-upgrade backup."
        )
    for name in (
        "caregiver_links",
        "caregiver_invitations",
        "consent_history",
        "session_analyses",
        "medication_batch_requests",
    ):
        op.drop_table(name)
    with op.batch_alter_table("medication_schedules") as batch:
        batch.drop_column("ended_at")
        batch.create_unique_constraint(
            "uq_schedule_medication_time", ["medication_id", "remind_at"]
        )
    with op.batch_alter_table("consents") as batch:
        for name in ("share_medication", "share_mood", "share_language", "onboarding_completed"):
            batch.drop_column(name)
    with op.batch_alter_table("users") as batch:
        batch.drop_column("chat_reminder_at")
        batch.drop_column("chat_reminder_enabled")
