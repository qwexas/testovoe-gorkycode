import { type DemoStateId, isDemoStateId } from "./types";

export type SearchParams = Record<string, string | string[] | undefined>;

/** `?state=list&bar=0` → начальное состояние демо и видимость служебной панели. */
export function readDemoParams(params: SearchParams): { state: DemoStateId; showBar: boolean } {
  return {
    state: isDemoStateId(params.state) ? params.state : "idle",
    showBar: params.bar !== "0",
  };
}
