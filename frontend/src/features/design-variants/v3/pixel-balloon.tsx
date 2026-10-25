"use client";

import { type RefObject, useRef } from "react";

import { type SphereFrame, useSphereLoop } from "../hooks/use-sphere-loop";
import type { SphereMode } from "../model/types";

export const BALLOON_W = 64;
export const BALLOON_H = 80;

/** Матрица Байера 4×4: пиксельный дизеринг на границах света и тени. */
const BAYER = [
  [0, 8, 2, 10],
  [12, 4, 14, 6],
  [3, 11, 1, 9],
  [15, 7, 13, 5],
] as const;

function bayer(x: number, y: number): number {
  return (BAYER[y & 3]?.[x & 3] ?? 0) / 16;
}

function noise(n: number): number {
  const v = Math.sin(n * 12.9898) * 43_758.5453;
  return v - Math.floor(v);
}

type Palette = Record<
  | "a"
  | "b"
  | "hi"
  | "sh"
  | "deep"
  | "basket"
  | "basketDark"
  | "rope"
  | "flame"
  | "flame2"
  | "danger",
  string
>;

function readPalette(element: Element): Palette {
  const style = getComputedStyle(element);
  const get = (name: string) => style.getPropertyValue(name).trim();
  return {
    a: get("--b-a"),
    b: get("--b-b"),
    hi: get("--b-hi"),
    sh: get("--b-sh"),
    deep: get("--b-deep"),
    basket: get("--b-basket"),
    basketDark: get("--b-basket-dark"),
    rope: get("--b-rope"),
    flame: get("--flame"),
    flame2: get("--flame-2"),
    danger: get("--danger"),
  };
}

/**
 * Пиксельный воздушный шар (как в программе GORKYCODE) — «сфера» голоса.
 * Слушает — оболочка раздувается от голоса; думает — горит горелка; отвечает — шар
 * подпрыгивает; ошибка — шар вздрагивает и сдувается; в покое качается и замирает.
 */
function drawBalloon(ctx: CanvasRenderingContext2D, frame: SphereFrame) {
  const { t, mode, level, calm } = frame;
  const colors = readPalette(ctx.canvas);
  ctx.clearRect(0, 0, BALLOON_W, BALLOON_H);

  const px = (x: number, y: number, color: string) => {
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x), Math.round(y), 1, 1);
  };

  let bob = Math.sin(t * 1.6) * 1.6 * calm;
  if (mode === "listening") bob = -level * 2;
  if (mode === "thinking") bob = -1 + Math.sin(t * 6) * 0.5;
  if (mode === "speaking") bob = Math.sin(t * 5) * 1.2 - 1;
  const shake = mode === "error" ? Math.sin(t * 38) * 1.6 * Math.max(0, 1 - t / 1.2) : 0;
  const ox = Math.round(shake);
  const oy = Math.round(bob);

  const cx = 32 + ox;
  const cy = 26 + oy;
  const inflate = mode === "listening" ? 1 + 0.09 * level : mode === "error" ? 0.92 : 1;
  const radius = 20 * inflate;
  const neckY = Math.round(cy + radius * 1.18);

  // Оболочка: 6 клиньев, свет сверху слева, дизеринг на переходах.
  for (let y = Math.floor(cy - radius); y <= neckY; y += 1) {
    const dy = y - cy;
    let half: number;
    if (dy <= radius * 0.3) {
      half = Math.sqrt(Math.max(0, radius * radius - dy * dy));
    } else {
      const k = Math.min(1, (dy - radius * 0.3) / (radius * 0.88));
      const top = Math.sqrt(radius * radius - (radius * 0.3) ** 2);
      half = top * (1 - k) + 3 * k;
    }
    const left = Math.round(cx - half);
    const right = Math.round(cx + half);
    for (let x = left; x <= right; x += 1) {
      const u = half > 0 ? (x - cx) / half : 0;
      const gore = Math.floor(
        ((Math.asin(Math.max(-1, Math.min(1, u))) / (Math.PI / 2) + 1) / 2) * 6,
      );
      let color = gore % 2 === 0 ? colors.a : colors.b;
      const light = u * 0.85 + (dy / radius) * 0.45;
      const threshold = bayer(x, y) * 0.3;
      if (light > 0.62 + threshold) color = gore % 2 === 0 ? colors.deep : colors.sh;
      else if (light < -0.72 + threshold) color = colors.hi;
      if (x === left || x === right) color = mode === "error" ? colors.danger : colors.deep;
      px(x, y, color);
    }
  }
  // Верхняя кромка оболочки.
  for (let x = Math.round(cx - 6); x <= Math.round(cx + 6); x += 1) {
    px(x, Math.floor(cy - radius), mode === "error" ? colors.danger : colors.deep);
  }

  // Горелка и пламя.
  const burnerY = neckY + 2;
  for (let x = cx - 2; x <= cx + 2; x += 1) px(x, burnerY, colors.rope);
  const burning = mode === "thinking" || mode === "speaking" || mode === "listening";
  if (burning) {
    const height =
      mode === "listening"
        ? 1 + Math.round(level * 3)
        : 2 + Math.round(noise(Math.floor(t * 12)) * 3);
    for (let i = 0; i < height; i += 1) {
      px(cx, burnerY - 1 - i, i === 0 ? colors.flame2 : colors.flame);
      if (i < height - 1 && noise(Math.floor(t * 12) + i) > 0.5)
        px(cx - 1, burnerY - 1 - i, colors.flame);
      if (i < height - 1 && noise(Math.floor(t * 12) + i + 7) > 0.5)
        px(cx + 1, burnerY - 1 - i, colors.flame2);
    }
  }

  // Стропы.
  const basketTop = burnerY + 6;
  for (let i = 0; i <= 5; i += 1) {
    px(cx - 3 - Math.round(i * 0.6), burnerY + i, colors.rope);
    px(cx + 3 + Math.round(i * 0.6), burnerY + i, colors.rope);
  }

  // Корзина с плетением.
  for (let y = basketTop; y < basketTop + 7; y += 1) {
    for (let x = cx - 6; x <= cx + 6; x += 1) {
      const edge = y === basketTop || x === cx - 6 || x === cx + 6 || y === basketTop + 6;
      const weave = (x + y) % 2 === 0;
      px(x, y, edge ? colors.basketDark : weave ? colors.basket : colors.basketDark);
    }
  }
}

export function PixelBalloon({
  mode,
  levelRef,
  className,
}: {
  mode: SphereMode;
  levelRef: RefObject<number>;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  useSphereLoop({
    canvasRef,
    mode,
    levelRef,
    render: drawBalloon,
    fps: 12,
    fixedWidth: BALLOON_W,
    fixedHeight: BALLOON_H,
  });

  return (
    <div className={className} aria-hidden="true">
      <canvas ref={canvasRef} className="v3-canvas" />
    </div>
  );
}
