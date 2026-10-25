import type { ApiError } from "@/lib/api/errors";
import type { Profile } from "@/types/api";

/** Профиль в интерфейсе. Код восстановления сюда не попадает — он живёт отдельно. */
export type ProfileStatus =
  | { status: "loading" }
  | { status: "ready"; profile: Profile }
  | { status: "deleted" }
  | { status: "failed"; error: ApiError };

export type ProfileState = {
  profile: ProfileStatus;
  /** Код из ответа на создание профиля; показываем один раз, потом обнуляем. */
  pendingRecoveryCode: string | null;
};

export type ProfileAction =
  | { type: "load_failed"; error: ApiError }
  | { type: "profile_received"; profile: Profile }
  | { type: "profile_deleted" }
  | { type: "recovery_code_dismissed" };

export const initialProfileState: ProfileState = {
  profile: { status: "loading" },
  pendingRecoveryCode: null,
};

export function profileReducer(state: ProfileState, action: ProfileAction): ProfileState {
  switch (action.type) {
    case "load_failed":
      return { ...state, profile: { status: "failed", error: action.error } };
    case "profile_received": {
      const { recovery_code: recoveryCode, ...profile } = action.profile;
      return {
        profile: { status: "ready", profile: { ...profile, recovery_code: null } },
        pendingRecoveryCode: recoveryCode ?? null,
      };
    }
    case "profile_deleted":
      return { profile: { status: "deleted" }, pendingRecoveryCode: null };
    case "recovery_code_dismissed":
      return { ...state, pendingRecoveryCode: null };
  }
}
