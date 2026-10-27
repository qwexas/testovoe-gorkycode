/**
 * Формат записи: Chrome и Firefox пишут webm/opus, Safari — mp4/aac (решение Q34).
 * Сервер принимает webm/opus, ogg, mp4/aac и wav.
 */
const CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4;codecs=mp4a.40.2",
  "audio/mp4",
  "audio/ogg;codecs=opus",
  "audio/aac",
] as const;

/** Первый формат из списка, который умеет MediaRecorder; undefined — пусть выберет сам. */
export function pickRecordingMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return undefined;
  }
  return CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type));
}

/** Имя файла для multipart: по расширению сервер тоже понимает формат. */
export function recordingFileName(mimeType: string): string {
  const type = mimeType.toLowerCase();
  if (type.includes("webm")) return "speech.webm";
  if (type.includes("mp4") || type.includes("aac") || type.includes("m4a")) return "speech.m4a";
  if (type.includes("ogg")) return "speech.ogg";
  if (type.includes("wav")) return "speech.wav";
  return "speech.webm";
}
