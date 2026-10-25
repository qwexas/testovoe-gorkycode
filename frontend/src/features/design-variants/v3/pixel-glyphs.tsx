import type { CalendarEvent } from "../model/types";

/** Пиксельные значки 7×7: у каждого типа своя форма, не только цвет (WCAG 1.4.1). */
const GLYPHS = {
  meeting: ["...#...", "..###..", ".#####.", "#######", ".#####.", "..###..", "...#..."],
  task: ["#######", "#.....#", "#.....#", "#.....#", "#.....#", "#.....#", "#######"],
  taskDone: ["#######", "#.....#", "#....##", "##..#.#", "#.##..#", "#.....#", "#######"],
  reminder: ["...#...", "..###..", ".#####.", ".#####.", ".#####.", "#######", "...#..."],
  mic: ["..###..", "..###..", "..###..", "#.###.#", "#.....#", ".#####.", "...#..."],
  stop: [".......", ".#####.", ".#####.", ".#####.", ".#####.", ".#####.", "......."],
  star: ["#"],
} as const;

export type GlyphName = keyof typeof GLYPHS;

export function PixelGlyph({
  name,
  size = 14,
  className,
}: {
  name: GlyphName;
  size?: number;
  className?: string;
}) {
  const rows = GLYPHS[name];
  const width = rows[0]?.length ?? 1;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${width} ${rows.length}`}
      aria-hidden="true"
      shapeRendering="crispEdges"
      className={className}
    >
      {rows.flatMap((row, y) =>
        [...row].map((cell, x) =>
          cell === "#" ? (
            <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill="currentColor" />
          ) : null,
        ),
      )}
    </svg>
  );
}

export function eventGlyph(event: CalendarEvent): GlyphName {
  if (event.type === "task") return event.status === "done" ? "taskDone" : "task";
  return event.type;
}

const CLOUD = [
  "......####......",
  "....########....",
  "..############..",
  ".##############.",
  "################",
  ".##############.",
];

const CLOUD_SHADE = [
  "................",
  "................",
  "................",
  "................",
  "......#####.####",
  ".##############.",
];

/** Пиксельное облако: тело и нижняя тень двумя слоями. */
export function PixelCloud({ className, scale = 6 }: { className?: string; scale?: number }) {
  const width = CLOUD[0]?.length ?? 16;
  return (
    <svg
      width={width * scale}
      height={CLOUD.length * scale}
      viewBox={`0 0 ${width} ${CLOUD.length}`}
      aria-hidden="true"
      shapeRendering="crispEdges"
      className={className}
    >
      {CLOUD.flatMap((row, y) =>
        [...row].map((cell, x) =>
          cell === "#" ? (
            <rect
              key={`c-${x}-${y}`}
              x={x}
              y={y}
              width="1"
              height="1"
              className="v3-cloud"
              fill="currentColor"
            />
          ) : null,
        ),
      )}
      {CLOUD_SHADE.flatMap((row, y) =>
        [...row].map((cell, x) =>
          cell === "#" ? (
            <rect
              key={`s-${x}-${y}`}
              x={x}
              y={y}
              width="1"
              height="1"
              className="v3-cloudShade"
              fill="currentColor"
            />
          ) : null,
        ),
      )}
    </svg>
  );
}
