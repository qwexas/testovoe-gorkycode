"use client";

import {
  type ReactNode,
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import { StatusToast } from "@/components/ui/status-toast";
import { apiErrorFromException } from "@/lib/api/errors";

import {
  createProfile as requestNewProfile,
  deleteCurrentProfile,
  fetchCurrentProfile,
  restoreProfile as requestRestore,
} from "./api";
import { type ProfileStatus, initialProfileState, profileReducer } from "./profile-state";

type ProfileContextValue = {
  profile: ProfileStatus;
  pendingRecoveryCode: string | null;
  dismissRecoveryCode: () => void;
  /** Повторная загрузка после ошибки; статус остаётся «failed», пока не придёт ответ. */
  reload: () => Promise<void>;
  /** Действия ниже бросают ApiError — окно, из которого их вызвали, показывает ошибку. */
  createProfile: () => Promise<void>;
  restoreProfile: (code: string) => Promise<void>;
  deleteAllData: () => Promise<void>;
  /** Короткое сообщение под шапкой (озвучивается экранным диктором). */
  notify: (message: string) => void;
};

const ProfileContext = createContext<ProfileContextValue | null>(null);

const TOAST_DURATION_MS = 5000;

function useToast(): { message: string | null; show: (message: string) => void } {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const show = useCallback((next: string) => {
    window.clearTimeout(timer.current);
    setMessage(next);
    timer.current = window.setTimeout(() => setMessage(null), TOAST_DURATION_MS);
  }, []);

  return { message, show };
}

export function ProfileProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(profileReducer, initialProfileState);
  const { message: toastMessage, show: showToast } = useToast();
  const initialLoadStarted = useRef(false);

  const load = useCallback(async () => {
    try {
      dispatch({ type: "profile_received", profile: await fetchCurrentProfile() });
    } catch (error) {
      dispatch({ type: "load_failed", error: apiErrorFromException(error) });
    }
  }, []);

  useEffect(() => {
    // Один запрос даже при двойном эффекте Strict Mode: без cookie каждый GET /api/me
    // создаёт новый профиль, и показанный код мог бы оказаться от чужого профиля.
    if (initialLoadStarted.current) return;
    initialLoadStarted.current = true;
    void load();
  }, [load]);

  const createProfile = useCallback(async () => {
    const profile = await requestNewProfile();
    dispatch({ type: "profile_received", profile });
  }, []);

  const restoreProfile = useCallback(
    async (code: string) => {
      const profile = await requestRestore(code);
      dispatch({ type: "profile_received", profile });
      showToast("Вы вошли в профиль по коду восстановления");
    },
    [showToast],
  );

  const deleteAllData = useCallback(async () => {
    await deleteCurrentProfile();
    dispatch({ type: "profile_deleted" });
    showToast("Все данные удалены");
  }, [showToast]);

  const dismissRecoveryCode = useCallback(() => dispatch({ type: "recovery_code_dismissed" }), []);

  const value = useMemo<ProfileContextValue>(
    () => ({
      profile: state.profile,
      pendingRecoveryCode: state.pendingRecoveryCode,
      dismissRecoveryCode,
      reload: load,
      createProfile,
      restoreProfile,
      deleteAllData,
      notify: showToast,
    }),
    [
      state.profile,
      state.pendingRecoveryCode,
      dismissRecoveryCode,
      load,
      createProfile,
      restoreProfile,
      deleteAllData,
      showToast,
    ],
  );

  return (
    <ProfileContext value={value}>
      {children}
      <StatusToast message={toastMessage} />
    </ProfileContext>
  );
}

export function useProfile(): ProfileContextValue {
  const context = use(ProfileContext);
  if (!context) throw new Error("useProfile должен вызываться внутри <ProfileProvider>");
  return context;
}
