import React from 'react';
import { useSession } from '../context/SessionContext';
import Sidebar from '../components/Sidebar/Sidebar';
import ChatArea from '../components/Chat/ChatArea';
import ContextPanel from '../components/ContextPanel/ContextPanel';

export default function ChatPage() {
  const { showContext } = useSession();

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex-1 flex overflow-hidden">
          <div className={`flex-1 flex flex-col transition-all duration-300 ${showContext ? 'w-3/5' : 'w-full'}`}>
            <ChatArea />
          </div>
          
          {showContext && (
            <div className="w-2/5 border-l border-white/10 bg-black/20 flex flex-col">
              <ContextPanel />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
