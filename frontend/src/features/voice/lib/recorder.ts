/**
 * Запись голоса (решение Q26): MediaRecorder пишет фразу, AnalyserNode меряет громкость
 * для сферы и автостопа. Остановка — после ~1,2 с тишины, вручную, по пределу 60 с или
 * если речь так и не началась. Отмена (Esc) выбрасывает запись. Микрофон освобождается
 * сразу после остановки; аудио никуда не сохраняется (решение Q35).
 */
import { getAudioContext } from "@/lib/audio";

import { pickRecordingMimeType } from "./recording-format";
import {
  DEFAULT_SILENCE_CONFIG,
  type SilenceDetectorConfig,
  createSilenceDetector,
  levelFromRms,
} from "./silence-detector";

/** Сервер принимает до 60 с; останавливаемся чуть раньше, чтобы не упереться в предел. */
export const MAX_RECORDING_MS = 59_000;
const FRAME_MS = 50;
/** Тише этого за всю запись — микрофон, похоже, ничего не слышит. */
const AUDIBLE_PEAK = 0.01;

export type StopReason = "manual" | "silence" | "limit" | "no-speech";

export type Recording = {
  blob: Blob;
  mimeType: string;
  durationMs: number;
  reason: StopReason;
  /** Была ли в записи речь по оценке детектора (без Web Audio — всегда true). */
  heardSpeech: boolean;
  /** Было ли в записи хоть что-то громче фона. */
  audible: boolean;
};

export type RecorderErrorCode =
  /** Страница открыта не по HTTPS — браузер не даёт микрофон. */
  | "insecure"
  /** Браузер не умеет записывать звук. */
  | "unsupported"
  /** Пользователь или настройки запретили микрофон. */
  | "denied"
  /** Микрофона нет. */
  | "no-device"
  /** Микрофон занят другим приложением. */
  | "busy"
  | "failed";

export class RecorderError extends Error {
  override readonly name = "RecorderError";
  constructor(
    readonly code: RecorderErrorCode,
    options?: { cause?: unknown },
  ) {
    super(code, options);
  }
}

export type RecorderCallbacks = {
  /** Громкость 0..1 примерно 20 раз в секунду. */
  onLevel: (level: number) => void;
  onStop: (recording: Recording) => void;
  onError: (error: RecorderError) => void;
};

export type RecordingHandle = {
  /** Остановить и отдать запись. */
  stop: () => void;
  /** Остановить и выбросить запись. */
  cancel: () => void;
};

function errorFromMedia(cause: unknown): RecorderError {
  const name = cause instanceof DOMException ? cause.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return new RecorderError("denied", { cause });
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return new RecorderError("no-device", { cause });
  }
  if (name === "NotReadableError" || name === "AbortError") {
    return new RecorderError("busy", { cause });
  }
  return new RecorderError("failed", { cause });
}

function createRecorder(stream: MediaStream): MediaRecorder {
  const mimeType = pickRecordingMimeType();
  if (mimeType) {
    try {
      return new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64_000 });
    } catch {
      // Формат заявлен, но не завёлся — пусть браузер выберет сам.
    }
  }
  return new MediaRecorder(stream);
}

/** Громкость кадра — среднеквадратичное значение сигнала. */
function readRms(analyser: AnalyserNode, buffer: Float32Array<ArrayBuffer>): number {
  analyser.getFloatTimeDomainData(buffer);
  let sum = 0;
  for (const sample of buffer) sum += sample * sample;
  return Math.sqrt(sum / buffer.length);
}

/** Проверки, которые можно сделать до запроса микрофона. */
function recorderAvailability(): RecorderErrorCode | null {
  if (typeof window === "undefined") return "unsupported";
  if (!window.isSecureContext) return "insecure";
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    return "unsupported";
  }
  return null;
}

/**
 * Запрашивает микрофон и начинает запись. Бросает RecorderError, если записать нельзя;
 * ошибки во время записи приходят в `onError`.
 */
export async function startRecording(
  callbacks: RecorderCallbacks,
  config: SilenceDetectorConfig = DEFAULT_SILENCE_CONFIG,
): Promise<RecordingHandle> {
  const unavailable = recorderAvailability();
  if (unavailable) throw new RecorderError(unavailable);

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
  } catch (cause) {
    throw errorFromMedia(cause);
  }

  let recorder: MediaRecorder;
  try {
    recorder = createRecorder(stream);
  } catch (cause) {
    for (const track of stream.getTracks()) track.stop();
    throw new RecorderError("unsupported", { cause });
  }

  const chunks: Blob[] = [];
  const detector = createSilenceDetector(config);
  const startedAt = performance.now();
  let stopReason: StopReason = "manual";
  let cancelled = false;
  let finished = false;

  // Анализ громкости — если есть Web Audio. Без него работают ручная остановка и предел 60 с.
  const audio = getAudioContext();
  let source: MediaStreamAudioSourceNode | null = null;
  let analyser: AnalyserNode | null = null;
  if (audio) {
    try {
      if (audio.state === "suspended") void audio.resume().catch(() => undefined);
      source = audio.createMediaStreamSource(stream);
      analyser = audio.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
    } catch {
      source = null;
      analyser = null;
    }
  }
  const buffer = new Float32Array(analyser?.fftSize ?? 0);

  const release = () => {
    window.clearInterval(interval);
    source?.disconnect();
    for (const track of stream.getTracks()) track.stop();
    callbacks.onLevel(0);
  };

  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };
  recorder.onerror = (event) => {
    finished = true;
    release();
    callbacks.onError(new RecorderError("failed", { cause: event }));
  };
  recorder.onstop = () => {
    release();
    if (cancelled) return;
    const mimeType = recorder.mimeType || chunks[0]?.type || "audio/webm";
    callbacks.onStop({
      blob: new Blob(chunks, { type: mimeType }),
      mimeType,
      durationMs: performance.now() - startedAt,
      reason: stopReason,
      heardSpeech: analyser ? detector.heardSpeech : true,
      audible: analyser ? detector.peak >= AUDIBLE_PEAK : true,
    });
  };

  const finish = (reason: StopReason, discard = false) => {
    if (finished) return;
    finished = true;
    stopReason = reason;
    cancelled = discard;
    window.clearInterval(interval);
    if (recorder.state !== "inactive") recorder.stop();
    else release();
  };

  const interval = window.setInterval(() => {
    const elapsed = performance.now() - startedAt;
    if (elapsed >= MAX_RECORDING_MS) {
      finish("limit");
      return;
    }
    if (!analyser) return;
    const rms = readRms(analyser, buffer);
    callbacks.onLevel(levelFromRms(rms));
    const verdict = detector.push(rms, elapsed);
    if (verdict === "end-of-speech") finish("silence");
    else if (verdict === "no-speech") finish("no-speech");
  }, FRAME_MS);

  try {
    recorder.start();
  } catch (cause) {
    finished = true;
    release();
    throw new RecorderError("failed", { cause });
  }

  return {
    stop: () => finish("manual"),
    cancel: () => finish("manual", true),
  };
}
