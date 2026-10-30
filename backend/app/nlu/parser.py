"""`IntentParser` на языковой модели: LLM извлекает смысл, код считает даты."""

import logging

from app.llm.interfaces import LLMClient
from app.nlu.intent_builder import build_intent
from app.nlu.interfaces import DialogContext, Intent
from app.nlu.prompt import build_messages
from app.nlu.schema import EXTRACTION_SCHEMA, Extraction

logger = logging.getLogger(__name__)


class LLMIntentParser:
    """разбор реплики через `LLMClient` по схеме `EXTRACTION_SCHEMA`.

    Модель только относит реплику к действию и переписывает названное (вид дня, время
    как сказано, название); конкретные даты, периоды и правила Q31 считает
    `app.nlu.time_resolution`. Чего не хватает для действия, парсер не решает.
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def parse(self, text: str, context: DialogContext) -> Intent:
        """разбирает реплику; недоступная модель — `DomainError` с кодом `llm_unavailable`."""
        answer = await self._llm.complete_json(build_messages(text, context), EXTRACTION_SCHEMA)
        extraction = Extraction.model_validate(answer)
        logger.debug("Разбор реплики: %s", extraction.model_dump(exclude_defaults=True))
        return build_intent(extraction, text, context)
