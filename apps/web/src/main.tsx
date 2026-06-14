import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

// Import the i18n initializer BEFORE App so i18next is configured and the
// active language resolved before the first React render. `initReactI18next`
// resolves synchronously, so no Suspense/loading flash on first paint.
import './i18n';

import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
