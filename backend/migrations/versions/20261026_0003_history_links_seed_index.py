"""История профиля ссылается на общий поисковый индекс `seed_events`.

Записи истории больше не копируют вектор (≈5,8 МБ на профиль): у них `seed_event_id`,
а `embedding` и `lemmas` пусты, пока пользователь не сменит название. Поэтому
`lemmas` становится nullable. Записи, импортированные до этой миграции, сохраняют
собственный индекс и ищутся по нему.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26 01:00:00+03:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPTY_TEXT_ARRAY = sa.text("'{}'::text[]")


def upgrade() -> None:
    op.add_column("events", sa.Column("seed_event_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_events_seed_event_id_seed_events"),
        "events",
        "seed_events",
        ["seed_event_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_events_seed_event_id"), "events", ["seed_event_id"])
    op.alter_column(
        "events",
        "lemmas",
        existing_type=postgresql.ARRAY(sa.Text()),
        nullable=True,
        server_default=None,
        existing_server_default=EMPTY_TEXT_ARRAY,
    )


def downgrade() -> None:
    # Возвращаем записям истории собственный индекс из заготовки: в 0002 он обязателен.
    op.execute(
        "UPDATE events SET embedding = seed.embedding, lemmas = seed.lemmas "
        "FROM seed_events AS seed "
        "WHERE events.seed_event_id = seed.id AND events.embedding IS NULL"
    )
    op.execute("UPDATE events SET lemmas = '{}' WHERE lemmas IS NULL")
    op.alter_column(
        "events",
        "lemmas",
        existing_type=postgresql.ARRAY(sa.Text()),
        nullable=False,
        server_default=EMPTY_TEXT_ARRAY,
    )
    op.drop_index(op.f("ix_events_seed_event_id"), table_name="events")
    op.drop_constraint(op.f("fk_events_seed_event_id_seed_events"), "events", type_="foreignkey")
    op.drop_column("events", "seed_event_id")
