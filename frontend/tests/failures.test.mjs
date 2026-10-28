import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Эти модули имеют только импорты типов. Выполняем исходный обработчик без браузера
// и без отдельного тестового сборщика; TypeScript уже есть в devDependencies проекта.
async function loadTypeScript(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}

const { apiErrorFromResponse } = await loadTypeScript("../src/lib/api/errors.ts");
const { describeRequestFailure } = await loadTypeScript(
  "../src/features/assistant/model/failures.ts",
);

function describe(code, message, via = "voice", status = 422) {
  const error = apiErrorFromResponse(new Response(null, { status }), {
    error: { code, message },
  });
  return describeRequestFailure(error, via, null);
}

for (const via of ["voice", "text"]) {
  test(`invalid command date keeps the server message (${via})`, () => {
    const message = "Некорректная дата. Укажите существующую дату.";
    const failure = describe("validation_error", message, via);
    assert.equal(failure.text, message);
    assert.equal(failure.kind, "error");
    assert.deepEqual(
      failure.actions,
      via === "voice" ? [{ type: "record" }, { type: "type" }] : [],
    );
  });
}

test("other command validation errors also keep the server message", () => {
  const message = "Дата выходит за допустимый диапазон.";
  assert.equal(describe("validation_error", message).text, message);
});

test("missing audio field keeps its specific validation message", () => {
  const message = "Проверьте данные запроса. Поле: «audio».";
  assert.equal(describe("validation_error", message).text, message);
});

for (const code of ["speech_not_recognized", "audio_unsupported", "audio_too_large"]) {
  test(`audio failure still has recording guidance (${code})`, () => {
    const failure = describe(
      code,
      "Ошибка аудио",
      "voice",
      code === "audio_unsupported" ? 415 : 422,
    );
    assert.equal(failure.kind, "not-heard");
    assert.match(failure.text, /Не расслышал/);
    assert.ok(failure.actions.some((action) => action.type === "type"));
  });
}
