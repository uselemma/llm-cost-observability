import type { Metrics } from '@/api';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { compact, ms, pct, usd } from '@/lib/stats';

export default function KpiCards({ data, loading }: { data?: Metrics; loading: boolean }) {
  const items: { label: string; value: string; hint?: string }[] = data
    ? [
        {
          label: 'Spend',
          value: usd(data.spend),
          // Calls with no recorded cost and no models.dev price for their model.
          hint: data.unpriced_calls
            ? `${compact(data.unpriced_calls)} calls with no price`
            : 'Excludes failed calls',
        },
        { label: 'Calls', value: compact(data.calls), hint: `${usd(data.avg_cost)} avg / call` },
        {
          label: 'Tokens',
          value: compact(data.input_tokens + data.output_tokens),
          hint: `${compact(data.input_tokens)} in · ${compact(data.output_tokens)} out`,
        },
        { label: 'Error rate', value: pct(data.error_rate), hint: `${compact(data.errors)} failed` },
        { label: 'p50 latency', value: ms(data.p50_ms) },
        { label: 'p95 latency', value: ms(data.p95_ms) },
      ]
    : [];
  return (
    <div
      className="grid gap-4"
      style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(11rem, 1fr))' }}
    >
      {loading || !data
        ? Array.from({ length: 6 }, (_, i) => (
            <Card key={i} className="h-24 animate-pulse bg-muted" />
          ))
        : items.map((it) => (
            <Card key={it.label}>
              <CardHeader>
                <CardDescription className="text-section-header">{it.label}</CardDescription>
                <CardTitle className="font-heading text-h3 tabular-nums">{it.value}</CardTitle>
                {it.hint && <CardDescription className="text-body-xs">{it.hint}</CardDescription>}
              </CardHeader>
            </Card>
          ))}
    </div>
  );
}
