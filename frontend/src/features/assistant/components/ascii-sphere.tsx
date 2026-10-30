"use client";

import { type RefObject, useRef } from "react";

import { tty } from "@/components/ui/tty";

import { type SphereFrame, useSphereLoop } from "../hooks/use-sphere-loop";
import type { SphereMode } from "../model/sphere";

/** шкала яркости: от пустоты до плотного символа. */
const RAMP = " .·:-=+*#%@";

function hash(n: number): number {
  const x = Math.sin(n * 91.345 + 47.853) * 43_758.5453;
  return x - Math.floor(x);
}

function cssVar(element: Element, name: string, fallback: string): string {
  return getComputedStyle(element).getPropertyValue(name).trim() || fallback;
}

/**
 * яркость шара передаётся плотностью символов, анимация зависит от состояния ассистента.
 */
function drawAsciiSphere(ctx: CanvasRenderingContext2D, frame: SphereFrame) {
  const { width, height, t, mode, level, calm } = frame;
  const canvas = ctx.canvas;
  ctx.clearRect(0, 0, width, height);
  if (width === 0 || height === 0) return;

  const family = getComputedStyle(canvas).fontFamily;
  const cols = width < 240 ? 28 : 44;
  const cellW = width / cols;
  const fontSize = cellW / 0.62;
  const cellH = fontSize * 1.18;
  const rows = Math.floor(height / cellH);
  const offsetY = (height - rows * cellH) / 2;

  const hi = cssVar(canvas, "--sphere-hi", "#e2d8ff");
  const lo = cssVar(canvas, "--sphere-lo", "#6a52b8");
  const err = cssVar(canvas, "--sphere-err", "#ff8a80");

  const cx = width / 2;
  const cy = height / 2;
  const listening = mode === "listening";
  const radius =
    Math.min(width, height) *
    0.43 *
    (listening ? 1 + 0.1 * level : 1) *
    (mode === "error" ? 0.94 : 1);

  // свет медленно обходит шар; в покое движение затухает (calm → 0).
  const speed = mode === "thinking" ? 1.6 : 0.5;
  const angle = -0.9 + Math.sin(t * speed) * 0.9 * calm + (mode === "thinking" ? t * 0.8 : 0);
  const light = { x: Math.cos(angle) * 0.75, y: -0.55, z: Math.sin(angle) * 0.4 + 0.6 };
  const norm = Math.hypot(light.x, light.y, light.z);
  light.x /= norm;
  light.y /= norm;
  light.z /= norm;

  const scan = Math.sin(t * 2.4);
  const glitch = mode === "error" && t < 0.9;

  ctx.font = `600 ${fontSize.toFixed(2)}px ${family}`;
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";

  for (let row = 0; row < rows; row += 1) {
    const shift = glitch && hash(row + Math.floor(t * 12) * 31) > 0.72 ? (hash(row) - 0.5) * 6 : 0;
    for (let col = 0; col < cols; col += 1) {
      const px = (col + 0.5) * cellW - cx;
      const py = offsetY + (row + 0.5) * cellH - cy;
      const theta = Math.atan2(py, px);
      const wobble = listening ? 1 + 0.07 * level * Math.sin(theta * 7 + t * 11) : 1;
      const r = radius * wobble;
      const d2 = px * px + py * py;
      let brightness = 0;

      if (d2 < r * r) {
        const nx = px / r;
        const ny = py / r;
        const nz = Math.sqrt(Math.max(0, 1 - nx * nx - ny * ny));
        brightness = Math.max(0, nx * light.x + ny * light.y + nz * light.z) * 0.92 + 0.08;
        if (mode === "thinking") {
          brightness += 0.75 * Math.exp(-((ny - scan) ** 2) / 0.012);
        }
        if (mode === "speaking") {
          const ring = Math.sin(Math.sqrt(nx * nx + ny * ny) * 14 - t * 9);
          brightness += 0.3 * ring * (0.35 + level);
        }
        if (mode === "waiting") brightness *= 0.7 + 0.15 * Math.sin(t * 2) * calm;
      } else if (listening && level > 0.08) {
        // брызги вокруг шара: чем громче, тем дальше и гуще.
        const dist = Math.sqrt(d2) / radius;
        const spray = hash(col * 13 + row * 101 + Math.floor(t * 14) * 7);
        if (dist < 1 + 0.45 * level && spray > 0.9 - level * 0.25) brightness = 0.18;
      }

      brightness = Math.min(1, brightness);
      const index = Math.round(brightness * (RAMP.length - 1));
      const char = RAMP[index];
      if (!char || char === " ") continue;

      ctx.fillStyle = mode === "error" ? err : brightness > 0.62 ? hi : lo;
      ctx.globalAlpha = 0.45 + 0.55 * brightness;
      ctx.fillText(char, (col + 0.5) * cellW + shift * cellW, offsetY + (row + 0.5) * cellH);
    }
  }
  ctx.globalAlpha = 1;
}

export function AsciiSphere({
  mode,
  levelRef,
  className,
}: {
  mode: SphereMode;
  levelRef: RefObject<number>;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  useSphereLoop({ canvasRef, mode, levelRef, render: drawAsciiSphere, fps: 24 });

  return (
    <div className={className} aria-hidden="true">
      <canvas ref={canvasRef} className={tty.canvas} />
    </div>
  );
}
