"""Eval разбора реплик настоящим GigaChat (решение Q37).

Прогоняет `tests/fixtures/parser_eval.json` через `LLMIntentParser` последовательно
(у физлиц один поток) и считает:
- долю полностью верных разборов — все ожидаемые поля совпали;
- точность по полям: action, event_type, when.date, when.time, period, target, title и др.;
- задержку разбора p50 / p95.
Отдельно — по отложенной проверке (`holdout`): по этим случаям промпт не подгонялся.
Конфигурация как в приложении: основная модель и запасная (`GIGACHAT_FALLBACK_MODEL`) для
пустого или битого ответа; отчёт показывает, сколько раз отвечала запасная.

Запуск из каталога backend/:
    uv run python -m scripts.eval_parser                                  # модель из настроек
    uv run python -m scripts.eval_parser --models GigaChat-2-Pro GigaChat-3-Ultra
    uv run python -m scripts.eval_parser --models GigaChat-2-Pro --show-failures
    uv run python -m scripts.eval_parser --models GigaChat-2-Pro --no-fallback  # без запасной
    uv run python -m scripts.eval_parser --models GigaChat-2-Pro --save-raw raw.json
    uv run python -m scripts.eval_parser --replay raw.json                # пересчёт без сети
"""

import argparse
import asyncio
import datetime as dt
import json
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np

from app.core.enums import EventType, PendingExpectation
from app.core.errors import DomainError
from app.llm.gigachat import ChatTransport, CompletionOptions, GigaChatClient, GigaChatTransport
from app.llm.interfaces import LLMClient, LLMMessage
from app.llm.settings import GigaChatSettings
from app.nlu.interfaces import (
    Action,
    ContextEvent,
    DialogContext,
    DialogTurn,
    Intent,
    Period,
    When,
)
from app.nlu.parser import LLMIntentParser
from app.search.lemmas import MorphLemmatizer, normalize_yo

DESCRIPTION = "Eval разбора реплик настоящим GigaChat"
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "parser_eval.json"
SECONDS_TO_MS = 1000.0
LATENCY_BUDGET_MS = 3000.0
"""Q37: выбираем лучшую точность при задержке не больше 3 с."""

NOTHING_PARSED = Intent(action=Action.UNKNOWN, text="")
"""Заглушка для сбоя модели: по ней получаем имена ожидаемых полей, все — не совпали."""

FIELD_ORDER = (
    "action",
    "event_type",
    "when.date",
    "when.time",
    "when.week_of",
    "period",
    "target",
    "title",
    "query",
    "time_scope",
    "status",
    "choice_index",
    "duration_minutes",
)


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    group: str
    holdout: bool
    text: str
    context: DialogContext
    expected: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: EvalCase
    checks: dict[str, bool]
    latency_ms: float
    intent: Intent | None
    error: str | None = None
    models: tuple[str, ...] = ()
    """Какие модели отвечали на запросы этого случая, по порядку попыток."""

    @property
    def correct(self) -> bool:
        return self.error is None and all(self.checks.values())


@dataclass(slots=True)
class ModelUsage:
    """`ChatTransport`, который запоминает, какая модель отвечала в каждом случае."""

    inner: ChatTransport
    current: list[str] = field(default_factory=list)
    requests: Counter[str] = field(default_factory=Counter)

    async def complete(self, payload: Mapping[str, Any]) -> str:
        model = str(payload.get("model"))
        self.current.append(model)
        self.requests[model] += 1
        return await self.inner.complete(payload)

    async def ping(self) -> None:
        await self.inner.ping()

    async def aclose(self) -> None:
        await self.inner.aclose()

    def finish_case(self) -> tuple[str, ...]:
        """Модели текущего случая; счёт начинается заново."""
        models, self.current = tuple(self.current), []
        return models


@dataclass(slots=True)
class RecordingLLM:
    """Обёртка `LLMClient`: запоминает ответы модели по случаям для `--replay`."""

    inner: LLMClient
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    current_case: str = ""

    async def complete_json(
        self, messages: Sequence[LLMMessage], json_schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        answer = await self.inner.complete_json(messages, json_schema)
        self.answers[self.current_case] = answer
        return answer


@dataclass(slots=True)
class ReplayLLM:
    """Отдаёт сохранённые ответы модели — пересчёт метрик без сети."""

    answers: Mapping[str, dict[str, Any]]
    current_case: str = ""

    async def complete_json(
        self, messages: Sequence[LLMMessage], json_schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        return dict(self.answers[self.current_case])


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--models", nargs="+", help="модели GigaChat; по умолчанию из настроек")
    parser.add_argument("--only", choices=("all", "dev", "holdout"), default="all")
    parser.add_argument("--cases", nargs="+", help="прогнать только эти id случаев")
    parser.add_argument("--show-failures", action="store_true", help="разбор ошибок по случаям")
    parser.add_argument("--save-raw", type=Path, help="сохранить ответы модели в JSON")
    parser.add_argument("--replay", type=Path, help="пересчитать по сохранённым ответам")
    parser.add_argument(
        "--no-fallback", action="store_true", help="без запасной модели (по умолчанию — как в .env)"
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    cases = _select(load_cases(FIXTURE_PATH), args)
    lemmatizer = MorphLemmatizer()
    if args.replay:
        recorded = json.loads(args.replay.read_text(encoding="utf-8"))
        for model, answers in recorded.items():
            results = await _evaluate(ReplayLLM(answers), cases, lemmatizer, usage=None)
            _report(f"{model} (повтор сохранённых ответов)", results, args.show_failures)
        return
    raw: dict[str, dict[str, dict[str, Any]]] = {}
    for model in args.models or [GigaChatSettings().model]:
        settings = GigaChatSettings(model=model)
        if args.no_fallback:
            settings = settings.model_copy(update={"fallback_model": None})
        usage = ModelUsage(GigaChatTransport(settings))
        client = GigaChatClient(usage, CompletionOptions.from_settings(settings))
        recorder = RecordingLLM(client)
        try:
            results = await _evaluate(recorder, cases, lemmatizer, usage)
        finally:
            await client.aclose()
        raw[model] = recorder.answers
        _report(_title(settings), results, args.show_failures)
        _print_model_usage(settings, results, usage)
    if args.save_raw:
        args.save_raw.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")


def _select(cases: list[EvalCase], args: argparse.Namespace) -> list[EvalCase]:
    if args.cases:
        wanted = set(args.cases)
        return [case for case in cases if case.case_id in wanted]
    if args.only == "dev":
        return [case for case in cases if not case.holdout]
    if args.only == "holdout":
        return [case for case in cases if case.holdout]
    return cases


def _title(settings: GigaChatSettings) -> str:
    fallback = settings.fallback_model or "нет"
    return f"{settings.model} (запасная модель: {fallback})"


async def _evaluate(
    llm: RecordingLLM | ReplayLLM,
    cases: Sequence[EvalCase],
    lemmatizer: MorphLemmatizer,
    usage: ModelUsage | None,
) -> list[CaseResult]:
    """Случаи по одному: у физлиц один поток, параллельные запросы получат 429."""
    parser = LLMIntentParser(llm)
    results = []
    for case in cases:
        llm.current_case = case.case_id
        started = time.perf_counter()
        try:
            intent = await parser.parse(case.text, case.context)
        except DomainError as error:
            latency = (time.perf_counter() - started) * SECONDS_TO_MS
            models = usage.finish_case() if usage else ()
            failed = dict.fromkeys(compare(NOTHING_PARSED, case.expected, lemmatizer), False)
            results.append(
                CaseResult(case, failed, latency, None, error=error.message, models=models)
            )
            continue
        latency = (time.perf_counter() - started) * SECONDS_TO_MS
        checks = compare(intent, case.expected, lemmatizer)
        models = usage.finish_case() if usage else ()
        results.append(CaseResult(case, checks, latency, intent, models=models))
    return results


def load_cases(path: Path) -> list[EvalCase]:
    """Случаи eval-набора с контекстами диалога и фиксированным «сейчас»."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    now = dt.datetime.fromisoformat(raw["now"])
    contexts = raw.get("contexts", {})
    return [
        EvalCase(
            case_id=item["id"],
            group=item["group"],
            holdout=item.get("holdout", False),
            text=item["text"],
            context=_context(now, contexts.get(item.get("context", ""), {})),
            expected=item["expected"],
        )
        for item in raw["cases"]
    ]


def _context(now: dt.datetime, raw: Mapping[str, Any]) -> DialogContext:
    pending = raw.get("pending")
    return DialogContext(
        now=now,
        pending=PendingExpectation(pending) if pending else None,
        pending_question=raw.get("pending_question"),
        recent=tuple(
            DialogTurn(role=turn["role"], text=turn["text"]) for turn in raw.get("recent", ())
        ),
        focus=tuple(
            ContextEvent(
                id=event["id"],
                type=EventType(event["type"]),
                title=event["title"],
                starts_at=dt.datetime.fromisoformat(event["starts_at"])
                if event["starts_at"]
                else None,
            )
            for event in raw.get("focus", ())
        ),
    )


def compare(
    intent: Intent, expected: Mapping[str, Any], lemmatizer: MorphLemmatizer
) -> dict[str, bool]:
    """Совпадение каждого ожидаемого поля; поля, которых нет в `expected`, не сравниваются."""
    checks: dict[str, bool] = {}
    for key, value in expected.items():
        match key:
            case "when":
                checks.update(_compare_when(intent.when, value, prefix="when"))
            case "period":
                checks["period"] = _same_period(intent.period, value)
            case "target":
                checks["target"] = _same_target(intent, value, lemmatizer)
            case "title" | "query":
                checks[key] = _same_text(getattr(intent, key), value, lemmatizer)
            case _:
                checks[key] = _plain(getattr(intent, key)) == value
    return checks


def _compare_when(
    actual: When | None, expected: Mapping[str, Any] | None, prefix: str
) -> dict[str, bool]:
    if expected is None:
        return {f"{prefix}.date": actual is None, f"{prefix}.time": actual is None}
    return {
        f"{prefix}.{name}": _matches(_plain(getattr(actual, name) if actual else None), value)
        for name, value in expected.items()
    }


def _matches(actual: object, expected: object) -> bool:
    """Список в `expected` — допустимые варианты: `[null, "2026-10-29"]`."""
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def _same_period(actual: Period | None, expected: Mapping[str, str] | None) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    return (
        f"{actual.start:%Y-%m-%dT%H:%M}" == expected["start"]
        and f"{actual.end:%Y-%m-%dT%H:%M}" == expected["end"]
    )


def _same_target(intent: Intent, expected: Mapping[str, Any], lemmatizer: MorphLemmatizer) -> bool:
    target = intent.target
    if target is None:
        return False
    checks = []
    for name, value in expected.items():
        if name == "query":
            checks.append(_same_text(target.query, value, lemmatizer))
        elif name == "when":
            checks.extend(_compare_when(target.when, value, prefix="target.when").values())
        else:
            checks.append(_plain(getattr(target, name)) == value)
    return all(checks)


def _same_text(actual: str | None, variants: Sequence[str], lemmatizer: MorphLemmatizer) -> bool:
    """Мягкое сравнение: одинаковые наборы лемм (регистр, падежи, «ё» не важны)."""
    if actual is None:
        return False
    actual_key = _text_key(actual, lemmatizer)
    return any(actual_key == _text_key(variant, lemmatizer) for variant in variants)


def _text_key(text: str, lemmatizer: MorphLemmatizer) -> frozenset[str]:
    lemmas = frozenset(lemmatizer.lemmas(text))
    return lemmas or frozenset({normalize_yo(text.lower().strip())})


def _plain(value: object) -> object:
    """Значение поля Intent в виде, как в фикстуре: строки дат и времени, значения enum."""
    if isinstance(value, dt.time):
        return f"{value:%H:%M}"
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


def _report(title: str, results: Sequence[CaseResult], show_failures: bool) -> None:
    print(f"\n=== {title}: {len(results)} случаев ===")
    _print_accuracy("Все", results)
    _print_accuracy("Основные (dev)", [r for r in results if not r.case.holdout])
    _print_accuracy("Отложенные (holdout)", [r for r in results if r.case.holdout])
    _print_fields(results)
    _print_groups(results)
    _print_latency(results)
    if show_failures:
        _print_failures(results)


def _print_model_usage(
    settings: GigaChatSettings, results: Sequence[CaseResult], usage: ModelUsage
) -> None:
    """Сколько запросов ушло каждой модели и в каких случаях отвечала запасная."""
    requests = ", ".join(f"{model} {count}" for model, count in usage.requests.items())
    print(f"Запросов к моделям: {requests}")
    if not settings.fallback_model:
        return
    rescued = [r.case.case_id for r in results if settings.fallback_model in r.models]
    print(f"Запасная модель отвечала в {len(rescued)} из {len(results)} случаев: {rescued}")


def _print_accuracy(title: str, results: Sequence[CaseResult]) -> None:
    if not results:
        return
    correct = sum(result.correct for result in results)
    print(f"{title}: полностью верно {correct}/{len(results)} = {correct / len(results):.3f}")


def _print_fields(results: Sequence[CaseResult]) -> None:
    by_field: defaultdict[str, list[bool]] = defaultdict(list)
    for result in results:
        for name, ok in result.checks.items():
            by_field[name].append(ok)
    known = [name for name in FIELD_ORDER if name in by_field]
    print("Точность по полям:")
    for name in [*known, *sorted(set(by_field) - set(known))]:
        values = by_field[name]
        print(f"  {name:<18} {sum(values) / len(values):.3f} ({sum(values)}/{len(values)})")


def _print_groups(results: Sequence[CaseResult]) -> None:
    by_group: defaultdict[str, list[bool]] = defaultdict(list)
    for result in results:
        by_group[result.case.group].append(result.correct)
    print("По группам (полностью верно):")
    for group, values in by_group.items():
        print(f"  {group:<15} {sum(values)}/{len(values)}")


def _print_latency(results: Sequence[CaseResult]) -> None:
    latencies = [result.latency_ms for result in results]
    p50, p95 = (float(np.percentile(latencies, q)) for q in (50, 95))
    errors = sum(result.error is not None for result in results)
    verdict = "в пределах" if p95 <= LATENCY_BUDGET_MS else "сверх"
    print(
        f"Задержка: p50 {p50:.0f} мс, p95 {p95:.0f} мс, "
        f"среднее {statistics.fmean(latencies):.0f} мс ({verdict} 3 с по p95); "
        f"ошибок модели: {errors}"
    )


def _print_failures(results: Sequence[CaseResult]) -> None:
    print("Ошибки:")
    for result in results:
        if result.correct:
            continue
        mark = " [holdout]" if result.case.holdout else ""
        print(f"  {result.case.case_id}{mark} «{result.case.text}»")
        if result.error is not None:
            print(f"    сбой: {result.error}")
            continue
        wrong = [name for name, ok in result.checks.items() if not ok]
        print(f"    не совпало: {', '.join(wrong)}")
        print(f"    ожидалось: {json.dumps(result.case.expected, ensure_ascii=False)}")
        print(f"    получено:  {_intent_summary(result.intent)}")


def _intent_summary(intent: Intent | None) -> str:
    if intent is None:
        return "—"
    fields = {
        name: _plain(value)
        for name in Intent.__dataclass_fields__
        if name != "text" and (value := getattr(intent, name)) not in (None, "any")
    }
    return repr(fields)


if __name__ == "__main__":
    main()
