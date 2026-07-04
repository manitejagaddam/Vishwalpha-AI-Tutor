import React, { useState } from 'react';
import { useSession } from '../../context/SessionContext';

export default function ContextPanel() {
  const { messages, metrics, cognitiveSkills, metricsAdjustments } = useSession();
  const [activeTab, setActiveTab] = useState('chunks');

  // Find the last tutor message
  const lastTutorMsg = [...messages].reverse().find(m => m.role === 'tutor');
  
  const tabs = [
    { id: 'chunks', label: '📖 Retrieved Context' },
    { id: 'prompt', label: '🔬 Prompt Inspector' },
    { id: 'cognitive', label: '🧠 Cognitive Evaluation' }
  ];

  return (
    <div className="flex flex-col h-full bg-black/40 backdrop-blur-md text-sm border-l border-white/10">
      
      {/* Tabs */}
      <div className="flex border-b border-white/10 overflow-x-auto">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 py-3 px-4 text-xs font-medium whitespace-nowrap transition-colors border-b-2 ${
              activeTab === tab.id ? 'border-indigo-500 text-indigo-400' : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {/* Tab 1: Retrieved Chunks */}
        {activeTab === 'chunks' && (
          <div className="space-y-4">
            {!lastTutorMsg ? (
              <div className="text-center text-gray-500 mt-10">Ask a question to see the retrieved context here.</div>
            ) : (
              <>
                {(lastTutorMsg.chapter || lastTutorMsg.topic) && (
                  <div className="text-xs text-gray-400 mb-4">
                    <span className="font-semibold text-indigo-400">Routed to: </span>
                    {lastTutorMsg.chapter} {lastTutorMsg.topic && `› ${lastTutorMsg.topic}`}
                  </div>
                )}
                
                {!lastTutorMsg.chunks?.length ? (
                  <div className={`p-4 rounded-lg text-xs ${lastTutorMsg.question_type === 'conversational' ? 'text-emerald-400 bg-emerald-500/10' : 'text-amber-400 bg-amber-500/10'}`}>
                    {lastTutorMsg.question_type === 'conversational' 
                      ? '💬 Conversational — no Qdrant retrieval performed.' 
                      : '⚠️ No chunks passed the confidence threshold. Polite refusal was returned.'}
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="text-xs text-gray-400 flex gap-2">
                      <span>{lastTutorMsg.chunks.length} chunks retrieved</span>
                      <span>·</span>
                      <span className="text-emerald-400">{lastTutorMsg.chunks.filter(c => c.score >= 0.60).length} passed</span>
                      <span>·</span>
                      <span className="text-red-400">{lastTutorMsg.chunks.filter(c => c.score < 0.60).length} blocked</span>
                    </div>
                    
                    {lastTutorMsg.chunks.map((c, i) => {
                      const passed = c.score >= 0.60;
                      return (
                        <div key={i} className={`bg-white/5 border-l-4 rounded-r p-3 ${passed ? 'border-indigo-500' : 'border-red-500'}`}>
                          <div className="flex justify-between items-center mb-2">
                            <span className="text-xs font-semibold">{passed ? '✅' : '🚫'} Chunk {i+1}</span>
                            <span className="text-[10px] bg-white/10 px-2 py-0.5 rounded text-gray-300">score {c.score.toFixed(3)}</span>
                          </div>
                          <div className="text-xs text-gray-300 whitespace-pre-wrap">
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
              <div className="text-center text-gray-500 mt-10">Ask a question to inspect the LLM prompt here.</div>
            ) : (
              !lastTutorMsg.prompt_messages?.length ? (
                <div className="text-center text-gray-500 mt-10">No prompt messages recorded for this turn.</div>
              ) : (
                <div className="space-y-3">
                  {lastTutorMsg.prompt_messages.map((pm, i) => (
                    <div key={i} className="bg-white/5 rounded border border-white/10 overflow-hidden">
                      <div className="bg-white/10 px-3 py-1 text-xs font-mono text-indigo-300">
                        {pm.role.toUpperCase()}
                      </div>
                      <div className="p-3 text-xs text-gray-300 whitespace-pre-wrap font-mono">
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
              <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                <div className="text-[10px] uppercase text-gray-400 font-bold tracking-wider mb-2">Bloom's Taxonomy Level</div>
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
                      <div className={`text-lg font-bold ${color}`}>{level}</div>
                      <div className="text-xs text-gray-400 mt-1">{desc}</div>
                    </>
                  );
                })()}
              </div>
            )}
            
            {/* Metrics Adjustments */}
            {metricsAdjustments && Object.keys(metricsAdjustments).length > 0 && (
              <div>
                <h3 className="text-xs font-bold uppercase text-gray-400 mb-3 border-b border-white/10 pb-1">Recent Cognitive Adjustments</h3>
                <div className="space-y-2">
                  {Object.entries(metricsAdjustments).map(([key, val]) => {
                    const isInc = val.adjustment === 'increase';
                    const isDec = val.adjustment === 'decrease';
                    if (!isInc && !isDec) return null;
                    
                    const label = key.replace(/_/g, ' ');
                    return (
                      <div key={key} className={`bg-white/5 border-l-4 p-2 rounded-r ${isInc ? 'border-emerald-500' : 'border-red-500'}`}>
                        <div className="flex justify-between text-xs">
                          <span className="capitalize font-semibold text-gray-300">{label}</span>
                          <span className={`font-bold ${isInc ? 'text-emerald-400' : 'text-red-400'}`}>
                            {isInc ? '+' : '-'}{Math.abs(val.delta).toFixed(1)}
                          </span>
                        </div>
                        {val.reason && <div className="text-[10px] text-gray-400 mt-1">{val.reason}</div>}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
            
            {/* Raw Metrics Table */}
            {Object.keys(metrics).length > 0 && (
              <div>
                <h3 className="text-xs font-bold uppercase text-gray-400 mb-3 border-b border-white/10 pb-1">Raw Base Metrics</h3>
                <div className="space-y-3">
                  {Object.entries(metrics).map(([k, v]) => (
                    <div key={k}>
                      <div className="flex justify-between text-xs text-gray-400 mb-1">
                        <span className="capitalize">{k.replace(/_/g, ' ')}</span>
                        <span>{v.toFixed(1)}</span>
                      </div>
                      <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden">
                        <div 
                          className="h-full bg-indigo-500 rounded-full" 
                          style={{ width: `${Math.min(100, Math.max(0, k.includes('rate') ? v * 100 : v))}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
          </div>
        )}
      </div>
    </div>
  );
}
