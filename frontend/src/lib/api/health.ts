import type { HealthResponse } from "@/types/api";

import { apiClient, unwrap } from "./client";

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return unwrap(apiClient.GET("/api/health", { signal, cache: "no-store" }));
}
