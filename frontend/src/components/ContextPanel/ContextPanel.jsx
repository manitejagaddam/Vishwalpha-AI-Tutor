import React, { useState } from 'react';
import { useSession } from '../../context/SessionContext';
import { FileText, SearchCode, Brain } from 'lucide-react';

export default function ContextPanel() {
  const { messages, metrics, cognitiveSkills, metricsAdjustments } = useSession();
  const [activeTab, setActiveTab] = useState('chunks');

  // Find the last tutor message
  const lastTutorMsg = [...messages].reverse().find(m => m.role === 'tutor');
  
  const tabs = [
    { id: 'chunks', label: 'Retrieved Context', icon: FileText, color: 'indigo' },
    { id: 'prompt', label: 'Prompt Inspector', icon: SearchCode, color: 'purple' },
    { id: 'cognitive', label: 'Cognitive Eval', icon: Brain, color: 'pink' }
  ];

  return (
    <div className="glass-panel flex flex-col h-full text-sm">
      
      {/* Tabs */}
      <div className="flex bg-black/40 p-2 gap-2">
        {tabs.map(tab => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 py-2 px-3 text-xs font-bold whitespace-nowrap rounded-lg transition-all flex items-center justify-center gap-1.5 border ${
                isActive 
                  ? `bg-${tab.color}-500/20 text-${tab.color}-300 border-${tab.color}-500/30 shadow-[0_0_15px_rgba(var(--tw-colors-${tab.color}-500),0.2)]` 
                  : 'bg-transparent text-gray-500 border-transparent hover:bg-white/5 hover:text-gray-300'
              }`}
            >
              <Icon size={14} className={isActive ? `text-${tab.color}-400` : ''} />
              {tab.label}
            </button>
          )
        })}
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {/* Tab 1: Retrieved Chunks */}
        {activeTab === 'chunks' && (
          <div className="space-y-5">
            {!lastTutorMsg ? (
              <div className="flex flex-col items-center justify-center h-40 text-gray-500 gap-3">
                <FileText size={32} className="opacity-50" />
                <span>Ask a question to see retrieved context here.</span>
              </div>
            ) : (
              <>
                {(lastTutorMsg.chapter || lastTutorMsg.topic) && (
                  <div className="glass-card p-3 rounded-xl border border-indigo-500/20">
                    <div className="text-[10px] text-gray-400 uppercase font-extrabold tracking-widest mb-1">Routed Destination</div>
                    <div className="text-sm font-medium text-white">
                      {lastTutorMsg.chapter} {lastTutorMsg.topic && <span className="text-indigo-400">› {lastTutorMsg.topic}</span>}
                    </div>
                  </div>
                )}
                
                {!lastTutorMsg.chunks?.length ? (
                  <div className={`p-4 rounded-xl text-sm font-medium border ${
                    lastTutorMsg.question_type === 'conversational' 
                      ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' 
                      : 'text-amber-400 bg-amber-500/10 border-amber-500/20'
                  }`}>
                    {lastTutorMsg.question_type === 'conversational' 
                      ? '💬 Conversational — no Qdrant retrieval performed.' 
                      : '⚠️ No chunks passed the confidence threshold. Polite refusal was returned.'}
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="flex gap-2 mb-2">
                      <div className="flex-1 bg-black/40 rounded-lg p-2 text-center border border-white/5">
                        <div className="text-lg font-bold text-white">{lastTutorMsg.chunks.length}</div>
                        <div className="text-[10px] uppercase text-gray-500 font-bold tracking-wider">Total</div>
                      </div>
                      <div className="flex-1 bg-emerald-500/10 rounded-lg p-2 text-center border border-emerald-500/20">
                        <div className="text-lg font-bold text-emerald-400">{lastTutorMsg.chunks.filter(c => c.score >= 0.60).length}</div>
                        <div className="text-[10px] uppercase text-emerald-500/70 font-bold tracking-wider">Passed</div>
                      </div>
                      <div className="flex-1 bg-red-500/10 rounded-lg p-2 text-center border border-red-500/20">
                        <div className="text-lg font-bold text-red-400">{lastTutorMsg.chunks.filter(c => c.score < 0.60).length}</div>
                        <div className="text-[10px] uppercase text-red-500/70 font-bold tracking-wider">Blocked</div>
                      </div>
                    </div>
                    
                    {lastTutorMsg.chunks.map((c, i) => {
                      const passed = c.score >= 0.60;
                      return (
                        <div key={i} className={`glass-card rounded-xl overflow-hidden border-l-4 ${passed ? 'border-l-indigo-500 border-white/5' : 'border-l-red-500 border-white/5 opacity-70'}`}>
                          <div className="flex justify-between items-center bg-black/40 px-3 py-2 border-b border-white/5">
                            <span className="text-xs font-bold text-gray-200">{passed ? '✅' : '🚫'} Chunk {i+1}</span>
                            <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${passed ? 'bg-indigo-500/20 text-indigo-300' : 'bg-red-500/20 text-red-300'}`}>
                              score {c.score.toFixed(3)}
                            </span>
                          </div>
                          <div className="p-4 text-xs text-gray-300 whitespace-pre-wrap leading-relaxed font-medium">
                            {c.content.substring(0, 400)}{c.content.length > 400 ? '...' : ''}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Tab 2: Prompt Inspector */}
        {activeTab === 'prompt' && (
          <div className="space-y-4">
            {!lastTutorMsg ? (
              <div className="flex flex-col items-center justify-center h-40 text-gray-500 gap-3">
                <SearchCode size={32} className="opacity-50" />
                <span>Ask a question to inspect the LLM prompt here.</span>
              </div>
            ) : (
              !lastTutorMsg.prompt_messages?.length ? (
                <div className="text-center text-gray-500 mt-10 bg-black/20 p-4 rounded-xl border border-white/5">No prompt messages recorded for this turn.</div>
              ) : (
                <div className="space-y-4">
                  {lastTutorMsg.prompt_messages.map((pm, i) => (
                    <div key={i} className="glass-card rounded-xl overflow-hidden border border-white/10">
                      <div className="bg-purple-900/40 border-b border-purple-500/20 px-4 py-2 flex items-center justify-between">
                        <span className="text-[10px] uppercase font-bold tracking-widest text-purple-300">
                          {pm.role}
                        </span>
                        <span className="text-[10px] text-gray-500 font-mono">MSG_{i}</span>
                      </div>
                      <div className="p-4 text-xs text-gray-300 whitespace-pre-wrap font-mono leading-relaxed bg-black/60">
                        {pm.content}
                      </div>
                    </div>
                  ))}
                </div>
              )
            )}
          </div>
        )}

        {/* Tab 3: Cognitive Eval */}
        {activeTab === 'cognitive' && (
          <div className="space-y-6">
            
            {/* Bloom's Taxonomy */}
            {cognitiveSkills.cognitive_depth !== undefined && (
              <div className="glass-card p-5 rounded-2xl border border-white/10 relative overflow-hidden group">
                <div className="absolute -right-4 -top-4 text-8xl opacity-5 mix-blend-overlay group-hover:scale-110 transition-transform duration-700">🧠</div>
                <div className="text-[10px] uppercase text-gray-400 font-extrabold tracking-widest mb-3">Bloom's Taxonomy Level</div>
                {(() => {
                  const val = cognitiveSkills.cognitive_depth;
                  let color, level, desc;
                  if (val <= 20) { level = 'Remember'; color = 'text-yellow-400'; desc = 'Recalling facts and basic concepts.'; }
                  else if (val <= 40) { level = 'Understand'; color = 'text-purple-400'; desc = 'Explaining concepts and summaries.'; }
                  else if (val <= 60) { level = 'Apply'; color = 'text-blue-400'; desc = 'Using concepts in new situations.'; }
                  else if (val <= 80) { level = 'Analyze'; color = 'text-pink-400'; desc = 'Drawing connections.'; }
                  else { level = 'Evaluate & Create'; color = 'text-emerald-400'; desc = 'Critiquing theories and creating original ideas.'; }
                  
                  return (
                    <>
                      <div className={`text-2xl font-black ${color} drop-shadow-md`}>{level}</div>
                      <div className="text-xs text-gray-400 mt-2 font-medium">{desc}</div>
                    </>
                  );
                })()}
              </div>
            )}
            
            {/* Metrics Adjustments */}
            {metricsAdjustments && Object.keys(metricsAdjustments).length > 0 && (
              <div className="glass-card p-5 rounded-2xl border border-white/10">
                <h3 className="text-[10px] font-extrabold uppercase tracking-widest text-gray-400 mb-4 flex items-center gap-2">
                  <Activity size={14} className="text-pink-400" />
                  Recent Adjustments
                </h3>
                <div className="space-y-3">
                  {Object.entries(metricsAdjustments).map(([key, val]) => {
                    const isInc = val.adjustment === 'increase';
                    const isDec = val.adjustment === 'decrease';
                    if (!isInc && !isDec) return null;
                    
                    const label = key.replace(/_/g, ' ');
                    return (
                      <div key={key} className={`bg-black/40 border-l-4 p-3 rounded-r-lg shadow-inner ${isInc ? 'border-l-emerald-500' : 'border-l-red-500'}`}>
                        <div className="flex justify-between text-xs items-center mb-1.5">
                          <span className="capitalize font-bold text-gray-200">{label}</span>
                          <span className={`font-black px-2 py-0.5 rounded-full ${isInc ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                            {isInc ? '+' : '-'}{Math.abs(val.delta).toFixed(1)}
                          </span>
                        </div>
                        {val.reason && <div className="text-[10px] text-gray-400 leading-snug">{val.reason}</div>}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
            
            {/* Raw Metrics Table */}
            {Object.keys(metrics).length > 0 && (
              <div className="glass-card p-5 rounded-2xl border border-white/10">
                <h3 className="text-[10px] font-extrabold uppercase tracking-widest text-gray-400 mb-5">Raw Base Metrics</h3>
                <div className="space-y-4">
                  {Object.entries(metrics).map(([k, v]) => {
                    const percentage = Math.min(100, Math.max(0, k.includes('rate') ? v * 100 : v));
                    return (
                      <div key={k} className="group">
                        <div className="flex justify-between text-[11px] font-bold text-gray-400 mb-1.5 group-hover:text-gray-200 transition-colors">
                          <span className="capitalize">{k.replace(/_/g, ' ')}</span>
                          <span className="text-indigo-300 font-mono">{v.toFixed(1)}</span>
                        </div>
                        <div className="w-full bg-black/60 h-2 rounded-full overflow-hidden shadow-inner p-[1px]">
                          <div 
                            className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full shadow-[0_0_10px_rgba(99,102,241,0.5)] relative" 
                            style={{ width: `${percentage}%` }}
                          >
                            <div className="absolute inset-0 bg-white/20 w-full animate-[shimmer_2s_infinite]"></div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
            
          </div>
        )}
      </div>
    </div>
  );
}
