"""Промпт разбора реплики: правила с примерами и сведения о моменте и диалоге.

Системное сообщение не меняется от запроса к запросу (его префикс GigaChat может
кэшировать). Всё переменное — текущий момент, календарь, контекст диалога и сама
реплика — идёт в сообщение пользователя.
"""

import datetime as dt
import json
from collections.abc import Sequence

from app.core.enums import EventType, PendingExpectation
from app.llm.interfaces import LLMMessage
from app.nlu.interfaces import ContextEvent, DialogContext, DialogTurn
from app.nlu.time_resolution import in_moscow, week_start

CALENDAR_WEEKS_BEFORE = 2
CALENDAR_WEEKS_AFTER = 2
DAYS_IN_WEEK = 7
WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
WEEKDAYS_FULL = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
WEEK_NAMES = {
    -2: "позапрошлая неделя",
    -1: "прошлая неделя",
    0: "эта неделя",
    1: "следующая неделя",
    2: "через неделю",
}
EXPECTATIONS = {
    PendingExpectation.DATE: "день",
    PendingExpectation.TIME: "время",
    PendingExpectation.DATETIME: "день и время",
    PendingExpectation.CHOICE: "выбор одного из вариантов",
    PendingExpectation.CONFIRM: "подтверждение (да или нет)",
    PendingExpectation.TITLE: "название записи",
}
EVENT_TYPE_NAMES = {
    EventType.TASK: "задача",
    EventType.REMINDER: "напоминание",
    EventType.MEETING: "встреча",
}
ROLE_NAMES = {"user": "пользователь", "assistant": "ассистент"}

SYSTEM_PROMPT = """\
Ты — модуль разбора реплик голосового ассистента «Горький». Пользователь ведёт задачи, \
напоминания и встречи и говорит свободно; текст распознан из речи, поэтому знаков препинания \
может не быть, а числа бывают словами. Заполни JSON по схеме.

Главное правило: ничего не придумывай. Заполняй только поля, нужные выбранному action, и \
только тем, что сказано в самой реплике. Поле, которое пользователь не назвал, пропусти. \
Название, день и время из прошлых реплик и записей в фокусе не переписывай — их знает \
программа. Даты не вычисляй: только отметь, как назван день, — дату посчитает программа.

action:
- create — создать задачу, напоминание или встречу: «напомни…», «поставь задачу…», \
«добавь встречу…», «в пятницу нужно…», «завтра у меня встреча…». «Поставь», «добавь», \
«запланируй», «назначь» — всегда create, даже если похожая запись уже есть в фокусе;
- list — показать записи за период: «что у меня…», «какие планы…», «покажи встречи на…», \
«есть ли у меня…», «что запланировано…»;
- search — найти конкретную запись: «найди…», «когда у меня была/будет…», «была ли у меня…», \
«я ставил задачу про…»;
- reschedule — перенести существующую запись: «перенеси», «сдвинь», «передвинь», «отложи», \
«поменяй время»; rename — переименовать; complete — отметить \
выполненной («я уже позвонил…», «отметь… как сделанную»); delete — удалить («удали…», \
«отмени встречу…», «убери…»);
- answer — короткий ответ на вопрос ассистента: время, день или название;
- choose — выбор из пронумерованного списка: «вторую», «ту, что с Ольгой»;
- confirm — согласие на вопрос ассистента: «да», «давай», «удаляй», «всё равно добавь»;
- deny — отказ на вопрос ассистента: «нет», «не надо»;
- undo — отменить последнее действие ассистента, когда он ничего не спрашивает: «отмени», \
«отмена», «верни как было» (без названия записи; «отмени встречу с …» — это delete);
- smalltalk — приветствие, благодарность, вопрос о том, что ассистент умеет;
- unknown — не про задачи и встречи (погода, анекдоты, вычисления) или непонятно.

event_type: meeting — встреча, созвон, совещание, планёрка, переговоры; reminder — есть слово \
«напомни» или «напоминание»; task — задача или дело без «напомни» («нужно отправить», \
«купить», «позвонить»). Для list и search — тип, о котором спрашивают: «встречи» → meeting, \
«задачи» → task, «напоминания» → reminder, «что у меня», «планы», «дела» → none.

title — для create и ответа на вопрос о названии: коротко, с заглавной буквы, без \
слов-команд, дат и времени, глагол в инфинитиве: «напомни в среду написать Ольге» → «Написать \
Ольге». Встречу называй «Встреча с …», если пользователь не назвал её иначе («Созвон с …», \
«Планёрка»). Если назван только тип без содержания («поставь встречу на завтра в 12», \
«добавь задачу»), title пустой — название спросит программа.
new_title — только для rename: новое название, «переименуй X в Y» → new_title «Y».

query — для search заполняй всегда: что искать, без слов «найди», «когда», «задача» \
(«встреча с Иваном», «договор»). Для reschedule, rename, complete, delete — какую запись \
менять, словами самого пользователя: «отметь звонок Ивану как сделанный» → «звонок Ивану», \
«перенеси встречу с дизайнером» → «встреча с дизайнером». Не подставляй в query название из \
«Записей в фокусе», даже если оно похоже: нужной записи там может не быть. На запись из \
фокуса ссылайся только через about_last (местоимение) или choice (выбор из списка). Если \
запись названа местоимением или «эта», «последняя» («её», «его», «эту встречу») — query \
пустое и about_last = true, даже если понятно, о какой записи речь. Для изменяемой записи \
event_type и date — только если они названы в самой реплике («звонок» — не встреча).

date — как назван день: для create и answer — день записи; для reschedule — новый день, \
куда перенести; для list и search — период, если назван («в прошлом месяце» → last_month); \
для complete, delete, rename — день изменяемой записи, только если он назван. Относительные \
выражения не переводи в число и месяц: «через неделю» — in_days, а не exact.
today «сегодня»; tomorrow «завтра»; after_tomorrow «послезавтра»; yesterday «вчера»;
mon, tue, wed, thu, fri, sat, sun — «в пятницу», «к пятнице», «до пятницы», «в эту пятницу»;
next_mon … next_sun — «в следующую пятницу», «в пятницу на следующей неделе»;
exact — число и месяц, значение в date_value: «26 октября» → «26.10», с годом — «26.10.2027»;
in_days — «через N дней», число дней в date_value: «через неделю» → «7», «через три дня» → «3»;
this_week «на этой неделе»; next_week «на следующей неделе»; last_week «на прошлой неделе»;
end_of_week «до конца недели»; weekend «на выходных»;
this_month «в этом месяце»; next_month; last_month; end_of_month «до конца месяца».

time — время, как его назвали, в виде Ч:ММ: «в 15:00» → «15:00», «в 10 утра» → «10:00», \
«в 9 вечера» → «9:00», «в 3» → «3:00», «в 11» → «11:00», «пятнадцать тридцать» → «15:30», \
«в половине третьего» → «2:30», «в полдень» → «12:00». Время не названо — "".
day_part — часть суток, если сказана: morning «утром», «утра»; day «днём», «дня», «в обед»; \
evening «вечером», «вечера»; night «ночью», «ночи». Иначе none. Если назвали только часть \
суток без часа («утром», «в обед», «вечером»), time пустое — час подставит программа.
in_minutes — «через N минут или часов» от текущего момента: «через два часа» → 120, \
«через полчаса» → 30. Тогда date и time пустые.
target_date и target_time — только для reschedule: где запись стоит сейчас, если это \
названо («перенеси завтрашний созвон на пятницу» → target_date tomorrow, date fri; \
«перенеси встречу в 15:00 на 17:00», «сдвинь созвон с 15 на 17» → target_time «15:00», \
time «17:00»). target_time пиши в 24-часовом виде: «в 9 вечера» → «21:00». Новый день и \
время переноса — только в date и time, прежние — только в target_date и target_time.
duration_minutes — длительность встречи, если названа: «на полчаса» → 30, «с 15 до 17» → 120. \
Для reschedule — новая длительность: «перенеси на 17:00 на полчаса» → time «17:00», \
duration_minutes 30.
time_scope — для search: past («была», «ставил», «звонил»), future («будет»), иначе any.
status — для list и search: open («невыполненные», «что осталось сделать»), done («что я \
сделал», «выполненные»), иначе none.
choice — для choose: номер варианта из «Записей в фокусе», начиная с 1: «вторую» → 2, \
«последнюю» → номер последней, «ту, что с Ольгой» → номер записи с Ольгой.
rest — если в реплике несколько команд («перенеси планёрку на 11 и удали встречу с Петром», \
«создай встречу с Иваном и задачу купить билеты»): все поля выше заполни только по первой \
команде, а остальные перепиши в rest словами пользователя, с глаголом: «удали встречу с \
Петром», «создай задачу купить билеты». Одна запись с перечислением в названии («купить \
хлеб и молоко») — одна команда, rest пустой.

Контекст. Если есть строка «Ассистент ждёт», реплика обычно отвечает на этот вопрос: время, \
день или название → answer, а не create (черновик записи уже у программы; заполни только \
названное в реплике); номер или описание варианта → choose; «да» / «нет» → confirm / deny. \
Если реплика — новая самостоятельная просьба, разбирай её как обычно. Местоимения «её», \
«его», «эту» относятся к первой записи в фокусе.

Примеры (показаны только непустые поля):
{examples}"""

FEW_SHOT_EXAMPLES: tuple[tuple[str, dict[str, object]], ...] = (
    (
        "напомни послезавтра в 8 утра записаться к врачу",
        {
            "action": "create",
            "event_type": "reminder",
            "title": "Записаться к врачу",
            "date": "after_tomorrow",
            "time": "8:00",
            "day_part": "morning",
        },
    ),
    (
        "в среду надо сдать отчёт по продажам",
        {
            "action": "create",
            "event_type": "task",
            "title": "Сдать отчёт по продажам",
            "date": "wed",
        },
    ),
    (
        "созвон с Петром в понедельник в 4",
        {
            "action": "create",
            "event_type": "meeting",
            "title": "Созвон с Петром",
            "date": "mon",
            "time": "4:00",
        },
    ),
    (
        "в четверг вечером забрать костюм из химчистки",
        {
            "action": "create",
            "event_type": "task",
            "title": "Забрать костюм из химчистки",
            "date": "thu",
            "day_part": "evening",
        },
    ),
    (
        "запиши задачу оплатить аренду",
        {"action": "create", "event_type": "task", "title": "Оплатить аренду"},
    ),
    ("что было вчера", {"action": "list", "date": "yesterday"}),
    (
        "какие встречи были на прошлой неделе",
        {"action": "list", "event_type": "meeting", "date": "last_week"},
    ),
    (
        "когда я последний раз созванивался с Анной",
        {
            "action": "search",
            "event_type": "meeting",
            "query": "созвон с Анной",
            "time_scope": "past",
        },
    ),
    (
        "найди встречу с Борисом на прошлой неделе",
        {
            "action": "search",
            "event_type": "meeting",
            "query": "встреча с Борисом",
            "date": "last_week",
        },
    ),
    (
        "перенеси созвон с Анной с четверга на 12 ноября в 14:30",
        {
            "action": "reschedule",
            "event_type": "meeting",
            "query": "созвон с Анной",
            "target_date": "thu",
            "date": "exact",
            "date_value": "12.11",
            "time": "14:30",
        },
    ),
    (
        "перенеси завтрашнюю встречу в 10 на пятницу в 12 на полчаса",
        {
            "action": "reschedule",
            "event_type": "meeting",
            "query": "встреча",
            "target_date": "tomorrow",
            "target_time": "10:00",
            "date": "fri",
            "time": "12:00",
            "duration_minutes": 30,
        },
    ),
    (
        "сдвинь планёрку на 11 и удали встречу с Петром",
        {
            "action": "reschedule",
            "event_type": "meeting",
            "query": "планёрка",
            "time": "11:00",
            "rest": "удали встречу с Петром",
        },
    ),
    ("убери эту встречу", {"action": "delete", "event_type": "meeting", "about_last": True}),
    (
        "сдвинь его на послезавтра",
        {"action": "reschedule", "about_last": True, "date": "after_tomorrow"},
    ),
    (
        "переименуй встречу с Петром в обед с Петром",
        {
            "action": "rename",
            "event_type": "meeting",
            "query": "встреча с Петром",
            "new_title": "Обед с Петром",
        },
    ),
    (
        "(ассистент ждёт время) к семи вечера",
        {"action": "answer", "time": "7:00", "day_part": "evening"},
    ),
    ("(ассистент ждёт выбор из трёх записей) третью", {"action": "choose", "choice": 3}),
)


def build_messages(text: str, context: DialogContext) -> list[LLMMessage]:
    """Сообщения для разбора реплики `text` в контексте диалога."""
    return [
        LLMMessage(role="system", content=system_prompt()),
        LLMMessage(role="user", content=user_prompt(text, context)),
    ]


def system_prompt() -> str:
    """Правила и примеры — одинаковые для всех запросов."""
    examples = "\n".join(
        f"«{phrase}» → {json.dumps(fields, ensure_ascii=False)}"
        for phrase, fields in FEW_SHOT_EXAMPLES
    )
    return SYSTEM_PROMPT.format(examples=examples)


def user_prompt(text: str, context: DialogContext) -> str:
    """Текущий момент, календарь, контекст диалога и реплика."""
    now = in_moscow(context.now)
    sections = [
        f"Сейчас: {WEEKDAYS_FULL[now.weekday()]}, {now:%d.%m.%Y}, {now:%H:%M} (Москва).",
        "Календарь:\n" + calendar(now.date()),
        *_dialog_sections(context),
        *_pending_section(context),
        f"Реплика пользователя: «{text.strip()}»",
    ]
    return "\n".join(sections)


def calendar(today: dt.date) -> str:
    """Недели вокруг сегодняшнего дня: «эта неделя: пн 26.10, вт 27.10 (сегодня), …»."""
    monday = week_start(today)
    lines = []
    for week in range(-CALENDAR_WEEKS_BEFORE, CALENDAR_WEEKS_AFTER + 1):
        start = monday + dt.timedelta(days=DAYS_IN_WEEK * week)
        days = ", ".join(_calendar_day(start + dt.timedelta(days=i), today) for i in range(7))
        lines.append(f"{WEEK_NAMES[week]}: {days}")
    return "\n".join(lines)


def _calendar_day(day: dt.date, today: dt.date) -> str:
    mark = " (сегодня)" if day == today else ""
    return f"{WEEKDAYS_SHORT[day.weekday()]} {day:%d.%m}{mark}"


def _pending_section(context: DialogContext) -> list[str]:
    if context.pending is None:
        return []
    question = f" — вопрос «{context.pending_question}»" if context.pending_question else ""
    return [
        f"Ассистент ждёт: {EXPECTATIONS[context.pending]}{question}. Реплика может быть "
        "ответом на этот вопрос (action answer, choose, confirm или deny — в полях только то, "
        "что сказано в самой реплике) или новой командой (create, list, search, reschedule, "
        "rename, complete, delete, undo) — тогда разбирай её как обычно."
    ]


def _dialog_sections(context: DialogContext) -> list[str]:
    sections = []
    if context.recent:
        sections.append("Последние реплики:\n" + _turns(context.recent))
    if context.focus:
        sections.append("Записи в фокусе:\n" + _focus(context.focus))
    return sections


def _turns(turns: Sequence[DialogTurn]) -> str:
    return "\n".join(f"{ROLE_NAMES.get(turn.role, turn.role)}: {turn.text}" for turn in turns)


def _focus(events: Sequence[ContextEvent]) -> str:
    return "\n".join(
        f"{number}. {EVENT_TYPE_NAMES[event.type]} «{event.title}»{_starts(event.starts_at)}"
        for number, event in enumerate(events, start=1)
    )


def _starts(starts_at: dt.datetime | None) -> str:
    if starts_at is None:
        return ", без срока"
    moment = in_moscow(starts_at)
    return f", {WEEKDAYS_SHORT[moment.weekday()]} {moment:%d.%m %H:%M}"
