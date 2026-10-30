/**
 * системные голоса могут читать кавычки и скобки вслух — убираем их перед озвучкой
 * серверному Silero передаём исходный текст
 */

const QUOTES = /[«»„“”‟"'`‘’‚‹›]/g;
const DASH_BETWEEN = /\s+[—–-]\s+|\s*[—–]\s*/g;
const BRACKETS = /\s*[()[\]{}]\s*/g;
const SYMBOLS = /[\\/|*_#~^<>•·→←=+]/g;
const ELLIPSIS = /…/g;
const SPACES = /[ \t ]+/g;
const COMMA_RUNS = /\s*,(?:\s*,)+/g;
const SPACE_BEFORE_PUNCTUATION = /\s+([,.:;!?])/g;
const COMMA_BEFORE_STOP = /,\s*([.:;!?])/g;
const LEADING_COMMA = /(^|[\n.!?:]\s*),\s*/g;

export function textForBrowserSpeech(text: string): string {
  return text
    .replace(QUOTES, "")
    .replace(ELLIPSIS, ".")
    .replace(DASH_BETWEEN, ", ")
    .replace(BRACKETS, ", ")
    .replace(SYMBOLS, " ")
    .replace(SPACES, " ")
    .replace(COMMA_RUNS, ",")
    .replace(SPACE_BEFORE_PUNCTUATION, "$1")
    .replace(COMMA_BEFORE_STOP, "$1")
    .replace(LEADING_COMMA, "$1")
    .replace(/,\s*$/, "")
    .trim();
}
