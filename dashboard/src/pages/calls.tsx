import { useMemo, useState } from 'react';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { api } from '@/api';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import CallsTable from '@/components/calls-table';
import CallDrawer from '@/components/call-drawer';
import FilterBar, { type Filters } from '@/components/filter-bar';
import { ModeToggle } from '@/components/mode-toggle';

type PageSizeOption = 100 | 250 | 500 | 'max';

const DEFAULT_PAGE_SIZE: PageSizeOption = 100;

export default function Calls() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: api.me });
  const [filters, setFilters] = useState<Filters>({ since: defaultSince() });
  const [selectedId, setSelectedId] = useState<string | null>(null);
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
    <div className="flex h-full flex-col bg-background">
      <header className="flex items-center justify-between border-b bg-background px-4 py-3">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-semibold tracking-tight">LLM call log</h1>
          {me.data?.env && (
            <span className="bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              {me.data.env}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ModeToggle />
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={isFetching ? 'animate-spin' : ''} />
            Refresh
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={async () => {
              await api.logout();
              qc.invalidateQueries();
            }}
          >
            Sign out
          </Button>
        </div>
      </header>

      <FilterBar filters={filters} onChange={setFilters} availableTags={availableTags} />
      <Separator />

      <main className="flex-1 overflow-hidden bg-muted">
        {error ? (
          <div className="p-4 text-sm text-destructive">Failed to load: {(error as Error).message}</div>
        ) : (
          <CallsTable
            rows={rows}
            onSelect={setSelectedId}
            loading={isFetching && rows.length === 0}
            hasMore={!!hasNextPage}
            loadingMore={isFetchingNextPage}
            onLoadMore={() => fetchNextPage()}
            pageSize={pageSize}
            onPageSizeChange={setPageSize}
          />
        )}
      </main>

      {selectedId && <CallDrawer requestId={selectedId} onClose={() => setSelectedId(null)} />}
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
