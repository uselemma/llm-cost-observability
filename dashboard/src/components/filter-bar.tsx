import { useQuery } from '@tanstack/react-query';
import { api } from '@/api';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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

  function set<K extends keyof Filters>(k: K, v: Filters[K]) {
    onChange({ ...filters, [k]: v || undefined });
  }

  return (
    <div className="flex flex-wrap items-end gap-3 px-4 py-3">
      <Field label="Range" htmlFor="range">
        <DateTimeRangePicker
          since={filters.since}
          until={filters.until}
          onChange={({ since, until }) => onChange({ ...filters, since, until })}
        />
      </Field>
      <Field label="Model" htmlFor="model">
        <Select
          value={filters.model ?? ALL}
          onValueChange={(v) => set('model', v === ALL ? undefined : v)}
        >
          <SelectTrigger id="model" className="w-64">
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
          <SelectTrigger id="status" className="w-32">
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
          className="w-72"
        />
      </Field>
    </div>
  );
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
