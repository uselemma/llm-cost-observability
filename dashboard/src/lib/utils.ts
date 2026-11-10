import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

/**
 * Custom design-system type-scale utilities (defined as @utility in globals.css).
 * They must be registered with tailwind-merge as members of the `font-size` group
 * so they conflict with each other / built-in text sizes, but NOT with `text-{color}`.
 * Without this, twMerge silently drops e.g. `text-label-action` when a component
 * also applies `text-destructive`, or `text-body-sm` when a button sets a text color.
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': [
        {
          text: [
            'display',
            'h1',
            'h2',
            'h3',
            'h4',
            'body',
            'body-lg',
            'body-bold',
            'body-sm',
            'body-xs',
            'micro',
            'section-header',
            'label-action',
            'label-passive',
            'label-dense',
            'label-micro',
          ],
        },
      ],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
