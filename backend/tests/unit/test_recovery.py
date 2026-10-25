"""Коды восстановления: генерация, нормализация ввода, отпечаток, лимит попыток."""

import random
import re

import pytest

from app.core.errors import InvalidRecoveryCodeError, TooManyAttemptsError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.recovery import (
    RESTORE_ATTEMPTS_LIMIT,
    RecoveryCodes,
    generate_recovery_code,
    normalize_recovery_code,
)
from app.core.recovery_words import RECOVERY_WORDS

CODE_FORMAT = re.compile(r"[а-я]+-[а-я]+-[а-я]+-[0-9]{4}")
SECRET = b"unit-test-secret"


def make_codes(max_attempts: int = 100) -> RecoveryCodes:
    return RecoveryCodes(SECRET, SlidingWindowRateLimiter(max_attempts, window_seconds=60))


class TestWordList:
    def test_has_at_least_256_words(self) -> None:
        assert len(RECOVERY_WORDS) >= 256

    def test_words_are_unique(self) -> None:
        assert len(set(RECOVERY_WORDS)) == len(RECOVERY_WORDS)

    def test_words_are_lowercase_cyrillic_without_yo(self) -> None:
        bad_words = [word for word in RECOVERY_WORDS if not re.fullmatch(r"[а-я]+", word)]
        assert bad_words == []
        assert not any("ё" in word for word in RECOVERY_WORDS)


class TestGenerateRecoveryCode:
    def test_has_three_distinct_known_words_and_four_digits(self) -> None:
        code = generate_recovery_code(random.Random(7))

        assert CODE_FORMAT.fullmatch(code)
        words = code.split("-")[:3]
        assert len(set(words)) == 3
        assert all(word in RECOVERY_WORDS for word in words)

    def test_codes_differ_between_calls(self) -> None:
        codes = {generate_recovery_code() for _ in range(50)}
        assert len(codes) == 50


class TestNormalizeRecoveryCode:
    @pytest.mark.parametrize(
        "raw_code",
        [
            "сирень-лиса-кедр-4821",
            "Сирень-Лиса-КЕДР-4821",
            "  сирень   лиса  кедр 4821  ",
            "сирень, лиса, кедр — 4821",
            "сирень лиса кедр4821",
            "сирень_лиса_кедр_4821",
        ],
    )
    def test_ignores_case_spaces_and_separators(self, raw_code: str) -> None:
        assert normalize_recovery_code(raw_code) == "сирень-лиса-кедр-4821"

    def test_treats_yo_as_ye(self) -> None:
        assert normalize_recovery_code("Берёза-лиса-кедр-4821") == "береза-лиса-кедр-4821"

    @pytest.mark.parametrize(
        "raw_code",
        [
            "",
            "сирень-лиса-4821",
            "сирень-лиса-кедр-482",
            "сирень-лиса-кедр-48210",
            "сирень-лиса-кедр-дуб-4821",
            "4821-сирень-лиса-кедр",
            "lisa-sosna-kedr-4821",
            "сирень-лиса-кедр-٤٨٢١",
        ],
    )
    def test_rejects_input_not_shaped_like_code(self, raw_code: str) -> None:
        assert normalize_recovery_code(raw_code) is None


class TestRecoveryCodes:
    def test_issued_digest_matches_any_spelling_of_the_code(self) -> None:
        codes = make_codes()
        issued = codes.issue()

        assert codes.digest(issued.code.upper().replace("-", "  ")) == issued.digest

    def test_digest_is_hmac_not_plain_hash(self) -> None:
        issued = make_codes().issue()
        other_key_codes = RecoveryCodes(b"another-secret")

        assert issued.code not in issued.digest
        assert other_key_codes.digest(issued.code) != issued.digest

    def test_attempt_with_malformed_code_is_rejected(self) -> None:
        with pytest.raises(InvalidRecoveryCodeError):
            make_codes().digest_attempt("не код", requester="10.0.0.1")

    def test_attempts_are_limited_per_requester(self) -> None:
        codes = RecoveryCodes(SECRET)
        issued = codes.issue()
        for _ in range(RESTORE_ATTEMPTS_LIMIT):
            codes.digest_attempt(issued.code, requester="10.0.0.1")

        with pytest.raises(TooManyAttemptsError) as error:
            codes.digest_attempt(issued.code, requester="10.0.0.1")

        assert error.value.retry_after_seconds > 0
        assert codes.digest_attempt(issued.code, requester="10.0.0.2") == issued.digest
