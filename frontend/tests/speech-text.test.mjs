import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function loadTypeScript(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}

const { textForBrowserSpeech } = await loadTypeScript("../src/features/voice/lib/speech-text.ts");

test("кавычки-ёлочки и тире не читаются вслух", () => {
  assert.equal(
    textForBrowserSpeech("Встреча «Встреча с командой» — завтра, 31 октября, в 15:00."),
    "Встреча Встреча с командой, завтра, 31 октября, в 15:00.",
  );
});

test("скобки превращаются в паузу", () => {
  assert.equal(
    textForBrowserSpeech("В это время уже стоит «Планёрка» (15:00–16:00). Всё равно добавить?"),
    "В это время уже стоит Планёрка, 15:00, 16:00. Всё равно добавить?",
  );
});

test("служебные символы убираются, дефис в словах остаётся", () => {
  assert.equal(
    textForBrowserSpeech("Я когда-то ставил задачу \\ по договору / найди *её*…"),
    "Я когда-то ставил задачу по договору найди её.",
  );
});

test("обычный текст не меняется", () => {
  const text = "Во сколько напомнить? Сегодня у вас 2 дела: встреча и задача.";
  assert.equal(textForBrowserSpeech(text), text);
});

test("нет запятой в начале и перед точкой", () => {
  assert.equal(textForBrowserSpeech("«Отчёт» (сегодня)."), "Отчёт, сегодня.");
  assert.equal(textForBrowserSpeech("(14:00) Созвон"), "14:00, Созвон");
});
