"""Поиск по записям и общая история из CSV.

У записей появляются вектор названия (`embedding`) и его леммы (`lemmas`, GIN-индекс
для `&&`). Таблица `seed_events` хранит 1000 записей истории из CSV с готовыми
векторами — новый профиль копирует их одним `INSERT … SELECT` (решение Q22).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25 23:00:00+03:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSION = 1024
EMPTY_TEXT_ARRAY = sa.text("'{}'::text[]")


def upgrade() -> None:
    op.add_column("events", sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "lemmas", postgresql.ARRAY(sa.Text()), server_default=EMPTY_TEXT_ARRAY, nullable=False
        ),
    )
    op.create_index("ix_events_lemmas", "events", ["lemmas"], postgresql_using="gin")

    op.create_table(
        "seed_events",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("has_time", sa.Boolean(), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
        sa.Column("lemmas", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seed_events")),
        sa.CheckConstraint(
            "type IN ('task', 'reminder', 'meeting')", name=op.f("ck_seed_events_event_type")
        ),
    )


def downgrade() -> None:
    op.drop_table("seed_events")
    op.drop_index("ix_events_lemmas", table_name="events")
    op.drop_column("events", "lemmas")
    op.drop_column("events", "embedding")
