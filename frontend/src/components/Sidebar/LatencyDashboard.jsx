import React, { useState, useEffect } from 'react';
import { useSession } from '../../context/SessionContext';
import { 
  Zap, Clock, Cpu, Database, ChevronDown, ChevronUp, 
  Activity, CheckCircle2, AlertCircle, Sparkles, Layers 
} from 'lucide-react';

export default function LatencyDashboard() {
  const { latencyData } = useSession();
  const [isOpen, setIsOpen] = useState(true);
  const [liveElapsed, setLiveElapsed] = useState(0);

  // Live timer tick when a request is actively processing
  useEffect(() => {
    if (!latencyData?.isLive || !latencyData?.turnStartTime) {
      setLiveElapsed(0);
      return;
    }

    const interval = setInterval(() => {
      setLiveElapsed(Math.round((Date.now() - latencyData.turnStartTime) / 100) / 10);
    }, 100);

    return () => clearInterval(interval);
  }, [latencyData?.isLive, latencyData?.turnStartTime]);

  if (!latencyData) {
    return (
      <div className="bg-black/30 border border-white/5 rounded-2xl p-4 text-xs text-gray-400">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 font-bold text-gray-300">
            <Zap size={14} className="text-amber-400" />
            <span>Latency Monitor</span>
          </div>
          <span className="text-[10px] bg-white/5 px-2 py-0.5 rounded text-gray-500 font-mono">Idle</span>
        </div>
        <p className="mt-2 text-[11px] text-gray-500 leading-relaxed">
          Ask a question in chat to view end-to-end response breakdown and engine latency metrics.
        </p>
      </div>
    );
  }

  const {
    status,
    isLive,
    client_total_ms,
    client_ttft_ms,
    total_turn_ms,
    total_ttft_ms,
    llm_ttft_ms,
    llm_stream_ms,
    db_prep_ms = 0,
    syllabus_ms = 0,
    topic_match_ms = 0,
    profile_ms = 0,
    progress_ms = 0,
    conv_init_ms = 0,
    save_msg_ms = 0,
    history_ms = 0,
    question_snippet,
  } = latencyData;

  const totalTime = client_total_ms || total_turn_ms || (isLive ? liveElapsed * 1000 : 0);
  const ttftTime = client_ttft_ms || total_ttft_ms || 0;
  const dbTime = db_prep_ms || (syllabus_ms + topic_match_ms + profile_ms + progress_ms + conv_init_ms + save_msg_ms + history_ms);
  const llmEngineTime = llm_ttft_ms || Math.max(0, ttftTime - dbTime);
  const streamTime = llm_stream_ms || Math.max(0, totalTime - ttftTime);

  // Speed Badge Status
  let badgeColor = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
  let badgeText = '⚡ Fast';
  if (isLive) {
    badgeColor = 'bg-amber-500/10 text-amber-300 border-amber-500/30 animate-pulse';
    badgeText = `⏳ ${liveElapsed.toFixed(1)}s`;
  } else if (totalTime > 4000) {
    badgeColor = 'bg-rose-500/10 text-rose-300 border-rose-500/30';
    badgeText = '🔴 High';
  } else if (totalTime > 2200) {
    badgeColor = 'bg-amber-500/10 text-amber-300 border-amber-500/30';
    badgeText = '🟡 Normal';
  }

  // Waterfall percentage calculations
  const safeTotal = Math.max(totalTime, 1);
  const dbPct = Math.min(100, Math.max(5, Math.round((dbTime / safeTotal) * 100)));
  const llmPct = Math.min(100, Math.max(5, Math.round((llmEngineTime / safeTotal) * 100)));
  const streamPct = Math.max(5, 100 - dbPct - llmPct);

  return (
    <div className="bg-gradient-to-b from-indigo-950/20 via-black/40 to-black/60 border border-indigo-500/20 rounded-2xl p-4 shadow-xl backdrop-blur-md transition-all">
      {/* Header */}
      <div 
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between cursor-pointer select-none group"
      >
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-indigo-500/20 border border-indigo-400/30 flex items-center justify-center">
            <Zap size={13} className="text-amber-400" />
          </div>
          <div>
            <div className="text-[11px] font-extrabold uppercase tracking-wider text-indigo-200">
              Latency Monitor
            </div>
            {question_snippet && (
              <div className="text-[10px] text-gray-400 truncate max-w-[140px]">
                "{question_snippet}"
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full border ${badgeColor}`}>
            {badgeText}
          </span>
          <button className="text-gray-400 hover:text-white transition-colors">
            {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {isOpen && (
        <div className="mt-4 space-y-3.5 pt-3 border-t border-white/5 text-xs">
          {/* Key KPI Tiles */}
          <div className="grid grid-cols-2 gap-2">
            {/* Total TTFT Tile */}
            <div className="bg-black/40 border border-white/5 p-2.5 rounded-xl">
              <div className="text-[10px] text-gray-400 uppercase font-semibold flex items-center gap-1">
                <Clock size={11} className="text-amber-400" /> Time to First Token
              </div>
              <div className="text-base font-extrabold text-white mt-1 font-mono">
                {ttftTime ? `${ttftTime.toLocaleString()} ms` : (isLive ? `${(liveElapsed * 1000).toFixed(0)} ms...` : '—')}
              </div>
              <div className="text-[9px] text-gray-500 mt-0.5">
                Client perceived start
              </div>
            </div>

            {/* Total Response Time Tile */}
            <div className="bg-black/40 border border-white/5 p-2.5 rounded-xl">
              <div className="text-[10px] text-gray-400 uppercase font-semibold flex items-center gap-1">
                <Activity size={11} className="text-indigo-400" /> Total Turn Time
              </div>
              <div className="text-base font-extrabold text-white mt-1 font-mono">
                {totalTime ? `${(totalTime / 1000).toFixed(2)} s` : (isLive ? `${liveElapsed.toFixed(1)} s` : '—')}
              </div>
              <div className="text-[9px] text-gray-500 mt-0.5">
                Full response completed
              </div>
            </div>
          </div>

          {/* Waterfall Proportional Progress Bar */}
          <div>
            <div className="flex justify-between text-[10px] text-gray-400 mb-1.5 font-medium">
              <span>Time Distribution</span>
              <span className="font-mono text-gray-500">{totalTime} ms</span>
            </div>
            <div className="w-full h-2.5 bg-black/50 rounded-full overflow-hidden flex border border-white/10 shadow-inner">
              <div 
                style={{ width: `${dbPct}%` }}
                className="bg-indigo-500 h-full transition-all duration-300" 
                title={`DB & Context Prep: ${dbTime}ms (${dbPct}%)`}
              />
              <div 
                style={{ width: `${llmPct}%` }}
                className="bg-purple-500 h-full transition-all duration-300" 
                title={`LLM TTFT Inference: ${llmEngineTime}ms (${llmPct}%)`}
              />
              <div 
                style={{ width: `${streamPct}%` }}
                className="bg-cyan-500 h-full transition-all duration-300" 
                title={`Token Streaming: ${streamTime}ms (${streamPct}%)`}
              />
            </div>
            <div className="flex justify-between items-center text-[9px] text-gray-400 mt-1 px-0.5">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 inline-block" /> Prep ({dbTime}ms)
              </span>
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-purple-500 inline-block" /> LLM ({llmEngineTime}ms)
              </span>
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 inline-block" /> Stream ({streamTime}ms)
              </span>
            </div>
          </div>

          {/* Granular Sub-Task Timings */}
          <div className="space-y-1.5 bg-black/30 border border-white/5 rounded-xl p-2.5">
            <div className="text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-2 flex items-center justify-between">
              <span>Sub-Task Latency</span>
              <span className="text-[9px] font-normal text-indigo-300">Phase Breakdown</span>
            </div>

            <div className="flex items-center justify-between py-0.5 text-[11px] border-b border-white/5">
              <span className="text-gray-300 flex items-center gap-1.5">
                <Database size={11} className="text-blue-400" /> Syllabus Context (Cached)
              </span>
              <span className="font-mono text-gray-200 font-semibold">{syllabus_ms} ms</span>
            </div>

            <div className="flex items-center justify-between py-0.5 text-[11px] border-b border-white/5">
              <span className="text-gray-300 flex items-center gap-1.5">
                <Sparkles size={11} className="text-amber-400" /> Fast Topic Match (V4)
              </span>
              <span className="font-mono text-gray-200 font-semibold">{topic_match_ms} ms</span>
            </div>

            <div className="flex items-center justify-between py-0.5 text-[11px] border-b border-white/5">
              <span className="text-gray-300 flex items-center gap-1.5">
                <Layers size={11} className="text-purple-400" /> Student Profile & Memory
              </span>
              <span className="font-mono text-gray-200 font-semibold">{profile_ms} ms</span>
            </div>

            <div className="flex items-center justify-between py-0.5 text-[11px] border-b border-white/5">
              <span className="text-gray-300 flex items-center gap-1.5">
                <Clock size={11} className="text-emerald-400" /> Progress & Topic Mastery
              </span>
              <span className="font-mono text-gray-200 font-semibold">{progress_ms} ms</span>
            </div>

            <div className="flex items-center justify-between py-0.5 text-[11px] border-b border-white/5">
              <span className="text-gray-300 flex items-center gap-1.5">
                <Activity size={11} className="text-pink-400" /> Conversation & Message Save
              </span>
              <span className="font-mono text-gray-200 font-semibold">{conv_init_ms + save_msg_ms} ms</span>
            </div>

            <div className="flex items-center justify-between py-0.5 text-[11px] border-b border-white/5">
              <span className="text-gray-300 flex items-center gap-1.5">
                <Clock size={11} className="text-sky-400" /> Linearized History Fetch
              </span>
              <span className="font-mono text-gray-200 font-semibold">{history_ms} ms</span>
            </div>

            <div className="flex items-center justify-between py-0.5 text-[11px]">
              <span className="text-gray-300 flex items-center gap-1.5">
                <Cpu size={11} className="text-violet-400" /> Azure OpenAI TTFT
              </span>
              <span className="font-mono text-violet-300 font-bold">{llm_ttft_ms} ms</span>
            </div>
          </div>

          {/* Architecture Status Badge */}
          <div className="p-2 rounded-xl bg-violet-950/20 border border-violet-500/20 text-[10px] text-violet-300 flex items-center justify-between">
            <span className="font-semibold flex items-center gap-1">
              <CheckCircle2 size={11} className="text-emerald-400" /> V4 Direct Core
            </span>
            <span className="text-gray-400 font-mono">0ms RAG Overhead</span>
          </div>
        </div>
      )}
    </div>
  );
}
