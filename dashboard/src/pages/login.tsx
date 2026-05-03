import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { api } from '@/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [secret, setSecret] = useState('');
  const m = useMutation({
    mutationFn: (s: string) => api.login(s),
    onSuccess,
  });

  return (
    <div className="flex h-full items-center justify-center px-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate(secret);
        }}
        className="w-full max-w-sm space-y-5 rounded-lg border bg-card p-6 shadow-sm"
      >
        <div className="space-y-1">
          <h1 className="text-lg font-semibold tracking-tight">LLM call log</h1>
          <p className="text-sm text-muted-foreground">Enter a LiteLLM key to sign in.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="secret">Secret</Label>
          <Input
            id="secret"
            type="password"
            autoFocus
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder="sk-..."
          />
        </div>
        {m.isError && <p className="text-sm text-destructive">Invalid secret.</p>}
        <Button type="submit" className="w-full" disabled={m.isPending || !secret}>
          {m.isPending && <Loader2 className="animate-spin" />}
          Sign in
        </Button>
      </form>
    </div>
  );
}
