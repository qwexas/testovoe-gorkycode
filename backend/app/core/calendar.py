"""Экспорт записей профиля в iCalendar (RFC 5545): файл `.ics` и подписка `webcal://` (Q27).

В календарь попадают открытые записи с датой, начиная с сегодняшнего дня по Москве.
Выполненные, прошедшие и задачи «без срока» — нет. Предупреждения `VALARM` — это
«телефон напомнит сам» (Q32г):

| Запись | Событие | Предупреждение |
|---|---|---|
| встреча | от начала до конца | за 15 минут |
| напоминание, задача со временем | 15 минут с момента | в момент начала |
| задача только с датой | на весь день | в 09:00 этого дня («утром», Q31) |

Время событий — с `TZID=Europe/Moscow` и описанием пояса `VTIMEZONE`: запись стоит
в московском времени (Q9) в любом клиенте, а Google, Apple и Яндекс узнают пояс по
стандартному имени из базы IANA. Служебные отметки (`DTSTAMP`, `CREATED`,
`LAST-MODIFIED`) — в UTC, как требует RFC 5545.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from icalendar import Alarm, Calendar, Event, Timezone, vDuration

from app.core.enums import EventStatus, EventType
from app.core.errors import CalendarNotFoundError, TooManyCalendarRequestsError
from app.core.events import EventCard
from app.core.queries import EventFilter
from app.core.rate_limit import Throttle
from app.core.schedule import (
    DEFAULT_MEETING_DURATION,
    MOSCOW,
    PROFILE_TIMEZONE,
    moscow_now,
    start_of_day,
)
from app.storage.database import UnitOfWork

CALENDAR_NAME = "Горький"
PRODUCT_ID = "-//GORKYCODE//Gorky voice assistant//RU"
UID_DOMAIN = "voice.wexasas.online"
"""Пространство имён `UID`: постоянное, чтобы клиент узнавал событие при каждом обновлении."""

MEETING_ALERT_LEAD = timedelta(minutes=15)
MOMENT_DURATION = timedelta(minutes=15)
"""Длительность напоминания и задачи со временем: видно в сетке дня, но не «занимает» день."""
AT_START = timedelta(0)
ALL_DAY_ALERT_OFFSET = timedelta(hours=9)
"""Предупреждение задачи на весь день — в 09:00 её дня («утром» по Q31)."""
ONE_DAY = timedelta(days=1)
REFRESH_INTERVAL = timedelta(minutes=15)
"""Как часто клиенту перечитывать подписку (подсказка, клиенты могут реже)."""
EXPORT_LIMIT = 5000
"""Предел записей в файле: история из CSV и записи пользователя помещаются с запасом."""

SUBSCRIPTION_REQUESTS_PER_WINDOW = 60
SUBSCRIPTION_WINDOW_SECONDS = 60

TYPE_LABELS = {
    EventType.TASK: "Задача",
    EventType.REMINDER: "Напоминание",
    EventType.MEETING: "Встреча",
}

Clock = Callable[[], datetime]


class SubscriptionThrottle(Throttle):
    """Не больше `SUBSCRIPTION_REQUESTS_PER_WINDOW` запросов подписки в минуту с одного IP.

    Клиенты календарей перечитывают ссылку раз в 15 минут или реже; запас оставлен
    для сервисов вроде Google Календаря, которые забирают подписки многих людей
    с общих адресов.
    """

    max_hits = SUBSCRIPTION_REQUESTS_PER_WINDOW
    window_seconds = SUBSCRIPTION_WINDOW_SECONDS
    rejection = TooManyCalendarRequestsError


class CalendarExport:
    """Календарь профиля: для кнопки «Скачать .ics» и по секретной ссылке подписки."""

    def __init__(
        self, storage: UnitOfWork, throttle: SubscriptionThrottle, clock: Clock = moscow_now
    ) -> None:
        self._storage = storage
        self._throttle = throttle
        self._clock = clock

    async def for_profile(self, profile_id: UUID) -> bytes:
        """Календарь профиля в формате iCalendar."""
        now = self._clock()
        criteria = EventFilter(
            profile_id=profile_id, period_start=start_of_day(now), status=EventStatus.OPEN
        )
        records = await self._storage.events.list_matching(criteria, EXPORT_LIMIT)
        return render_calendar((EventCard.from_record(record) for record in records), now)

    async def for_subscription(self, token: str, requester: str) -> bytes:
        """Календарь по токену ссылки подписки. Профиль здесь никогда не создаётся.

        Raises:
            TooManyCalendarRequestsError: С адреса `requester` слишком много запросов.
            CalendarNotFoundError: Профиля с таким токеном нет.
        """
        self._throttle.admit(requester)
        profile = await self._storage.profiles.get_by_calendar_token(token)
        if profile is None:
            raise CalendarNotFoundError()
        return await self.for_profile(profile.id)


def render_calendar(cards: Iterable[EventCard], generated_at: datetime) -> bytes:
    """Календарь iCalendar из записей; записи без даты пропускаются, время — по Москве."""
    calendar = _empty_calendar(generated_at.date())
    stamp = generated_at.astimezone(UTC)
    for card in cards:
        if card.starts_at is not None:
            calendar.add_component(_event(card, card.starts_at.astimezone(MOSCOW), stamp))
    content: bytes = calendar.to_ical()
    return content


@dataclass(frozen=True, slots=True)
class _Slot:
    """Когда событие стоит в календаре и когда о нём предупредить (сдвиг от начала)."""

    start: date | datetime
    end: date | datetime
    alert_offset: timedelta
    busy: bool


def _empty_calendar(today: date) -> Calendar:
    calendar = Calendar()
    calendar.add("prodid", PRODUCT_ID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", CALENDAR_NAME)
    calendar.add("x-wr-timezone", PROFILE_TIMEZONE)
    calendar.add("refresh-interval", REFRESH_INTERVAL, parameters={"VALUE": "DURATION"})
    calendar.add("x-published-ttl", vDuration(REFRESH_INTERVAL))
    calendar.add_component(Timezone.from_tzid(PROFILE_TIMEZONE, first_date=today))
    return calendar


def _event(card: EventCard, starts_at: datetime, stamp: datetime) -> Event:
    slot = _slot(card, starts_at)
    event = Event()
    event.add("uid", f"event-{card.id}@{UID_DOMAIN}")
    event.add("dtstamp", stamp)
    event.add("created", card.created_at.astimezone(UTC))
    event.add("last-modified", card.updated_at.astimezone(UTC))
    event.add("dtstart", slot.start)
    event.add("dtend", slot.end)
    event.add("summary", card.title)
    event.add("description", f"{TYPE_LABELS[card.type]} из ассистента «{CALENDAR_NAME}».")
    event.add("transp", "OPAQUE" if slot.busy else "TRANSPARENT")
    event.add_component(_alarm(card.title, slot.alert_offset))
    return event


def _slot(card: EventCard, starts_at: datetime) -> _Slot:
    if not card.has_time:
        day = starts_at.date()
        return _Slot(day, day + ONE_DAY, ALL_DAY_ALERT_OFFSET, busy=False)
    if card.type is EventType.MEETING:
        ends_at = starts_at + DEFAULT_MEETING_DURATION if card.ends_at is None else card.ends_at
        return _Slot(starts_at, ends_at.astimezone(MOSCOW), -MEETING_ALERT_LEAD, busy=True)
    return _Slot(starts_at, starts_at + MOMENT_DURATION, AT_START, busy=False)


def _alarm(title: str, offset: timedelta) -> Alarm:
    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", title)
    alarm.add("trigger", offset)
    return alarm
