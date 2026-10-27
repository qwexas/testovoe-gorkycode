"""Прогрев моделей речи при старте: в фоне, только у моделей, где он есть."""

import asyncio

from app.factory import _warm_up_in_background


class WarmableModel:
    def __init__(self) -> None:
        self.warmed = False

    async def warm_up(self) -> None:
        self.warmed = True


class StubWithoutWarmUp:
    pass


async def test_models_with_warm_up_are_warmed_in_background() -> None:
    model = WarmableModel()

    tasks = _warm_up_in_background(model, StubWithoutWarmUp())
    await asyncio.gather(*tasks)

    assert len(tasks) == 1
    assert model.warmed


async def test_nothing_to_warm_gives_no_tasks() -> None:
    assert _warm_up_in_background(StubWithoutWarmUp()) == []
