import { Composer } from "./composer";
import { VoiceSphere } from "./voice-sphere";

/** Фразы из ТЗ: по одной на каждое ключевое действие. */
const EXAMPLE_PHRASES = [
  "Напомни мне завтра в 10 утра позвонить Ивану",
  "Добавь встречу с командой завтра в 15:00",
  "Что у меня сегодня?",
  "Найди задачу про презентацию",
];

/** Основная зона: сфера голоса, диалог и ввод. Диалог появится вместе с /api/chat. */
export function AssistantStage() {
  return (
    <section
      aria-labelledby="assistant-title"
      className="flex min-h-[28rem] flex-1 flex-col items-center rounded-3xl border border-border bg-surface px-4 pt-10 pb-4 sm:px-8 sm:pt-14"
    >
      <VoiceSphere />
      <h1
        id="assistant-title"
        className="mt-8 max-w-[20ch] text-center text-3xl leading-tight font-semibold tracking-tight text-balance sm:text-4xl"
      >
        Скажите, что запланировать
      </h1>
      <p className="mt-3 max-w-[48ch] text-center text-pretty text-fg-muted">
        Горький ставит задачи, напоминания и встречи, рассказывает о планах на день и находит
        прошлые записи.
      </p>

      <h2 className="sr-only">Примеры фраз</h2>
      <ul className="mt-6 flex max-w-2xl flex-wrap justify-center gap-2">
        {EXAMPLE_PHRASES.map((phrase) => (
          <li
            key={phrase}
            className="rounded-full border border-border px-3 py-1.5 text-sm text-fg-muted"
          >
            «{phrase}»
          </li>
        ))}
      </ul>

      <div className="mt-auto w-full max-w-2xl pt-10">
        <Composer />
      </div>
    </section>
  );
}
