"""ответ ассистента в JSON формата контракта `AssistantReply`.

Этот же JSON хранится в `chat_messages.reply`, поэтому история диалога отдаётся
ровно в том виде, в каком ответ пришёл в `POST /api/chat`.
"""

from collections.abc import Sequence

from pydantic import TypeAdapter

from app.core.dialog.models import AssistantAnswer, JsonObject, PendingQuestion, UndoTicket
from app.core.events import EventCard
from app.nlu.interfaces import Period

_EVENT = TypeAdapter(EventCard)
_PENDING = TypeAdapter(PendingQuestion | None)
_UNDO = TypeAdapter(UndoTicket | None)


def answer_payload(answer: AssistantAnswer) -> JsonObject:
    """полный ответ ассистента в формате контракта."""
    reply = answer.reply
    return {
        "message_id": answer.message_id,
        "kind": reply.kind.value,
        "text": reply.text,
        "recognized_text": answer.recognized_text,
        "events": _events(reply.events),
        "period": None if reply.period is None else _period(reply.period),
        "choices": [
            {"index": index, "event": _EVENT.dump_python(card, mode="json")}
            for index, card in enumerate(reply.choices, start=1)
        ],
        "conflicts": _events(reply.conflicts),
        "pending": _PENDING.dump_python(reply.pending, mode="json"),
        "undo": _UNDO.dump_python(reply.undo, mode="json"),
    }


def _events(cards: Sequence[EventCard]) -> list[JsonObject]:
    return [_EVENT.dump_python(card, mode="json") for card in cards]


def _period(period: Period) -> JsonObject:
    return {
        "from": period.start.isoformat(),
        "to": period.end.isoformat(),
        "label": period.label,
    }
