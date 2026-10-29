/** Общая граница всех запросов профиля, включая voice/TTS и скачивание календаря. */
let active = false;
let generation = 0;
const listeners = new Set<() => void>();

export function setSessionProfile(profileId: string | null): void {
  active = profileId !== null;
  generation += 1;
}

export function subscribeSessionLoss(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function needsProfile(path: string, method: string): boolean {
  if (path === "/api/me") return method !== "GET" && method !== "DELETE";
  return (
    path.startsWith("/api/") &&
    path !== "/api/health" &&
    path !== "/api/profiles" &&
    path !== "/api/profiles/restore" &&
    !/^\/api\/calendar\/[^/]+\.ics$/.test(path)
  );
}

export const sessionFetch: typeof fetch = async (input, init) => {
  const url = input instanceof Request ? input.url : String(input);
  const path = new URL(url, "http://same-origin.invalid").pathname;
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  if (!active && needsProfile(path, method)) {
    return new Response(
      JSON.stringify({
        error: {
          code: "session_required",
          message: "Создайте профиль или войдите по коду восстановления.",
        },
      }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    );
  }
  const owner = generation;
  const response = await fetch(input, init);
  if (response.status === 401 && owner === generation) {
    active = false;
    generation += 1;
    for (const listener of listeners) listener();
  }
  return response;
};
