import React from 'react';
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from 'react-resizable-panels';
import { useSession } from '../context/SessionContext';
import Sidebar from '../components/Sidebar/Sidebar';
import ChatArea from '../components/Chat/ChatArea';
import ContextPanel from '../components/ContextPanel/ContextPanel';



export default function ChatPage() {
  const { showContext } = useSession();

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-transparent">
      <PanelGroup orientation="horizontal">
        
        {/* Left Sidebar Panel */}
        <Panel defaultSize={20} minSize={15} maxSize={300}>
          <Sidebar />
        </Panel>

        <PanelResizeHandle className="w-1.5 bg-black/20 hover:bg-indigo-500/50 transition-colors duration-200 cursor-col-resize flex flex-col justify-center items-center group relative z-10">
          <div className="h-8 w-1 rounded-full bg-white/20 group-hover:bg-indigo-300 transition-colors" />
        </PanelResizeHandle>

        {/* Center Chat Panel */}
        <Panel minSize={30}>
          <ChatArea />
        </Panel>

        {/* Right Context Panel (Conditionally rendered) */}
        {showContext && (
          <>
            <PanelResizeHandle className="w-1.5 bg-black/20 hover:bg-indigo-500/50 transition-colors duration-200 cursor-col-resize flex flex-col justify-center items-center group relative z-10">
              <div className="h-8 w-1 rounded-full bg-white/20 group-hover:bg-indigo-300 transition-colors" />
            </PanelResizeHandle>
            <Panel defaultSize={30} minSize={20} maxSize={500}>
              <button>  </button>
              <ContextPanel />
            </Panel>
          </>
        )}
        
      </PanelGroup>
    </div>
  );
}
