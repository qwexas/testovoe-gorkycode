"use client";

import { useState } from "react";

import { type ServerHealth, useServerHealth } from "@/hooks/use-server-health";
import { cn } from "@/lib/cn";
import type { HealthChecks } from "@/types/api";

import { Tooltip } from "./ui/tooltip";

type Tone = "neutral" | "success" | "warning" | "danger";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "text-fg-muted",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
};

/**
 * Пиксельные глифы 5×5: у каждого статуса своя форма, а не только цвет (WCAG 1.4.1) —
 * на узком экране текст статуса скрыт и остаётся только глиф. «#» — закрашенный пиксель.
 */
const TONE_GLYPHS: Record<Tone, readonly string[]> = {
  // полый квадрат — проверка идёт
  neutral: [".....", ".###.", ".#.#.", ".###.", "....."],
  // сплошной квадрат — всё работает
  success: [".....", ".###.", ".###.", ".###.", "....."],
  // восклицательный знак — работает с перебоями
  warning: ["..#..", "..#..", "..#..", ".....", "..#.."],
  // крест — недоступен
  danger: ["#...#", ".#.#.", "..#..", ".#.#.", "#...#"],
};

function glyphPixels(rows: readonly string[]): Array<{ x: number; y: number }> {
  return rows.flatMap((row, y) => [...row].flatMap((cell, x) => (cell === "#" ? [{ x, y }] : [])));
}

function StatusGlyph({ tone }: { tone: Tone }) {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 5 5"
      aria-hidden="true"
      shapeRendering="crispEdges"
      className={cn("shrink-0", TONE_CLASSES[tone])}
    >
      {glyphPixels(TONE_GLYPHS[tone]).map(({ x, y }) => (
        <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill="currentColor" />
      ))}
    </svg>
  );
}

const CHECK_LABELS: Record<keyof HealthChecks, string> = {
  db: "База данных",
  llm: "Разбор запросов",
  stt: "Распознавание речи",
  tts: "Озвучка ответов",
};

const CHECK_VALUES: Record<HealthChecks[keyof HealthChecks], string> = {
  ok: "работает",
  fail: "не отвечает",
  unknown: "нет данных",
};

function describe(health: ServerHealth): { label: string; tone: Tone; details: string[] } {
  switch (health.status) {
    case "checking":
      return { label: "Проверяем сервер…", tone: "neutral", details: [] };
    case "offline":
      return { label: "Сервер недоступен", tone: "danger", details: [health.error.message] };
    case "online":
    case "degraded": {
      const details = (Object.keys(CHECK_LABELS) as Array<keyof HealthChecks>).map(
        (key) => `${CHECK_LABELS[key]}: ${CHECK_VALUES[health.health.checks[key]]}`,
      );
      return health.status === "online"
        ? { label: "Сервер работает", tone: "success", details }
        : { label: "Сервер работает с перебоями", tone: "warning", details };
    }
  }
}

/** Индикатор статуса сервера в шапке. Нажатие — проверить ещё раз. */
export function ServerStatus() {
  const { health, isChecking, recheck } = useServerHealth();
  const { label, tone, details } = describe(health);

  // Озвучиваем только смену статуса, а не первый результат при загрузке страницы.
  const [previousStatus, setPreviousStatus] = useState(health.status);
  const [announcement, setAnnouncement] = useState("");
  if (health.status !== previousStatus) {
    setPreviousStatus(health.status);
    if (previousStatus !== "checking") setAnnouncement(label);
  }

  return (
    <>
      <Tooltip
        content={
          <>
            {details.length > 0 ? (
              <ul className="grid gap-0.5">
                {details.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : null}
            <p className={cn(details.length > 0 && "mt-1.5", "text-fg-muted")}>
              Нажмите, чтобы проверить снова
            </p>
          </>
        }
      >
        <button
          type="button"
          onClick={recheck}
          aria-busy={isChecking || undefined}
          className="inline-flex h-10 min-w-10 items-center justify-center gap-2 rounded-lg px-2.5 font-mono text-xs text-fg-muted transition-colors hover:bg-surface-raised hover:text-fg aria-busy:cursor-progress"
        >
          <StatusGlyph tone={tone} />
          <span className="sr-only sm:not-sr-only">{label}</span>
          <span className="sr-only">. Проверить снова</span>
        </button>
      </Tooltip>
      <span role="status" className="sr-only">
        {announcement}
      </span>
    </>
  );
}
