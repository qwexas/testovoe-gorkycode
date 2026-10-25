"use client";

import { type RefObject, useRef } from "react";

import { type SphereFrame, useSphereLoop } from "../hooks/use-sphere-loop";
import type { SphereMode } from "../model/types";

const LINES = 30;

function cssVar(element: Element, name: string, fallback: string): string {
  return getComputedStyle(element).getPropertyValue(name).trim() || fallback;
}

/**
 * Сфера-гравюра: шар нарисован горизонтальной штриховкой, как в старых книжных
 * иллюстрациях, — в тени штрих толще, на свету тоньше. Голос пускает по штрихам волну,
 * разбор запроса ведёт свет вокруг шара, ошибка сбивает штрихи, как смазанный оттиск.
 */
function drawEngraving(ctx: CanvasRenderingContext2D, frame: SphereFrame) {
  const { width, height, t, mode, level, calm } = frame;
  ctx.clearRect(0, 0, width, height);
  if (width === 0 || height === 0) return;

  const canvas = ctx.canvas;
  const ink = cssVar(canvas, mode === "error" ? "--sphere-err" : "--sphere-ink", "#3a1a7d");
  const size = Math.min(width, height);
  const cx = width / 2;
  const cy = height * 0.47;
  const radius = size * 0.4 * (mode === "listening" ? 1 + 0.05 * level : 1);
  const spacing = (radius * 2) / LINES;

  // Свет: в покое слегка «дышит» и замирает; при разборе обходит шар.
  const base = -2.3;
  const angle = mode === "thinking" ? base + t * 1.4 : base + Math.sin(t * 0.8) * 0.35 * calm;
  const light = { x: Math.cos(angle) * 0.7, y: -0.6, z: 0.45 + Math.sin(angle) * 0.2 };
  const norm = Math.hypot(light.x, light.y, light.z);

  const wave = mode === "listening" ? level : mode === "speaking" ? 0.35 + level * 0.5 : 0;
  const smudge = mode === "error" && t < 1;
  const thin = mode === "waiting" ? 0.75 : 1;

  ctx.fillStyle = ink;

  for (let i = 0; i < LINES; i += 1) {
    const y = -radius + spacing * (i + 0.5);
    const halfWidth = Math.sqrt(Math.max(0, radius * radius - y * y));
    if (halfWidth < 1) continue;
    const shift = smudge ? (i % 2 === 0 ? 1 : -1) * radius * 0.05 * (1 - t) : 0;
    const steps = Math.max(8, Math.round(halfWidth / 3));
    const top: Array<[number, number]> = [];
    const bottom: Array<[number, number]> = [];

    for (let s = 0; s <= steps; s += 1) {
      const x = -halfWidth + (2 * halfWidth * s) / steps;
      const nx = x / radius;
      const ny = y / radius;
      const nz = Math.sqrt(Math.max(0, 1 - nx * nx - ny * ny));
      const lit = Math.max(0, (nx * light.x + ny * light.y + nz * light.z) / norm);
      const shade = 1 - lit;
      // В тени штрих почти смыкается с соседним, в блике почти исчезает.
      const thickness =
        Math.min(spacing * 0.82, (0.18 + 3.4 * shade ** 1.7) * (spacing / 7)) * thin;
      const envelope = Math.sin((Math.PI * s) / steps);
      const dy = wave * spacing * 0.85 * envelope * Math.sin(x * 0.09 - t * 9 + i * 0.55);
      const px = cx + x + shift;
      const py = cy + y + dy;
      top.push([px, py - thickness / 2]);
      bottom.push([px, py + thickness / 2]);
    }

    ctx.beginPath();
    const [first] = top;
    if (!first) continue;
    ctx.moveTo(first[0], first[1]);
    for (const [px, py] of top) ctx.lineTo(px, py);
    for (let k = bottom.length - 1; k >= 0; k -= 1) {
      const point = bottom[k];
      if (point) ctx.lineTo(point[0], point[1]);
    }
    ctx.closePath();
    ctx.fill();
  }

  // Контур шара и падающая тень — короткие штрихи под ним.
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 1;
  ctx.strokeStyle = ink;
  ctx.beginPath();
  ctx.arc(cx, cy, radius + spacing * 0.2, 0, Math.PI * 2);
  ctx.stroke();

  const shadowY = cy + radius + spacing * 2.2;
  for (let k = 0; k < 4; k += 1) {
    const w = radius * (0.75 - k * 0.16);
    ctx.globalAlpha = 0.45 - k * 0.08;
    ctx.fillRect(
      cx - w + radius * 0.12,
      shadowY + k * spacing * 0.7,
      w * 2,
      Math.max(1, spacing * 0.18),
    );
  }
  ctx.globalAlpha = 1;
}

export function EngravedSphere({
  mode,
  levelRef,
  className,
}: {
  mode: SphereMode;
  levelRef: RefObject<number>;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  useSphereLoop({ canvasRef, mode, levelRef, render: drawEngraving, fps: 60 });

  return (
    <span className={className} aria-hidden="true">
      <canvas ref={canvasRef} className="v2-canvas" />
    </span>
  );
}
