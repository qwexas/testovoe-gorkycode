"use client";

import { motion } from "motion/react";

/**
 * Заглушка «сферы» голоса (решение Q8). Пока одно появление при загрузке; реакция на
 * запись и речь — вместе с голосовым вводом. MotionConfig reducedMotion="user" в
 * провайдерах убирает масштабирование при prefers-reduced-motion.
 */
export function VoiceSphere() {
  return (
    <motion.div
      aria-hidden="true"
      className="voice-sphere size-36 rounded-full sm:size-44"
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
    />
  );
}
