import { useQuery } from '@tanstack/react-query';
import { api } from '@/api';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';

export default function CallDrawer({
  requestId,
  onClose,
}: {
  requestId: string;
  onClose: () => void;
}) {
  const { data, isPending, error } = useQuery({
    queryKey: ['call', requestId],
    queryFn: () => api.getCall(requestId),
  });

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-[min(900px,95vw)] overflow-y-auto sm:max-w-none">
        <SheetHeader>
          <SheetTitle className="text-base">{data?.model ?? 'Call'}</SheetTitle>
          <SheetDescription className="font-mono text-xs">{requestId}</SheetDescription>
        </SheetHeader>

        {isPending && <div className="mt-4 text-sm text-muted-foreground">Loading…</div>}
        {error && (
          <div className="mt-4 text-sm text-destructive">Error: {(error as Error).message}</div>
        )}

        {data && (
          <div className="mt-4 space-y-5">
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 md:grid-cols-4">
              <Stat label="Time" value={new Date(data.timestamp).toLocaleString()} />
              <Stat label="Status" value={data.status} />
              <Stat label="Finish" value={data.finish_reason || '—'} />
              <Stat label="Env" value={data.team || '—'} />
              <Stat label="Cost" value={`$${data.spend_usd.toFixed(6)}`} />
              <Stat label="Tokens" value={`${data.prompt_tokens} → ${data.completion_tokens}`} />
              <Stat label="Latency" value={`${data.latency_ms} ms`} />
              <Stat label="TTFT" value={data.ttft_ms ? `${data.ttft_ms} ms` : '—'} />
            </div>

            {data.tags?.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {data.tags.map((t) => (
                  <Badge key={t} variant="secondary" className="font-mono text-[11px]">
                    {t}
                  </Badge>
                ))}
              </div>
            )}

            {data.error_message && (
              <pre className="whitespace-pre-wrap rounded-md border border-destructive/40 bg-destructive/10 p-3 text-[11px] text-destructive">
                {data.error_message}
              </pre>
            )}

            <Separator />

            <Section title="Input">
              <Pre>{prettyJson(data.input_messages)}</Pre>
            </Section>

            {data.output_text && (
              <Section title="Output">
                <Pre prose>{data.output_text}</Pre>
              </Section>
            )}

            {data.reasoning_content && (
              <Section title="Reasoning">
                <Pre prose>{data.reasoning_content}</Pre>
              </Section>
            )}

            {data.tool_calls && (
              <Section title="Tool calls">
                <Pre>{prettyJson(data.tool_calls)}</Pre>
              </Section>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  );
}

function Pre({ children, prose = false }: { children: string; prose?: boolean }) {
  return (
    <pre
      className={
        prose
          ? 'whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-[12px]'
          : 'whitespace-pre-wrap break-words rounded-md bg-muted p-3 font-mono text-[11px]'
      }
    >
      {children}
    </pre>
  );
}

function prettyJson(s: string): string {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}
