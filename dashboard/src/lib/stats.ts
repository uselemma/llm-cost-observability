import type { Bucket, Dimension } from '@/api';

export const DIMENSION_LABELS: Record<Dimension, string> = {
  model: 'Model',
  provider: 'Provider',
  feature_parent: 'Feature',
  feature: 'Sub-feature',
  prompt: 'Prompt',
  project_id: 'Project',
  variant: 'Variant',
};

export const usd = (n: number) =>
  n === 0
    ? '$0'
    : n >= 100
    ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
    : n >= 1
      ? `$${n.toFixed(2)}`
      : `$${n.toFixed(n < 0.01 ? 4 : 3)}`;

export const compact = (n: number) =>
  new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(n);

export const ms = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${Math.round(n)}ms`);

export const pct = (n: number) => `${(n * 100).toFixed(n > 0 && n < 0.001 ? 2 : 1)}%`;

// Lemma's chart palette is --chart-1..6, ordered by salience (purple accent first), so a series
// is colored by its rank. Every chart passes its keys spend-ordered (top-N then Other), which
// keeps a given model/feature on the same color across charts for the same filters.
const OTHER_KEYS = new Set(['Other', '(none)']);
const PALETTE_SIZE = 6;

export function colorFor(key: string, keys: string[]): string {
  if (OTHER_KEYS.has(key)) return 'var(--chart-other)';
  const rank = keys.filter((k) => !OTHER_KEYS.has(k)).indexOf(key);
  const r = Math.max(rank, 0);
  const base = `var(--chart-${(r % PALETTE_SIZE) + 1})`;
  // Past the 6th series, reuse the palette as lighter tints so colors don't collide.
  return r < PALETTE_SIZE ? base : `color-mix(in oklab, ${base} 55%, var(--card))`;
}

// Recharts data keys can't safely contain dots/spaces, so charts use positional ids.
export const seriesId = (key: string, keys: string[]) => `s${keys.indexOf(key)}`;

export const GRANULARITIES: { value: Bucket; label: string; ms: number }[] = [
  { value: '1min', label: '1 minute', ms: 60_000 },
  { value: '5min', label: '5 minutes', ms: 5 * 60_000 },
  { value: '15min', label: '15 minutes', ms: 15 * 60_000 },
  { value: '30min', label: '30 minutes', ms: 30 * 60_000 },
  { value: 'hour', label: '1 hour', ms: 3600_000 },
  { value: '6hour', label: '6 hours', ms: 6 * 3600_000 },
  { value: 'day', label: '1 day', ms: 24 * 3600_000 },
];

// Beyond this many buckets a chart is unreadable and the response gets large.
export const MAX_BUCKETS = 400;
export const bucketCount = (spanMs: number, bucket: Bucket) =>
  spanMs / (GRANULARITIES.find((g) => g.value === bucket)?.ms ?? 3600_000);
