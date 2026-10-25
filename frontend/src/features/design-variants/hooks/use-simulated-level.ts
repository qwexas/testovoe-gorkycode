"use client";

import { type RefObject, useEffect, useRef } from "react";

import type { SphereMode } from "../model/types";

function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

/** Детерминированный шум 0..1 по целому числу. */
function hash(n: number): number {
  const x = Math.sin(n * 127.1 + 311.7) * 43_758.5453;
  return x - Math.floor(x);
}

/**
 * Огибающая, похожая на речь: слоги ~5 в секунду, слова и короткие паузы между ними.
 * Это симуляция для демо; в продукте уровень даст AnalyserNode с микрофона.
 */
function speechEnvelope(t: number, gain: number): number {
  const syllable = Math.abs(Math.sin(t * 9.1)) ** 0.8;
  const word = 0.55 + 0.45 * Math.sin(t * 1.9 + Math.sin(t * 0.7) * 2);
  const gap = Math.sin(t * 2.3) + Math.sin(t * 0.9 + 1) > -1.1 ? 1 : 0.08;
  const noise = (hash(Math.floor(t * 30)) - 0.5) * 0.15;
  return clamp(gain * (0.08 + 0.85 * syllable * word * gap + noise));
}

/**
 * Уровень голоса 0..1 в ref (без перерисовки React на каждый кадр): растёт, пока сфера
 * слушает пользователя или «говорит» ответ, и плавно гаснет после.
 */
export function useSimulatedLevel(mode: SphereMode): RefObject<number> {
  const level = useRef(0);

  useEffect(() => {
    const active = mode === "listening" || mode === "speaking";
    const gain = mode === "speaking" ? 0.75 : 1;
    const start = performance.now();
    let frame = 0;

    const tick = (now: number) => {
      const t = (now - start) / 1000;
      const target = active ? speechEnvelope(t, gain) : 0;
      const k = target > level.current ? 0.5 : 0.14;
      level.current += (target - level.current) * k;
      if (active || level.current > 0.005) {
        frame = requestAnimationFrame(tick);
      } else {
        level.current = 0;
      }
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [mode]);

  return level;
}
