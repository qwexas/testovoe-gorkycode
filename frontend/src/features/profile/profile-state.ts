import type { ApiError } from "@/lib/api/errors";
import type { Profile } from "@/types/api";

/** Профиль в интерфейсе. Код восстановления сюда не попадает — он живёт отдельно. */
export type ProfileStatus =
  | { status: "loading" }
  | { status: "ready"; profile: Profile }
  | { status: "deleted" }
  | { status: "anonymous"; reason: "missing" | "expired" }
  | { status: "failed"; error: ApiError };

export type ProfileState = {
  profile: ProfileStatus;
  /** Код из ответа на создание профиля; показываем один раз, потом обнуляем. */
  pendingRecoveryCode: string | null;
  recoveryProfileId: string | null;
  changing: boolean;
};

export type ProfileAction =
  | { type: "load_failed"; error: ApiError }
  | { type: "profile_received"; profile: Profile }
  | { type: "profile_deleted" }
  | { type: "recovery_code_dismissed" };
// Потеря сессии — отдельное состояние, не повторная попытка создания профиля.
type SessionAction = { type: "session_lost" } | { type: "mutation_started" };

export const initialProfileState: ProfileState = {
  profile: { status: "loading" },
  pendingRecoveryCode: null,
  recoveryProfileId: null,
  changing: false,
};

export function profileReducer(
  state: ProfileState,
  action: ProfileAction | SessionAction,
): ProfileState {
  switch (action.type) {
    case "mutation_started":
      return { ...state, changing: true };
    case "session_lost":
      return {
        profile:
          state.profile.status === "deleted"
            ? state.profile
            : {
                status: "anonymous",
                reason: state.profile.status === "ready" ? "expired" : "missing",
              },
        pendingRecoveryCode: null,
        recoveryProfileId: null,
        changing: false,
      };
    case "load_failed":
      return { ...state, changing: false, profile: { status: "failed", error: action.error } };
    case "profile_received": {
      const { recovery_code: recoveryCode, ...profile } = action.profile;
      return {
        profile: { status: "ready", profile: { ...profile, recovery_code: null } },
        changing: false,
        recoveryProfileId: profile.id,
        pendingRecoveryCode:
          recoveryCode ??
          (state.recoveryProfileId === profile.id ? state.pendingRecoveryCode : null),
      };
    }
    case "profile_deleted":
      return {
        profile: { status: "deleted" },
        pendingRecoveryCode: null,
        recoveryProfileId: null,
        changing: false,
      };
    case "recovery_code_dismissed":
      return { ...state, pendingRecoveryCode: null };
  }
}

type ProfileRequests = {
  read: () => Promise<Profile>;
  create: () => Promise<Profile>;
  restore: (code: string) => Promise<Profile>;
  remove: () => Promise<void>;
  setSession: (id: string | null) => void;
  error: (cause: unknown) => ApiError;
};

/** Общий жизненный цикл для React и тестов: GET никогда не превращается в POST. */
export function createProfileController(requests: ProfileRequests) {
  let state = initialProfileState;
  let revision = 0;
  let reading: { revision: number; promise: Promise<void> } | null = null;
  let mutation: { kind: string; promise: Promise<void> } | null = null;
  const listeners = new Set<() => void>();
  function replaceState(next: ProfileState) {
    state = next;
    for (const listener of listeners) listener();
  }
  function dispatch(action: ProfileAction | SessionAction) {
    replaceState(profileReducer(state, action));
  }
  function receive(profile: Profile) {
    requests.setSession(profile.id);
    dispatch({ type: "profile_received", profile });
  }
  function sessionLost() {
    revision += 1;
    requests.setSession(null);
    dispatch({ type: "session_lost" });
  }
  function load(): Promise<void> {
    if (mutation) return mutation.promise;
    if (reading?.revision === revision) return reading.promise;
    const owner = revision;
    const promise = requests
      .read()
      .then((profile) => {
        if (owner === revision) receive(profile);
      })
      .catch((cause: unknown) => {
        if (owner !== revision) return;
        const error = requests.error(cause);
        if (error.code === "session_required") sessionLost();
        else {
          requests.setSession(null);
          dispatch({ type: "load_failed", error });
        }
      });
    reading = { revision: owner, promise };
    void promise.finally(() => {
      if (reading?.promise === promise) reading = null;
    });
    return promise;
  }
  function mutate(kind: string, work: () => Promise<Profile | void>): Promise<void> {
    if (mutation) {
      if (mutation.kind === kind) return mutation.promise;
      return Promise.reject(new Error("Дождитесь завершения операции с профилем."));
    }
    const owner = ++revision;
    const previous = state;
    requests.setSession(null);
    dispatch({ type: "mutation_started" });
    const promise = work()
      .then((profile) => {
        if (owner !== revision) return;
        if (profile) receive(profile);
        else dispatch({ type: "profile_deleted" });
      })
      .catch((cause: unknown) => {
        if (owner === revision) {
          const error = requests.error(cause);
          if (
            ["invalid_recovery_code", "rate_limited", "forbidden", "validation_error"].includes(
              error.code,
            )
          ) {
            // Эти отказы сервера происходят до переключения cookie: сохраняем форму и старый код.
            requests.setSession(
              previous.profile.status === "ready" ? previous.profile.profile.id : null,
            );
            replaceState(previous);
          } else dispatch({ type: "load_failed", error });
        }
        throw cause;
      })
      .finally(() => {
        mutation = null;
      });
    mutation = { kind, promise };
    return promise;
  }
  function recheckSession(): Promise<void> {
    revision += 1;
    requests.setSession(null);
    // Код хранится с владельцем, но скрыт до проверки cookie: тот же ID сохранит его.
    dispatch({ type: "mutation_started" });
    return load();
  }
  return {
    getSnapshot: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    load,
    sessionLost,
    sessionChanged: () => {
      if (mutation) return mutation.promise.then(recheckSession, recheckSession);
      return recheckSession();
    },
    create: () => mutate("create", requests.create),
    restore: (code: string) => mutate("restore", () => requests.restore(code)),
    remove: () => mutate("remove", requests.remove),
    dismissCode: () => dispatch({ type: "recovery_code_dismissed" }),
  };
}
