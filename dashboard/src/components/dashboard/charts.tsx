import { useMemo, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { format } from 'date-fns';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, XAxis, YAxis } from 'recharts';
import {
  api,
  DIMENSIONS,
  type Bucket,
  type BreakdownRow,
  type Dimension,
  type StatsFilterParams,
  type TimeseriesPoint,
} from '@/api';
import { Button } from '@/components/ui/button';
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { colorFor, compact, DIMENSION_LABELS, seriesId, usd } from '@/lib/stats';
import ChartCard from './chart-card';

type SelectFilter = (dim: Dimension, value: string, mode?: 'include' | 'exclude') => void;
type Metric = 'spend' | 'calls' | 'tokens';

const BUCKET_LABELS: Record<Bucket, string> = {
  '1min': 'minute',
  '5min': '5 minutes',
  '15min': '15 minutes',
  '30min': '30 minutes',
  hour: 'hour',
  '6hour': '6 hours',
  day: 'day',
};
const METRIC_LABELS: Record<Metric, string> = {
  spend: 'Spend',
  calls: 'Calls',
  tokens: 'Tokens',
};
const metricFmt = (m: Metric) => (m === 'spend' ? usd : compact);
const metricOf = (p: Pick<TimeseriesPoint, 'spend' | 'calls' | 'input_tokens' | 'output_tokens'>, m: Metric) =>
  m === 'tokens' ? p.input_tokens + p.output_tokens : p[m];

function DimSelect({
  value,
  onChange,
  options = DIMENSIONS,
}: {
  value: Dimension;
  onChange: (d: Dimension) => void;
  options?: readonly Dimension[];
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as Dimension)}>
      <SelectTrigger size="sm" className="w-36">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((d) => (
          <SelectItem key={d} value={d}>
            {DIMENSION_LABELS[d]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function MetricSelect({ value, onChange }: { value: Metric; onChange: (m: Metric) => void }) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as Metric)}>
      <SelectTrigger size="sm" className="w-28">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {(Object.keys(METRIC_LABELS) as Metric[]).map((m) => (
          <SelectItem key={m} value={m}>
            {METRIC_LABELS[m]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// One tooltip row: colored dot, series label, formatted value.
function tooltipRow(fmt: (n: number) => string, config: ChartConfig) {
  return (value: unknown, name: unknown, item: { color?: string }): ReactNode => (
    <div className="flex w-full items-center justify-between gap-4">
      <span className="flex items-center gap-1.5">
        <span className="size-2 shrink-0 rounded-[2px]" style={{ background: item.color }} />
        {config[String(name)]?.label ?? String(name)}
      </span>
      <span className="font-mono tabular-nums">{fmt(Number(value))}</span>
    </div>
  );
}

// Short time-only labels are ambiguous once the range spans more than a day.
const tickTime = (bucket: Bucket, spanMs: number) => (t: string) =>
  format(
    new Date(t),
    bucket === 'day' ? 'MMM d' : spanMs > 24 * 3600_000 || bucket === '6hour' ? 'MMM d HH:mm' : 'HH:mm',
  );

// ---------------------------------------------------------------------------

function pivot(series: TimeseriesPoint[], keys: string[], metric: Metric) {
  const byT = new Map<string, Record<string, number | string>>();
  for (const p of series) {
    const row = byT.get(p.t) ?? { t: p.t, ...Object.fromEntries(keys.map((k) => [seriesId(k, keys), 0])) };
    row[seriesId(p.key, keys)] = metricOf(p, metric);
    byT.set(p.t, row);
  }
  return [...byT.values()];
}

export function SpendOverTime({
  filters,
  bucket,
  spanMs,
}: {
  filters: StatsFilterParams;
  bucket: Bucket;
  spanMs: number;
}) {
  const [groupBy, setGroupBy] = useState<Dimension>('model');
  const [metric, setMetric] = useState<Metric>('spend');
  const q = useQuery({
    queryKey: ['ts', filters, bucket, groupBy],
    queryFn: () => api.statsTimeseries(filters, { bucket, group_by: groupBy }),
  });
  const keys = q.data?.keys ?? [];
  const data = useMemo(() => pivot(q.data?.series ?? [], keys, metric), [q.data, keys, metric]);
  const config: ChartConfig = Object.fromEntries(
    keys.map((k) => [seriesId(k, keys), { label: k, color: colorFor(k, keys) }]),
  );
  const fmt = metricFmt(metric);
  return (
    <ChartCard
      title={`${METRIC_LABELS[metric]} over time`}
      description={`Per ${BUCKET_LABELS[bucket]}, split by ${DIMENSION_LABELS[groupBy].toLowerCase()} (top 6 + Other)`}
      actions={
        <div className="flex gap-2">
          <MetricSelect value={metric} onChange={setMetric} />
          <DimSelect value={groupBy} onChange={setGroupBy} />
        </div>
      }
      loading={q.isLoading}
      error={q.error}
      empty={data.length === 0}
      className="col-span-full"
    >
      <ChartContainer config={config} className="h-72 w-full">
        <AreaChart data={data} margin={{ left: 4, right: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="t" tickFormatter={tickTime(bucket, spanMs)} tickLine={false} axisLine={false} minTickGap={32} />
          <YAxis tickFormatter={fmt} tickLine={false} axisLine={false} width={56} />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={(_, p) => (p?.[0] ? tickTime(bucket, spanMs)(String(p[0].payload.t)) : '')}
                formatter={tooltipRow(fmt, config)}
              />
            }
          />
          <ChartLegend content={<ChartLegendContent />} />
          {keys.map((k) => (
            <Area
              key={k}
              isAnimationActive={false}
              dataKey={seriesId(k, keys)}
              type="monotone"
              stackId="a"
              stroke={colorFor(k, keys)}
              fill={colorFor(k, keys)}
              fillOpacity={0.3}
              strokeWidth={1.5}
            />
          ))}
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  );
}

// ---------------------------------------------------------------------------

function useBreakdown(filters: StatsFilterParams, by: Dimension, limit = 10) {
  return useQuery({
    queryKey: ['breakdown', filters, by, limit],
    queryFn: () => api.statsBreakdown(filters, { by, limit }),
  });
}

function HBar({
  rows,
  valueOf,
  fmt,
  label,
  by,
  onSelect,
}: {
  rows: BreakdownRow[];
  valueOf: (r: BreakdownRow) => number;
  fmt: (n: number) => string;
  label: string;
  by: Dimension;
  onSelect: SelectFilter;
}) {
  const keys = rows.map((r) => r.key);
  const config: ChartConfig = { value: { label } };
  const data = rows.map((r) => ({ key: r.key, value: valueOf(r) }));
  return (
    <ChartContainer config={config} className="w-full" style={{ height: rows.length * 34 + 32 }}>
      <BarChart data={data} layout="vertical" margin={{ left: 4, right: 56 }}>
        <CartesianGrid horizontal={false} />
        <YAxis
          dataKey="key"
          type="category"
          tickLine={false}
          axisLine={false}
          width={176}
          tickFormatter={(v: string) => (v.length > 24 ? `${v.slice(0, 23)}…` : v)}
        />
        <XAxis type="number" hide />
        <ChartTooltip
          cursor={false}
          content={<ChartTooltipContent hideLabel formatter={tooltipRow(fmt, config)} />}
        />
        <Bar
          isAnimationActive={false}
          dataKey="value"
          radius={4}
          className="cursor-pointer"
          label={{ position: 'right', formatter: (v: unknown) => fmt(Number(v)), fontSize: 11 }}
          onClick={(d: { payload?: { key: string } }, _i: number, e?: { shiftKey?: boolean }) =>
            d.payload &&
            d.payload.key !== 'Other' &&
            onSelect(by, d.payload.key, e?.shiftKey ? 'exclude' : 'include')
          }
        >
          {data.map((d) => (
            <Cell key={d.key} fill={colorFor(d.key, keys)} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

export function TopSpenders({
  filters,
  onSelect,
}: {
  filters: StatsFilterParams;
  onSelect: SelectFilter;
}) {
  const [by, setBy] = useState<Dimension>('feature_parent');
  const [metric, setMetric] = useState<Metric>('spend');
  const [hideTop, setHideTop] = useState(false);
  const q = useBreakdown(filters, by);
  const rows = useMemo(() => {
    const sorted = [...(q.data?.rows ?? [])].sort(
      (a, b) => metricOf(b, metric) - metricOf(a, metric),
    );
    return hideTop ? sorted.slice(1) : sorted;
  }, [q.data, metric, hideTop]);
  return (
    <ChartCard
      title={`${METRIC_LABELS[metric]} by ${DIMENSION_LABELS[by].toLowerCase()}`}
      description="Click a bar to filter, shift-click to exclude. Hide the top entry when one dominates."
      actions={
        <div className="flex gap-2">
          <Button
            size="sm"
            variant={hideTop ? 'secondary' : 'outline'}
            onClick={() => setHideTop((h) => !h)}
          >
            Hide top
          </Button>
          <MetricSelect value={metric} onChange={setMetric} />
          <DimSelect value={by} onChange={setBy} />
        </div>
      }
      loading={q.isLoading}
      error={q.error}
      empty={rows.length === 0}
    >
      <HBar
        rows={rows}
        valueOf={(r) => metricOf(r, metric)}
        fmt={metricFmt(metric)}
        label={METRIC_LABELS[metric]}
        by={by}
        onSelect={onSelect}
      />
    </ChartCard>
  );
}

// ---------------------------------------------------------------------------

export function SpendMatrix({ filters }: { filters: StatsFilterParams }) {
  const [rowsBy, setRowsBy] = useState<Dimension>('feature_parent');
  const [colsBy, setColsBy] = useState<Dimension>('model');
  const q = useQuery({
    queryKey: ['matrix', filters, rowsBy, colsBy],
    queryFn: () => api.statsMatrix(filters, { rows: rowsBy, cols: colsBy }),
    enabled: rowsBy !== colsBy,
  });
  const cols = q.data?.cols ?? [];
  const data = (q.data?.rows ?? []).map((row) => {
    const out: Record<string, number | string> = { row };
    for (const c of cols) {
      out[seriesId(c, cols)] =
        q.data?.cells.find((x) => x.row === row && x.col === c)?.spend ?? 0;
    }
    return out;
  });
  const config: ChartConfig = Object.fromEntries(
    cols.map((c) => [seriesId(c, cols), { label: c, color: colorFor(c, cols) }]),
  );
  return (
    <ChartCard
      title="Spend breakdown"
      description={`${DIMENSION_LABELS[rowsBy]} × ${DIMENSION_LABELS[colsBy].toLowerCase()}`}
      actions={
        <div className="flex gap-2">
          <DimSelect value={rowsBy} onChange={setRowsBy} />
          <DimSelect value={colsBy} onChange={setColsBy} />
        </div>
      }
      loading={q.isLoading}
      error={q.error}
      empty={rowsBy === colsBy || data.length === 0}
      emptyText={rowsBy === colsBy ? 'Pick two different dimensions.' : undefined}
    >
      <ChartContainer config={config} className="w-full" style={{ height: data.length * 34 + 72 }}>
        <BarChart data={data} layout="vertical" margin={{ left: 4, right: 12 }}>
          <CartesianGrid horizontal={false} />
          <YAxis
            dataKey="row"
            type="category"
            tickLine={false}
            axisLine={false}
            width={176}
            tickFormatter={(v: string) => (v.length > 24 ? `${v.slice(0, 23)}…` : v)}
          />
          <XAxis type="number" tickFormatter={usd} tickLine={false} axisLine={false} />
          <ChartTooltip cursor={false} content={<ChartTooltipContent formatter={tooltipRow(usd, config)} />} />
          <ChartLegend content={<ChartLegendContent />} />
          {cols.map((c) => (
            <Bar key={c} isAnimationActive={false} dataKey={seriesId(c, cols)} stackId="m" fill={colorFor(c, cols)} />
          ))}
        </BarChart>
      </ChartContainer>
    </ChartCard>
  );
}

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------

export function CallsOverTime({
  filters,
  bucket,
  spanMs,
}: {
  filters: StatsFilterParams;
  bucket: Bucket;
  spanMs: number;
}) {
  const [groupBy, setGroupBy] = useState<Dimension>('feature_parent');
  // Same query key as SpendOverTime, so the same group-by shares one request.
  const q = useQuery({
    queryKey: ['ts', filters, bucket, groupBy],
    queryFn: () => api.statsTimeseries(filters, { bucket, group_by: groupBy }),
  });
  const keys = q.data?.keys ?? [];
  const data = useMemo(() => pivot(q.data?.series ?? [], keys, 'calls'), [q.data, keys]);
  const config: ChartConfig = Object.fromEntries(
    keys.map((k) => [seriesId(k, keys), { label: k, color: colorFor(k, keys) }]),
  );
  return (
    <ChartCard
      title="Calls over time"
      description={`Per ${BUCKET_LABELS[bucket]}, split by ${DIMENSION_LABELS[groupBy].toLowerCase()} (top 6 + Other)`}
      actions={<DimSelect value={groupBy} onChange={setGroupBy} />}
      loading={q.isLoading}
      error={q.error}
      empty={data.length === 0}
    >
      <ChartContainer config={config} className="h-72 w-full">
        <BarChart data={data} margin={{ left: 4, right: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="t" tickFormatter={tickTime(bucket, spanMs)} tickLine={false} axisLine={false} minTickGap={32} />
          <YAxis tickFormatter={compact} tickLine={false} axisLine={false} width={48} />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={(_, p) => (p?.[0] ? tickTime(bucket, spanMs)(String(p[0].payload.t)) : '')}
                formatter={tooltipRow(compact, config)}
              />
            }
          />
          <ChartLegend content={<ChartLegendContent />} />
          {keys.map((k) => (
            <Bar
              key={k}
              isAnimationActive={false}
              dataKey={seriesId(k, keys)}
              stackId="c"
              fill={colorFor(k, keys)}
            />
          ))}
        </BarChart>
      </ChartContainer>
    </ChartCard>
  );
}

// ---------------------------------------------------------------------------

const MIX_METRICS = ['spend', 'calls'] as const;

export function MixDonut({
  filters,
  onSelect,
}: {
  filters: StatsFilterParams;
  onSelect: SelectFilter;
}) {
  const [by, setBy] = useState<Dimension>('provider');
  const [metric, setMetric] = useState<'spend' | 'calls'>('spend');
  const q = useBreakdown(filters, by, 8);
  const rows = useMemo(
    () =>
      (q.data?.rows ?? [])
        .filter((r) => metricOf(r, metric) > 0)
        .sort((a, b) => metricOf(b, metric) - metricOf(a, metric)),
    [q.data, metric],
  );
  const keys = rows.map((r) => r.key);
  const total = rows.reduce((sum, r) => sum + metricOf(r, metric), 0);
  const fmt = metricFmt(metric);
  const config: ChartConfig = { value: { label: METRIC_LABELS[metric] } };
  const pick = (key: string, e?: { shiftKey?: boolean }) =>
    key !== 'Other' && onSelect(by, key, e?.shiftKey ? 'exclude' : 'include');
  return (
    <ChartCard
      title={`${METRIC_LABELS[metric]} mix by ${DIMENSION_LABELS[by].toLowerCase()}`}
      description="Share of the total. Click a slice or row to filter, shift-click to exclude."
      actions={
        <div className="flex gap-2">
          <Select value={metric} onValueChange={(v) => setMetric(v as 'spend' | 'calls')}>
            <SelectTrigger size="sm" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MIX_METRICS.map((m) => (
                <SelectItem key={m} value={m}>
                  {METRIC_LABELS[m]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <DimSelect value={by} onChange={setBy} />
        </div>
      }
      loading={q.isLoading}
      error={q.error}
      empty={rows.length === 0}
    >
      <div className="flex flex-wrap items-center gap-6">
        <div className="relative mx-auto size-56 shrink-0">
          <ChartContainer config={config} className="size-full">
            <PieChart>
              <ChartTooltip
                content={<ChartTooltipContent hideLabel formatter={tooltipRow(fmt, config)} />}
              />
              <Pie
                data={rows.map((r) => ({ name: r.key, value: metricOf(r, metric) }))}
                dataKey="value"
                nameKey="name"
                innerRadius={68}
                outerRadius={104}
                paddingAngle={1}
                isAnimationActive={false}
                className="cursor-pointer"
                onClick={(d: { name?: string }, _i: number, e?: { shiftKey?: boolean }) =>
                  d.name && pick(d.name, e)
                }
              >
                {rows.map((r) => (
                  <Cell key={r.key} fill={colorFor(r.key, keys)} stroke="var(--card)" />
                ))}
              </Pie>
            </PieChart>
          </ChartContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-xl font-semibold tabular-nums">{fmt(total)}</span>
            <span className="text-xs text-muted-foreground">total</span>
          </div>
        </div>
        <ul className="min-w-0 flex-1 basis-56 space-y-1 text-xs">
          {rows.map((r) => {
            const v = metricOf(r, metric);
            return (
              <li key={r.key}>
                <button
                  type="button"
                  disabled={r.key === 'Other'}
                  onClick={(e) => pick(r.key, e)}
                  className="grid w-full grid-cols-[0.75rem_minmax(0,1fr)_4.5rem_3.25rem] items-center gap-2 rounded px-1 py-1 text-left enabled:hover:bg-muted"
                >
                  <span className="size-2.5 rounded-[2px]" style={{ background: colorFor(r.key, keys) }} />
                  <span className="truncate font-mono text-[11px]" title={r.key}>
                    {r.key}
                  </span>
                  <span className="text-right tabular-nums">{fmt(v)}</span>
                  <span className="text-right tabular-nums text-muted-foreground">
                    {((v / total) * 100).toFixed(v / total < 0.001 ? 2 : 1)}%
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </ChartCard>
  );
}
