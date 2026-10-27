"use client";

import { tty } from "@/components/ui/tty";
import { AsciiSphere } from "@/features/assistant/components/ascii-sphere";
import type { Assistant } from "@/features/assistant/hooks/use-assistant";
import { LevelMeter } from "@/features/voice/components/level-meter";
import { cn } from "@/lib/cn";

/**
 * Панель-монитор: ASCII-сфера голоса и крупная строка состояния. На телефоне — узкая
 * полоса сверху со строкой «дальше: 17:00 …» из плана дня.
 */
export function SpherePane({
  assistant,
  upcoming,
}: {
  assistant: Assistant;
  /** «17:00 Разбор макетов» — ближайшая запись из плана дня. */
  upcoming: string | null;
}) {
  const { sphere } = assistant;
  return (
    <section aria-labelledby="sphere-title" className={cn(tty.pane, "lg:col-start-1")}>
      <h2 id="sphere-title" className={tty.paneTitle}>
        сфера
      </h2>
      <div className="flex items-center gap-3 px-3 pt-3 pb-2 sm:gap-6 sm:px-5 lg:pt-4">
        <AsciiSphere
          mode={sphere}
          levelRef={assistant.levelRef}
          className="h-24 w-32 shrink-0 sm:h-36 sm:w-52 lg:h-52 lg:w-80"
        />
        <div className="grid min-w-0 flex-1 gap-1.5">
          <p
            role="status"
            className={cn(
              tty.bigState,
              "text-balance",
              sphere === "error" && tty.danger,
              sphere === "waiting" && tty.wait,
            )}
          >
            {assistant.headline}
          </p>
          <LevelMeter
            levelRef={assistant.levelRef}
            recording={assistant.recorder.status === "recording"}
            seconds={assistant.recordingSeconds}
          />
          <p className={cn(tty.muted, "text-xs text-pretty sm:text-sm")}>{assistant.subline}</p>
          {upcoming ? (
            <p className="text-xs text-pretty sm:text-sm lg:hidden">
              <span className={tty.muted}>дальше: </span>
              {upcoming}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
