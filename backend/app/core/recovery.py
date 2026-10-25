"""Коды восстановления профиля: «сирень-лиса-кедр-4821».

Код — три слова из `RECOVERY_WORDS` и четыре цифры. В базе хранится только
HMAC-SHA256 канонического вида кода с ключом `APP_SECRET`. При вводе регистр,
лишние пробелы и разделители не важны, «ё» считается за «е».
"""

import hashlib
import hmac
import random
import re
import secrets
import string
from dataclasses import dataclass

from app.core.errors import InvalidRecoveryCodeError, TooManyAttemptsError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.recovery_words import RECOVERY_WORDS

WORD_COUNT = 3
DIGIT_COUNT = 4
SEPARATOR = "-"
RESTORE_ATTEMPTS_LIMIT = 5
RESTORE_WINDOW_SECONDS = 15 * 60

_CODE_TOKEN = re.compile(r"[а-я]+|[0-9]+")
_CANONICAL_CODE = re.compile(
    SEPARATOR.join([r"[а-я]+"] * WORD_COUNT + [rf"[0-9]{{{DIGIT_COUNT}}}"]),
)


@dataclass(frozen=True, slots=True)
class IssuedRecoveryCode:
    """Новый код: `code` показывается пользователю один раз, `digest` сохраняется в базе."""

    code: str
    digest: str


def generate_recovery_code(rng: random.Random | None = None) -> str:
    """Три разных слова и четыре цифры через дефис."""
    chooser = rng or secrets.SystemRandom()
    words = chooser.sample(RECOVERY_WORDS, WORD_COUNT)
    digits = "".join(chooser.choice(string.digits) for _ in range(DIGIT_COUNT))
    return SEPARATOR.join([*words, digits])


def normalize_recovery_code(raw_code: str) -> str | None:
    """Канонический вид введённого кода или `None`, если ввод не похож на код."""
    lowered = raw_code.casefold().replace("ё", "е")
    candidate = SEPARATOR.join(_CODE_TOKEN.findall(lowered))
    return candidate if _CANONICAL_CODE.fullmatch(candidate) else None


class RecoveryCodes:
    """Выдаёт коды восстановления и проверяет попытки входа по ним.

    Попытки считаются по `requester` (IP клиента): не больше
    `RESTORE_ATTEMPTS_LIMIT` за `RESTORE_WINDOW_SECONDS`.
    """

    def __init__(self, secret: bytes, attempts: SlidingWindowRateLimiter | None = None) -> None:
        self._secret = secret
        self._attempts = attempts or SlidingWindowRateLimiter(
            max_hits=RESTORE_ATTEMPTS_LIMIT,
            window_seconds=RESTORE_WINDOW_SECONDS,
        )

    def issue(self) -> IssuedRecoveryCode:
        """Генерирует новый код и его отпечаток для базы."""
        code = generate_recovery_code()
        return IssuedRecoveryCode(code=code, digest=self._sign(code))

    def digest(self, raw_code: str) -> str | None:
        """Отпечаток введённого кода или `None`, если ввод не похож на код."""
        code = normalize_recovery_code(raw_code)
        return None if code is None else self._sign(code)

    def digest_attempt(self, raw_code: str, requester: str) -> str:
        """Учитывает попытку входа и возвращает отпечаток кода.

        Raises:
            TooManyAttemptsError: Лимит попыток для `requester` исчерпан.
            InvalidRecoveryCodeError: Ввод не похож на код восстановления.
        """
        decision = self._attempts.hit(requester)
        if not decision.allowed:
            raise TooManyAttemptsError(decision.retry_after_seconds)
        digest = self.digest(raw_code)
        if digest is None:
            raise InvalidRecoveryCodeError()
        return digest

    def _sign(self, canonical_code: str) -> str:
        return hmac.new(self._secret, canonical_code.encode(), hashlib.sha256).hexdigest()
