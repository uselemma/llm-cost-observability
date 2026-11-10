// Class lists copied from uselemma/platform frontend/src/components/ui/button.tsx
// (loading/shine state removed: this app has no loader).
import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  // Hover is a simple darker background per variant (no gradient overlay).
  // Icons default to icon-gray; filled variants override to `currentColor`.
  "group/button relative inline-flex shrink-0 items-center justify-center rounded-[4px] border border-transparent whitespace-nowrap transition-[color,background-color,border-color,box-shadow,opacity,translate,scale] outline-none select-none focus-visible:border-ring focus-visible:ring-1 focus-visible:ring-ring/50 active:translate-y-px disabled:pointer-events-none disabled:opacity-40 aria-invalid:border-destructive aria-invalid:ring-1 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg]:text-muted-foreground [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-xs hover:bg-[oklch(from_color-mix(in_oklab,var(--color-primary),var(--brand-accent)_40%)_l_calc(c_*_1.2)_h)] [&_svg]:text-current",
        outline:
          "border-border bg-card shadow-xs hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground dark:border-input dark:hover:bg-input/50",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-[color-mix(in_oklab,var(--color-secondary),black_10%)] aria-expanded:bg-secondary aria-expanded:text-secondary-foreground",
        ghost:
          // --ghost-hover resolves per theme (muted / translucent foreground) as
          // unprefixed utilities, so caller overrides like `hover:bg-success/10`
          // beat them via tailwind-merge in dark mode too.
          "hover:bg-ghost-hover hover:text-foreground aria-expanded:bg-ghost-hover aria-expanded:text-foreground",
        destructive:
          "bg-destructive/10 text-destructive hover:bg-destructive/20 focus-visible:border-destructive/40 focus-visible:ring-destructive/20 [&_svg]:text-current dark:bg-destructive/20 dark:hover:bg-destructive/30 dark:focus-visible:ring-destructive/40",
        "destructive-solid":
          "bg-destructive text-destructive-foreground hover:bg-[color-mix(in_oklab,var(--color-destructive),black_10%)] focus-visible:border-destructive/40 focus-visible:ring-destructive/20 [&_svg]:text-current",
        link: "text-primary [&_svg]:text-current after:pointer-events-none after:absolute after:inset-x-3 after:bottom-1.5 after:h-px after:origin-left after:scale-x-0 after:bg-current after:transition-transform after:duration-200 after:ease-out hover:after:scale-x-100",
      },
      size: {
        default:
          "h-8 gap-1 px-3.5 text-body-sm has-[>svg:first-child]:pl-2.5",
        xs: "h-7 gap-1 px-2.5 text-body-xs has-[>svg:first-child]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1 px-3 text-body-sm has-[>svg:first-child]:pl-2 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "gap-1.5 px-4.5 py-2 text-body has-[>svg:first-child]:pl-3.5",
        icon: "size-8 text-body-sm",
        "icon-xs": "size-7 text-body-xs [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-8 text-body-sm [&_svg:not([class*='size-'])]:size-3.5",
        "icon-lg": "size-10 text-body [&_svg:not([class*='size-'])]:size-5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  disabled,
  onClick,
  children,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      disabled={disabled}
      className={cn(buttonVariants({ variant, size, className }))}
      onClick={onClick}
      {...props}
    >
      {children}
    </Comp>
  )
}

export { Button, buttonVariants }
