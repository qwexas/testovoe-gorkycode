"""Eval-набор разбора (решение Q37): полнота и согласованность без сети."""

import datetime as dt
import json
from dataclasses import replace

import pytest

from app.core.enums import EventType
from app.core.schedule import MOSCOW
from app.nlu.interfaces import Action, Intent, Period, TargetRef, When
from app.search.lemmas import MorphLemmatizer
from scripts.eval_parser import FIXTURE_PATH, compare, load_cases

MIN_CASES = 70
MIN_HOLDOUT_SHARE = 0.2

TZ_PHRASES = (
    "Напомни мне завтра в 10 утра позвонить Ивану",
    "В пятницу нужно отправить отчет",
    "Поставь задачу купить билеты до конца недели",
    "Добавь встречу с командой завтра в 15:00",
    "В четверг в 11 у меня встреча с дизайнером",
    "Что у меня сегодня?",
    "Есть ли у меня встречи сегодня?",
    "Какие задачи у меня на завтра?",
    "Что запланировано на эту неделю?",
    "Найди задачу про презентацию",
    "Когда у меня была встреча с Иваном?",
    "Я когда-то ставил задачу по договору, найди ее",
    "Какие планы на сегодня?",
    "Покажи мои встречи на сегодня",
    "Поставь встречу с Иваном завтра",
)
"""Все фразы-примеры из ТЗ дословно."""
TZ_RELATIVE_DATES = ("сегодня", "завтра", "послезавтра", "в пятницу", "через два часа")
TZ_NEXT_WEEK = "на следующей неделе"


@pytest.fixture(scope="module")
def lemmatizer() -> MorphLemmatizer:
    return MorphLemmatizer()


def test_fixture_is_big_enough_and_has_unique_ids() -> None:
    cases = load_cases(FIXTURE_PATH)
    ids = [case.case_id for case in cases]

    assert len(cases) >= MIN_CASES
    assert len(ids) == len(set(ids))


def test_every_tz_phrase_is_in_the_set_verbatim() -> None:
    texts = {case.text for case in load_cases(FIXTURE_PATH)}

    assert set(TZ_PHRASES) <= texts


def test_every_relative_date_from_tz_is_covered() -> None:
    texts = " ".join(case.text.lower() for case in load_cases(FIXTURE_PATH))

    for phrase in (*TZ_RELATIVE_DATES, TZ_NEXT_WEEK):
        assert phrase in texts


def test_part_of_set_is_held_out() -> None:
    cases = load_cases(FIXTURE_PATH)
    held_out = [case for case in cases if case.holdout]

    assert len(held_out) / len(cases) >= MIN_HOLDOUT_SHARE
    assert not any(case.holdout and case.group == "tz" for case in cases)


def test_referenced_contexts_exist() -> None:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for item in raw["cases"]:
        if "context" in item:
            assert item["context"] in raw["contexts"], item["id"]


def test_expected_actions_are_known() -> None:
    for case in load_cases(FIXTURE_PATH):
        Action(case.expected["action"])


def test_compare_accepts_matching_intent(lemmatizer: MorphLemmatizer) -> None:
    [case] = [c for c in load_cases(FIXTURE_PATH) if c.case_id == "tz-01"]
    intent = Intent(
        action=Action.CREATE,
        text=case.text,
        event_type=EventType.REMINDER,
        title="Позвонить Ивану",
        when=When(date=dt.date(2026, 10, 28), time=dt.time(10, 0)),
    )

    assert all(compare(intent, case.expected, lemmatizer).values())


def test_compare_catches_invented_time(lemmatizer: MorphLemmatizer) -> None:
    [case] = [c for c in load_cases(FIXTURE_PATH) if c.case_id == "tz-15"]
    intent = Intent(
        action=Action.CREATE,
        text=case.text,
        event_type=EventType.MEETING,
        title="Встреча с Иваном",
        when=When(date=dt.date(2026, 10, 28), time=dt.time(10, 0)),
    )

    assert compare(intent, case.expected, lemmatizer) == {
        "action": True,
        "event_type": True,
        "title": True,
        "when.date": True,
        "when.time": False,
    }


def test_compare_titles_softly_by_lemmas(lemmatizer: MorphLemmatizer) -> None:
    expected = {"action": "create", "title": ["Отправить отчет"]}

    for title, ok in (("отправить отчёт", True), ("Отправить отчёты", True), ("Отчёт", False)):
        intent = Intent(action=Action.CREATE, text="", title=title)
        assert compare(intent, expected, lemmatizer)["title"] is ok


def test_compare_period_and_target(lemmatizer: MorphLemmatizer) -> None:
    expected = {
        "action": "list",
        "period": {"start": "2026-10-27T00:00", "end": "2026-10-28T00:00"},
        "target": {"last": False, "query": ["встреча с Иваном"]},
    }
    intent = Intent(
        action=Action.LIST,
        text="",
        period=Period(
            start=dt.datetime(2026, 10, 27, tzinfo=MOSCOW),
            end=dt.datetime(2026, 10, 28, tzinfo=MOSCOW),
            label="сегодня",
        ),
        target=TargetRef(last=False, query="встречу с Иваном"),
    )

    assert compare(intent, expected, lemmatizer) == {"action": True, "period": True, "target": True}


def test_compare_accepts_any_listed_variant(lemmatizer: MorphLemmatizer) -> None:
    expected = {"action": "reschedule", "when": {"date": [None, "2026-10-29"], "time": "17:00"}}

    for date, ok in ((None, True), (dt.date(2026, 10, 29), True), (dt.date(2026, 10, 27), False)):
        intent = Intent(action=Action.RESCHEDULE, text="", when=When(date=date, time=dt.time(17)))
        assert compare(intent, expected, lemmatizer)["when.date"] is ok


def test_compare_old_and_new_moment_and_unhandled(lemmatizer: MorphLemmatizer) -> None:
    """F11: прежние и новые день и время переноса и остальные команды реплики."""
    cases = {case.case_id: case for case in load_cases(FIXTURE_PATH)}
    moved = Intent(
        action=Action.RESCHEDULE,
        text=cases["mod-09"].text,
        target=TargetRef(
            last=False,
            event_type=EventType.MEETING,
            when=When(date=dt.date(2026, 10, 28), time=dt.time(10, 0)),
        ),
        when=When(date=dt.date(2026, 10, 30), time=dt.time(12, 0)),
    )
    split = Intent(
        action=Action.RESCHEDULE,
        text=cases["multi-01"].text,
        target=TargetRef(last=False, query="планёрка"),
        when=When(time=dt.time(11, 0)),
        unhandled="удали встречу с Петром",
    )
    lost = replace(split, unhandled=None)

    assert all(compare(moved, cases["mod-09"].expected, lemmatizer).values())
    assert all(compare(split, cases["multi-01"].expected, lemmatizer).values())
    assert not compare(lost, cases["multi-01"].expected, lemmatizer)["unhandled"]
