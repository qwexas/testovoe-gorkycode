import { Button } from "@/components/ui/button";
import { MicIcon, SendIcon } from "@/components/ui/icons";

const SOON_NOTE_ID = "composer-soon-note";

/** Ввод текстом и голосом. На КТ1 отключён: POST /api/chat и /api/voice ещё не работают. */
export function Composer() {
  return (
    <div className="w-full">
      <form
        aria-label="Сообщение для Горького"
        className="flex items-center gap-2 rounded-2xl border border-border-strong bg-surface p-2"
      >
        <label htmlFor="composer-input" className="sr-only">
          Сообщение для Горького
        </label>
        <input
          id="composer-input"
          name="text"
          type="text"
          disabled
          placeholder="Что у меня завтра?"
          aria-describedby={SOON_NOTE_ID}
          autoComplete="off"
          className="h-11 min-w-0 flex-1 bg-transparent px-3 text-base text-fg placeholder:text-fg-muted disabled:cursor-not-allowed"
        />
        <Button type="submit" variant="ghost" size="icon" disabled aria-label="Отправить">
          <SendIcon size={20} />
        </Button>
        <Button
          variant="primary"
          size="icon"
          disabled
          aria-label="Записать голосом"
          aria-describedby={SOON_NOTE_ID}
          className="size-11 rounded-full"
        >
          <MicIcon size={20} />
        </Button>
      </form>
      <p id={SOON_NOTE_ID} className="mt-2 text-center text-sm text-fg-muted">
        Скоро: ввод текстом и голосом
      </p>
    </div>
  );
}
