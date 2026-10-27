import { getAudioContext } from "@/lib/audio";

/** Две ноты «динь-дон»: тон — частота в Гц, начало и длина — в секундах. */
const NOTES = [
  { frequency: 1046.5, start: 0, duration: 0.22 },
  { frequency: 784, start: 0.24, duration: 0.42 },
] as const;

/**
 * Короткий сигнал напоминания через Web Audio — без звуковых файлов. Играет, только если
 * звук уже разбужен жестом пользователя; возвращает, прозвучал ли сигнал.
 */
export function playChime(): boolean {
  const audio = getAudioContext();
  if (!audio || audio.state !== "running") return false;
  const startAt = audio.currentTime + 0.02;
  for (const note of NOTES) {
    const oscillator = audio.createOscillator();
    const gain = audio.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = note.frequency;
    const begin = startAt + note.start;
    const end = begin + note.duration;
    gain.gain.setValueAtTime(0, begin);
    gain.gain.linearRampToValueAtTime(0.18, begin + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, end);
    oscillator.connect(gain);
    gain.connect(audio.destination);
    oscillator.start(begin);
    oscillator.stop(end + 0.02);
  }
  return true;
}
