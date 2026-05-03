import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import TagSelect from '@/components/tag-select';
import DateTimeRangePicker from '@/components/datetime-range-picker';

export type Filters = {
  since?: string;
  until?: string;
  model?: string;
  status?: string;
  tag?: string[];
  q?: string;
};

const ALL = '__all__';
const CUSTOM_RANGE = '__custom__';

const RANGE_PRESETS = [
  { value: '5m', label: 'Last 5 mins', ms: 5 * 60 * 1000 },
  { value: '15m', label: 'Last 15 mins', ms: 15 * 60 * 1000 },
  { value: '1h', label: 'Last 1 hr', ms: 60 * 60 * 1000 },
  { value: '1d', label: 'Last 1 day', ms: 24 * 60 * 60 * 1000 },
  { value: '1w', label: 'Last 1 week', ms: 7 * 24 * 60 * 60 * 1000 },
] as const;

type RangePreset = (typeof RANGE_PRESETS)[number]['value'] | typeof CUSTOM_RANGE;

export default function FilterBar({
  filters,
  onChange,
  availableTags,
}: {
  filters: Filters;
  onChange: (f: Filters) => void;
  availableTags?: string[];
}) {
  const models = useQuery({ queryKey: ['models'], queryFn: api.listModels });
  const [rangePreset, setRangePreset] = useState<RangePreset>(() => inferInitialRangePreset(filters));

  function set<K extends keyof Filters>(k: K, v: Filters[K]) {
    onChange({ ...filters, [k]: v || undefined });
  }

  function applyPreset(nextPreset: RangePreset) {
    setRangePreset(nextPreset);
    if (nextPreset === CUSTOM_RANGE) return;
    const preset = RANGE_PRESETS.find((p) => p.value === nextPreset);
    if (!preset) return;
    const since = toLocalDateTime(new Date(Date.now() - preset.ms));
    onChange({ ...filters, since, until: undefined });
  }

  return (
    <div className="flex flex-wrap items-end gap-3 bg-background px-4 py-3">
      <Field label="Range" htmlFor="range">
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <Button
              id="range"
              variant="outline"
              className="w-64 justify-between bg-background font-normal dark:bg-background"
            >
              <span>{rangeLabel(rangePreset)}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
            <DropdownMenuRadioGroup value={rangePreset} onValueChange={(v) => applyPreset(v as RangePreset)}>
              {RANGE_PRESETS.map((preset) => (
                <DropdownMenuRadioItem key={preset.value} value={preset.value}>
                  {preset.label}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
            <DropdownMenuSub>
              <DropdownMenuSubTrigger inset>Custom...</DropdownMenuSubTrigger>
              <DropdownMenuSubContent className="w-[680px] p-0">
                <DateTimeRangePicker
                  inline
                  since={filters.since}
                  until={filters.until}
                  onChange={({ since, until }) => {
                    setRangePreset(CUSTOM_RANGE);
                    onChange({ ...filters, since, until });
                  }}
                />
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          </DropdownMenuContent>
        </DropdownMenu>
      </Field>
      <Field label="Model" htmlFor="model">
        <Select
          value={filters.model ?? ALL}
          onValueChange={(v) => set('model', v === ALL ? undefined : v)}
        >
          <SelectTrigger id="model" className="w-64 bg-background dark:bg-background">
            <SelectValue placeholder="All models" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All models</SelectItem>
            {(models.data?.models ?? []).map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Status" htmlFor="status">
        <Select
          value={filters.status ?? ALL}
          onValueChange={(v) => set('status', v === ALL ? undefined : v)}
        >
          <SelectTrigger id="status" className="w-32 bg-background dark:bg-background">
            <SelectValue placeholder="Any" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Any</SelectItem>
            <SelectItem value="success">Success</SelectItem>
            <SelectItem value="failure">Failure</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label="Tags" htmlFor="tags">
        <TagSelect
          value={filters.tag ?? []}
          onChange={(next) => set('tag', next.length ? next : undefined)}
          fallbackTags={availableTags}
        />
      </Field>
      <Field label="Search bodies" htmlFor="q">
        <Input
          id="q"
          placeholder="substring of input or output"
          value={filters.q ?? ''}
          onChange={(e) => set('q', e.target.value)}
          className="w-72 bg-background dark:bg-background"
        />
      </Field>
    </div>
  );
}

function toLocalDateTime(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const h = String(d.getHours()).padStart(2, '0');
  const min = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${day}T${h}:${min}`;
}

function inferInitialRangePreset(filters: Filters): RangePreset {
  if (filters.until) return CUSTOM_RANGE;
  if (!filters.since) return CUSTOM_RANGE;
  const parsedSince = new Date(filters.since);
  if (Number.isNaN(parsedSince.getTime())) return CUSTOM_RANGE;
  const delta = Date.now() - parsedSince.getTime();
  const tolerance = 90 * 1000;
  for (const preset of RANGE_PRESETS) {
    if (Math.abs(delta - preset.ms) <= tolerance) return preset.value;
  }
  return CUSTOM_RANGE;
}

function rangeLabel(rangePreset: RangePreset): string {
  if (rangePreset === CUSTOM_RANGE) return 'Custom...';
  return RANGE_PRESETS.find((p) => p.value === rangePreset)?.label ?? 'Range';
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor} className="text-xs text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}
