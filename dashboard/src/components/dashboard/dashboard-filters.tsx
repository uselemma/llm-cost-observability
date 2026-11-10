import { useState } from 'react';
import { CaretUpDown, Check, Prohibit, X } from '@phosphor-icons/react';
import { DIMENSIONS, type Bucket, type Dimension, type DimensionValues } from '@/api';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import type { RangeState } from '@/lib/range';
import DateRangeFilter from './date-range-filter';
import {
  bucketCount,
  compact,
  DIMENSION_LABELS,
  GRANULARITIES,
  MAX_BUCKETS,
} from '@/lib/stats';

export type Selected = Partial<Record<Dimension, string[]>>;
export type FilterMode = 'include' | 'exclude';
export type FilterState = { include: Selected; exclude: Selected };
export type Granularity = 'auto' | Bucket;

// Edits are staged in a local draft and only applied on Save, so toggling several
// values triggers one refresh instead of one per click.
function DimensionFilter({
  dim,
  options,
  included,
  excluded,
  onApply,
}: {
  dim: Dimension;
  options: { value: string; calls: number }[];
  included: string[];
  excluded: string[];
  onApply: (include: string[], exclude: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draftInc, setDraftInc] = useState(included);
  const [draftExc, setDraftExc] = useState(excluded);

  function handleOpenChange(next: boolean) {
    // Every open starts from the applied filters; closing discards unsaved edits.
    if (next) {
      setDraftInc(included);
      setDraftExc(excluded);
    }
    setOpen(next);
  }

  // A value is in at most one of include/exclude; picking the active mode again clears it.
  function toggle(value: string, mode: FilterMode) {
    const [cur, setCur, other, setOther] =
      mode === 'include'
        ? [draftInc, setDraftInc, draftExc, setDraftExc]
        : [draftExc, setDraftExc, draftInc, setDraftInc];
    setCur(cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value]);
    setOther(other.filter((v) => v !== value));
  }

  const sameSet = (x: string[], y: string[]) => x.length === y.length && x.every((v) => y.includes(v));
  const dirty = !sameSet(draftInc, included) || !sameSet(draftExc, excluded);

  // Selected values stay listed even if they dropped out of the current window.
  const values = [
    ...options,
    ...[...draftInc, ...draftExc, ...included, ...excluded]
      .filter((v, i, all) => all.indexOf(v) === i && !options.some((o) => o.value === v))
      .map((value) => ({ value, calls: 0 })),
  ];

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="font-normal">
          {DIMENSION_LABELS[dim]}
          {included.length > 0 && (
            <Badge variant="secondary" className="h-4 px-1.5 py-0 text-micro">
              {included.length}
            </Badge>
          )}
          {excluded.length > 0 && (
            <Badge variant="destructive" className="h-4 px-1.5 py-0 text-micro">
              −{excluded.length}
            </Badge>
          )}
          <CaretUpDown className="size-3.5 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-96 p-0" align="start">
        <Command>
          <CommandInput placeholder={`Search ${DIMENSION_LABELS[dim].toLowerCase()}…`} />
          <CommandList>
            <CommandEmpty>No values.</CommandEmpty>
            <CommandGroup heading="Click to include · ban icon to exclude">
              {values.map((o) => {
                const isIn = draftInc.includes(o.value);
                const isEx = draftExc.includes(o.value);
                return (
                  <CommandItem key={o.value} value={o.value} onSelect={() => toggle(o.value, 'include')}>
                    {/* Fixed columns: check | name | count | exclude. CommandItem appends its own
                        ml-auto check icon, so rows use one grid child instead of ml-auto spacers. */}
                    <div className="grid min-w-0 flex-1 grid-cols-[1rem_minmax(0,1fr)_3.5rem_1.5rem] items-center gap-2">
                      <Check className={cn('size-3.5', isIn ? 'opacity-100' : 'opacity-0')} />
                      <span
                        className={cn(
                          'truncate font-mono text-[11px]',
                          isEx && 'text-muted-foreground line-through',
                        )}
                        title={o.value}
                      >
                        {o.value}
                      </span>
                      <span className="text-right text-xs tabular-nums text-muted-foreground">
                        {compact(o.calls)}
                      </span>
                      <button
                        type="button"
                        aria-label={`Exclude ${o.value}`}
                        aria-pressed={isEx}
                        title={isEx ? 'Remove exclusion' : 'Exclude'}
                        className={cn(
                          'flex size-6 items-center justify-center rounded hover:bg-accent',
                          isEx ? 'text-destructive' : 'text-muted-foreground/60',
                        )}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggle(o.value, 'exclude');
                        }}
                      >
                        <Prohibit className="size-3.5" />
                      </button>
                    </div>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
        <div className="flex items-center justify-between gap-2 border-t px-2 py-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={draftInc.length === 0 && draftExc.length === 0}
            onClick={() => {
              setDraftInc([]);
              setDraftExc([]);
            }}
          >
            Clear
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={!dirty}
              onClick={() => {
                onApply(draftInc, draftExc);
                setOpen(false);
              }}
            >
              Save
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function GranularitySelect({
  value,
  onChange,
  spanMs,
  autoBucket,
}: {
  value: Granularity;
  onChange: (g: Granularity) => void;
  spanMs: number;
  autoBucket: Bucket;
}) {
  const autoLabel = GRANULARITIES.find((g) => g.value === autoBucket)?.label;
  return (
    <Select value={value} onValueChange={(v) => onChange(v as Granularity)}>
      <SelectTrigger size="sm" aria-label="Chart granularity">
        <span className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Granularity:</span>
          <SelectValue />
        </span>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="auto">Auto ({autoLabel})</SelectItem>
        {GRANULARITIES.map((g) => {
          const tooMany = bucketCount(spanMs, g.value) > MAX_BUCKETS;
          // A bucket wider than the range yields a single point.
          const tooWide = g.ms > spanMs;
          return (
            <SelectItem key={g.value} value={g.value} disabled={tooMany || tooWide}>
              {g.label}
              {tooMany ? ' (too many points)' : ''}
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}

export default function DashboardFilters({
  range,
  onRange,
  granularity,
  onGranularity,
  autoBucket,
  spanMs,
  state,
  dimensions,
  onToggle,
  onApply,
  onClear,
}: {
  range: RangeState;
  onRange: (r: RangeState) => void;
  granularity: Granularity;
  onGranularity: (g: Granularity) => void;
  autoBucket: Bucket;
  spanMs: number;
  state: FilterState;
  dimensions?: DimensionValues;
  onToggle: (dim: Dimension, value: string, mode: FilterMode) => void;
  onApply: (dim: Dimension, include: string[], exclude: string[]) => void;
  onClear: () => void;
}) {
  const chips = DIMENSIONS.flatMap((d) => [
    ...(state.include[d] ?? []).map((v) => [d, v, 'include'] as const),
    ...(state.exclude[d] ?? []).map((v) => [d, v, 'exclude'] as const),
  ]);
  return (
    <div className="flex flex-col gap-2 rounded-lg bg-card px-4 py-3 shadow-xs ring-1 ring-foreground/10">
      <div className="flex flex-wrap items-center gap-2">
        <DateRangeFilter value={range} onApply={onRange} />
        <GranularitySelect
          value={granularity}
          onChange={onGranularity}
          spanMs={spanMs}
          autoBucket={autoBucket}
        />
        {DIMENSIONS.map((d) => (
          <DimensionFilter
            key={d}
            dim={d}
            options={dimensions?.[d] ?? []}
            included={state.include[d] ?? []}
            excluded={state.exclude[d] ?? []}
            onApply={(inc, exc) => onApply(d, inc, exc)}
          />
        ))}
      </div>
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {chips.map(([d, v, mode]) => (
            <Badge
              key={`${mode}:${d}:${v}`}
              variant={mode === 'exclude' ? 'destructive' : 'secondary'}
              className="cursor-pointer font-mono text-[10px]"
              onClick={() => onToggle(d, v, mode)}
            >
              {DIMENSION_LABELS[d]} {mode === 'exclude' ? '≠' : ':'} {v}
              <X className="ml-1 size-3 opacity-60" />
            </Badge>
          ))}
          <Button variant="ghost" size="sm" onClick={onClear}>
            Clear all
          </Button>
        </div>
      )}
    </div>
  );
}
