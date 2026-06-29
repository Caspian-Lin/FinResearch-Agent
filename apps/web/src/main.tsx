import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import dayjs from 'dayjs';
import localizedFormat from 'dayjs/plugin/localizedFormat';

// Import the i18n initializer BEFORE App so i18next is configured and the
// active language resolved before the first React render. `initReactI18next`
// resolves synchronously, so no Suspense/loading flash on first paint.
import './i18n';
import './index.css';

// `LL` / `LT` are *localized* formats that need this plugin; without it
// `dayjs(x).format('LL')` prints the literal string "LL" (watchlist added-at,
// dashboard missing sessions). Extending once at entry, before any render.
dayjs.extend(localizedFormat);

import App from './App';
import LoginPage from '@/pages/LoginPage';
import RegisterPage from '@/pages/RegisterPage';
import WatchlistPage from '@/pages/WatchlistPage';
import DashboardPage from '@/pages/DashboardPage';
import BacktestPage from '@/pages/BacktestPage';
import BacktestHistoryPage from '@/pages/BacktestHistoryPage';
import FactorResearchPage from '@/pages/FactorResearchPage';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        {/* App is the layout route (renders Header + <Outlet/> + disclaimer). */}
        <Route element={<App />}>
          {/* Public auth routes. */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />

          {/* Protected routes — guarded by ProtectedRoute. */}
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/watchlist" element={<WatchlistPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/backtest" element={<BacktestPage />} />
            <Route path="/backtest/history" element={<BacktestHistoryPage />} />
            <Route path="/backtest/history/:runId" element={<BacktestHistoryPage />} />
            <Route path="/factor-research" element={<FactorResearchPage />} />
          </Route>

          {/* Unknown paths funnel toward the (protected) dashboard. */}
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
