import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import JsonCard from "@/components/json-card";
import { parseApiTimestamp } from "@/lib/datetime";

export default function CallDrawer({
  requestId,
  timestamp,
  onClose,
}: {
  requestId: string;
  timestamp: string;
  onClose: () => void;
}) {
  const { data, isPending, error } = useQuery({
    queryKey: ["call", requestId, timestamp],
    queryFn: () => api.getCall(requestId, timestamp),
  });

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 overflow-y-auto data-[side=right]:sm:max-w-3xl">
        <SheetHeader className="px-6 pt-6 pb-4">
          <SheetTitle className="text-base">
            {data ? parseApiTimestamp(data.timestamp).toLocaleString() : "Call"}
          </SheetTitle>
          <SheetDescription className="font-mono text-xs">
            {requestId}
          </SheetDescription>
        </SheetHeader>

        {isPending && (
          <div className="px-6 pb-6 text-sm text-muted-foreground">
            Loading…
          </div>
        )}
        {error && (
          <div className="px-6 pb-6 text-sm text-destructive">
            Error: {(error as Error).message}
          </div>
        )}

        {data && (
          <div className="space-y-5 px-6 pb-6">
            {(data.model || data.tags?.length > 0) && (
              <div className="flex flex-wrap gap-1.5">
                <Badge
                  variant={data.is_complete ? "outline" : "destructive"}
                  className="font-mono text-[11px]"
                >
                  {data.reconciliation_status.replace("_", " ")}
                </Badge>
                {data.model && (
                  <Badge variant="secondary" className="font-mono text-[11px]">
                    {data.model}
                  </Badge>
                )}
                {data.tags?.map((t) => (
                  <Badge
                    key={t}
                    variant="secondary"
                    className="font-mono text-[11px]"
                  >
                    {t}
                  </Badge>
                ))}
              </div>
            )}

            <div className="grid grid-cols-2 gap-x-6 gap-y-2 md:grid-cols-4">
              <Stat label="Provider" value={data.provider || "—"} />
              <Stat label="Status" value={data.status} />
              <Stat label="Finish" value={data.finish_reason || "—"} />
              <Stat label="Env" value={data.team || "—"} />
              <Stat
                label="Cost"
                value={
                  data.cost_included
                    ? `$${data.spend_usd.toFixed(6)}`
                    : "excluded (unreconciled)"
                }
              />
              <Stat label="Market cost" value={`$${data.market_cost_usd.toFixed(6)}`} />
              <Stat
                label="Tokens"
                value={`${formatTokenCount(data.prompt_tokens)} → ${formatTokenCount(outputTokenCount(data))}`}
              />
              <Stat
                label="Cache Read"
                value={formatOptionalTokens(data.cache_read_tokens ?? 0)}
              />
              <Stat
                label="Cache Create"
                value={formatOptionalTokens(data.cache_creation_tokens ?? 0)}
              />
              <Stat label="Latency" value={`${data.latency_ms} ms`} />
              <Stat label="TPS" value={formatTps(tokensPerSecond(data))} />
              <Stat
                label="TTFT"
                value={data.ttft_ms ? `${data.ttft_ms} ms` : "—"}
              />
              <Stat
                label="Reconcile"
                value={
                  data.reconciliation_status === "reconciled"
                    ? `${data.reconciliation_ms} ms`
                    : data.reconciliation_status.replace("_", " ")
                }
              />
              <Stat label="Region" value={data.region || "—"} />
              <Stat label="Credential" value={data.credential_type || "—"} />
              <Stat label="Generation" value={data.generation_id || "—"} />
              <Stat
                label="ZDR"
                value={data.zdr_requested === "" ? "—" : data.zdr_requested}
              />
            </div>

            <JsonCard title="Metadata" json={data.metadata} />

            {data.error_message && (
              <pre className="whitespace-pre-wrap border border-destructive/40 bg-destructive/10 p-3 text-[11px] text-destructive">
                {data.error_message}
              </pre>
            )}

            {data.attempts.length > 0 && (
              <Section title="Routing & provider attempts">
                <div className="space-y-2">
                  {data.attempts.map((attempt) => (
                    <div
                      key={attempt.span_id}
                      className="grid grid-cols-2 gap-x-4 gap-y-1 border bg-muted/50 p-3 text-xs md:grid-cols-4"
                    >
                      <Stat label="Span" value={attempt.name} />
                      <Stat label="Status" value={attempt.status} />
                      <Stat label="Provider" value={attempt.provider || "—"} />
                      <Stat label="Model" value={attempt.model || "—"} />
                      <Stat label="Latency" value={`${attempt.latency_ms} ms`} />
                      <Stat
                        label="Attempt"
                        value={
                          attempt.attempt_number
                            ? String(attempt.attempt_number)
                            : attempt.model_attempt_index
                              ? String(attempt.model_attempt_index)
                              : "—"
                        }
                      />
                      <Stat label="Region" value={attempt.region || "—"} />
                      <Stat label="Credential" value={attempt.credential_type || "—"} />
                      {attempt.error_message && (
                        <div className="col-span-full text-destructive">
                          {attempt.error_message}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
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
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className="text-sm">{value}</span>
    </div>
  );
}

function formatTokenCount(tokens: number): string {
  return tokens.toLocaleString();
}

function formatOptionalTokens(tokens: number): string {
  return tokens > 0 ? formatTokenCount(tokens) : "—";
}

function outputTokenCount({
  completion_tokens,
  reasoning_tokens,
}: {
  completion_tokens: number;
  reasoning_tokens: number;
}): number {
  return completion_tokens + reasoning_tokens;
}

function tokensPerSecond({
  completion_tokens,
  reasoning_tokens,
  latency_ms,
  ttft_ms,
}: {
  completion_tokens: number;
  reasoning_tokens: number;
  latency_ms: number;
  ttft_ms: number;
}): number | null {
  const outputTokens = outputTokenCount({ completion_tokens, reasoning_tokens });
  const generationMs =
    ttft_ms > 0 && latency_ms > ttft_ms ? latency_ms - ttft_ms : latency_ms;

  if (generationMs <= 0 || outputTokens <= 0) return null;
  return outputTokens / (generationMs / 1000);
}

function formatTps(tps: number | null): string {
  if (tps == null || !Number.isFinite(tps)) return "—";
  return `${tps >= 10 ? tps.toFixed(0) : tps.toFixed(1)} tok/s`;
}
