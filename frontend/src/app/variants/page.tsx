import type { Metadata } from "next";
import Link from "next/link";

import { MAIN_CONTENT_ID, SkipLink } from "@/components/skip-link";
import { DEMO_STATES } from "@/features/design-variants/model/states";

export const metadata: Metadata = { title: "Варианты дизайна — Горький" };

const DIRECTIONS = [
  {
    id: 1,
    name: "Консоль",
    idea: "Сессия tmux: сфера из символов, лог разговора и план дня в панелях, статусная строка внизу. В светлой теме — распечатка на перфорированной бумаге.",
  },
  {
    id: 2,
    name: "Рукопись",
    idea: "Книжный разворот: слева содержание дня и гравюра-сфера, справа разговор. Горький пишет фиолетовыми чернилами антиквой.",
  },
  {
    id: 3,
    name: "Шар",
    idea: "Пиксельное небо и воздушный шар из программы GORKYCODE. Разговор — в окне диалога, как в RPG: уточнения и выбор — меню с курсором.",
  },
] as const;

/** Оглавление демо-страниц КТ2: три направления главного экрана. */
export default function VariantsIndexPage() {
  return (
    <>
      <SkipLink />
      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="mx-auto w-full max-w-3xl px-4 py-12 outline-none sm:px-6"
      >
        <h1 className="text-3xl leading-tight font-semibold tracking-tight text-balance">
          Горький: три варианта главного экрана
        </h1>
        <p className="mt-3 max-w-[60ch] text-pretty text-fg-muted">
          Все три на одних мок-данных. Состояния переключаются панелью сверху или параметром{" "}
          <code className="font-mono text-sm">?state=</code>, тема — в интерфейсе варианта.
        </p>
        <ol className="mt-8 grid gap-4">
          {DIRECTIONS.map(({ id, name, idea }) => (
            <li key={id} className="rounded-2xl border border-border bg-surface p-5">
              <h2 className="text-xl font-semibold">
                <Link
                  href={`/variants/${id}`}
                  className="text-accent-text underline-offset-4 hover:underline"
                >
                  {id}. {name}
                </Link>
              </h2>
              <p className="mt-2 text-pretty text-fg-muted">{idea}</p>
            </li>
          ))}
        </ol>
        <h2 className="mt-10 text-lg font-semibold">Состояния</h2>
        <ul className="mt-3 flex flex-wrap gap-2">
          {DEMO_STATES.map(({ id, label }) => (
            <li key={id}>
              <code className="rounded-md bg-surface-raised px-2 py-1 font-mono text-sm">
                ?state={id}
              </code>{" "}
              <span className="text-sm text-fg-muted">{label}</span>
            </li>
          ))}
        </ul>
      </main>
    </>
  );
}
