"""Начальная схема: профили, сессии, записи, диалог, отмена действий.

Revision ID: 0001
Revises:
Create Date: 2026-10-25 22:00:00+03:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CASCADE = "CASCADE"


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _updated_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _profile_id() -> sa.Column[sa.Uuid]:
    return sa.Column("profile_id", sa.Uuid(), nullable=False)


def _profile_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["profile_id"],
        ["profiles.id"],
        name=op.f(f"fk_{table}_profile_id_profiles"),
        ondelete=CASCADE,
    )


def upgrade() -> None:
    # Векторы эмбеддингов появятся на КТ2, когда будет выбрана модель и её размерность.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recovery_code_digest", sa.String(length=64), nullable=False),
        sa.Column("calendar_token", sa.String(length=64), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
        sa.UniqueConstraint("recovery_code_digest", name=op.f("uq_profiles_recovery_code_digest")),
        sa.UniqueConstraint("calendar_token", name=op.f("uq_profiles_calendar_token")),
    )

    op.create_table(
        "profile_sessions",
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        _profile_id(),
        _created_at(),
        sa.PrimaryKeyConstraint("token_digest", name=op.f("pk_profile_sessions")),
        _profile_fk("profile_sessions"),
    )
    op.create_index(op.f("ix_profile_sessions_profile_id"), "profile_sessions", ["profile_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        _profile_id(),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("has_time", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("source", sa.String(length=16), server_default="user", nullable=False),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        _profile_fk("events"),
        sa.CheckConstraint(
            "type IN ('task', 'reminder', 'meeting')", name=op.f("ck_events_event_type")
        ),
        sa.CheckConstraint("status IN ('open', 'done')", name=op.f("ck_events_event_status")),
        sa.CheckConstraint("source IN ('user', 'import')", name=op.f("ck_events_event_source")),
    )
    op.create_index("ix_events_profile_id_starts_at", "events", ["profile_id", "starts_at"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        _profile_id(),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("reply", postgresql.JSONB(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        _profile_fk("chat_messages"),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name=op.f("ck_chat_messages_message_role")
        ),
    )
    op.create_index("ix_chat_messages_profile_id_id", "chat_messages", ["profile_id", "id"])

    op.create_table(
        "dialog_state",
        _profile_id(),
        sa.Column("pending", postgresql.JSONB(), nullable=True),
        sa.Column(
            "last_event_ids",
            postgresql.ARRAY(sa.BigInteger()),
            server_default=sa.text("'{}'::bigint[]"),
            nullable=False,
        ),
        sa.Column(
            "recent", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        _updated_at(),
        sa.PrimaryKeyConstraint("profile_id", name=op.f("pk_dialog_state")),
        _profile_fk("dialog_state"),
    )

    op.create_table(
        "undo_actions",
        sa.Column("action_id", sa.String(length=64), nullable=False),
        _profile_id(),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("action_id", name=op.f("pk_undo_actions")),
        _profile_fk("undo_actions"),
    )
    op.create_index(op.f("ix_undo_actions_profile_id"), "undo_actions", ["profile_id"])
    op.create_index(op.f("ix_undo_actions_expires_at"), "undo_actions", ["expires_at"])


def downgrade() -> None:
    # Расширение vector не удаляем: им могут пользоваться другие схемы этой базы.
    for table in (
        "undo_actions",
        "dialog_state",
        "chat_messages",
        "events",
        "profile_sessions",
        "profiles",
    ):
        op.drop_table(table)
