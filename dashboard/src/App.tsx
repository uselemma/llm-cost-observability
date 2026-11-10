import { Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './components/app-shell';
import Calls from './pages/calls';
import Dashboard from './pages/dashboard';

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/calls" element={<Calls />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
