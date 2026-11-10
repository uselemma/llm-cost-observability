import { useMemo, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { ArrowsClockwise } from '@phosphor-icons/react';
import { api } from '@/api';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import CallsTable from '@/components/calls-table';
import CallDrawer from '@/components/call-drawer';
import FilterBar, { type Filters } from '@/components/filter-bar';
import { PageHeader } from '@/components/app-shell';

type PageSizeOption = 100 | 250 | 500 | 'max';

const DEFAULT_PAGE_SIZE: PageSizeOption = 100;

export default function Calls() {
  const [filters, setFilters] = useState<Filters>({ since: defaultSince() });
  const [selectedCall, setSelectedCall] = useState<{
    id: string;
    timestamp: string;
  } | null>(null);
  const [pageSize, setPageSize] = useState<PageSizeOption>(DEFAULT_PAGE_SIZE);
  const isMaxMode = pageSize === 'max';
  const requestLimit = isMaxMode ? 0 : pageSize;

  const {
    data,
    isFetching,
    isFetchingNextPage,
    error,
    refetch,
    fetchNextPage,
    hasNextPage,
  } = useInfiniteQuery({
    queryKey: ['calls', filters, pageSize],
    queryFn: ({ pageParam }) =>
      api.listCalls({ ...filters, limit: requestLimit, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => {
      if (isMaxMode) return undefined;
      return last.rows.length < requestLimit ? undefined : all.length * requestLimit;
    },
  });

  const rows = data?.pages.flatMap((p) => p.rows) ?? [];
  const availableTags = useMemo(
    () =>
      Array.from(
        new Set(rows.flatMap((r) => r.tags.filter((t) => !t.startsWith('env:')))),
      ).sort((a, b) => a.localeCompare(b)),
    [rows],
  );

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <PageHeader
        title="LLM call log"
        actions={
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <ArrowsClockwise className={isFetching ? 'animate-spin' : ''} />
            Refresh
          </Button>
        }
      />

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg bg-card shadow-xs ring-1 ring-foreground/10">
        <FilterBar filters={filters} onChange={setFilters} availableTags={availableTags} />
        <Separator />

        <div className="min-h-0 flex-1 overflow-hidden">
          {error ? (
            <div className="p-4 text-body-sm text-destructive">Failed to load: {(error as Error).message}</div>
          ) : (
            <CallsTable
              rows={rows}
              onSelect={(id, timestamp) => setSelectedCall({ id, timestamp })}
              loading={isFetching && rows.length === 0}
              hasMore={!!hasNextPage}
              loadingMore={isFetchingNextPage}
              onLoadMore={() => fetchNextPage()}
              pageSize={pageSize}
              onPageSizeChange={setPageSize}
            />
          )}
        </div>
      </div>

      {selectedCall && (
        <CallDrawer
          requestId={selectedCall.id}
          timestamp={selectedCall.timestamp}
          onClose={() => setSelectedCall(null)}
        />
      )}
    </div>
  );
}

function defaultSince(): string {
  const d = new Date(Date.now() - 24 * 60 * 60 * 1000);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const h = String(d.getHours()).padStart(2, '0');
  const min = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${day}T${h}:${min}`;
}
