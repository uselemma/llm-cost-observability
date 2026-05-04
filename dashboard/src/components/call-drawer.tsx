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
import MessageCard, { type Message } from '@/components/message-card';
import { parseApiTimestamp } from '@/lib/datetime';

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

  const inputMessages = data ? parseMessages(data.input_messages) : [];

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 overflow-y-auto data-[side=right]:sm:max-w-3xl">
        <SheetHeader className="px-6 pt-6 pb-4">
          <SheetTitle className="text-base">
            {data ? parseApiTimestamp(data.timestamp).toLocaleString() : 'Call'}
          </SheetTitle>
          <SheetDescription className="font-mono text-xs">{requestId}</SheetDescription>
        </SheetHeader>

        {isPending && <div className="px-6 pb-6 text-sm text-muted-foreground">Loading…</div>}
        {error && (
          <div className="px-6 pb-6 text-sm text-destructive">Error: {(error as Error).message}</div>
        )}

        {data && (
          <div className="space-y-5 px-6 pb-6">
            {(data.model || data.tags?.length > 0) && (
              <div className="flex flex-wrap gap-1.5">
                {data.model && (
                  <Badge variant="secondary" className="font-mono text-[11px]">
                    {data.model}
                  </Badge>
                )}
                {data.tags?.map((t) => (
                  <Badge key={t} variant="secondary" className="font-mono text-[11px]">
                    {t}
                  </Badge>
                ))}
              </div>
            )}

            <div className="grid grid-cols-2 gap-x-6 gap-y-2 md:grid-cols-4">
              <Stat label="Provider" value={data.provider || '—'} />
              <Stat label="Status" value={data.status} />
              <Stat label="Finish" value={data.finish_reason || '—'} />
              <Stat label="Env" value={data.team || '—'} />
              <Stat label="Cost" value={`$${data.spend_usd.toFixed(6)}`} />
              <Stat label="Tokens" value={`${data.prompt_tokens} → ${data.completion_tokens}`} />
              <Stat label="Latency" value={`${data.latency_ms} ms`} />
              <Stat label="TTFT" value={data.ttft_ms ? `${data.ttft_ms} ms` : '—'} />
            </div>

            <Section title="Metadata">
              <MessageCard
                message={{
                  role: 'metadata',
                  content: data.metadata || null,
                }}
                defaultOpen={false}
              />
            </Section>

            {data.error_message && (
              <pre className="whitespace-pre-wrap border border-destructive/40 bg-destructive/10 p-3 text-[11px] text-destructive">
                {data.error_message}
              </pre>
            )}

            <Separator />

            <Section title="Input">
              {inputMessages.length === 0 ? (
                <pre className="bg-muted p-3 font-mono text-[11px]">{data.input_messages}</pre>
              ) : (
                <div className="space-y-2">
                  {inputMessages.map((m, i) => (
                    <MessageCard key={i} message={m} />
                  ))}
                </div>
              )}
            </Section>

            {(data.output_text || data.reasoning_content || data.tool_calls) && (
              <Section title="Output">
                <div className="space-y-2">
                  {data.reasoning_content && (
                    <MessageCard
                      message={{
                        role: 'reasoning',
                        content: data.reasoning_content,
                      }}
                    />
                  )}
                  <MessageCard
                    message={{
                      role: 'assistant',
                      content: data.output_text || null,
                      tool_calls: data.tool_calls ? safeJson(data.tool_calls) : undefined,
                    }}
                  />
                </div>
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

function parseMessages(raw: string): Message[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    if (Array.isArray(v)) return v as Message[];
    return [];
  } catch {
    return [];
  }
}

function safeJson(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}

