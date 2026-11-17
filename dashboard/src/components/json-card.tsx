import { useState } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";
import JsonView from "@uiw/react-json-view";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

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

function parseJson(text: string): object | undefined {
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null ? parsed : undefined;
  } catch {
    return undefined;
  }
}

/** Collapsible panel showing a JSON string as a tree (plain text if it is not a JSON object). */
export default function JsonCard({
  title,
  json,
}: {
  title: string;
  json: string;
}) {
  const [open, setOpen] = useState(false);
  const value = parseJson(json);

  return (
    <Card size="sm" className="gap-3!">
      <CardHeader className="p-0">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex w-full items-center gap-3 text-left"
        >
          {open ? (
            <CaretDown className="size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <CaretRight className="size-3.5 shrink-0 text-muted-foreground" />
          )}
          <Badge className="bg-muted font-mono text-[10px] uppercase tracking-wider text-foreground hover:bg-muted">
            {title}
          </Badge>
          {!open && json && (
            <span className="truncate text-xs text-muted-foreground">
              {json.slice(0, 140)}
            </span>
          )}
        </button>
      </CardHeader>
      {open && (
        <CardContent className="border-t px-3 pt-3">
          {!json ? (
            <span className="text-xs italic text-muted-foreground">empty</span>
          ) : value ? (
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
          ) : (
            <pre className="overflow-x-auto whitespace-pre-wrap break-words bg-muted p-2 font-mono text-[11px] leading-relaxed">
              {json}
            </pre>
          )}
        </CardContent>
      )}
    </Card>
  );
}
