import { Navigate, Route, Routes } from 'react-router-dom';
import Calls from './pages/calls';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Calls />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
