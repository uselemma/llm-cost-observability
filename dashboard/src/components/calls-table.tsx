import { Loader2 } from 'lucide-react';
import type { CallRow } from '@/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { parseApiTimestamp } from '@/lib/datetime';
import {
  Table,
  TableBody,
  TableCell,
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
}: {
  rows: CallRow[];
  onSelect: (id: string) => void;
  loading: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}) {
  if (loading) return <div className="p-4 text-sm text-muted-foreground">Loading…</div>;
  if (rows.length === 0)
    return <div className="p-4 text-sm text-muted-foreground">No calls in this window.</div>;

  return (
    <div className="flex h-full flex-col">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="sticky top-0 z-20 w-[160px] bg-background">Time</TableHead>
            <TableHead className="sticky top-0 z-20 w-[260px] bg-background">Tags</TableHead>
            <TableHead className="sticky top-0 z-20 w-[240px] bg-background">Model</TableHead>
            <TableHead className="sticky top-0 z-20 w-[100px] bg-background">Status</TableHead>
            <TableHead className="sticky top-0 z-20 w-[100px] bg-background text-right">Cost</TableHead>
            <TableHead className="sticky top-0 z-20 w-[140px] bg-background text-right">Tokens</TableHead>
            <TableHead className="sticky top-0 z-20 w-[80px] bg-background text-right">ms</TableHead>
            <TableHead className="sticky top-0 z-20 bg-background">Output preview</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
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
                {r.prompt_tokens}+{r.completion_tokens}
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {r.latency_ms}
              </TableCell>
              <TableCell className="max-w-[1px] truncate">{r.output_preview || '—'}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="flex items-center justify-center gap-3 border-t bg-background/80 px-4 py-3 text-xs text-muted-foreground">
        <span className="tabular-nums">{rows.length} rows</span>
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

function TagPills({ tags }: { tags: string[] }) {
  // Hide env:* (already known per-session); surface feature/prompt/customer/experiment.
  const visible = tags.filter((t) => !t.startsWith('env:'));
  if (visible.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {visible.map((t) => (
        <Badge key={t} variant="outline" className="font-mono text-[10px]">
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
