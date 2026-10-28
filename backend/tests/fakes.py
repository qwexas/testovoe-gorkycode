from uuid import UUID


class FakeProfiles:
    async def lock(self, profile_id: UUID) -> None:
        """В модульных тестах блокировка не требуется."""
        pass
