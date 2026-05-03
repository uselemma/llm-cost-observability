import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Check, ChevronsUpDown, X } from 'lucide-react';
import { api } from '@/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

type Props = {
  value: string[];
  onChange: (next: string[]) => void;
  fallbackTags?: string[];
};

export default function TagSelect({ value, onChange, fallbackTags = [] }: Props) {
  const [open, setOpen] = useState(false);
  const tags = useQuery({ queryKey: ['tags'], queryFn: api.listTags });
  const allTags = useMemo(() => {
    const merged = [...(tags.data?.tags ?? []), ...fallbackTags];
    return Array.from(new Set(merged)).sort((a, b) => a.localeCompare(b));
  }, [fallbackTags, tags.data?.tags]);

  // Group available tags by key prefix.
  const grouped = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const t of allTags) {
      const key = t.split(':', 1)[0];
      (out[key] ??= []).push(t);
    }
    return out;
  }, [allTags]);

  const selected = new Set(value);

  function toggle(tag: string) {
    const next = new Set(selected);
    if (next.has(tag)) next.delete(tag);
    else next.add(tag);
    onChange([...next]);
  }

  const summary =
    value.length === 0
      ? 'Any'
      : value.length === 1
        ? value[0]
        : `${value.length} selected`;

  return (
    <div className="flex flex-col gap-1.5">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="w-72 justify-between font-normal"
          >
            <span className="truncate text-left">{summary}</span>
            <ChevronsUpDown className="ml-2 size-3.5 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="start">
          <Command>
            <CommandInput placeholder="Search tags…" />
            <CommandList>
              <CommandEmpty>
                {tags.isError ? 'Failed to load tags.' : tags.isLoading ? 'Loading tags…' : 'No tags.'}
              </CommandEmpty>
              {Object.entries(grouped).map(([key, vals]) => (
                <CommandGroup key={key} heading={key}>
                  {vals.map((t) => (
                    <CommandItem key={t} value={t} onSelect={() => toggle(t)}>
                      <Check
                        className={cn(
                          'mr-2 size-3.5',
                          selected.has(t) ? 'opacity-100' : 'opacity-0',
                        )}
                      />
                      <span className="truncate font-mono text-[11px]">{t}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              ))}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {value.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {value.map((t) => (
            <Badge
              key={t}
              variant="secondary"
              className="cursor-pointer font-mono text-[10px]"
              onClick={() => toggle(t)}
            >
              {t}
              <X className="ml-1 size-3 opacity-60" />
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
