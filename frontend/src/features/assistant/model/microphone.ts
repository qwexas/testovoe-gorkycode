/** Проблемы с микрофоном и записью → строка лога. Текстовый ввод работает всегда. */
import type { RecorderErrorCode, Recording } from "@/features/voice/lib/recorder";

import type { FailureCopy } from "./failures";

/** Короче этого — случайное нажатие, отправлять нечего. */
const MIN_RECORDING_MS = 400;

export function describeRecorderError(code: RecorderErrorCode): FailureCopy {
  switch (code) {
    case "insecure":
      return {
        text: "Микрофон работает только на странице с https://. Откройте сайт по защищённому адресу или пишите текстом.",
        kind: "microphone",
        actions: [{ type: "type" }],
      };
    case "unsupported":
      return {
        text: "Этот браузер не умеет записывать звук. Пишите текстом или откройте сайт в Chrome или Safari.",
        kind: "microphone",
        actions: [{ type: "type" }],
      };
    case "denied":
      return {
        text: "Нет доступа к микрофону. Разрешите его в настройках сайта (значок у адресной строки) и нажмите «говорить» ещё раз.",
        kind: "microphone",
        actions: [{ type: "record" }, { type: "type" }],
      };
    case "no-device":
      return {
        text: "Микрофон не найден. Подключите его или пишите текстом.",
        kind: "microphone",
        actions: [{ type: "type" }],
      };
    case "busy":
      return {
        text: "Микрофон занят другим приложением. Закройте его и нажмите «говорить» ещё раз.",
        kind: "microphone",
        actions: [{ type: "record" }, { type: "type" }],
      };
    case "failed":
      return {
        text: "Запись не получилась. Попробуйте ещё раз или напишите текстом.",
        kind: "microphone",
        actions: [{ type: "record" }, { type: "type" }],
      };
  }
}

/** Запись, которую нет смысла отправлять на распознавание: что сказать вместо этого. */
export function rejectRecording(recording: Recording): FailureCopy | null {
  if (recording.durationMs < MIN_RECORDING_MS || recording.blob.size === 0) {
    return {
      text: "Запись слишком короткая. Нажмите «говорить» и скажите фразу целиком.",
      kind: "not-heard",
      actions: [{ type: "record" }, { type: "type" }],
    };
  }
  if (recording.reason === "no-speech" && !recording.audible) {
    return {
      text: "Не слышу микрофон: за несколько секунд — ни звука. Проверьте, что он включён, или напишите текстом.",
      kind: "microphone",
      actions: [{ type: "record" }, { type: "type" }],
    };
  }
  return null;
}
