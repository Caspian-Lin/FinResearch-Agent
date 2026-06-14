import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

// Import the i18n initializer BEFORE App so i18next is configured and the
// active language resolved before the first React render. `initReactI18next`
// resolves synchronously, so no Suspense/loading flash on first paint.
import './i18n';

import App from './App';
import WatchlistPage from '@/pages/WatchlistPage';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        {/* App is the layout route (renders Header + <Outlet/> + disclaimer). */}
        <Route element={<App />}>
          <Route path="/" element={<Navigate to="/watchlist" replace />} />
          <Route path="/watchlist" element={<WatchlistPage />} />
          <Route path="*" element={<Navigate to="/watchlist" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
