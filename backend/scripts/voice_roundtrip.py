"""Замер голосового контура: озвучка → кодеки браузеров → распознавание Whisper.

Четыре команды (распознавание — в своём процессе на каждую
конфигурацию, чтобы честно мерить загрузку модели и память):

    corpus     озвучить фразы ТЗ и свои (Silero xenia/baya/aidar и, на Mac, `say -v Milena` —
               чтобы не проверять Whisper синтетикой одного движка), перекодировать ffmpeg
               в webm/opus (Chrome) и mp4/aac (Safari), добавить тишину и шум; замерить синтез;
    recognize  распознать корпус одной конфигурацией Whisper через `WhisperSpeechToText`;
    latency    задержка нескольких моделей вперемешку на одних записях (честно при фоновой
               нагрузке машины);
    report     сводная таблица Markdown по результатам recognize.

Запуск из каталога backend/ (нужен ffmpeg; веса — в ./models репозитория):
    uv run python -m scripts.voice_roundtrip corpus --out /tmp/voice-corpus
    uv run python -m scripts.voice_roundtrip recognize --corpus /tmp/voice-corpus \\
        --model large-v3-turbo --beam-size 5 --out /tmp/turbo.json
    uv run python -m scripts.voice_roundtrip latency --corpus /tmp/voice-corpus \\
        --configs large-v3-turbo:5 medium:5 small:5 --formats webm
    uv run python -m scripts.voice_roundtrip report /tmp/voice-corpus/tts.json /tmp/*.json
"""

import argparse
import asyncio
import json
import os
import platform
import re
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np

from app.voice.audio import SPEECH_SAMPLE_RATE, decode_speech
from app.voice.interfaces import AudioClip
from app.voice.settings import (
    DEFAULT_BEAM_SIZE,
    DEFAULT_STT_CPU_THREADS,
    DEFAULT_WHISPER_MODEL,
    SILERO_VOICES,
    SileroSampleRate,
    SpeechToTextSettings,
    TextToSpeechSettings,
)
from app.voice.silero import SileroTextToSpeech, load_silero_model
from app.voice.text_normalizer import normalize_for_speech
from app.voice.whisper import WhisperSpeechToText, load_whisper_model

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO_ROOT / "models"

TZ_PHRASES = (
    "Напомни мне завтра в 10 утра позвонить Ивану",
    "В пятницу нужно отправить отчет",
    "Поставь задачу купить билеты до конца недели",
    "Добавь встречу с командой завтра в 15:00",
    "В четверг в 11 у меня встреча с дизайнером",
    "Что у меня сегодня?",
    "Есть ли у меня встречи сегодня?",
    "Какие задачи у меня на завтра?",
    "Что запланировано на эту неделю?",
    "Найди задачу про презентацию",
    "Когда у меня была встреча с Иваном?",
    "Я когда-то ставил задачу по договору, найди ее",
    "Какие планы на сегодня?",
    "Покажи мои встречи на сегодня",
    "Поставь встречу с Иваном завтра",
    "А перенеси ее на завтра",
)
"""Все примеры фраз из ТЗ."""
OWN_PHRASES = (
    "Горький, напомни через два часа проверить почту",
    "Созвон с Ольгой послезавтра в 8:45",
    "Удали встречу с дизайнером",
    "Отметь задачу про отчет выполненной",
    "Перенеси созвон по CRM на следующую неделю",
    "Поставь задачу подготовить КП для клиента до пятницы",
    "Какие встречи у меня на следующей неделе?",
    "Напомни 5 ноября в 9:30 оплатить счет",
    "Добавь задачу согласовать ТЗ с Петром",
    "Что у меня запланировано на послезавтра?",
)
"""Свои фразы: имя ассистента, время с минутами, дата, аббревиатуры, изменение и удаление."""
ASSISTANT_REPLIES = (
    "Встреча «Встреча с командой» — завтра, 27 октября, в 15:00.",
    "Сегодня у вас 3 дела: 2 встречи и задача. Ближайшее — «Созвон по CRM» в 17:00.",
    "В это время уже стоит «Планёрка» (15:00\u201316:00). Всё равно добавить?",
    "Последняя встреча «Встреча с Иваном» была 5 марта 2026 в 15:45.",
    "Я Горький — веду ваши задачи, напоминания и встречи. Скажите, например: "
    "«Напомни завтра в 10 позвонить Ивану», «Что у меня сегодня?» "
    "или «Найди задачу про презентацию».",
)
"""Типичные ответы ассистента — для замера синтеза."""

MAC_VOICE = "Milena"
NEGATIVE_CLIPS = ("silence", "noise")
NEGATIVE_SECONDS = 3
NOISE_LEVEL = 0.03
FFMPEG_FORMATS = {
    "webm": ("-c:a", "libopus", "-b:a", "32k", "-ar", "48000", "-ac", "1"),
    "mp4": (
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-ar",
        "44100",
        "-ac",
        "1",
        "-movflags",
        "+frag_keyframe+empty_moov",
    ),
}
"""Как пишут браузеры: Chrome — webm/opus, Safari — фрагментированный mp4/aac."""
PERCENTILE_95 = 0.95
_WHISPER_TIME_PATTERN = re.compile(r"\b([01]?\d|2[0-3])[.-]([0-5]\d)\b")
_SPOKEN_TIME_PATTERN = re.compile(r"\b([01]?\d|2[0-3]) час(?:а|ов)?,? (\d{1,2}) минут[аы]?")
_NOT_LETTERS_PATTERN = re.compile(r"[^а-я ]")


# --- Сравнение текстов -------------------------------------------------------------------------


def comparable(text: str) -> str:
    """Текст для сравнения: числа словами, без пунктуации, регистра, «ё» и ударений.

    Whisper пишет время как «15.00», а голос macOS читает «15:00» как «15 часов 0 минут» —
    всё это приводим к «15:00», чтобы оно читалось как время.
    """
    text = _SPOKEN_TIME_PATTERN.sub(lambda match: f"{match[1]}:{int(match[2]):02d}", text)
    text = _WHISPER_TIME_PATTERN.sub(r"\1:\2", text)
    spoken = normalize_for_speech(text).replace("+", "").lower().replace("ё", "е")
    return " ".join(_NOT_LETTERS_PATTERN.sub(" ", spoken.replace("-", " ")).split())


def edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    """Расстояние Левенштейна между последовательностями слов или символов."""
    previous = list(range(len(hypothesis) + 1))
    for row, expected in enumerate(reference, start=1):
        current = [row]
        for column, actual in enumerate(hypothesis, start=1):
            substitution = previous[column - 1] + (expected != actual)
            current.append(min(previous[column] + 1, current[column - 1] + 1, substitution))
        previous = current
    return previous[-1]


def percentile(values: Sequence[float], share: float) -> float:
    """Перцентиль по ближайшему рангу."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * len(ordered)) - 1))
    return ordered[index]


def peak_memory_mb() -> float:
    """Пиковая RSS процесса: на macOS `ru_maxrss` в байтах, на Linux — в килобайтах."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return peak / divisor


# --- Корпус -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Clip:
    """Запись корпуса: что сказано, кем и в каком формате."""

    path: str
    text: str
    source: str
    audio_format: str
    seconds: float


@dataclass(slots=True)
class SynthesisReport:
    """Замер Silero: загрузка и время озвучки по голосам."""

    load_seconds: float = 0.0
    first_call_seconds: float = 0.0
    latencies: dict[str, list[float]] = field(default_factory=dict)
    audio_seconds: dict[str, list[float]] = field(default_factory=dict)
    reply_bytes: list[int] = field(default_factory=list)
    peak_memory_mb: float = 0.0


def build_corpus(out_dir: Path, sample_rate: SileroSampleRate) -> None:
    """Озвучивает фразы, перекодирует их и пишет `manifest.json` и `tts.json`."""
    if shutil.which("ffmpeg") is None:
        sys.exit("Нужен ffmpeg (brew install ffmpeg / apt install ffmpeg)")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(_measure_synthesis(sample_rate))
    (out_dir / "tts.json").write_text(json.dumps(asdict(report), indent=1))
    clips = asyncio.run(_spoken_clips(out_dir, sample_rate))
    manifest = [asdict(clip) for clip in clips]
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"Корпус: {len(clips)} записей в {out_dir}")


async def _spoken_clips(out_dir: Path, sample_rate: SileroSampleRate) -> list[Clip]:
    phrases = (*TZ_PHRASES, *OWN_PHRASES)
    sources = _speech_sources(sample_rate)
    clips: list[Clip] = []
    with tempfile.TemporaryDirectory() as raw_dir:
        for source_name, speak in sources.items():
            for index, phrase in enumerate(phrases):
                raw = Path(raw_dir) / f"{source_name}-{index:02d}"
                await speak(phrase, raw)
                clips.extend(_encoded_clips(raw, out_dir, phrase, source_name))
        clips.extend(_negative_clips(Path(raw_dir), out_dir))
    return clips


SpeakFunction = Callable[[str, Path], Awaitable[None]]


def _speech_sources(sample_rate: SileroSampleRate) -> dict[str, SpeakFunction]:
    settings = TextToSpeechSettings(
        _env_file=None, cache_dir=MODELS_DIR / "silero", sample_rate=sample_rate
    )
    tts = SileroTextToSpeech(settings)
    sources: dict[str, SpeakFunction] = {
        f"silero-{voice}": _silero_speaker(tts, voice) for voice in SILERO_VOICES
    }
    if platform.system() == "Darwin" and shutil.which("say"):
        sources[f"say-{MAC_VOICE.lower()}"] = _say
    return sources


def _silero_speaker(tts: SileroTextToSpeech, voice: str) -> SpeakFunction:
    async def speak(text: str, target: Path) -> None:
        clip = await tts.synthesize(text, voice)
        target.with_suffix(".ogg").write_bytes(clip.data)

    return speak


async def _say(text: str, target: Path) -> None:
    """Системный голос macOS читает цифры сам — второй, независимый от Silero источник."""
    subprocess.run(
        ["say", "-v", MAC_VOICE, "-o", str(target.with_suffix(".aiff")), text], check=True
    )


def _encoded_clips(raw: Path, out_dir: Path, text: str, source: str) -> list[Clip]:
    [source_file] = raw.parent.glob(f"{raw.name}.*")
    clips = []
    for audio_format, codec_args in FFMPEG_FORMATS.items():
        target = out_dir / f"{raw.name}.{audio_format}"
        _ffmpeg(source_file, codec_args, target)
        seconds = decode_speech(target.read_bytes()).size / SPEECH_SAMPLE_RATE
        clips.append(Clip(target.name, text, source, audio_format, round(seconds, 2)))
    return clips


def _ffmpeg(source: Path, codec_args: Iterable[str], target: Path) -> None:
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), *codec_args, str(target)]
    subprocess.run(command, check=True)


def _negative_clips(raw_dir: Path, out_dir: Path) -> list[Clip]:
    """Тишина и белый шум: распознаватель должен вернуть пустую строку."""
    generator = np.random.default_rng(7)
    samples = SPEECH_SAMPLE_RATE * NEGATIVE_SECONDS
    signals = {
        "silence": np.zeros(samples, dtype=np.float32),
        "noise": (generator.standard_normal(samples) * NOISE_LEVEL).astype(np.float32),
    }
    clips = []
    for name, signal in signals.items():
        raw = raw_dir / f"negative-{name}"
        _write_wav(raw.with_suffix(".wav"), signal)
        clips.extend(_encoded_clips(raw, out_dir, "", f"negative-{name}"))
    return clips


def _write_wav(path: Path, signal: np.ndarray) -> None:
    import wave

    pcm = (np.clip(signal, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(SPEECH_SAMPLE_RATE)
        file.writeframes(pcm.tobytes())


async def _measure_synthesis(sample_rate: SileroSampleRate) -> SynthesisReport:
    """Загрузка Silero и время озвучки ответов ассистента каждым голосом.

    Идёт первым, пока в процессе одна модель: пик памяти — как у сервиса озвучки.
    """
    settings = TextToSpeechSettings(
        _env_file=None, cache_dir=MODELS_DIR / "silero", sample_rate=sample_rate
    )
    report = SynthesisReport()
    started = time.perf_counter()
    model = load_silero_model(settings)
    report.load_seconds = time.perf_counter() - started
    tts = SileroTextToSpeech(settings, load_model=lambda _: model)
    started = time.perf_counter()
    await tts.synthesize(ASSISTANT_REPLIES[0], None)
    report.first_call_seconds = time.perf_counter() - started
    for voice in SILERO_VOICES:
        report.latencies[voice] = []
        report.audio_seconds[voice] = []
        for reply in ASSISTANT_REPLIES:
            started = time.perf_counter()
            clip = await tts.synthesize(reply, voice)
            report.latencies[voice].append(time.perf_counter() - started)
            report.audio_seconds[voice].append(decode_speech(clip.data).size / SPEECH_SAMPLE_RATE)
            report.reply_bytes.append(len(clip.data))
    report.peak_memory_mb = peak_memory_mb()
    return report


# --- Распознавание ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Recognition:
    """Результат одной записи."""

    path: str
    source: str
    audio_format: str
    reference: str
    hypothesis: str
    seconds: float
    latency: float


@dataclass(slots=True)
class RecognitionRun:
    """Прогон одной конфигурации Whisper по корпусу."""

    label: str
    model: str
    beam_size: int
    prompt: bool
    cpu_threads: int
    machine: str
    load_seconds: float = 0.0
    first_call_seconds: float = 0.0
    memory_before_mb: float = 0.0
    peak_memory_mb: float = 0.0
    results: list[Recognition] = field(default_factory=list)


def recognize_corpus(args: argparse.Namespace) -> None:
    """Распознаёт все записи корпуса (или с фильтром) одной конфигурацией."""
    clips = [Clip(**item) for item in json.loads((args.corpus / "manifest.json").read_text())]
    clips = [clip for clip in clips if _selected(clip, args.formats, args.sources)]
    settings = SpeechToTextSettings(
        _env_file=None,
        model=args.model,
        cache_dir=MODELS_DIR,
        beam_size=args.beam_size,
        cpu_threads=args.threads,
        domain_prompt=not args.no_prompt,
        warm_up_on_startup=False,
    )
    run = RecognitionRun(
        label=args.label or f"{args.model} beam={args.beam_size} prompt={not args.no_prompt}",
        model=args.model,
        beam_size=args.beam_size,
        prompt=not args.no_prompt,
        cpu_threads=args.threads,
        machine=f"{platform.machine()} {platform.processor() or platform.system()}",
        memory_before_mb=peak_memory_mb(),
    )
    started = time.perf_counter()
    model = load_whisper_model(settings)
    run.load_seconds = time.perf_counter() - started
    stt = WhisperSpeechToText(settings, load_model=lambda _: model)
    asyncio.run(_recognize_all(stt, clips, args.corpus, run))
    run.peak_memory_mb = peak_memory_mb()
    args.out.write_text(json.dumps(asdict(run), ensure_ascii=False, indent=1))
    print(_summary_line(run))


def _selected(clip: Clip, formats: Sequence[str] | None, sources: Sequence[str] | None) -> bool:
    negative = clip.source.startswith("negative")
    return (formats is None or clip.audio_format in formats) and (
        sources is None or negative or clip.source in sources
    )


async def _recognize_all(
    stt: WhisperSpeechToText, clips: Sequence[Clip], corpus: Path, run: RecognitionRun
) -> None:
    for index, clip in enumerate(clips):
        data = (corpus / clip.path).read_bytes()
        started = time.perf_counter()
        hypothesis = await stt.transcribe(AudioClip(data, f"audio/{clip.audio_format}"))
        latency = time.perf_counter() - started
        if index == 0:
            run.first_call_seconds = latency
        run.results.append(
            Recognition(
                clip.path,
                clip.source,
                clip.audio_format,
                clip.text,
                hypothesis,
                clip.seconds,
                latency,
            )
        )


# --- Задержка вперемешку -------------------------------------------------------------------------


def compare_latency(args: argparse.Namespace) -> None:
    """Задержка нескольких моделей на одних и тех же записях по очереди.

    Модели загружены одновременно и распознают каждую запись друг за другом, поэтому
    фоновая нагрузка машины (сборки, другие процессы) достаётся всем поровну.
    """
    clips = [Clip(**item) for item in json.loads((args.corpus / "manifest.json").read_text())]
    clips = [clip for clip in clips if clip.text and _selected(clip, args.formats, args.sources)]
    recognizers = {spec: _recognizer_for(spec, args.threads) for spec in args.configs}
    latencies: dict[str, list[float]] = {spec: [] for spec in args.configs}
    load_before = os.getloadavg()[0]
    asyncio.run(_interleaved(recognizers, clips, args.corpus, latencies))
    print(
        f"Записей: {len(clips)}, потоков: {args.threads}, load average "
        f"{load_before:.1f} → {os.getloadavg()[0]:.1f}"
    )
    print("| Модель:луч | p50, с | p95, с | среднее, с |")
    print("|---|---|---|---|")
    for spec, values in latencies.items():
        print(
            f"| {spec} | {statistics.median(values):.2f} | "
            f"{percentile(values, PERCENTILE_95):.2f} | {statistics.mean(values):.2f} |"
        )


def _recognizer_for(spec: str, threads: int) -> WhisperSpeechToText:
    """`large-v3-turbo:5` → распознаватель этой модели с лучом 5 (модель грузится сразу)."""
    model_name, beam_size = spec.rsplit(":", 1)
    settings = SpeechToTextSettings(
        _env_file=None,
        model=model_name,
        cache_dir=MODELS_DIR,
        beam_size=int(beam_size),
        cpu_threads=threads,
        warm_up_on_startup=False,
    )
    model = load_whisper_model(settings)
    return WhisperSpeechToText(settings, load_model=lambda _: model)


async def _interleaved(
    recognizers: dict[str, WhisperSpeechToText],
    clips: Sequence[Clip],
    corpus: Path,
    latencies: dict[str, list[float]],
) -> None:
    for clip in clips:
        audio = AudioClip((corpus / clip.path).read_bytes(), f"audio/{clip.audio_format}")
        for spec, stt in recognizers.items():
            started = time.perf_counter()
            await stt.transcribe(audio)
            latencies[spec].append(time.perf_counter() - started)


# --- Отчёт -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scores:
    """Качество и скорость на наборе записей с речью."""

    clips: int
    exact: float
    wer: float
    cer: float
    latency_p50: float
    latency_p95: float
    false_speech: int


def score(results: Sequence[Recognition]) -> Scores:
    """Точные совпадения, WER и CER по корпусу, задержка, «речь» в тишине и шуме."""
    speech = [result for result in results if result.reference]
    references = [comparable(result.reference) for result in speech]
    hypotheses = [comparable(result.hypothesis) for result in speech]
    word_errors = sum(
        edit_distance(ref.split(), hyp.split())
        for ref, hyp in zip(references, hypotheses, strict=True)
    )
    char_errors = sum(
        edit_distance(ref.replace(" ", ""), hyp.replace(" ", ""))
        for ref, hyp in zip(references, hypotheses, strict=True)
    )
    latencies = [result.latency for result in speech]
    return Scores(
        clips=len(speech),
        exact=sum(ref == hyp for ref, hyp in zip(references, hypotheses, strict=True))
        / len(speech),
        wer=word_errors / sum(len(ref.split()) for ref in references),
        cer=char_errors / sum(len(ref.replace(" ", "")) for ref in references),
        latency_p50=statistics.median(latencies),
        latency_p95=percentile(latencies, PERCENTILE_95),
        false_speech=sum(1 for result in results if not result.reference and result.hypothesis),
    )


def _summary_line(run: RecognitionRun) -> str:
    scores = score(run.results)
    return (
        f"{run.label}: точно {scores.exact:.1%}, WER {scores.wer:.1%}, CER {scores.cer:.1%}, "
        f"p50 {scores.latency_p50:.2f} с, p95 {scores.latency_p95:.2f} с, "
        f"загрузка {run.load_seconds:.1f} с, RSS {run.peak_memory_mb:.0f} МБ"
    )


def _load_run(data: dict[str, Any]) -> RecognitionRun:
    results = [Recognition(**item) for item in data.pop("results")]
    return RecognitionRun(**data, results=results)


def print_report(paths: Sequence[Path]) -> None:
    """Таблицы Markdown: синтез Silero, конфигурации Whisper, разбивка по источникам."""
    runs = []
    for path in paths:
        data = json.loads(path.read_text())
        if "results" in data:
            runs.append(_load_run(data))
        else:
            _print_synthesis(SynthesisReport(**data))
    if runs:
        _print_recognition(runs)


def _print_recognition(runs: Sequence[RecognitionRun]) -> None:
    print(
        "| Конфигурация | Записей | Точно | WER | CER | p50, с | p95, с | Первая, с | "
        "Загрузка, с | RSS, МБ | Речь в тишине/шуме |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for run in runs:
        scores = score(run.results)
        negatives = sum(1 for result in run.results if not result.reference)
        print(
            f"| {run.label} | {scores.clips} | {scores.exact:.1%} | {scores.wer:.1%} | "
            f"{scores.cer:.1%} | {scores.latency_p50:.2f} | {scores.latency_p95:.2f} | "
            f"{run.first_call_seconds:.2f} | {run.load_seconds:.1f} | "
            f"{run.peak_memory_mb:.0f} | {scores.false_speech} из {negatives} |"
        )
    for run in runs:
        _print_breakdown(run)


def _print_breakdown(run: RecognitionRun) -> None:
    groups: dict[str, list[Recognition]] = defaultdict(list)
    for result in run.results:
        if result.reference:
            groups[f"{result.source} / {result.audio_format}"].append(result)
    print(f"\n{run.label}: по источникам")
    for name, group in sorted(groups.items()):
        scores = score(group)
        print(f"- {name}: точно {scores.exact:.0%}, WER {scores.wer:.1%}")
    misses = [
        result
        for result in run.results
        if comparable(result.reference) != comparable(result.hypothesis)
    ]
    print(f"\n{run.label}: расхождения ({len(misses)})")
    for result in misses:
        print(f"- [{result.source}/{result.audio_format}] {result.reference} → {result.hypothesis}")


def _print_synthesis(report: SynthesisReport) -> None:
    print(
        f"Silero: загрузка {report.load_seconds:.2f} с, первая озвучка "
        f"{report.first_call_seconds:.2f} с, RSS {report.peak_memory_mb:.0f} МБ, "
        f"ответ OGG {statistics.median(report.reply_bytes) / 1024:.0f} КБ (медиана)"
    )
    print("| Голос | p50, с | p95, с | Длительность речи p50, с | RTF |")
    print("|---|---|---|---|---|")
    for voice, values in report.latencies.items():
        durations = report.audio_seconds[voice]
        print(
            f"| {voice} | {statistics.median(values):.2f} | "
            f"{percentile(values, PERCENTILE_95):.2f} | "
            f"{statistics.median(durations):.1f} | {sum(values) / sum(durations):.2f} |"
        )


# --- Командная строка ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Замер голосового контура: Silero → Whisper")
    commands = parser.add_subparsers(dest="command", required=True)
    corpus = commands.add_parser("corpus", help="озвучить и перекодировать фразы")
    corpus.add_argument("--out", type=Path, required=True)
    corpus.add_argument("--sample-rate", type=int, default=48000, choices=(24000, 48000))
    recognize = commands.add_parser("recognize", help="распознать корпус одной конфигурацией")
    recognize.add_argument("--corpus", type=Path, required=True)
    recognize.add_argument("--out", type=Path, required=True)
    recognize.add_argument("--model", default=DEFAULT_WHISPER_MODEL)
    recognize.add_argument("--beam-size", type=int, default=DEFAULT_BEAM_SIZE)
    recognize.add_argument("--threads", type=int, default=DEFAULT_STT_CPU_THREADS)
    recognize.add_argument("--no-prompt", action="store_true", help="без подсказки декодеру")
    recognize.add_argument("--formats", nargs="*", choices=tuple(FFMPEG_FORMATS))
    recognize.add_argument("--sources", nargs="*", help="например silero-xenia say-milena")
    recognize.add_argument("--label")
    latency = commands.add_parser("latency", help="задержка моделей вперемешку на одних записях")
    latency.add_argument("--corpus", type=Path, required=True)
    latency.add_argument("--configs", nargs="+", required=True, help="модель:луч, напр. small:5")
    latency.add_argument("--threads", type=int, default=DEFAULT_STT_CPU_THREADS)
    latency.add_argument("--formats", nargs="*", choices=tuple(FFMPEG_FORMATS))
    latency.add_argument("--sources", nargs="*")
    report = commands.add_parser("report", help="таблицы Markdown по результатам")
    report.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args()
    if args.command == "corpus":
        build_corpus(args.out, cast(SileroSampleRate, args.sample_rate))
    elif args.command == "recognize":
        recognize_corpus(args)
    elif args.command == "latency":
        compare_latency(args)
    else:
        print_report(args.results)


if __name__ == "__main__":
    main()
