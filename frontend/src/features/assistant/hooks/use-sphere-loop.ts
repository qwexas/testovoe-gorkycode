"use client";

import { useReducedMotion } from "motion/react";
import { type RefObject, useEffect, useLayoutEffect, useRef } from "react";

import type { SphereMode } from "../model/sphere";

export type SphereFrame = {
  /** секунды с начала текущего режима. */
  t: number;
  mode: SphereMode;
  /** уровень голоса 0..1; при reduced motion всегда 0. */
  level: number;
  /** амплитуда движения 0..1: в покое затухает до 0, чтобы сфера не двигалась бесконечно. */
  calm: number;
  width: number;
  height: number;
  reduced: boolean;
};

export type SphereRenderer = (ctx: CanvasRenderingContext2D, frame: SphereFrame) => void;

/**
 * сколько длится движение в режиме. Покой и ожидание «дышат» 5 секунд и замирают
 * (WCAG 2.2.2: само по себе ничего не движется дольше 5 с); запись, разбор и речь
 * идут, пока режим активен — это обратная связь на действие пользователя.
 */
function activeDuration(mode: SphereMode): number {
  switch (mode) {
    case "idle":
    case "waiting":
      return 5_000;
    case "error":
      return 1_400;
    default:
      return Number.POSITIVE_INFINITY;
  }
}

type Options = {
  canvasRef: RefObject<HTMLCanvasElement | null>;
  mode: SphereMode;
  levelRef: RefObject<number>;
  render: SphereRenderer;
  /** кадров в секунду: терминалу хватает 24, пиксельной графике — 12. */
  fps?: number;
  /** фиксированный размер холста в пикселях (пиксель-арт масштабирует CSS). */
  fixedWidth?: number;
  fixedHeight?: number;
};

/**
 * цикл отрисовки сферы на canvas: подгоняет холст под размер и плотность пикселей,
 * останавливается в фоне (requestAnimationFrame) и при prefers-reduced-motion
 * рисует один статичный кадр на каждый режим.
 */
export function useSphereLoop({
  canvasRef,
  mode,
  levelRef,
  render,
  fps = 60,
  fixedWidth,
  fixedHeight,
}: Options): void {
  const reduced = useReducedMotion() ?? false;
  const renderRef = useRef(render);

  useLayoutEffect(() => {
    renderRef.current = render;
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return undefined;

    let width = 0;
    let height = 0;

    const resize = () => {
      if (fixedWidth && fixedHeight) {
        canvas.width = fixedWidth;
        canvas.height = fixedHeight;
        width = fixedWidth;
        height = fixedHeight;
        ctx.imageSmoothingEnabled = false;
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = rect.width;
      height = rect.height;
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const duration = activeDuration(mode);
    const start = performance.now();
    let last = Number.NEGATIVE_INFINITY;
    let frame = 0;

    const paint = (now: number) => {
      const elapsed = Math.min(now - start, duration);
      const calm = reduced
        ? 0
        : duration === Number.POSITIVE_INFINITY
          ? 1
          : Math.min(1, Math.max(0, (duration - elapsed) / 1_500));
      ctx.save();
      renderRef.current(ctx, {
        t: elapsed / 1000,
        mode,
        level: reduced ? 0 : (levelRef.current ?? 0),
        calm,
        width,
        height,
        reduced,
      });
      ctx.restore();
    };

    const loop = (now: number) => {
      if (now - last >= 1000 / fps - 1) {
        last = now;
        paint(now);
      }
      if (now - start < duration) {
        frame = requestAnimationFrame(loop);
      } else {
        paint(start + duration);
      }
    };

    resize();
    if (reduced) {
      paint(start);
    } else {
      frame = requestAnimationFrame(loop);
    }

    // шрифт для текстовой сферы может догрузиться позже первого кадра.
    void document.fonts?.ready.then(() => {
      if (reduced || duration !== Number.POSITIVE_INFINITY) paint(performance.now());
    });

    const observer = new ResizeObserver(() => {
      resize();
      paint(performance.now());
    });
    if (!fixedWidth) observer.observe(canvas);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [canvasRef, mode, levelRef, reduced, fps, fixedWidth, fixedHeight]);
}
