import * as React from 'react';

import { cva, type VariantProps } from 'class-variance-authority';
import { Slot } from 'radix-ui';

import { cn } from '@/lib/utils';

// Glyphs are 10px, about the 12px label's cap height, so an icon reads as a
// peer to the letters instead of looming over them (Phosphor fills its box).
const badgeVariants = cva(
  'group/badge inline-flex h-5.5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-lg border border-transparent px-2 pt-[3px] pb-0.5 text-body-xs whitespace-nowrap transition-colors focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 has-[>svg:first-child]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-2.5!',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground [a]:hover:bg-primary/80',
        secondary:
          'bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80',
        destructive:
          'bg-destructive/10 text-destructive focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:focus-visible:ring-destructive/40 [a]:hover:bg-destructive/20',
        'destructive-solid':
          'bg-destructive text-destructive-foreground focus-visible:ring-destructive/20 [a]:hover:bg-destructive/90',
        success:
          'bg-success/10 text-success-strong focus-visible:ring-success/20 [a]:hover:bg-success/20',
        warning:
          'bg-warning/10 text-warning focus-visible:ring-warning/20 [a]:hover:bg-warning/20',
        info: 'bg-info/10 text-info focus-visible:ring-info/20 [a]:hover:bg-info/20',
        low: 'bg-muted text-muted-foreground focus-visible:ring-ring/20 [a]:hover:bg-muted/80',
        outline:
          'border-border bg-input/30 text-foreground [a]:hover:bg-muted [a]:hover:text-muted-foreground',
        ghost:
          'hover:bg-muted hover:text-muted-foreground dark:hover:bg-muted/50',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: '',
        md: 'h-6 gap-1.5 px-2.5 [&>svg]:size-3.5!',
      },
      // Where the icon sits against the label. Flex-centered beside Britti
      // Sans, a glyph lands ~1px below the label's cap row, so `cap` lifts it
      // by a pixel. Plex Mono's digits sit lower than Britti's capitals, so a
      // mono label wants the glyph on the flex center instead.
      iconAlign: {
        cap: '[&>svg]:-translate-y-px',
        center: '',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
      iconAlign: 'cap',
    },
  }
);

function Badge({
  className,
  variant = 'default',
  size = 'default',
  iconAlign = 'cap',
  asChild = false,
  ...props
}: React.ComponentProps<'span'> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : 'span';

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant, size, iconAlign }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
