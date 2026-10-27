/**
 * Детектор конца фразы для автостопа записи (решение Q26): запись останавливается после
 * ~1,2 с тишины. Порог речи считается от шума комнаты: первые доли секунды — калибровка,
 * дальше уровень шума медленно подстраивается в паузах. Чистая логика без Web Audio:
 * на вход — громкость кадра (RMS 0..1) и время, на выход — что сейчас происходит.
 */

export type SilenceDetectorConfig = {
  /** Сколько тишины после речи считать концом фразы. */
  silenceMs: number;
  /** Сколько первых миллисекунд слушать шум комнаты. */
  calibrationMs: number;
  /** Если речь так и не началась — остановиться. */
  noSpeechMs: number;
  /** Сколько громкость должна держаться выше порога, чтобы считаться речью (не щелчок). */
  speechHoldMs: number;
  /** Порог речи = шум × ratio, но в пределах [minThreshold, maxThreshold]. */
  thresholdRatio: number;
  minThreshold: number;
  maxThreshold: number;
};

export const DEFAULT_SILENCE_CONFIG: SilenceDetectorConfig = {
  silenceMs: 1_200,
  calibrationMs: 300,
  noSpeechMs: 7_000,
  speechHoldMs: 120,
  thresholdRatio: 3,
  minThreshold: 0.008,
  // Потолок порога: если человек заговорил сразу и калибровка услышала речь, а не шум,
  // обычная речь у микрофона (RMS 0,05–0,3) всё равно окажется выше порога.
  maxThreshold: 0.05,
};

export type SilenceVerdict =
  /** Слушаем шум комнаты. */
  | "calibrating"
  /** Речи ещё не было. */
  | "waiting"
  /** Идёт речь. */
  | "speech"
  /** Пауза внутри фразы — ещё не конец. */
  | "pause"
  /** Тишина после речи дольше `silenceMs` — фраза закончилась. */
  | "end-of-speech"
  /** За `noSpeechMs` речь так и не началась. */
  | "no-speech";

export type SilenceDetector = {
  push: (rms: number, elapsedMs: number) => SilenceVerdict;
  /** Самый громкий кадр записи: отличает «молчали» от «микрофон не слышит». */
  readonly peak: number;
  readonly heardSpeech: boolean;
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Нижняя пятая часть калибровочных кадров — устойчивая оценка шума. */
function noiseFloor(samples: number[]): number {
  if (samples.length === 0) return 0;
  const sorted = [...samples].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) * 0.2)] ?? 0;
}

export function createSilenceDetector(
  config: SilenceDetectorConfig = DEFAULT_SILENCE_CONFIG,
): SilenceDetector {
  const calibration: number[] = [];
  let floor: number | null = null;
  let peak = 0;
  let heardSpeech = false;
  let aboveSince: number | null = null;
  let belowSince: number | null = null;

  const threshold = () =>
    clamp((floor ?? 0) * config.thresholdRatio, config.minThreshold, config.maxThreshold);

  function push(rms: number, elapsedMs: number): SilenceVerdict {
    peak = Math.max(peak, rms);

    if (floor === null) {
      calibration.push(rms);
      if (elapsedMs < config.calibrationMs) return "calibrating";
      floor = noiseFloor(calibration);
    }

    if (rms >= threshold()) {
      belowSince = null;
      aboveSince ??= elapsedMs;
      if (elapsedMs - aboveSince >= config.speechHoldMs) heardSpeech = true;
      return heardSpeech ? "speech" : "waiting";
    }

    aboveSince = null;
    // В тишине шум комнаты подстраивается: включили вентилятор — порог подрос.
    floor = floor * 0.95 + rms * 0.05;

    if (heardSpeech) {
      belowSince ??= elapsedMs;
      return elapsedMs - belowSince >= config.silenceMs ? "end-of-speech" : "pause";
    }
    return elapsedMs >= config.noSpeechMs ? "no-speech" : "waiting";
  }

  return {
    push,
    get peak() {
      return peak;
    },
    get heardSpeech() {
      return heardSpeech;
    },
  };
}

/** Громкость для интерфейса 0..1 по шкале децибел: −55 дБ — тишина, −10 дБ — крик. */
export function levelFromRms(rms: number): number {
  const decibels = 20 * Math.log10(Math.max(rms, 1e-5));
  return clamp((decibels + 55) / 45, 0, 1);
}
