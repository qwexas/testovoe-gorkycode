"""Cookie профиля `gorky_session`.

Обработчики не пишут cookie в ответ сами, а оставляют распоряжение в состоянии
запроса; `SessionCookieMiddleware` добавляет `Set-Cookie` в любой ответ — и в
успешный, и в ответ-ошибку. Так профиль, созданный по ходу запроса, не теряется,
даже если запрос закончился ошибкой (например, 501 или 503).
"""

from dataclasses import dataclass
from http.cookies import SimpleCookie

from starlette.datastructures import MutableHeaders, State
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SESSION_COOKIE_NAME = "gorky_session"
SESSION_COOKIE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60
EXPIRED_COOKIE_DATE = "Thu, 01 Jan 1970 00:00:00 GMT"

_STATE_ATTRIBUTE = "session_cookie_change"


@dataclass(frozen=True, slots=True)
class SessionCookieChange:
    """Что сделать с cookie: поставить токен или удалить cookie (`token is None`)."""

    token: str | None


def issue_session_cookie(request: Request, token: str) -> None:
    """Поставить устройству cookie с новым токеном сессии."""
    setattr(request.state, _STATE_ATTRIBUTE, SessionCookieChange(token=token))


def revoke_session_cookie(request: Request) -> None:
    """Удалить cookie сессии на устройстве."""
    setattr(request.state, _STATE_ATTRIBUTE, SessionCookieChange(token=None))


def render_session_cookie(change: SessionCookieChange, secure: bool) -> str:
    """Значение заголовка `Set-Cookie`: HttpOnly, SameSite=Lax, на год (или удаление)."""
    cookie: SimpleCookie = SimpleCookie()
    cookie[SESSION_COOKIE_NAME] = change.token or ""
    morsel = cookie[SESSION_COOKIE_NAME]
    morsel["path"] = "/"
    morsel["httponly"] = True
    morsel["samesite"] = "lax"
    morsel["secure"] = secure
    if change.token is None:
        morsel["max-age"] = 0
        morsel["expires"] = EXPIRED_COOKIE_DATE
    else:
        morsel["max-age"] = SESSION_COOKIE_MAX_AGE_SECONDS
    return morsel.OutputString()


class SessionCookieMiddleware:
    """Добавляет `Set-Cookie` по распоряжению, оставленному обработчиком запроса."""

    def __init__(self, app: ASGIApp, cookie_secure: bool) -> None:
        self._app = app
        self._cookie_secure = cookie_secure

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request_state = State(scope.setdefault("state", {}))

        async def send_with_cookie(message: Message) -> None:
            change = getattr(request_state, _STATE_ATTRIBUTE, None)
            if message["type"] == "http.response.start" and change is not None:
                header = render_session_cookie(change, secure=self._cookie_secure)
                MutableHeaders(scope=message).append("set-cookie", header)
            await send(message)

        await self._app(scope, receive, send_with_cookie)
