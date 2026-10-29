import asyncio
from uuid import uuid4

import pytest

from app.core.admission import (
    DialogAdmission,
    InFlightLimit,
    ProfileTurns,
    ServiceBusyError,
    SpeechAdmission,
    TurnInProgressError,
)


def test_in_flight_limit_rejects_over_limit_and_frees_slot() -> None:
    limit = InFlightLimit(1)
    with limit.hold("a"):
        with pytest.raises(ServiceBusyError), limit.hold("a"):
            pass
        with limit.hold("b"):
            pass
    with limit.hold("a"):
        pass


@pytest.mark.asyncio
async def test_profile_turns_run_one_after_another() -> None:
    turns = ProfileTurns()
    profile = uuid4()
    order: list[str] = []
    release = asyncio.Event()

    async def first() -> None:
        async with turns.turn(profile):
            order.append("first-in")
            await release.wait()
            order.append("first-out")

    async def second() -> None:
        async with turns.turn(profile):
            order.append("second-in")

    a = asyncio.create_task(first())
    await asyncio.sleep(0)
    b = asyncio.create_task(second())
    await asyncio.sleep(0.01)
    assert order == ["first-in"]
    release.set()
    await asyncio.gather(a, b)
    assert order == ["first-in", "first-out", "second-in"]


@pytest.mark.asyncio
async def test_profile_turns_reject_third_waiting_turn() -> None:
    turns = ProfileTurns(max_members=2)
    profile = uuid4()
    release = asyncio.Event()

    async def hold() -> None:
        async with turns.turn(profile):
            await release.wait()

    tasks = [asyncio.create_task(hold()), asyncio.create_task(hold())]
    await asyncio.sleep(0.01)
    with pytest.raises(TurnInProgressError):
        async with turns.turn(profile):
            pass
    async with turns.turn(uuid4()):
        pass  # другой профиль не ждёт
    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_profile_turn_wait_respects_deadline() -> None:
    turns = ProfileTurns()
    profile = uuid4()
    release = asyncio.Event()

    async def hold() -> None:
        async with turns.turn(profile):
            await release.wait()

    task = asyncio.create_task(hold())
    await asyncio.sleep(0)
    deadline = asyncio.get_running_loop().time() + 0.05
    with pytest.raises(TimeoutError):
        async with turns.turn(profile, deadline):
            pass
    release.set()
    await task
    async with turns.turn(profile):
        pass  # очередь не застряла после таймаута


@pytest.mark.asyncio
async def test_dialog_admission_limits_one_client_across_profiles() -> None:
    admission = DialogAdmission(overall=10, per_client=2)
    release = asyncio.Event()

    async def hold() -> None:
        async with admission.enter(uuid4(), "1.2.3.4"):
            await release.wait()

    tasks = [asyncio.create_task(hold()) for _ in range(2)]
    await asyncio.sleep(0.01)
    with pytest.raises(ServiceBusyError):
        async with admission.enter(uuid4(), "1.2.3.4"):
            pass
    async with admission.enter(uuid4(), "5.6.7.8"):
        pass
    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_dialog_admission_overall_limit() -> None:
    admission = DialogAdmission(overall=1, per_client=5)
    release = asyncio.Event()

    async def hold() -> None:
        async with admission.enter(uuid4(), "a"):
            await release.wait()

    task = asyncio.create_task(hold())
    await asyncio.sleep(0.01)
    with pytest.raises(ServiceBusyError):
        async with admission.enter(uuid4(), "b"):
            pass
    release.set()
    await task


@pytest.mark.asyncio
async def test_dialog_admission_rate_per_client() -> None:
    admission = DialogAdmission(client_rate=2)
    for _ in range(2):
        async with admission.enter(uuid4(), "a"):
            pass
    with pytest.raises(ServiceBusyError):
        async with admission.enter(uuid4(), "a"):
            pass


def test_speech_admission_limits_client() -> None:
    admission = SpeechAdmission(per_client=1)
    with admission.enter("a"):
        with pytest.raises(ServiceBusyError), admission.enter("a"):
            pass
        with admission.enter("b"):
            pass
