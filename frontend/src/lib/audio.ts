/**
 * Общий AudioContext страницы: уровень микрофона, анализ озвучки и сигнал напоминания.
 * Браузеры запускают звук только после действия пользователя, поэтому контекст создаётся
 * и «будится» в обработчике первого жеста (`installAudioUnlock`), а не при загрузке.
 */

let context: AudioContext | null = null;

function audioContextConstructor(): typeof AudioContext | null {
  if (typeof window === "undefined") return null;
  return window.AudioContext ?? null;
}

/** Контекст, если браузер поддерживает Web Audio. Может быть ещё приостановлен. */
export function getAudioContext(): AudioContext | null {
  if (context) return context;
  const Constructor = audioContextConstructor();
  if (!Constructor) return null;
  try {
    context = new Constructor();
  } catch {
    return null;
  }
  return context;
}

/** Будит контекст. Вызывать из обработчика жеста пользователя. */
export function unlockAudio(): void {
  const audio = getAudioContext();
  if (audio && audio.state === "suspended") void audio.resume().catch(() => undefined);
}

/** Контекст можно использовать прямо сейчас (звук не будет заглушён политикой автовоспроизведения). */
export function isAudioRunning(): boolean {
  return context?.state === "running";
}

/**
 * Будит звук на первом нажатии или клавише. Заодно «прогревает» speechSynthesis:
 * Safari на iOS озвучивает только после первого вызова внутри жеста.
 */
export function installAudioUnlock(): () => void {
  let primed = false;
  const onGesture = () => {
    unlockAudio();
    if (primed || typeof window.speechSynthesis === "undefined") return;
    primed = true;
    try {
      const silent = new SpeechSynthesisUtterance("");
      silent.volume = 0;
      window.speechSynthesis.speak(silent);
    } catch {
      // Синтез речи недоступен — озвучка возьмёт аудио с сервера или промолчит.
    }
  };
  const options = { capture: true } as const;
  window.addEventListener("pointerdown", onGesture, options);
  window.addEventListener("keydown", onGesture, options);
  return () => {
    window.removeEventListener("pointerdown", onGesture, options);
    window.removeEventListener("keydown", onGesture, options);
  };
}
