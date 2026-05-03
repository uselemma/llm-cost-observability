import { useState } from 'react';
import { format, parse } from 'date-fns';
import { CalendarIcon } from 'lucide-react';
import type { DateRange } from 'react-day-picker';

import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

// Values are ISO-style "YYYY-MM-DDTHH:MM" strings (datetime-local format),
// which is what the dashboard API expects via ?since=&until=.
type Iso = string | undefined;

const DT_FMT = "yyyy-MM-dd'T'HH:mm";
const DATE_FMT = "yyyy-MM-dd";

export default function DateTimeRangePicker({
  since,
  until,
  onChange,
}: {
  since: Iso;
  until: Iso;
  onChange: (next: { since: Iso; until: Iso }) => void;
}) {
  const [open, setOpen] = useState(false);

  const fromDate = parseDt(since);
  const toDate = parseDt(until);

  const fromTime = since ? since.slice(11, 16) : '00:00';
  const toTime = until ? until.slice(11, 16) : '23:59';

  function setRange(range: DateRange | undefined) {
    onChange({
      since: range?.from ? `${format(range.from, DATE_FMT)}T${fromTime}` : undefined,
      until: range?.to ? `${format(range.to, DATE_FMT)}T${toTime}` : undefined,
    });
  }

  function setFromTime(value: string) {
    if (!fromDate) return;
    onChange({ since: `${format(fromDate, DATE_FMT)}T${value}`, until });
  }

  function setToTime(value: string) {
    if (!toDate) return;
    onChange({ since, until: `${format(toDate, DATE_FMT)}T${value}` });
  }

  const summary = formatSummary(fromDate, toDate, fromTime, toTime);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" className="w-72 justify-start font-normal">
          <CalendarIcon className="mr-2 size-3.5" />
          <span className="truncate">{summary}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="range"
          numberOfMonths={2}
          selected={{ from: fromDate, to: toDate }}
          onSelect={setRange}
          defaultMonth={fromDate}
        />
        <div className="grid grid-cols-2 gap-3 border-t p-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="from-time" className="text-xs text-muted-foreground">
              From time
            </Label>
            <Input
              id="from-time"
              type="time"
              value={fromTime}
              onChange={(e) => setFromTime(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="to-time" className="text-xs text-muted-foreground">
              To time
            </Label>
            <Input
              id="to-time"
              type="time"
              value={toTime}
              onChange={(e) => setToTime(e.target.value)}
            />
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function parseDt(s: string | undefined): Date | undefined {
  if (!s) return undefined;
  // Accept "YYYY-MM-DDTHH:mm" or "YYYY-MM-DDTHH:mm:ss".
  const trimmed = s.length > 16 ? s.slice(0, 16) : s;
  const d = parse(trimmed, DT_FMT, new Date());
  return Number.isNaN(d.getTime()) ? undefined : d;
}

function formatSummary(from?: Date, to?: Date, fromTime?: string, toTime?: string): string {
  if (!from && !to) return 'Pick a range';
  const fmt = (d?: Date, t?: string) =>
    d && !Number.isNaN(d.getTime()) ? `${format(d, 'MMM d, yyyy')} ${t ?? ''}`.trim() : '…';
  return `${fmt(from, fromTime)} → ${fmt(to, toTime)}`;
}
