import { Navigate, Route, Routes } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from './api';
import Login from './pages/login';
import Calls from './pages/calls';

export default function App() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me });

  if (me.isPending) {
    return <div className="flex h-full items-center justify-center text-zinc-400">Loading…</div>;
  }

  const authenticated = !me.isError;

  return (
    <Routes>
      <Route
        path="/login"
        element={authenticated ? <Navigate to="/" replace /> : <Login onSuccess={() => me.refetch()} />}
      />
      <Route
        path="/"
        element={
          authenticated ? <Calls /> : me.error instanceof ApiError && me.error.status === 401
            ? <Navigate to="/login" replace />
            : <Login onSuccess={() => me.refetch()} />
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
