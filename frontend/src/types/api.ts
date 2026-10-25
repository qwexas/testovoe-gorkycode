/**
 * Модели контракта API (docs/api-contract.md), общие для нескольких фич.
 * Единственное место, которое знает имена схем из сгенерированного schema.d.ts:
 * если после `pnpm gen:api` имена схем поменяются, правится только этот файл.
 */
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

export type Profile = Schemas["Profile"];
export type HealthResponse = Schemas["HealthResponse"];
export type HealthChecks = Schemas["HealthChecks"];
export type ServerErrorCode = Schemas["ErrorCode"];
export type ErrorResponse = Schemas["ErrorResponse"];

export type CalendarEvent = Schemas["Event"];
export type EventType = Schemas["EventType"];
export type AssistantReply = Schemas["AssistantReply"];
export type ChatMessage = Schemas["ChatMessage"];
