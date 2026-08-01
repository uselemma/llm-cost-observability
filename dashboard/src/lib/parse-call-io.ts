import type { Message } from "@/components/message-card";

/**
 * Normalize AI Gateway / OpenAI-ish prompt + completion payloads into Message[].
 *
 * CF stores prompt_json as `{"messages":[...]}` (not a bare array) and
 * completion_json as an OpenAI chat.completion wrapper, sometimes nested under
 * `{state, result}`.
 */
export function parseInputMessages(raw: string): Message[] {
  const v = parseJson(raw);
  if (v == null) return [];
  return asMessages(v);
}

export function parseOutputMessages(raw: string): Message[] {
  const v = parseJson(raw);
  if (v == null) {
    if (!raw?.trim()) return [];
    return [{ role: "assistant", content: raw }];
  }

  const fromMessages = asMessages(v);
  if (fromMessages.length > 0) return fromMessages;

  const completion = unwrapCompletion(v);
  if (completion) {
    const msgs = messagesFromChoices(completion);
    if (msgs.length > 0) return msgs;
  }

  if (isRecord(v) && typeof v.role === "string") {
    return [normalizeMessage(v)];
  }

  // Last resort: show the object as a single assistant message so the drawer
  // still renders something structured instead of a raw dump.
  return [{ role: "assistant", content: v as Record<string, unknown> }];
}

function parseJson(raw: string): unknown {
  if (!raw?.trim()) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function asMessages(v: unknown): Message[] {
  if (Array.isArray(v)) {
    return v.filter(isMessageLike).map(normalizeMessage);
  }
  if (!isRecord(v)) return [];

  for (const key of ["messages", "input", "prompt"] as const) {
    const candidate = v[key];
    if (Array.isArray(candidate)) {
      const msgs = candidate.filter(isMessageLike).map(normalizeMessage);
      if (msgs.length > 0) return msgs;
    }
  }
  return [];
}

function unwrapCompletion(v: unknown): Record<string, unknown> | null {
  if (!isRecord(v)) return null;
  // CF Workers AI / gateway wrapper: { state, result: <chat.completion> }
  if (isRecord(v.result) && Array.isArray(v.result.choices)) {
    return v.result;
  }
  if (Array.isArray(v.choices)) return v;
  return null;
}

function messagesFromChoices(completion: Record<string, unknown>): Message[] {
  const choices = completion.choices;
  if (!Array.isArray(choices)) return [];

  const out: Message[] = [];
  for (const choice of choices) {
    if (!isRecord(choice)) continue;
    const message = choice.message;
    if (isRecord(message) && typeof message.role === "string") {
      out.push(normalizeMessage(message));
      continue;
    }
    // Some exporters put text on the choice itself.
    if (typeof choice.text === "string" && choice.text) {
      out.push({ role: "assistant", content: choice.text });
    }
  }
  return out;
}

function isMessageLike(v: unknown): v is Record<string, unknown> {
  return isRecord(v) && typeof v.role === "string";
}

function normalizeMessage(v: Record<string, unknown>): Message {
  return {
    role: String(v.role),
    content: (v.content as Message["content"]) ?? null,
    name: typeof v.name === "string" ? v.name : undefined,
    tool_call_id:
      typeof v.tool_call_id === "string" ? v.tool_call_id : undefined,
    tool_calls: v.tool_calls,
  };
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
