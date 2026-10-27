/**
 * Ненавязчивое сообщение под шапкой (не перекрывает поле ввода и микрофон).
 * Live-регион смонтирован всегда, поэтому экранные дикторы озвучивают каждое новое сообщение.
 */
export function StatusToast({ message }: { message: string | null }) {
  return (
    <div
      role="status"
      className="pointer-events-none fixed inset-x-0 top-4 z-50 flex justify-center px-4"
    >
      {message ? (
        <p className="pointer-events-auto max-w-md border border-border-strong bg-surface px-4 py-3 text-sm text-pretty text-fg shadow-lg">
          {message}
        </p>
      ) : null}
    </div>
  );
}
