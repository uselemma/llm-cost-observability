import { Fragment, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Loader2 } from 'lucide-react';
import type { CallRow } from '@/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { parseApiTimestamp } from '@/lib/datetime';
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

export default function CallsTable({
  rows,
  onSelect,
  loading,
  hasMore,
  loadingMore,
  onLoadMore,
  pageSize,
  onPageSizeChange,
}: {
  rows: CallRow[];
  onSelect: (id: string) => void;
  loading: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  pageSize: 100 | 250 | 500 | 'max';
  onPageSizeChange: (size: 100 | 250 | 500 | 'max') => void;
}) {
  if (loading) return <div className="p-4 text-sm text-muted-foreground">Loading…</div>;
  if (rows.length === 0)
    return <div className="p-4 text-sm text-muted-foreground">No calls in this window.</div>;

  const tableContainerRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => tableContainerRef.current,
    estimateSize: () => 44,
    overscan: 20,
  });
  const virtualRows = rowVirtualizer.getVirtualItems();
  const topPaddingHeight = virtualRows.length > 0 ? virtualRows[0].start : 0;
  const bottomPaddingHeight =
    virtualRows.length > 0
      ? rowVirtualizer.getTotalSize() - virtualRows[virtualRows.length - 1].end
      : 0;

  const aggregates = rows.reduce(
    (acc, row) => {
      acc.cost += row.spend_usd;
      acc.cacheRead += tokenValue(row.cache_read_tokens);
      acc.cacheCreation += tokenValue(row.cache_creation_tokens);
      return acc;
    },
    { cost: 0, cacheRead: 0, cacheCreation: 0 },
  );
  const tokenPercentiles = percentileSummary(rows.map((row) => totalTokenCount(row)));
  const latencyPercentiles = percentileSummary(rows.map((row) => row.latency_ms));
  const tpsPercentiles = percentileSummary(rows.map((row) => tokensPerSecond(row)).filter(isNumber));

  return (
    <div className="flex h-full flex-col bg-muted">
      <Table containerRef={tableContainerRef}>
        <TableHeader>
          <TableRow>
            <TableHead className="sticky top-0 z-20 w-[160px] bg-muted">Time</TableHead>
            <TableHead className="sticky top-0 z-20 w-[260px] bg-muted">Tags</TableHead>
            <TableHead className="sticky top-0 z-20 w-[240px] bg-muted">Model</TableHead>
            <TableHead className="sticky top-0 z-20 w-[100px] bg-muted">Status</TableHead>
            <TableHead className="sticky top-0 z-20 w-[100px] bg-muted text-right">Cost</TableHead>
            <TableHead className="sticky top-0 z-20 w-[180px] bg-muted text-right">Tokens</TableHead>
            <TableHead className="sticky top-0 z-20 w-[140px] bg-muted text-right">Cached</TableHead>
            <TableHead className="sticky top-0 z-20 w-[200px] bg-muted text-right">Latency (ms)</TableHead>
            <TableHead className="sticky top-0 z-20 w-[120px] bg-muted text-right">TPS</TableHead>
            <TableHead className="sticky top-0 z-20 bg-muted">Output preview</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {topPaddingHeight > 0 && (
            <TableRow className="pointer-events-none hover:bg-transparent">
              <TableCell colSpan={10} className="border-b-0 p-0" style={{ height: topPaddingHeight }} />
            </TableRow>
          )}
          {virtualRows.map((virtualRow) => {
            const r = rows[virtualRow.index];
            return (
            <TableRow
              key={r.request_id}
              onClick={() => onSelect(r.request_id)}
              className="cursor-pointer"
            >
              <TableCell className="tabular-nums text-muted-foreground">
                {fmtTime(r.timestamp)}
              </TableCell>
              <TableCell><TagPills tags={r.tags} /></TableCell>
              <TableCell className="truncate font-mono text-xs">{r.model}</TableCell>
              <TableCell>{statusBadge(r.status, r.finish_reason)}</TableCell>
              <TableCell className="text-right tabular-nums">${r.spend_usd.toFixed(5)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {r.prompt_tokens}+{outputTokenCount(r)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                <CachedTokens read={tokenValue(r.cache_read_tokens)} creation={tokenValue(r.cache_creation_tokens)} />
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {r.latency_ms}
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {formatTps(tokensPerSecond(r))}
              </TableCell>
              <TableCell className="max-w-[1px] truncate">{r.output_preview || '—'}</TableCell>
            </TableRow>
            );
          })}
          {bottomPaddingHeight > 0 && (
            <TableRow className="pointer-events-none hover:bg-transparent">
              <TableCell colSpan={10} className="border-b-0 p-0" style={{ height: bottomPaddingHeight }} />
            </TableRow>
          )}
        </TableBody>
        <TableFooter>
          <TableRow className="hover:bg-muted">
            <TableCell
              colSpan={4}
              className="sticky bottom-0 z-10 border-t border-b-0 bg-muted/95 text-[10px] uppercase tracking-wider text-muted-foreground"
            >
              Aggregates for loaded rows
            </TableCell>
            <TableCell className="sticky bottom-0 z-10 border-t border-b-0 bg-muted/95 text-right font-mono text-[11px]">
              ${aggregates.cost.toFixed(5)}
            </TableCell>
            <TableCell className="sticky bottom-0 z-10 border-t border-b-0 bg-muted/95 text-right font-mono text-[11px]">
              <PercentileLines
                labels={['p50', 'p95', 'p99']}
                values={[
                  formatTokenCount(tokenPercentiles[50]),
                  formatTokenCount(tokenPercentiles[95]),
                  formatTokenCount(tokenPercentiles[99]),
                ]}
              />
            </TableCell>
            <TableCell className="sticky bottom-0 z-10 border-t border-b-0 bg-muted/95 text-right font-mono text-[11px]">
              <CachedTokens read={aggregates.cacheRead} creation={aggregates.cacheCreation} />
            </TableCell>
            <TableCell className="sticky bottom-0 z-10 border-t border-b-0 bg-muted/95 text-right font-mono text-[11px]">
              <PercentileLines
                labels={['p50', 'p95', 'p99']}
                values={[
                  String(Math.round(latencyPercentiles[50])),
                  String(Math.round(latencyPercentiles[95])),
                  String(Math.round(latencyPercentiles[99])),
                ]}
              />
            </TableCell>
            <TableCell className="sticky bottom-0 z-10 border-t border-b-0 bg-muted/95 text-right font-mono text-[11px]">
              <PercentileLines
                labels={['p50', 'p95', 'p99']}
                values={[
                  formatTps(tpsPercentiles[50]),
                  formatTps(tpsPercentiles[95]),
                  formatTps(tpsPercentiles[99]),
                ]}
              />
            </TableCell>
            <TableCell className="sticky bottom-0 z-10 border-t border-b-0 bg-muted/95" />
          </TableRow>
        </TableFooter>
      </Table>

      <div className="flex items-center justify-center gap-3 border-t bg-muted px-4 py-3 text-xs text-muted-foreground">
        <span className="tabular-nums">{rows.length.toLocaleString()} loaded</span>
        <RowsPerPageControl pageSize={pageSize} onPageSizeChange={onPageSizeChange} />
        {hasMore ? (
          <Button variant="outline" size="sm" onClick={onLoadMore} disabled={loadingMore}>
            {loadingMore && <Loader2 className="animate-spin" />}
            Load more
          </Button>
        ) : (
          <span>End of results</span>
        )}
      </div>
    </div>
  );
}

const PAGE_SIZE_OPTIONS: Array<100 | 250 | 500 | 'max'> = [100, 250, 500, 'max'];

function RowsPerPageControl({
  pageSize,
  onPageSizeChange,
}: {
  pageSize: 100 | 250 | 500 | 'max';
  onPageSizeChange: (size: 100 | 250 | 500 | 'max') => void;
}) {
  function pageSizeLabel(size: 100 | 250 | 500 | 'max'): string {
    return size === 'max' ? 'max (all)' : `${size} rows/page`;
  }

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="tabular-nums">
          {pageSizeLabel(pageSize)}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="center">
        <DropdownMenuRadioGroup
          value={String(pageSize)}
          onValueChange={(value) => onPageSizeChange(value === 'max' ? 'max' : (Number(value) as 100 | 250 | 500))}
        >
          {PAGE_SIZE_OPTIONS.map((size) => (
            <DropdownMenuRadioItem key={size} value={String(size)}>
              {pageSizeLabel(size)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function fmtTime(iso: string): string {
  const d = parseApiTimestamp(iso);
  return d.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatTokenCount(tokens: number): string {
  return tokens.toLocaleString();
}

function tokenValue(tokens: number | null | undefined): number {
  return typeof tokens === 'number' && Number.isFinite(tokens) ? tokens : 0;
}

function outputTokenCount(row: CallRow): number {
  return row.completion_tokens + row.reasoning_tokens;
}

function totalTokenCount(row: CallRow): number {
  return row.prompt_tokens + outputTokenCount(row);
}

function tokensPerSecond(row: CallRow): number | null {
  const outputTokens = outputTokenCount(row);
  const generationMs =
    row.ttft_ms > 0 && row.latency_ms > row.ttft_ms
      ? row.latency_ms - row.ttft_ms
      : row.latency_ms;

  if (generationMs <= 0 || outputTokens <= 0) return null;
  return outputTokens / (generationMs / 1000);
}

function formatTps(tps: number | null | undefined): string {
  if (!isNumber(tps)) return '—';
  return tps >= 10 ? tps.toFixed(0) : tps.toFixed(1);
}

function isNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function percentileSummary(values: number[]): Record<50 | 95 | 99, number> {
  const sorted = [...values].sort((a, b) => a - b);
  return {
    50: percentile(sorted, 50),
    95: percentile(sorted, 95),
    99: percentile(sorted, 99),
  };
}

function percentile(sortedValues: number[], p: number): number {
  if (sortedValues.length === 0) return 0;
  const index = Math.min(sortedValues.length - 1, Math.ceil((p / 100) * sortedValues.length) - 1);
  return sortedValues[index];
}

function PercentileLines({ labels, values }: { labels: string[]; values: string[] }) {
  return (
    <div className="ml-auto grid w-max grid-cols-[auto_auto] gap-x-2 gap-y-0.5">
      {labels.map((label, index) => (
        <Fragment key={label}>
          <div className="text-left">{label}</div>
          <div className="text-right">{values[index]}</div>
        </Fragment>
      ))}
    </div>
  );
}

function CachedTokens({ read, creation }: { read: number; creation: number }) {
  const total = read + creation;
  if (total === 0) return <span>—</span>;

  return (
    <div className="space-y-0.5">
      <div>{formatTokenCount(total)}</div>
      {creation > 0 && (
        <div className="text-[10px] text-muted-foreground/80">
          read {formatTokenCount(read)} + create {formatTokenCount(creation)}
        </div>
      )}
    </div>
  );
}

function TagPills({ tags }: { tags: string[] }) {
  // Hide env:* (already known per-session); surface feature/prompt/customer/experiment.
  const visible = tags.filter((t) => !t.startsWith('env:'));
  if (visible.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {visible.map((t) => (
        <Badge key={t} variant="secondary" className="font-mono text-[10px]">
          {t}
        </Badge>
      ))}
    </div>
  );
}

function statusBadge(status: string, finish: string) {
  const base = 'font-mono text-[10px] uppercase tracking-wider';
  if (status === 'failure') return <Badge className={cn(base, 'bg-red-700 text-red-50 hover:bg-red-700')}>failure</Badge>;
  if (finish === 'length')
    return <Badge className={cn(base, 'bg-amber-600 text-amber-50 hover:bg-amber-600')}>truncated</Badge>;
  return <Badge className={cn(base, 'bg-emerald-700 text-emerald-50 hover:bg-emerald-700')}>{status}</Badge>;
}
