/**
 * Быстрые ответы на вопрос ассистента. В контракте их нет и не нужно: они выводятся из
 * `pending.expects`, а время по умолчанию взято из решения Q31 (утро 9:00, день 13:00,
 * вечер 19:00). Каждая кнопка отправляет обычную реплику — так же, как её сказали бы
 * голосом, — поэтому сервер разбирает её тем же путём.
 */
import type { AssistantReply, Pending } from "@/types/api";

export type QuickReply = { label: string; text: string; tone?: "danger" };

const WEEKDAYS: QuickReply[] = [
  { label: "понедельник", text: "в понедельник" },
  { label: "вторник", text: "во вторник" },
  { label: "среда", text: "в среду" },
  { label: "четверг", text: "в четверг" },
  { label: "пятница", text: "в пятницу" },
];

export function quickReplies(reply: AssistantReply): QuickReply[] {
  const pending = reply.pending;
  switch (pending?.expects) {
    case "time":
      return [
        { label: "утром, 9:00", text: "в 9:00" },
        { label: "днём, 13:00", text: "в 13:00" },
        { label: "вечером, 19:00", text: "в 19:00" },
      ];
    case "date":
      return pending.question.includes("недел")
        ? WEEKDAYS
        : [
            { label: "сегодня", text: "сегодня" },
            { label: "завтра", text: "завтра" },
            { label: "послезавтра", text: "послезавтра" },
          ];
    case "datetime":
      return [
        { label: "через час", text: "через час" },
        { label: "сегодня, 19:00", text: "сегодня в 19:00" },
        { label: "завтра, 9:00", text: "завтра в 9:00" },
      ];
    case "confirm":
      if (reply.conflicts.length > 0) {
        return [
          { label: "да, всё равно", text: "да" },
          { label: "нет", text: "нет" },
        ];
      }
      return [
        { label: "да, удалить", text: "да", tone: "danger" },
        { label: "нет, оставить", text: "нет" },
      ];
    default:
      return [];
  }
}

/** Что «говорит» кнопка варианта в списке совпадений. Проверено на живом разборе. */
export function choiceText(index: number): string {
  return `вариант ${index}`;
}

/** Подсказка, что ответить можно и голосом. */
export function voiceHint(pending: Pending | null): string | null {
  switch (pending?.expects) {
    case "time":
      return "Или назовите время: «в 16:30»";
    case "date":
      return "Или назовите день: «в пятницу»";
    case "datetime":
      return "Или скажите, когда: «завтра в 10»";
    case "title":
      return "Скажите или напишите, как назвать";
    case "choice":
      return "Или скажите номер: «второй вариант»";
    case "confirm":
      return "Или скажите «да» или «нет»";
    default:
      return null;
  }
}

/** Пример в строке ввода под ожидаемый ответ. */
export function inputPlaceholder(pending: Pending | null): string {
  switch (pending?.expects) {
    case "time":
      return "например, в 16:30";
    case "date":
      return "например, в пятницу";
    case "datetime":
      return "например, завтра в 10";
    case "title":
      return "например, купить билеты";
    case "choice":
      return "например, второй вариант";
    case "confirm":
      return "да или нет";
    default:
      return "что у меня завтра?";
  }
}
