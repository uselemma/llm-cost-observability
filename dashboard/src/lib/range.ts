import type { Bucket } from '@/api';

// Relative presets re-anchor to "now" on every refresh; custom ranges are fixed.
export const PRESETS = [
  { value: '1h', label: 'Last hour', ms: 3600_000 },
  { value: '6h', label: 'Last 6 hours', ms: 6 * 3600_000 },
  { value: '24h', label: 'Last 24 hours', ms: 24 * 3600_000 },
  { value: '7d', label: 'Last 7 days', ms: 7 * 24 * 3600_000 },
  { value: '30d', label: 'Last 30 days', ms: 30 * 24 * 3600_000 },
] as const;
export type PresetValue = (typeof PRESETS)[number]['value'];

// Custom bounds are local "YYYY-MM-DDTHH:mm" strings (datetime-local format).
export type RangeState =
  | { kind: 'preset'; preset: PresetValue }
  | { kind: 'custom'; since: string; until: string };

export const DEFAULT_RANGE: RangeState = { kind: 'preset', preset: '1h' };

export const DT_FMT = "yyyy-MM-dd'T'HH:mm";

export function presetMs(p: PresetValue): number {
  return PRESETS.find((x) => x.value === p)!.ms;
}

// Granularity used when the user hasn't picked one: coarser as the span grows.
export function autoBucket(spanMs: number): Bucket {
  const h = 3600_000;
  if (spanMs <= 2 * h) return '5min';
  if (spanMs <= 12 * h) return '15min';
  if (spanMs <= 72 * h) return 'hour';
  return 'day';
}

export type ResolvedRange = { since: string; until?: string; spanMs: number };

export function resolveRange(r: RangeState, now: number): ResolvedRange {
  if (r.kind === 'preset') {
    const ms = presetMs(r.preset);
    return { since: new Date(now - ms).toISOString(), spanMs: ms };
  }
  const from = new Date(r.since).getTime();
  const to = new Date(r.until).getTime();
  return { since: new Date(from).toISOString(), until: new Date(to).toISOString(), spanMs: to - from };
}

// ?range=24h  or  ?since=2026-11-09T14:00&until=2026-11-09T20:00
export function readRange(sp: URLSearchParams): RangeState {
  const since = sp.get('since');
  const until = sp.get('until');
  if (since && until) {
    const a = new Date(since).getTime();
    const b = new Date(until).getTime();
    if (!Number.isNaN(a) && !Number.isNaN(b) && b > a) return { kind: 'custom', since, until };
  }
  const p = sp.get('range');
  const preset = PRESETS.find((x) => x.value === p);
  return preset ? { kind: 'preset', preset: preset.value } : DEFAULT_RANGE;
}

export function writeRange(usp: URLSearchParams, r: RangeState) {
  if (r.kind === 'custom') {
    usp.set('since', r.since);
    usp.set('until', r.until);
  } else if (r.preset !== (DEFAULT_RANGE as { preset: PresetValue }).preset) {
    usp.set('range', r.preset);
  }
}
