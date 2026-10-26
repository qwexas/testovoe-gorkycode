"""Состояние диалога между репликами (Q23) и его хранение в `dialog_state`.

- `pending` — отложенный шаг: вопрос ассистента и действие, которое ждёт ответа;
- `focus_ids` — записи в фокусе для «её», «эту»: последняя упомянутая — первой,
  при выборе — варианты по порядку;
- `recent` — последние реплики диалога для контекста разбора.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from app.core.dialog.models import Outcome, PendingStep, Reply
from app.core.enums import MessageRole
from app.nlu.interfaces import DialogTurn
from app.storage.models import DialogStateRecord

RECENT_TURNS_LIMIT = 6
FOCUS_LIMIT = 10

logger = logging.getLogger(__name__)

_PENDING = TypeAdapter(PendingStep | None)
_RECENT = TypeAdapter(tuple[DialogTurn, ...])


@dataclass(frozen=True, slots=True)
class DialogState:
    """Что помнит ассистент о разговоре с профилем."""

    pending: PendingStep | None = None
    focus_ids: tuple[int, ...] = ()
    recent: tuple[DialogTurn, ...] = ()

    @classmethod
    def from_record(cls, record: DialogStateRecord | None) -> Self:
        """Состояние из строки таблицы; без строки — пустое.

        Отложенный шаг в старом формате (после обновления приложения) забывается:
        пользователь просто повторит команду.
        """
        if record is None:
            return cls()
        return cls(
            pending=_decode_pending(record.pending),
            focus_ids=tuple(record.last_event_ids),
            recent=_RECENT.validate_python(record.recent),
        )

    def to_record(self, profile_id: UUID) -> DialogStateRecord:
        """Строка таблицы `dialog_state` для профиля."""
        return DialogStateRecord(
            profile_id=profile_id,
            pending=_PENDING.dump_python(self.pending, mode="json"),
            last_event_ids=list(self.focus_ids),
            recent=list(_RECENT.dump_python(self.recent, mode="json")),
        )

    def after_turn(self, user_text: str, outcome: Outcome) -> Self:
        """Состояние после реплики пользователя и ответа ассистента."""
        return type(self)(
            pending=outcome.pending,
            focus_ids=_merged_focus(outcome.focus, self.focus_ids),
            recent=self._with_turns(
                DialogTurn(role=MessageRole.USER.value, text=user_text),
                DialogTurn(role=MessageRole.ASSISTANT.value, text=outcome.reply.text),
            ),
        )

    def after_undo(self, reply: Reply) -> Self:
        """Состояние после отмены действия кнопкой: отложенный вопрос остаётся."""
        return type(self)(
            pending=self.pending,
            focus_ids=_merged_focus([card.id for card in reply.events], self.focus_ids),
            recent=self._with_turns(DialogTurn(role=MessageRole.ASSISTANT.value, text=reply.text)),
        )

    def _with_turns(self, *turns: DialogTurn) -> tuple[DialogTurn, ...]:
        return (*self.recent, *turns)[-RECENT_TURNS_LIMIT:]


def _merged_focus(leading: Sequence[int], previous: Sequence[int]) -> tuple[int, ...]:
    """Новые записи — первыми, затем прежние без повторов."""
    return tuple(dict.fromkeys([*leading, *previous]))[:FOCUS_LIMIT]


def _decode_pending(data: object) -> PendingStep | None:
    if data is None:
        return None
    try:
        return _PENDING.validate_python(data)
    except ValidationError:
        logger.warning("Отложенный шаг диалога в неизвестном формате — забыт", exc_info=True)
        return None
