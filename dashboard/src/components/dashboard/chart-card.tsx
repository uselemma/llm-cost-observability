import type { ReactNode } from 'react';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export default function ChartCard({
  title,
  description,
  actions,
  loading,
  error,
  empty,
  emptyText = 'No data for this selection.',
  className,
  children,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  loading?: boolean;
  error?: unknown;
  empty?: boolean;
  emptyText?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {actions && <CardAction>{actions}</CardAction>}
      </CardHeader>
      <CardContent>
        {error ? (
          <div className="flex h-64 items-center justify-center text-sm text-destructive">
            Failed to load: {(error as Error).message}
          </div>
        ) : loading ? (
          <div className="h-64 animate-pulse rounded-md bg-muted" />
        ) : empty ? (
          <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
            {emptyText}
          </div>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}
