"use client";

import {
  type ReactNode,
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { StatusToast } from "@/components/ui/status-toast";
import { apiErrorFromException } from "@/lib/api/errors";
import { setSessionProfile, subscribeSessionLoss } from "@/lib/api/profile-session";

import {
  createProfile as requestNewProfile,
  deleteCurrentProfile,
  fetchCurrentProfile,
  restoreProfile as requestRestore,
} from "./api";
import { type ProfileStatus, createProfileController, initialProfileState } from "./profile-state";

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
const PROFILE_CHANGE_KEY = "gorky-profile-change";
function announceProfileChange() {
  // Только сигнал, без ID, кода восстановления и других данных профиля.
  try {
    localStorage.setItem(PROFILE_CHANGE_KEY, crypto.randomUUID());
  } catch {
    /* storage недоступен */
  }
}

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
  const [controller] = useState(() =>
    createProfileController({
      read: fetchCurrentProfile,
      create: requestNewProfile,
      restore: requestRestore,
      remove: deleteCurrentProfile,
      setSession: setSessionProfile,
      error: apiErrorFromException,
    }),
  );
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    () => initialProfileState,
  );
  const { message: toastMessage, show: showToast } = useToast();
  const initialLoadStarted = useRef(false);

  useEffect(() => {
    const unsubscribe = subscribeSessionLoss(controller.sessionLost);
    const changed = (event: StorageEvent) => {
      if (event.key === PROFILE_CHANGE_KEY) void controller.sessionChanged();
    };
    const focused = () => {
      void controller.load();
    };
    window.addEventListener("storage", changed);
    window.addEventListener("focus", focused);
    if (!initialLoadStarted.current) {
      initialLoadStarted.current = true;
      void controller.load();
    }
    return () => {
      unsubscribe();
      window.removeEventListener("storage", changed);
      window.removeEventListener("focus", focused);
    };
  }, [controller]);

  const createProfile = useCallback(async () => {
    await controller.create();
    announceProfileChange();
  }, [controller]);

  const restoreProfile = useCallback(
    async (code: string) => {
      await controller.restore(code);
      announceProfileChange();
      showToast("Вы вошли в профиль по коду восстановления");
    },
    [controller, showToast],
  );

  const deleteAllData = useCallback(async () => {
    await controller.remove();
    announceProfileChange();
    showToast("Все данные удалены");
  }, [controller, showToast]);

  const dismissRecoveryCode = controller.dismissCode;

  const value = useMemo<ProfileContextValue>(
    () => ({
      profile:
        state.changing && state.profile.status === "ready" ? { status: "loading" } : state.profile,
      pendingRecoveryCode:
        !state.changing && state.profile.status === "ready" ? state.pendingRecoveryCode : null,
      dismissRecoveryCode,
      reload: controller.load,
      createProfile,
      restoreProfile,
      deleteAllData,
      notify: showToast,
    }),
    [
      state.profile,
      state.pendingRecoveryCode,
      state.changing,
      dismissRecoveryCode,
      controller,
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
