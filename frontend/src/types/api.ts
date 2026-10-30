/**
 * общие типы из сгенерированного контракта API.
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
export type EventStatus = Schemas["EventStatus"];
export type AssistantReply = Schemas["AssistantReply"];
export type ChatMessage = Schemas["ChatMessage"];
export type Pending = Schemas["Pending"];
export type Period = Schemas["Period"];
