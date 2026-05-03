import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import JsonView from "@uiw/react-json-view";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Role = "system" | "user" | "assistant" | "tool" | string;

type ContentBlock =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string } | string }
  | { type: "image"; source?: { data: string; media_type?: string } }
  | { type: string; [k: string]: unknown };

export type Message = {
  role: Role;
  content: string | ContentBlock[] | Record<string, unknown> | null;
  name?: string;
  tool_call_id?: string;
  tool_calls?: unknown;
};

const roleStyles: Record<string, string> = {
  system: "bg-zinc-700 text-zinc-100 hover:bg-zinc-700",
  user: "bg-sky-700 text-sky-50 hover:bg-sky-700",
  assistant: "bg-emerald-700 text-emerald-50 hover:bg-emerald-700",
  tool: "bg-violet-700 text-violet-50 hover:bg-violet-700",
};

const jsonViewTheme: React.CSSProperties & Record<string, string | number> = {
  backgroundColor: "transparent",
  fontSize: 11,
  "--w-rjv-font-family": "var(--font-mono)",
  "--w-rjv-background-color": "transparent",
  "--w-rjv-line-color": "var(--border)",
  "--w-rjv-arrow-color": "var(--muted-foreground)",
  "--w-rjv-info-color": "var(--muted-foreground)",
  "--w-rjv-color": "var(--foreground)",
  "--w-rjv-key-string": "var(--foreground)",
  "--w-rjv-curlybraces-color": "var(--muted-foreground)",
  "--w-rjv-colon-color": "var(--muted-foreground)",
  "--w-rjv-brackets-color": "var(--muted-foreground)",
  "--w-rjv-type-string-color": "var(--foreground)",
  "--w-rjv-type-int-color": "var(--muted-foreground)",
  "--w-rjv-type-float-color": "var(--muted-foreground)",
  "--w-rjv-type-bigint-color": "var(--muted-foreground)",
  "--w-rjv-type-boolean-color": "var(--muted-foreground)",
  "--w-rjv-type-date-color": "var(--muted-foreground)",
  "--w-rjv-type-url-color": "var(--foreground)",
  "--w-rjv-type-null-color": "var(--muted-foreground)",
  "--w-rjv-type-nan-color": "var(--muted-foreground)",
  "--w-rjv-type-undefined-color": "var(--muted-foreground)",
};

export default function MessageCard({
  message,
  defaultOpen,
}: {
  message: Message;
  defaultOpen?: boolean;
}) {
  const initial = defaultOpen ?? message.role !== "system";
  const [open, setOpen] = useState(initial);
  const cls = roleStyles[message.role] ?? "bg-muted text-foreground";
  const preview = previewOf(message.content);

  return (
    <Card size="sm" className="gap-0 gap-3!">
      <CardHeader className="p-0">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex w-full items-center gap-3 text-left"
        >
          {open ? (
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
          )}
          <Badge
            className={cn(
              "font-mono text-[10px] uppercase tracking-wider",
              cls,
            )}
          >
            {message.role}
          </Badge>
          {message.name && (
            <span className="font-mono text-[11px] text-muted-foreground">
              {message.name}
            </span>
          )}
          {!open && preview && (
            <span className="truncate text-xs text-muted-foreground">
              {preview}
            </span>
          )}
          {message.tool_call_id && (
            <span className="ml-auto font-mono text-[11px] text-muted-foreground">
              {message.tool_call_id}
            </span>
          )}
        </button>
      </CardHeader>
      {open && (
        <CardContent className="space-y-3 border-t px-3 pt-3">
          <ContentRenderer content={message.content} />
          {message.tool_calls != null && (
            <div>
              <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Tool calls
              </h4>
              <JsonBlock value={message.tool_calls} />
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

function ContentRenderer({ content }: { content: Message["content"] }) {
  if (content == null || content === "") {
    return <span className="text-xs italic text-muted-foreground">empty</span>;
  }

  if (typeof content === "object" && !Array.isArray(content)) {
    return <JsonBlock value={content} />;
  }

  if (Array.isArray(content)) {
    return (
      <div className="space-y-3">
        {content.map((b, i) => (
          <ContentBlockRenderer key={i} block={b} />
        ))}
      </div>
    );
  }

  return <SmartText text={content} />;
}

function ContentBlockRenderer({ block }: { block: ContentBlock }) {
  if ("type" in block && block.type === "text" && "text" in block) {
    return <SmartText text={(block as { text: string }).text} />;
  }
  if ("type" in block && block.type === "image_url") {
    const url =
      typeof (block as { image_url: { url: string } | string }).image_url ===
      "string"
        ? (block as { image_url: string }).image_url
        : (block as { image_url: { url: string } }).image_url.url;
    return (
      <div className="space-y-1">
        <Badge variant="outline" className="text-[10px]">
          image
        </Badge>
        {url.startsWith("data:") ? (
          <img src={url} alt="" className="max-h-64 border" />
        ) : (
          <a
            className="break-all text-xs text-sky-400 underline"
            href={url}
            target="_blank"
            rel="noreferrer"
          >
            {url}
          </a>
        )}
      </div>
    );
  }
  return <JsonBlock value={block} />;
}

function SmartText({ text }: { text: string }) {
  const parsed = tryJson(text);
  if (parsed !== undefined) {
    return <JsonBlock value={parsed} />;
  }
  return (
    <pre className="whitespace-pre-wrap break-words font-sans text-[13px] leading-relaxed text-foreground">
      {text}
    </pre>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap break-words bg-muted p-2 font-mono text-[11px] leading-relaxed">
      {children}
    </pre>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  if (typeof value !== "object" || value === null) {
    return <CodeBlock>{stringifyJson(value)}</CodeBlock>;
  }

  return (
    <div className="overflow-x-auto bg-muted p-2 text-xs">
      <JsonView
        value={value}
        collapsed={2}
        displayDataTypes={false}
        displayObjectSize={false}
        enableClipboard={false}
        style={jsonViewTheme}
      />
    </div>
  );
}

function tryJson(s: string): unknown | undefined {
  const t = s.trim();
  if (!t) return undefined;
  if (!(t.startsWith("{") || t.startsWith("["))) return undefined;
  try {
    return JSON.parse(t);
  } catch {
    return undefined;
  }
}

function stringifyJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function previewOf(content: Message["content"]): string {
  if (content == null) return "";
  if (typeof content === "string")
    return content.replace(/\s+/g, " ").slice(0, 140);
  if (Array.isArray(content)) {
    const text = content.find(
      (b) => "type" in b && b.type === "text" && "text" in b,
    );
    if (text && "text" in text)
      return (text as { text: string }).text.replace(/\s+/g, " ").slice(0, 140);
    return `${content.length} block${content.length === 1 ? "" : "s"}`;
  }
  return "";
}
