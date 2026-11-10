import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowsClockwise } from '@phosphor-icons/react';
import { useSearchParams } from 'react-router-dom';
import { api, DIMENSIONS, type Bucket, type Dimension, type StatsFilterParams } from '@/api';
import { bucketCount, GRANULARITIES, MAX_BUCKETS } from '@/lib/stats';
import { Button } from '@/components/ui/button';
import {
  CallsOverTime,
  MixDonut,
  SpendMatrix,
  SpendOverTime,
  TopSpenders,
} from '@/components/dashboard/charts';
import DashboardFilters, {
  type FilterMode,
  type FilterState,
  type Granularity,
  type Selected,
} from '@/components/dashboard/dashboard-filters';
import KpiCards from '@/components/dashboard/kpi-cards';
import { PageHeader } from '@/components/app-shell';
import { autoBucket, readRange, resolveRange, writeRange, type RangeState } from '@/lib/range';

const BUCKETS = new Set(GRANULARITIES.map((g) => g.value));

// Filters live in the URL so a view can be shared:
//   ?range=7d&gran=hour&model=gpt-6-luna&not_feature_parent=signal-pipeline
//   or a custom window: ?since=2026-11-09T14:00&until=2026-11-09T20:00
function readState(sp: URLSearchParams): {
  range: RangeState;
  granularity: Granularity;
  state: FilterState;
} {
  const range = readRange(sp);
  const g = sp.get('gran');
  const granularity = g && BUCKETS.has(g as Bucket) ? (g as Bucket) : 'auto';
  const state: FilterState = { include: {}, exclude: {} };
  for (const d of DIMENSIONS) {
    const inc = sp.getAll(d);
    if (inc.length) state.include[d] = inc;
    const exc = sp.getAll(`not_${d}`);
    if (exc.length) state.exclude[d] = exc;
  }
  return { range, granularity, state };
}

const toParams = (s: Selected, prefix = ''): StatsFilterParams =>
  Object.fromEntries(Object.entries(s).map(([d, v]) => [`${prefix}${d}`, v]));

export default function Dashboard() {
  const [sp, setSp] = useSearchParams();
  const { range, granularity, state } = readState(sp);
  // Anchor "now" so query keys stay stable between renders; Refresh moves it.
  const [anchor, setAnchor] = useState(() => Date.now());
  const queryClient = useQueryClient();
  const resolved = useMemo(
    () => resolveRange(range, anchor),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [anchor, sp.toString()],
  );
  const spanMs = resolved.spanMs;
  const auto = autoBucket(spanMs);
  // An explicit granularity can become invalid after the range changes; fall back to auto.
  const granValid =
    granularity !== 'auto' &&
    bucketCount(spanMs, granularity) <= MAX_BUCKETS &&
    (GRANULARITIES.find((g) => g.value === granularity)?.ms ?? 0) <= spanMs;
  const bucket: Bucket = granValid ? (granularity as Bucket) : auto;

  const filters: StatsFilterParams = useMemo(
    () => ({
      since: resolved.since,
      until: resolved.until,
      ...toParams(state.include),
      ...toParams(state.exclude, 'not_'),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [resolved, sp.toString()],
  );

  function update(nextRange: RangeState, nextGran: Granularity, next: FilterState) {
    const usp = new URLSearchParams();
    writeRange(usp, nextRange);
    if (nextGran !== 'auto') usp.set('gran', nextGran);
    for (const d of DIMENSIONS) {
      (next.include[d] ?? []).forEach((v) => usp.append(d, v));
      (next.exclude[d] ?? []).forEach((v) => usp.append(`not_${d}`, v));
    }
    setSp(usp, { replace: true });
    setAnchor(Date.now());
  }

  // Dropdown Save: replace a dimension's include/exclude lists in one update.
  function apply(dim: Dimension, include: string[], exclude: string[]) {
    update(range, granularity, {
      include: { ...state.include, [dim]: include },
      exclude: { ...state.exclude, [dim]: exclude },
    });
  }

  // A value is in exactly one of include/exclude: choosing one mode clears the other,
  // and choosing the active mode again removes it.
  function toggle(dim: Dimension, value: string, mode: FilterMode = 'include') {
    const other: FilterMode = mode === 'include' ? 'exclude' : 'include';
    const cur = state[mode][dim] ?? [];
    const nextCur = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
    update(range, granularity, {
      ...state,
      [mode]: { ...state[mode], [dim]: nextCur },
      [other]: { ...state[other], [dim]: (state[other][dim] ?? []).filter((v) => v !== value) },
    });
  }

  const summary = useQuery({ queryKey: ['summary', filters], queryFn: () => api.statsSummary(filters) });
  // Dropdown options come from the time window only, so they stay complete while filtering.
  const dims = useQuery({
    queryKey: ['dimensions', filters.since, filters.until],
    queryFn: () => api.statsDimensions({ since: filters.since, until: filters.until }),
  });

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <PageHeader
        title="LLM usage"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              // Presets re-anchor to now; fixed ranges just refetch.
              setAnchor(Date.now());
              queryClient.invalidateQueries();
            }}
            disabled={summary.isFetching}
          >
            <ArrowsClockwise className={summary.isFetching ? 'animate-spin' : ''} />
            Refresh
          </Button>
        }
      />

      <DashboardFilters
        range={range}
        onRange={(r) => update(r, granularity, state)}
        granularity={granValid ? granularity : 'auto'}
        onGranularity={(g) => update(range, g, state)}
        autoBucket={auto}
        spanMs={spanMs}
        state={state}
        dimensions={dims.data?.dimensions}
        onToggle={toggle}
        onApply={apply}
        onClear={() => update(range, granularity, { include: {}, exclude: {} })}
      />

      <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-4">
        {summary.error ? (
          <div className="text-sm text-destructive">
            Failed to load: {(summary.error as Error).message}
          </div>
        ) : (
          <KpiCards data={summary.data} loading={summary.isLoading} />
        )}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <SpendOverTime filters={filters} bucket={bucket} spanMs={spanMs} />
          <CallsOverTime filters={filters} bucket={bucket} spanMs={spanMs} />
          <MixDonut filters={filters} onSelect={toggle} />
          <TopSpenders filters={filters} onSelect={toggle} />
          <SpendMatrix filters={filters} />
        </div>
      </div>
    </div>
  );
}
