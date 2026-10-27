"""Таблицы PostgreSQL (SQLAlchemy 2, декларативные модели).

Схема меняется только миграциями Alembic (`migrations/versions`); `alembic check`
сверяет миграции с этими моделями.
"""

from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, ClassVar
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.enums import EventSource, EventStatus, EventType, MessageRole
from app.search.interfaces import EMBEDDING_DIMENSION

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

DIGEST_LENGTH = 64
TOKEN_LENGTH = 64

JsonObject = dict[str, Any]
CreatedAt = Annotated[datetime, mapped_column(server_default=func.now())]
UpdatedAt = Annotated[datetime, mapped_column(server_default=func.now(), onupdate=func.now())]
ProfileId = Annotated[UUID, mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))]


class Base(DeclarativeBase):
    """Общая база моделей: соглашение об именах ограничений и время с часовым поясом."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: DateTime(timezone=True)}


def _string_enum(enum_class: type[StrEnum], name: str) -> Enum:
    """Строковая колонка с CHECK-ограничением по значениям перечисления."""
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda members: [member.value for member in members],
    )


class ProfileRecord(Base):
    """Анонимный профиль: отпечаток кода восстановления и токен подписки на календарь."""

    __tablename__ = "profiles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recovery_code_digest: Mapped[str] = mapped_column(String(DIGEST_LENGTH), unique=True)
    calendar_token: Mapped[str] = mapped_column(String(TOKEN_LENGTH), unique=True)
    created_at: Mapped[CreatedAt]


class ProfileSessionRecord(Base):
    """Сессия устройства: SHA-256 токена из cookie. У профиля может быть несколько устройств."""

    __tablename__ = "profile_sessions"

    token_digest: Mapped[str] = mapped_column(String(DIGEST_LENGTH), primary_key=True)
    profile_id: Mapped[ProfileId] = mapped_column(index=True)
    created_at: Mapped[CreatedAt]


class EventRecord(Base):
    """Задача, напоминание или встреча.

    `embedding` и `lemmas` — поисковый индекс названия; загружаются только по явному
    запросу (`deferred`), списку записей они не нужны. Запись истории из CSV хранит
    ссылку `seed_event_id`, а индекс берёт из `seed_events`, пока у неё нет своего
    (`embedding IS NULL`); своё значение появляется, когда пользователь меняет название.
    """

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_profile_id_starts_at", "profile_id", "starts_at"),
        Index("ix_events_lemmas", "lemmas", postgresql_using="gin"),
    )
    __mapper_args__ = MappingProxyType({"eager_defaults": True})

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    profile_id: Mapped[ProfileId]
    type: Mapped[EventType] = mapped_column(_string_enum(EventType, "event_type"))
    title: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime | None]
    has_time: Mapped[bool] = mapped_column(server_default=text("false"))
    ends_at: Mapped[datetime | None]
    status: Mapped[EventStatus] = mapped_column(
        _string_enum(EventStatus, "event_status"), server_default=EventStatus.OPEN.value
    )
    source: Mapped[EventSource] = mapped_column(
        _string_enum(EventSource, "event_source"), server_default=EventSource.USER.value
    )
    seed_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("seed_events.id", ondelete="SET NULL"), index=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSION), deferred=True
    )
    lemmas: Mapped[list[str] | None] = mapped_column(ARRAY(Text), deferred=True)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class SeedEventRecord(Base):
    """Запись истории из CSV (Q22): общая заготовка, которую получает каждый новый профиль.

    `id` — номер строки в CSV. Вектор и леммы считаются один раз при старте приложения
    и общие для всех профилей: в записи профиля копируются только поля записи.
    """

    __tablename__ = "seed_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    type: Mapped[EventType] = mapped_column(_string_enum(EventType, "event_type"))
    title: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime]
    has_time: Mapped[bool]
    ends_at: Mapped[datetime | None]
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION))
    lemmas: Mapped[list[str]] = mapped_column(ARRAY(Text))


class ChatMessageRecord(Base):
    """Реплика истории диалога; у ответов ассистента — полный `AssistantReply` в `reply`."""

    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_profile_id_id", "profile_id", "id"),)
    __mapper_args__ = MappingProxyType({"eager_defaults": True})

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    profile_id: Mapped[ProfileId]
    role: Mapped[MessageRole] = mapped_column(_string_enum(MessageRole, "message_role"))
    text: Mapped[str] = mapped_column(Text)
    reply: Mapped[JsonObject | None] = mapped_column(JSONB)
    created_at: Mapped[CreatedAt]


class DialogStateRecord(Base):
    """Состояние диалога (Q23): чего ждёт ассистент, записи в фокусе, последние реплики.

    `pending` — отложенный шаг диалога, `last_event_ids` — записи в фокусе (последняя
    упомянутая первой), `focus_peers` — сколько первых из них пришли одним ответом-списком
    (тогда «её» неоднозначно), `recent` — последние реплики; формат задаёт
    `app.core.dialog.state`.
    """

    __tablename__ = "dialog_state"

    profile_id: Mapped[ProfileId] = mapped_column(primary_key=True)
    pending: Mapped[JsonObject | None] = mapped_column(JSONB)
    last_event_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), server_default=text("'{}'::bigint[]")
    )
    focus_peers: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    recent: Mapped[list[JsonObject]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    updated_at: Mapped[UpdatedAt]


class UndoActionRecord(Base):
    """Действие, которое можно отменить в течение короткого окна."""

    __tablename__ = "undo_actions"

    action_id: Mapped[str] = mapped_column(String(TOKEN_LENGTH), primary_key=True)
    profile_id: Mapped[ProfileId] = mapped_column(index=True)
    payload: Mapped[JsonObject] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[CreatedAt]
