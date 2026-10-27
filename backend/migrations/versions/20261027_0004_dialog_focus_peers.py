"""Состояние диалога помнит, сколько записей в фокусе пришли одним ответом-списком.

После «Что у меня сегодня?» с двумя напоминаниями «отметь её» неоднозначно: ассистент
переспрашивает «Какое…?». После создания или выбора одной записи «её» — она.
Колонка с постоянным значением по умолчанию добавляется без переписывания таблицы.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27 12:00:00+03:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dialog_state",
        sa.Column("focus_peers", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("dialog_state", "focus_peers")
