"use client";

import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

import { getAudioContext, isAudioRunning } from "@/lib/audio";

import { SPEECH_TEXT_LIMIT, fetchSpeech } from "../api";
import { textForBrowserSpeech } from "../lib/speech-text";

const LANG = "ru-RU";
/** Если сервер не озвучил за это время (модель грузится, очередь) — говорит браузер. */
const SERVER_SPEECH_TIMEOUT_MS = 8_000;

/** Умеет ли браузер играть OGG/Opus, который отдаёт сервер (старый Safari — нет). */
function canPlayServerAudio(): boolean {
  if (typeof Audio === "undefined") return false;
  return new Audio().canPlayType('audio/ogg; codecs="opus"') !== "";
}

function russianVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  return (
    voices.find((voice) => voice.lang === LANG && voice.localService) ??
    voices.find((voice) => voice.lang.toLowerCase().startsWith("ru")) ??
    null
  );
}

/** Огибающая «речи» для сферы, когда настоящий уровень недоступен (браузерный синтез). */
function syntheticLevel(t: number): number {
  return 0.25 + 0.35 * Math.abs(Math.sin(t * 8.3)) * (0.6 + 0.4 * Math.sin(t * 2.1));
}

/**
 * Сколько озвучка может длиться самое большее: если браузер так и не сообщил о конце
 * (нет звукового устройства, известная ошибка Chrome с длинными фразами), сфера не
 * должна навсегда остаться в «отвечаю». ~14 символов в секунду плюс запас.
 */
function watchdogMs(text: string): number {
  return Math.min(90_000, 3_000 + text.length * 110);
}

type Playback = {
  stop: () => void;
};

/**
 * Озвучка ответов (решение Q13): голос Silero с сервера (POST /api/tts), а если сервер
 * не озвучил (503, нет сети) или браузер не играет OGG/Opus — браузерный speechSynthesis
 * (ru-RU). `speaking` — для сферы; уровень звука — в `levelRef` (без перерисовок).
 */
export function useSpeech(): {
  speak: (text: string) => void;
  stop: () => void;
  speaking: boolean;
  levelRef: RefObject<number>;
} {
  const [speaking, setSpeaking] = useState(false);
  const levelRef = useRef(0);
  const sequence = useRef(0);
  const playback = useRef<Playback | null>(null);

  const finish = useCallback((id: number) => {
    if (id !== sequence.current) return;
    playback.current = null;
    levelRef.current = 0;
    setSpeaking(false);
  }, []);

  const stop = useCallback(() => {
    sequence.current += 1;
    playback.current?.stop();
    playback.current = null;
    levelRef.current = 0;
    setSpeaking(false);
  }, []);

  const speakWithBrowser = useCallback(
    (id: number, text: string) => {
      if (typeof window.speechSynthesis === "undefined") {
        finish(id);
        return;
      }
      const utterance = new SpeechSynthesisUtterance(textForBrowserSpeech(text));
      utterance.lang = LANG;
      const voice = russianVoice();
      if (voice) utterance.voice = voice;
      let frame = 0;
      const startedAt = performance.now();
      const tick = (now: number) => {
        levelRef.current = syntheticLevel((now - startedAt) / 1000);
        frame = requestAnimationFrame(tick);
      };
      let watchdog = 0;
      const done = () => {
        cancelAnimationFrame(frame);
        window.clearTimeout(watchdog);
        finish(id);
      };
      utterance.onend = done;
      utterance.onerror = done;
      const stopUtterance = () => {
        cancelAnimationFrame(frame);
        window.clearTimeout(watchdog);
        utterance.onend = null;
        utterance.onerror = null;
        window.speechSynthesis.cancel();
      };
      playback.current = { stop: stopUtterance };
      watchdog = window.setTimeout(() => {
        stopUtterance();
        finish(id);
      }, watchdogMs(text));
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
      setSpeaking(true);
      frame = requestAnimationFrame(tick);
    },
    [finish],
  );

  const playServerAudio = useCallback(
    async (id: number, blob: Blob, text: string): Promise<boolean> => {
      const url = URL.createObjectURL(blob);
      const element = new Audio(url);
      let frame = 0;
      let analyser: AnalyserNode | null = null;

      // Уровень звука для сферы — только если Web Audio уже разбужен жестом: иначе
      // звук, пропущенный через спящий контекст, получился бы беззвучным.
      const audio = getAudioContext();
      if (audio && isAudioRunning()) {
        try {
          const source = audio.createMediaElementSource(element);
          analyser = audio.createAnalyser();
          analyser.fftSize = 512;
          source.connect(analyser);
          analyser.connect(audio.destination);
        } catch {
          analyser = null;
        }
      }
      const buffer = new Float32Array(analyser?.fftSize ?? 0);
      const startedAt = performance.now();
      const tick = (now: number) => {
        if (analyser) {
          analyser.getFloatTimeDomainData(buffer);
          let sum = 0;
          for (const sample of buffer) sum += sample * sample;
          levelRef.current = Math.min(1, Math.sqrt(sum / buffer.length) * 4);
        } else {
          levelRef.current = syntheticLevel((now - startedAt) / 1000);
        }
        frame = requestAnimationFrame(tick);
      };
      let watchdog = 0;
      const cleanup = () => {
        cancelAnimationFrame(frame);
        window.clearTimeout(watchdog);
        element.onended = null;
        element.onerror = null;
        URL.revokeObjectURL(url);
      };
      const armWatchdog = (ms: number) => {
        window.clearTimeout(watchdog);
        watchdog = window.setTimeout(() => {
          element.pause();
          cleanup();
          finish(id);
        }, ms);
      };
      element.onended = () => {
        cleanup();
        finish(id);
      };
      element.onerror = () => {
        cleanup();
        finish(id);
      };
      playback.current = {
        stop: () => {
          element.pause();
          cleanup();
        },
      };
      try {
        await element.play();
      } catch {
        // Автовоспроизведение запрещено (нет жеста) или формат не играет.
        cleanup();
        return false;
      }
      setSpeaking(true);
      armWatchdog(
        Number.isFinite(element.duration) ? element.duration * 1000 + 3_000 : watchdogMs(text),
      );
      frame = requestAnimationFrame(tick);
      return true;
    },
    [finish],
  );

  const speak = useCallback(
    (rawText: string) => {
      const text = rawText.trim().slice(0, SPEECH_TEXT_LIMIT);
      stop();
      if (!text) return;
      const id = sequence.current;

      if (!canPlayServerAudio()) {
        speakWithBrowser(id, text);
        return;
      }

      // «Отвечаю» загорается, когда звук пошёл, а не пока ждём аудио с сервера.
      const controller = new AbortController();
      let timedOut = false;
      const timer = window.setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, SERVER_SPEECH_TIMEOUT_MS);
      playback.current = {
        stop: () => {
          window.clearTimeout(timer);
          controller.abort();
        },
      };
      void fetchSpeech(text, controller.signal)
        .then(async (blob) => {
          window.clearTimeout(timer);
          if (id !== sequence.current) return;
          const played = await playServerAudio(id, blob, text);
          if (!played && id === sequence.current) speakWithBrowser(id, text);
        })
        .catch(() => {
          window.clearTimeout(timer);
          if (id !== sequence.current || (controller.signal.aborted && !timedOut)) return;
          speakWithBrowser(id, text);
        });
    },
    [playServerAudio, speakWithBrowser, stop],
  );

  useEffect(() => () => playback.current?.stop(), []);

  return { speak, stop, speaking, levelRef };
}
