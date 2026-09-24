import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';
import { AuthProvider } from './context/AuthContext';
import { SessionProvider } from './context/SessionContext';
import { SyncProvider } from './context/SyncContext';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AuthProvider>
      <SessionProvider>
        <SyncProvider>
          <App />
        </SyncProvider>
      </SessionProvider>
    </AuthProvider>
  </React.StrictMode>,
);
