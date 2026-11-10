import * as React from 'react';

import { cn } from '@/lib/utils';

function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'h-8 w-full min-w-0 rounded bg-(--input-surface) px-2.5 py-1 text-body shadow-xs ring-1 ring-foreground/10 transition-[color,box-shadow] outline-none [--input-surface:var(--color-card)] file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-body-sm file:text-foreground placeholder:text-muted-foreground focus-visible:ring-foreground/30 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:ring-3 aria-invalid:ring-destructive/50 md:text-body-sm dark:aria-invalid:ring-destructive/40',
        className
      )}
      {...props}
    />
  );
}

export { Input };
