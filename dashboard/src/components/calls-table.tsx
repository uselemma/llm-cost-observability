import type { CallRow } from '@/api';
import { Badge } from '@/components/ui/badge';
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
}: {
  rows: CallRow[];
  onSelect: (id: string) => void;
  loading: boolean;
}) {
  if (loading) return <div className="p-4 text-sm text-muted-foreground">Loading…</div>;
  if (rows.length === 0)
    return <div className="p-4 text-sm text-muted-foreground">No calls in this window.</div>;

  return (
    <div className="h-full overflow-auto">
      <Table>
        <TableHeader className="sticky top-0 bg-background">
          <TableRow>
            <TableHead className="w-[160px]">Time</TableHead>
            <TableHead className="w-[260px]">Model</TableHead>
            <TableHead className="w-[100px]">Status</TableHead>
            <TableHead className="w-[100px] text-right">Cost</TableHead>
            <TableHead className="w-[140px] text-right">Tokens</TableHead>
            <TableHead className="w-[80px] text-right">ms</TableHead>
            <TableHead>Output preview</TableHead>
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
    </div>
  );
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function statusBadge(status: string, finish: string) {
  if (status === 'failure') return <Badge variant="destructive">failure</Badge>;
  if (finish === 'length')
    return <Badge variant="outline" className="border-amber-600 text-amber-600">truncated</Badge>;
  return <Badge variant="secondary">{status}</Badge>;
}
