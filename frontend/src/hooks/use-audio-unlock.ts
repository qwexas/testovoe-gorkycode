"use client";

import { useEffect } from "react";

import { installAudioUnlock } from "@/lib/audio";

/** будит звук на первом жесте пользователя: для озвучки ответов и сигнала напоминаний. */
export function useAudioUnlock(): void {
  useEffect(() => installAudioUnlock(), []);
}
