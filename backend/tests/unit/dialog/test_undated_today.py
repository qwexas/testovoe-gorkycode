from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.dialog.lookup import ListingFlow, today_period
from app.nlu.interfaces import Period

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone(timedelta(hours=3)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("period_name", "offset_days", "duration_days", "expected"),
    [
        ("today", 0, 1, True),
        ("tomorrow", 1, 1, False),
        ("yesterday", -1, 1, False),
        ("week", -2, 7, False),
    ],
)
async def test_undated_tasks_only_in_today_summary(
    period_name: str,
    offset_days: int,
    duration_days: int,
    expected: bool,
) -> None:
    today = today_period(NOW)

    period = (
        today
        if period_name == "today"
        else Period(
            start=today.start + timedelta(days=offset_days),
            end=today.start + timedelta(days=offset_days + duration_days),
            label=period_name,
        )
    )

    reader = SimpleNamespace(list_events=AsyncMock(return_value=[]))

    turn = SimpleNamespace(
        profile_id=uuid4(),
        now=NOW,
    )

    intent = SimpleNamespace(
        period=period,
        event_type=None,
        status=None,
    )

    flow = ListingFlow(reader)
    await flow.run(turn, intent)

    reader.list_events.assert_awaited_once()

    criteria = reader.list_events.await_args.args[0]

    assert criteria.include_undated is expected
