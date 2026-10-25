"""Лемматизация для поиска: падежи, стоп-слова, числа, имена, сокращения."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.search.lemmas import MorphLemmatizer, normalize_yo, shared_morph_analyzer


@pytest.fixture(scope="module")
def lemmatizer() -> MorphLemmatizer:
    return MorphLemmatizer()


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Найди задачу про презентацию", ["презентация"]),
        ("Когда у меня была встреча с Иваном?", ["встреча", "иван"]),
        ("Я когда-то ставил задачу по договору, найди ее", ["договор"]),
    ],
)
def test_tz_search_examples_keep_only_meaningful_lemmas(
    lemmatizer: MorphLemmatizer, query: str, expected: list[str]
) -> None:
    assert lemmatizer.lemmas(query) == expected


@pytest.mark.parametrize(
    ("word", "lemma"),
    [
        ("Иваном", "иван"),
        ("Ивану", "иван"),
        ("договору", "договор"),
        ("презентацию", "презентация"),
        ("Марией", "мария"),
        ("Партнёром", "партнер"),
        ("планёрку", "планерка"),
    ],
)
def test_word_forms_reduce_to_dictionary_lemma(
    lemmatizer: MorphLemmatizer, word: str, lemma: str
) -> None:
    assert lemmatizer.lemmas(word) == [lemma]


def test_numbers_and_latin_are_kept_lowercase(lemmatizer: MorphLemmatizer) -> None:
    assert lemmatizer.lemmas("Провести планёрку по CRM в 15:00, 2024") == [
        "провести",
        "планерка",
        "crm",
        "15",
        "00",
        "2024",
    ]


def test_yo_and_e_spellings_match(lemmatizer: MorphLemmatizer) -> None:
    assert lemmatizer.lemmas("Отчёт") == lemmatizer.lemmas("отчет") == ["отчет"]
    assert normalize_yo("пётр") == "петр"


def test_lemmas_are_unique_in_order_of_appearance(lemmatizer: MorphLemmatizer) -> None:
    assert lemmatizer.lemmas("Ивану отчёт, Иваном отчёты") == ["иван", "отчет"]


@pytest.mark.parametrize(
    "service_phrase",
    [
        "у меня",
        "найди мне, пожалуйста",
        "покажи все мои задачи",
        "когда это было на прошлой неделе",
        "Горький, что там было вчера?",
        "я когда-то ставил задачу",
    ],
)
def test_service_words_and_stop_words_are_dropped(
    lemmatizer: MorphLemmatizer, service_phrase: str
) -> None:
    assert lemmatizer.lemmas(service_phrase) == []


def test_record_verbs_stay_meaningful(lemmatizer: MorphLemmatizer) -> None:
    assert lemmatizer.lemmas("Напомнить Анной про CRM") == ["напомнить", "анна", "crm"]


def test_empty_and_punctuation_only_text_has_no_lemmas(lemmatizer: MorphLemmatizer) -> None:
    assert lemmatizer.lemmas("") == []
    assert lemmatizer.lemmas(" ?!, — ") == []


def test_unknown_words_keep_a_noun_lemma_or_the_word(lemmatizer: MorphLemmatizer) -> None:
    assert lemmatizer.lemmas("Демо проекта по хакатону") == ["демо", "проект", "хакатон"]


def test_ambiguous_forms_share_a_lemma(lemmatizer: MorphLemmatizer) -> None:
    record = set(lemmatizer.lemmas("Обсудить аналитике с Еленой"))

    assert "аналитика" in record
    assert set(lemmatizer.lemmas("аналитика")) & record


def test_rare_alternative_parse_is_not_added(lemmatizer: MorphLemmatizer) -> None:
    assert lemmatizer.lemmas("встречу") == ["встреча"]


@pytest.mark.parametrize(
    ("abbreviation", "full"),
    [("ТЗ", "техническое задание"), ("КП", "коммерческое предложение")],
)
def test_abbreviations_match_full_form(
    lemmatizer: MorphLemmatizer, abbreviation: str, full: str
) -> None:
    assert lemmatizer.lemmas(abbreviation) == lemmatizer.lemmas(full)


def test_custom_stop_words_replace_defaults() -> None:
    lemmatizer = MorphLemmatizer(stop_words=frozenset({"договор"}))

    assert lemmatizer.lemmas("найти договор") == ["найти"]


@pytest.mark.parametrize("lemma", ["иван", "мария", "петр", "максим", "наталья"])
def test_person_names_are_proper_nouns(lemmatizer: MorphLemmatizer, lemma: str) -> None:
    assert lemmatizer.is_proper_noun(lemma)


@pytest.mark.parametrize("lemma", ["вектор", "хакатон", "договор", "crm", "2024", ""])
def test_other_lemmas_are_not_proper_nouns(lemmatizer: MorphLemmatizer, lemma: str) -> None:
    assert not lemmatizer.is_proper_noun(lemma)


def test_lemmatizers_share_one_morph_analyzer() -> None:
    assert shared_morph_analyzer() is shared_morph_analyzer()


def test_concurrent_calls_give_same_lemmas(lemmatizer: MorphLemmatizer) -> None:
    texts = ["Встреча с Иваном по CRM", "Отправить договор Марией", "Подготовить презентацию"] * 50
    expected = [MorphLemmatizer().lemmas(text) for text in texts]

    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = list(pool.map(lemmatizer.lemmas, texts))

    assert actual == expected
