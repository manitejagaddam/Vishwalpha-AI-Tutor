import React from 'react';
import { useAuth } from './context/AuthContext';
import AuthPage from './pages/AuthPage';
import ChatPage from './pages/ChatPage';

function App() {
  const { student } = useAuth();

  if (!student) {
    return <AuthPage />;
  }

  return <ChatPage />;
}

export default App;
