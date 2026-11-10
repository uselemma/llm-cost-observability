import { NavLink, Outlet } from 'react-router-dom';
import { ChartLineUp, ListBullets, SquaresFour } from '@phosphor-icons/react';
import { ModeToggle } from '@/components/mode-toggle';
import { cn } from '@/lib/utils';

const NAV = [
  { to: '/', label: 'Dashboard', end: true, Icon: SquaresFour },
  { to: '/calls', label: 'Calls', end: false, Icon: ListBullets },
];

// Mirrors the real dashboard chrome: a flat sidebar (224px, icon rail below lg) and a main
// column on bg-sidebar with cards resting on it. Nav items are text-body-sm, the active one
// font-medium text-primary, hover/active fill bg-sidebar-accent.
export default function AppShell() {
  return (
    <div className="flex h-full w-full bg-sidebar">
      <aside className="flex w-14 shrink-0 flex-col gap-1 border-r border-sidebar-border bg-sidebar px-2 py-3 lg:w-56">
        <div className="mb-3 flex h-8 items-center gap-2 px-1">
          <ChartLineUp weight="fill" className="size-6 shrink-0 text-primary" />
          <span className="hidden text-body-bold lg:block">LLM usage</span>
        </div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map(({ to, label, end, Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              title={label}
              className={({ isActive }) =>
                cn(
                  'flex h-8 items-center gap-2 rounded-[4px] px-2 text-body-sm text-sidebar-foreground transition-colors hover:bg-sidebar-accent',
                  isActive && 'bg-sidebar-accent font-medium text-primary',
                )
              }
            >
              <Icon className="size-4 shrink-0" />
              <span className="hidden lg:inline">{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto">
          <ModeToggle />
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}

export function PageHeader({ title, actions }: { title: string; actions?: React.ReactNode }) {
  return (
    <header className="flex min-h-8 items-center justify-between gap-3">
      <h1 className="text-h4">{title}</h1>
      <div className="flex items-center gap-2">{actions}</div>
    </header>
  );
}
