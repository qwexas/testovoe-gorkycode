export const MAIN_CONTENT_ID = "main";

/** Первая точка фокуса: переход сразу к основной зоне мимо шапки. */
export function SkipLink() {
  return (
    <a
      href={`#${MAIN_CONTENT_ID}`}
      className="fixed top-2 left-2 z-50 -translate-y-20 bg-accent-fill px-4 py-2 text-sm font-medium text-on-accent focus-visible:translate-y-0"
    >
      Перейти к основному содержимому
    </a>
  );
}
