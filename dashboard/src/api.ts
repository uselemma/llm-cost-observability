export type CallRow = {
  request_id: string;
  timestamp: string;
  model: string;
  provider: string;
  team: string;
  status: string;
  finish_reason: string;
  spend_usd: number;
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  total_tokens: number;
  latency_ms: number;
  ttft_ms: number;
  tags: string[];
  output_preview: string;
  reconciliation_status: 'reconciled' | 'cache_hit' | 'legacy' | 'unreconciled';
  is_complete: number;
  reconciliation_overdue: number;
  reconciliation_ms: number;
  cost_included: number;
  exact_cache_hit: number;
};

export type ProviderAttempt = {
  span_id: string;
  parent_span_id: string;
  name: string;
  kind: string;
  status: string;
  error_message: string;
  latency_ms: number;
  model: string;
  provider: string;
  model_attempt_index: number;
  attempt_number: number;
  attempt_id: string;
  attempt_success: string;
  provider_timeout: string;
  configured_timeout_ms: number;
  credential_type: string;
  region: string;
  metadata: string;
};

export type CallDetail = CallRow & {
  audio_tokens: number;
  image_tokens: number;
  error_message: string;
  num_retries: number;
  temperature: number | null;
  top_p: number | null;
  max_tokens: number | null;
  presence_penalty: number | null;
  metadata: string;
  input_messages: string;
  output_text: string;
  reasoning_content: string;
  tool_calls: string;
  call_id: string;
  cloudflare_span_id: string;
  vercel_span_id: string;
  app_trace_id: string;
  billed_cost_usd: number;
  market_cost_usd: number;
  vercel_latency_ms: number;
  generation_id: string;
  credential_type: string;
  region: string;
  zdr_requested: string;
  attempts: ProviderAttempt[];
};

export type CallsListParams = {
  since?: string;
  until?: string;
  model?: string;
  status?: string;
  tag?: string[];
  cel?: string;
  q?: string;
  limit?: number;
  offset?: number;
};

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  });
  if (res.status === 401) throw new ApiError(401, 'unauthenticated');
  if (!res.ok) throw new ApiError(res.status, (await res.text()) || res.statusText);
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  me: () => request<{ authenticated: boolean; env: string | null }>('/api/me'),
  listCalls: (params: CallsListParams) => {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v == null || v === '') return;
      if (Array.isArray(v)) {
        v.forEach((item) => usp.append(k, String(item)));
      } else {
        if ((k === 'since' || k === 'until') && typeof v === 'string') {
          usp.set(k, normalizeDateTimeParam(v));
          return;
        }
        usp.set(k, String(v));
      }
    });
    return request<{ rows: CallRow[]; limit: number; offset: number }>(`/api/calls?${usp}`);
  },
  getCall: (id: string, timestamp?: string) => {
    const query = timestamp
      ? `?timestamp=${encodeURIComponent(normalizeDateTimeParam(timestamp))}`
      : '';
    return request<CallDetail>(`/api/calls/${encodeURIComponent(id)}${query}`);
  },
  listModels: () => request<{ models: string[] }>('/api/models'),
  listTags: () => request<{ tags: string[] }>('/api/tags'),
  listCelFields: () => request<{ fields: string[] }>('/api/cel-fields'),
};

export { ApiError };

function normalizeDateTimeParam(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString();
}
