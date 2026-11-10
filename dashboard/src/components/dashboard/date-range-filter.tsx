import { useState } from 'react';
import { format, parse } from 'date-fns';
import { CalendarBlank, Check } from '@phosphor-icons/react';
import type { DateRange } from 'react-day-picker';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { DT_FMT, PRESETS, presetMs, type PresetValue, type RangeState } from '@/lib/range';

const DATE_FMT = 'yyyy-MM-dd';
const TIME_FMT = 'HH:mm';

type Draft = { preset: PresetValue | null; from?: Date; to?: Date; fromTime: string; toTime: string };

function draftFrom(value: RangeState): Draft {
  if (value.kind === 'preset') {
    const now = Date.now();
    const from = new Date(now - presetMs(value.preset));
    const to = new Date(now);
    return { preset: value.preset, from, to, fromTime: format(from, TIME_FMT), toTime: format(to, TIME_FMT) };
  }
  const from = parse(value.since, DT_FMT, new Date());
  const to = parse(value.until, DT_FMT, new Date());
  return { preset: null, from, to, fromTime: format(from, TIME_FMT), toTime: format(to, TIME_FMT) };
}

function label(value: RangeState): string {
  if (value.kind === 'preset') return PRESETS.find((p) => p.value === value.preset)!.label;
  const from = parse(value.since, DT_FMT, new Date());
  const to = parse(value.until, DT_FMT, new Date());
  const sameDay = format(from, DATE_FMT) === format(to, DATE_FMT);
  return sameDay
    ? `${format(from, 'MMM d, HH:mm')} – ${format(to, 'HH:mm')}`
    : `${format(from, 'MMM d, HH:mm')} – ${format(to, 'MMM d, HH:mm')}`;
}

// Edits are staged in a draft and only applied on Apply, like the dimension filters.
export default function DateRangeFilter({
  value,
  onApply,
}: {
  value: RangeState;
  onApply: (next: RangeState) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => draftFrom(value));

  function handleOpenChange(next: boolean) {
    if (next) setDraft(draftFrom(value));
    setOpen(next);
  }

  const customSince = draft.from ? `${format(draft.from, DATE_FMT)}T${draft.fromTime}` : '';
  const customUntil = draft.to ? `${format(draft.to, DATE_FMT)}T${draft.toTime}` : '';
  const customValid =
    !!draft.from && !!draft.to && new Date(customUntil).getTime() > new Date(customSince).getTime();
  const canApply = draft.preset !== null || customValid;
  const invalidOrder = draft.preset === null && !!draft.from && !!draft.to && !customValid;

  function apply() {
    if (draft.preset) onApply({ kind: 'preset', preset: draft.preset });
    else onApply({ kind: 'custom', since: customSince, until: customUntil });
    setOpen(false);
  }

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="font-normal">
          <CalendarBlank />
          {label(value)}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <div className="flex">
          <div className="flex w-40 flex-col gap-0.5 border-r p-1.5">
            {PRESETS.map((p) => (
              <button
                key={p.value}
                type="button"
                onClick={() => setDraft({ ...draftFrom({ kind: 'preset', preset: p.value }) })}
                className={cn(
                  'flex h-8 items-center justify-between rounded-[4px] px-2 text-body-sm hover:bg-muted',
                  draft.preset === p.value && 'bg-muted font-medium',
                )}
              >
                {p.label}
                {draft.preset === p.value && <Check className="size-3.5 text-primary" />}
              </button>
            ))}
            <div className="mt-1 px-2 pt-2 text-section-header text-muted-foreground">Custom</div>
            <p className="px-2 pb-1 text-body-xs text-muted-foreground">
              Pick dates on the calendar, then set times.
            </p>
          </div>
          <div>
            <Calendar
              mode="range"
              numberOfMonths={2}
              selected={{ from: draft.from, to: draft.to } as DateRange}
              onSelect={(r) =>
                setDraft((d) => ({ ...d, preset: null, from: r?.from, to: r?.to }))
              }
              defaultMonth={draft.from}
              disabled={{ after: new Date() }}
            />
            <div className="grid grid-cols-2 gap-3 border-t p-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="range-from-time" className="text-body-xs text-muted-foreground">
                  From time
                </Label>
                <Input
                  id="range-from-time"
                  type="time"
                  value={draft.fromTime}
                  onChange={(e) => setDraft((d) => ({ ...d, preset: null, fromTime: e.target.value }))}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="range-to-time" className="text-body-xs text-muted-foreground">
                  To time
                </Label>
                <Input
                  id="range-to-time"
                  type="time"
                  value={draft.toTime}
                  onChange={(e) => setDraft((d) => ({ ...d, preset: null, toTime: e.target.value }))}
                />
              </div>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-between gap-2 border-t px-3 py-2">
          <span className={cn('text-body-xs', invalidOrder ? 'text-destructive' : 'text-muted-foreground')}>
            {invalidOrder
              ? 'End must be after start.'
              : draft.preset === null && (!draft.from || !draft.to)
                ? 'Select a start and end date.'
                : ''}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button size="sm" disabled={!canApply} onClick={apply}>
              Apply
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
