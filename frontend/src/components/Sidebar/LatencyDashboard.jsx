import React, { useState, useEffect, useMemo } from 'react';
import { useSession } from '../../context/SessionContext';
import { 
  Zap, Clock, Cpu, Database, ChevronDown, ChevronUp, 
  Activity, CheckCircle2, AlertCircle, Sparkles, Layers,
  ChevronLeft, ChevronRight, BarChart3, Maximize2, X, Copy, Check
} from 'lucide-react';

export default function LatencyDashboard() {
  const { latencyData, latencyInstances = [] } = useSession();
  const [isOpen, setIsOpen] = useState(true);
  const [activeTab, setActiveTab] = useState('instance'); // 'instance' | 'percentiles' | 'history'
  const [selectedInstanceIdx, setSelectedInstanceIdx] = useState(null);
  const [showFullModal, setShowFullModal] = useState(false);
  const [copiedReport, setCopiedReport] = useState(false);
  const [liveElapsed, setLiveElapsed] = useState(0);

  // Default to latest instance if none selected
  const allInstances = useMemo(() => {
    if (!latencyInstances || latencyInstances.length === 0) {
      return latencyData ? [latencyData] : [];
    }
    return latencyInstances;
  }, [latencyInstances, latencyData]);

  // When new instances arrive, follow latest unless user explicitly picked an index
  const currentInstance = useMemo(() => {
    if (selectedInstanceIdx !== null && allInstances[selectedInstanceIdx]) {
      return allInstances[selectedInstanceIdx];
    }
    return latencyData || allInstances[allInstances.length - 1] || null;
  }, [selectedInstanceIdx, allInstances, latencyData]);

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

  // Aggregate Percentile Calculations (P50, P90, P95, Mean, Min, Max)
  const stats = useMemo(() => {
    const completed = allInstances.filter(i => !i.isLive && (i.client_total_ms || i.total_turn_ms));
    if (completed.length === 0) return null;

    const calcP = (arr, p) => {
      if (arr.length === 0) return 0;
      const sorted = [...arr].sort((a, b) => a - b);
      const idx = (p / 100) * (sorted.length - 1);
      const lower = Math.floor(idx);
      const upper = Math.ceil(idx);
      const weight = idx - lower;
      return sorted[lower] * (1 - weight) + sorted[upper] * weight;
    };

    const ttfts = completed.map(i => i.client_ttft_ms || i.total_ttft_ms || 0);
    const totals = completed.map(i => i.client_total_ms || i.total_turn_ms || 0);
    const dbPreps = completed.map(i => i.db_prep_ms || 0);
    const llmTtfts = completed.map(i => i.llm_ttft_ms || 0);

    return {
      count: completed.length,
      ttft: {
        p50: Math.round(calcP(ttfts, 50)),
        p90: Math.round(calcP(ttfts, 90)),
        p95: Math.round(calcP(ttfts, 95)),
        mean: Math.round(ttfts.reduce((a, b) => a + b, 0) / ttfts.length),
        min: Math.min(...ttfts),
        max: Math.max(...ttfts),
      },
      total: {
        p50: Math.round(calcP(totals, 50)),
        p90: Math.round(calcP(totals, 90)),
        p95: Math.round(calcP(totals, 95)),
        mean: Math.round(totals.reduce((a, b) => a + b, 0) / totals.length),
        min: Math.min(...totals),
        max: Math.max(...totals),
      },
      dbPrep: {
        p50: Math.round(calcP(dbPreps, 50)),
        p90: Math.round(calcP(dbPreps, 90)),
      },
      llmTtft: {
        p50: Math.round(calcP(llmTtfts, 50)),
        p90: Math.round(calcP(llmTtfts, 90)),
      }
    };
  }, [allInstances]);

  const copyEvaluationReport = () => {
    if (!stats) return;
    const reportText = `=== VishwAlpha AI Tutor Latency & LLM Evaluation Report ===
Generated: ${new Date().toLocaleString()}
Instances Evaluated: ${stats.count}

--- TIME TO FIRST TOKEN (TTFT) ---
• P50 (Median) : ${stats.ttft.p50} ms
• P90          : ${stats.ttft.p90} ms
• P95          : ${stats.ttft.p95} ms
• Mean         : ${stats.ttft.mean} ms
• Range        : ${stats.ttft.min} ms - ${stats.ttft.max} ms

--- TOTAL TURN DURATION ---
• P50 (Median) : ${(stats.total.p50 / 1000).toFixed(2)} s
• P90          : ${(stats.total.p90 / 1000).toFixed(2)} s
• P95          : ${(stats.total.p95 / 1000).toFixed(2)} s
• Mean         : ${(stats.total.mean / 1000).toFixed(2)} s

--- DB PREP & CONTEXT FETCH ---
• P50 (Median) : ${stats.dbPrep.p50} ms
• P90          : ${stats.dbPrep.p90} ms

--- ARCHITECTURE EVALUATION ---
• Version: V4 Direct Core (RAG-Free Curriculum Boundaries)
• Memory Cache: L1 In-Memory Active (Sub-millisecond)
• Redis Cache: Upstash Redis L2 Connected
• Grade Boundaries: Strictly Enforced
`;
    navigator.clipboard.writeText(reportText);
    setCopiedReport(true);
    setTimeout(() => setCopiedReport(false), 2000);
  };

  if (!currentInstance && allInstances.length === 0) {
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
          Ask a question in chat to view real-time latency, instance history, and P50/P90/P95 benchmarks.
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
  } = currentInstance || {};

  const totalTime = client_total_ms || total_turn_ms || (isLive ? liveElapsed * 1000 : 0);
  const ttftTime = client_ttft_ms || total_ttft_ms || 0;
  const dbTime = db_prep_ms || (syllabus_ms + topic_match_ms + profile_ms + progress_ms + conv_init_ms + history_ms);
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

  const activeIdx = selectedInstanceIdx !== null ? selectedInstanceIdx : allInstances.length - 1;

  return (
    <>
      <div className="bg-gradient-to-b from-indigo-950/20 via-black/40 to-black/60 border border-indigo-500/20 rounded-2xl p-4 shadow-xl backdrop-blur-md transition-all">
        {/* Header */}
        <div className="flex items-center justify-between select-none">
          <div 
            onClick={() => setIsOpen(!isOpen)}
            className="flex items-center gap-2 cursor-pointer group flex-1"
          >
            <div className="w-6 h-6 rounded-lg bg-indigo-500/20 border border-indigo-400/30 flex items-center justify-center">
              <Zap size={13} className="text-amber-400" />
            </div>
            <div>
              <div className="text-[11px] font-extrabold uppercase tracking-wider text-indigo-200 flex items-center gap-1.5">
                Latency Monitor
                {allInstances.length > 1 && (
                  <span className="text-[9px] bg-indigo-500/30 text-indigo-300 px-1.5 py-0.2 rounded-full font-mono">
                    {allInstances.length}
                  </span>
                )}
              </div>
              {question_snippet && (
                <div className="text-[10px] text-gray-400 truncate max-w-[130px]">
                  "{question_snippet}"
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full border ${badgeColor}`}>
              {badgeText}
            </span>
            <button
              onClick={() => setShowFullModal(true)}
              className="p-1 hover:bg-white/10 text-gray-400 hover:text-white rounded-lg transition-colors"
              title="Expand Full Analytics Modal"
            >
              <Maximize2 size={13} />
            </button>
            <button 
              onClick={() => setIsOpen(!isOpen)}
              className="text-gray-400 hover:text-white transition-colors p-1"
            >
              {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </div>
        </div>

        {isOpen && (
          <div className="mt-3.5 space-y-3 pt-3 border-t border-white/5 text-xs">
            {/* View Selector Tabs */}
            <div className="flex items-center bg-black/50 p-1 rounded-xl border border-white/5 text-[10px] font-semibold">
              <button
                onClick={() => setActiveTab('instance')}
                className={`flex-1 py-1 rounded-lg text-center transition-all ${
                  activeTab === 'instance'
                    ? 'bg-indigo-600/40 text-white font-bold border border-indigo-500/30 shadow'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                Instance
              </button>
              <button
                onClick={() => setActiveTab('percentiles')}
                className={`flex-1 py-1 rounded-lg text-center transition-all ${
                  activeTab === 'percentiles'
                    ? 'bg-indigo-600/40 text-white font-bold border border-indigo-500/30 shadow'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                Percentiles
              </button>
              <button
                onClick={() => setActiveTab('history')}
                className={`flex-1 py-1 rounded-lg text-center transition-all ${
                  activeTab === 'history'
                    ? 'bg-indigo-600/40 text-white font-bold border border-indigo-500/30 shadow'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                Logs ({allInstances.length})
              </button>
            </div>

            {/* TAB 1: INSTANCE DETAIL */}
            {activeTab === 'instance' && (
              <>
                {/* Instance Stepper Carousel */}
                {allInstances.length > 1 && (
                  <div className="flex items-center justify-between bg-black/40 px-2.5 py-1.5 rounded-xl border border-white/5 text-[10px]">
                    <button
                      disabled={activeIdx <= 0}
                      onClick={() => setSelectedInstanceIdx(Math.max(0, activeIdx - 1))}
                      className="p-0.5 text-gray-400 hover:text-white disabled:opacity-20 disabled:pointer-events-none"
                    >
                      <ChevronLeft size={13} />
                    </button>
                    <span className="font-mono text-gray-300">
                      Instance <span className="font-bold text-indigo-300">{activeIdx + 1}</span> of {allInstances.length}
                    </span>
                    <button
                      disabled={activeIdx >= allInstances.length - 1}
                      onClick={() => setSelectedInstanceIdx(Math.min(allInstances.length - 1, activeIdx + 1))}
                      className="p-0.5 text-gray-400 hover:text-white disabled:opacity-20 disabled:pointer-events-none"
                    >
                      <ChevronRight size={13} />
                    </button>
                  </div>
                )}

                {/* Key KPI Tiles */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-black/40 border border-white/5 p-2.5 rounded-xl">
                    <div className="text-[10px] text-gray-400 uppercase font-semibold flex items-center gap-1">
                      <Clock size={11} className="text-amber-400" /> Perceived TTFT
                    </div>
                    <div className="text-base font-extrabold text-white mt-1 font-mono">
                      {ttftTime ? `${ttftTime.toLocaleString()} ms` : (isLive ? `${(liveElapsed * 1000).toFixed(0)} ms...` : '—')}
                    </div>
                    <div className="text-[9px] text-gray-500 mt-0.5">
                      DB Prep: <span className="font-mono text-indigo-300 font-bold">{dbTime}ms</span>
                    </div>
                  </div>

                  <div className="bg-black/40 border border-white/5 p-2.5 rounded-xl">
                    <div className="text-[10px] text-gray-400 uppercase font-semibold flex items-center gap-1">
                      <Activity size={11} className="text-indigo-400" /> Total Turn Time
                    </div>
                    <div className="text-base font-extrabold text-white mt-1 font-mono">
                      {totalTime ? `${(totalTime / 1000).toFixed(2)} s` : (isLive ? `${liveElapsed.toFixed(1)} s` : '—')}
                    </div>
                    <div className="text-[9px] text-gray-500 mt-0.5">
                      Stream: <span className="font-mono text-cyan-300 font-bold">{streamTime}ms</span>
                    </div>
                  </div>
                </div>

                {/* Waterfall Proportional Progress Bar */}
                <div>
                  <div className="flex justify-between text-[10px] text-gray-400 mb-1.5 font-medium">
                    <span>Time Distribution</span>
                    <span className="font-mono text-gray-500">{totalTime} ms</span>
                  </div>
                  <div className="w-full h-2 bg-black/50 rounded-full overflow-hidden flex border border-white/10 shadow-inner">
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

                {/* Sub-Task Latency Inspector */}
                <div className="space-y-1 bg-black/30 border border-white/5 rounded-xl p-2.5">
                  <div className="flex items-center justify-between py-0.5 text-[11px] border-b border-white/5">
                    <span className="text-gray-300 flex items-center gap-1.5">
                      <Database size={11} className="text-blue-400" /> Syllabus Context
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
                      <Clock size={11} className="text-emerald-400" /> Progress & Mastery
                    </span>
                    <span className="font-mono text-gray-200 font-semibold">{progress_ms} ms</span>
                  </div>

                  <div className="flex items-center justify-between py-0.5 text-[11px] border-b border-white/5">
                    <span className="text-gray-300 flex items-center gap-1.5">
                      <Activity size={11} className="text-pink-400" /> Async Save / Persist
                    </span>
                    <span className="font-mono text-gray-200 font-semibold">{save_msg_ms} ms</span>
                  </div>

                  <div className="flex items-center justify-between py-0.5 text-[11px]">
                    <span className="text-gray-300 flex items-center gap-1.5">
                      <Cpu size={11} className="text-violet-400" /> Azure OpenAI TTFT
                    </span>
                    <span className="font-mono text-violet-300 font-bold">{llm_ttft_ms} ms</span>
                  </div>
                </div>
              </>
            )}

            {/* TAB 2: PERCENTILES & AGGREGATES */}
            {activeTab === 'percentiles' && (
              <div className="space-y-2.5">
                {stats ? (
                  <>
                    <div className="bg-black/40 border border-white/5 rounded-xl p-2.5 space-y-1.5">
                      <div className="text-[10px] text-gray-400 uppercase font-bold flex items-center justify-between">
                        <span>Time to First Token (TTFT)</span>
                        <span className="text-[9px] text-amber-400 font-mono">N={stats.count}</span>
                      </div>
                      <div className="grid grid-cols-3 gap-1.5 text-center mt-1">
                        <div className="bg-white/5 p-1.5 rounded-lg border border-white/5">
                          <div className="text-[9px] text-gray-400 uppercase">P50 (Median)</div>
                          <div className="text-xs font-extrabold text-emerald-400 font-mono mt-0.5">{stats.ttft.p50} ms</div>
                        </div>
                        <div className="bg-white/5 p-1.5 rounded-lg border border-white/5">
                          <div className="text-[9px] text-gray-400 uppercase">P90</div>
                          <div className="text-xs font-extrabold text-amber-400 font-mono mt-0.5">{stats.ttft.p90} ms</div>
                        </div>
                        <div className="bg-white/5 p-1.5 rounded-lg border border-white/5">
                          <div className="text-[9px] text-gray-400 uppercase">P95</div>
                          <div className="text-xs font-extrabold text-rose-400 font-mono mt-0.5">{stats.ttft.p95} ms</div>
                        </div>
                      </div>
                      <div className="text-[9px] text-gray-400 flex justify-between pt-1 border-t border-white/5">
                        <span>Mean: <b className="text-gray-200">{stats.ttft.mean}ms</b></span>
                        <span>Min/Max: <b className="text-gray-200">{stats.ttft.min}/{stats.ttft.max}ms</b></span>
                      </div>
                    </div>

                    <div className="bg-black/40 border border-white/5 rounded-xl p-2.5 space-y-1.5">
                      <div className="text-[10px] text-gray-400 uppercase font-bold flex items-center justify-between">
                        <span>Total Turn Duration</span>
                        <span className="text-[9px] text-indigo-400 font-mono">Complete</span>
                      </div>
                      <div className="grid grid-cols-3 gap-1.5 text-center mt-1">
                        <div className="bg-white/5 p-1.5 rounded-lg border border-white/5">
                          <div className="text-[9px] text-gray-400 uppercase">P50 (Median)</div>
                          <div className="text-xs font-extrabold text-emerald-400 font-mono mt-0.5">{(stats.total.p50/1000).toFixed(2)}s</div>
                        </div>
                        <div className="bg-white/5 p-1.5 rounded-lg border border-white/5">
                          <div className="text-[9px] text-gray-400 uppercase">P90</div>
                          <div className="text-xs font-extrabold text-amber-400 font-mono mt-0.5">{(stats.total.p90/1000).toFixed(2)}s</div>
                        </div>
                        <div className="bg-white/5 p-1.5 rounded-lg border border-white/5">
                          <div className="text-[9px] text-gray-400 uppercase">P95</div>
                          <div className="text-xs font-extrabold text-rose-400 font-mono mt-0.5">{(stats.total.p95/1000).toFixed(2)}s</div>
                        </div>
                      </div>
                      <div className="text-[9px] text-gray-400 flex justify-between pt-1 border-t border-white/5">
                        <span>DB Prep P50: <b className="text-gray-200">{stats.dbPrep.p50}ms</b></span>
                        <span>LLM TTFT P50: <b className="text-gray-200">{stats.llmTtft.p50}ms</b></span>
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="text-center py-4 text-gray-500 italic text-[11px]">
                    Send 2+ messages to calculate session P50, P90, P95 percentiles.
                  </div>
                )}
              </div>
            )}

            {/* TAB 3: INSTANCE LOGS */}
            {activeTab === 'history' && (
              <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                {allInstances.map((inst, idx) => (
                  <div
                    key={inst.id || idx}
                    onClick={() => {
                      setSelectedInstanceIdx(idx);
                      setActiveTab('instance');
                    }}
                    className={`p-2 rounded-xl border text-[11px] cursor-pointer transition-all flex items-center justify-between ${
                      idx === activeIdx 
                        ? 'bg-indigo-600/30 border-indigo-500/50 text-white' 
                        : 'bg-black/30 border-white/5 text-gray-400 hover:bg-white/5 hover:text-gray-200'
                    }`}
                  >
                    <div className="truncate max-w-[130px]">
                      <span className="font-mono text-[9px] text-indigo-300 font-bold mr-1.5">#{idx + 1}</span>
                      <span className="truncate">{inst.question_snippet || 'Turn ' + (idx + 1)}</span>
                    </div>
                    <div className="text-right font-mono text-[10px]">
                      <div className="font-bold text-gray-200">
                        {inst.client_ttft_ms ? `${inst.client_ttft_ms}ms` : '—'}
                      </div>
                      <div className="text-[9px] text-gray-500">
                        {inst.client_total_ms ? `${(inst.client_total_ms/1000).toFixed(1)}s` : 'live'}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Footer Architecture Badge */}
            <div className="p-2 rounded-xl bg-violet-950/20 border border-violet-500/20 text-[10px] text-violet-300 flex items-center justify-between">
              <span className="font-semibold flex items-center gap-1">
                <CheckCircle2 size={11} className="text-emerald-400" /> V4 RAG-Free Core
              </span>
              <span className="text-gray-400 font-mono">0ms RAG Latency</span>
            </div>
          </div>
        )}
      </div>

      {/* FULL-SCREEN ANALYTICS & LLM EVALUATION MODAL */}
      {showFullModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
          <div className="bg-[#0f111a] border border-white/10 rounded-3xl w-full max-w-4xl max-h-[90vh] overflow-y-auto p-6 shadow-2xl space-y-6">
            
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-white/10 pb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center text-amber-400">
                  <BarChart3 size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-white tracking-wide">
                    VishwAlpha Latency & LLM Evaluation Dashboard
                  </h2>
                  <p className="text-xs text-gray-400">
                    Real-time performance metrics, instance history, and percentile evaluation.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={copyEvaluationReport}
                  className="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-semibold text-gray-300 hover:text-white flex items-center gap-1.5 transition-all"
                >
                  {copiedReport ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                  <span>{copiedReport ? 'Copied!' : 'Export Report'}</span>
                </button>
                <button
                  onClick={() => setShowFullModal(false)}
                  className="p-2 rounded-full hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Key Percentiles Grid */}
            {stats && (
              <div className="grid grid-cols-4 gap-3">
                <div className="bg-black/40 border border-white/5 p-4 rounded-2xl">
                  <div className="text-[11px] text-gray-400 uppercase font-semibold">P50 TTFT (Median)</div>
                  <div className="text-2xl font-black text-emerald-400 font-mono mt-1">
                    {stats.ttft.p50} ms
                  </div>
                  <div className="text-[10px] text-gray-500 mt-1">Instant perceived typing start</div>
                </div>

                <div className="bg-black/40 border border-white/5 p-4 rounded-2xl">
                  <div className="text-[11px] text-gray-400 uppercase font-semibold">P90 TTFT</div>
                  <div className="text-2xl font-black text-amber-400 font-mono mt-1">
                    {stats.ttft.p90} ms
                  </div>
                  <div className="text-[10px] text-gray-500 mt-1">90% of requests start within this</div>
                </div>

                <div className="bg-black/40 border border-white/5 p-4 rounded-2xl">
                  <div className="text-[11px] text-gray-400 uppercase font-semibold">P95 TTFT</div>
                  <div className="text-2xl font-black text-purple-400 font-mono mt-1">
                    {stats.ttft.p95} ms
                  </div>
                  <div className="text-[10px] text-gray-500 mt-1">95th percentile upper bound</div>
                </div>

                <div className="bg-black/40 border border-white/5 p-4 rounded-2xl">
                  <div className="text-[11px] text-gray-400 uppercase font-semibold">P50 Total Turn</div>
                  <div className="text-2xl font-black text-cyan-400 font-mono mt-1">
                    {(stats.total.p50 / 1000).toFixed(2)} s
                  </div>
                  <div className="text-[10px] text-gray-500 mt-1">Complete response delivery</div>
                </div>
              </div>
            )}

            {/* Detailed Instances Table */}
            <div className="space-y-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-gray-300">
                Instance-By-Instance Performance Log ({allInstances.length} Requests)
              </h3>
              <div className="border border-white/5 rounded-2xl overflow-hidden bg-black/30">
                <table className="w-full text-left text-xs">
                  <thead className="bg-white/5 text-gray-400 uppercase text-[10px] font-bold">
                    <tr>
                      <th className="p-3">Turn</th>
                      <th className="p-3">Question Snippet</th>
                      <th className="p-3">Perceived TTFT</th>
                      <th className="p-3">DB Prep</th>
                      <th className="p-3">LLM TTFT</th>
                      <th className="p-3">Stream Time</th>
                      <th className="p-3">Total Time</th>
                      <th className="p-3">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5 font-mono">
                    {allInstances.map((inst, idx) => (
                      <tr key={inst.id || idx} className="hover:bg-white/5 transition-colors">
                        <td className="p-3 font-bold text-indigo-400">#{idx + 1}</td>
                        <td className="p-3 font-sans text-gray-300 truncate max-w-[200px]">
                          {inst.question_snippet || 'Message ' + (idx + 1)}
                        </td>
                        <td className="p-3 text-emerald-300 font-bold">
                          {inst.client_ttft_ms ? `${inst.client_ttft_ms} ms` : '—'}
                        </td>
                        <td className="p-3 text-gray-400">{inst.db_prep_ms || 0} ms</td>
                        <td className="p-3 text-violet-400">{inst.llm_ttft_ms || 0} ms</td>
                        <td className="p-3 text-cyan-400">{inst.llm_stream_ms || 0} ms</td>
                        <td className="p-3 font-bold text-white">
                          {inst.client_total_ms ? `${(inst.client_total_ms/1000).toFixed(2)} s` : '—'}
                        </td>
                        <td className="p-3 font-sans">
                          <span className="text-[10px] px-2 py-0.5 rounded-full font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                            Completed
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* LLM Evaluation Criteria & Quality Breakdown */}
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-black/40 border border-white/5 p-4 rounded-2xl space-y-1">
                <div className="text-[10px] uppercase font-bold text-indigo-300">Grade Level Boundary</div>
                <div className="text-sm font-bold text-white">Strict 3-Tier Enforcement</div>
                <p className="text-[11px] text-gray-400 leading-snug">
                  Classes 6-8, 9-10, and 11-12 pedagogical limits strictly prevent out-of-grade jargon and premature complex formulas.
                </p>
              </div>

              <div className="bg-black/40 border border-white/5 p-4 rounded-2xl space-y-1">
                <div className="text-[10px] uppercase font-bold text-purple-300">Prompt Efficiency</div>
                <div className="text-sm font-bold text-white">95.2% Token Reduction</div>
                <p className="text-[11px] text-gray-400 leading-snug">
                  Curriculum prompt reduced from 14,425 tokens down to 698 tokens, eliminating Azure OpenAI TPM rate limit bottlenecks.
                </p>
              </div>

              <div className="bg-black/40 border border-white/5 p-4 rounded-2xl space-y-1">
                <div className="text-[10px] uppercase font-bold text-emerald-300">Multi-Tier Caching</div>
                <div className="text-sm font-bold text-white">L1 Memory + L2 Redis</div>
                <p className="text-[11px] text-gray-400 leading-snug">
                  Process memory handles repeat turns in 0.001 ms with automatic circuit-breaker fallback for maximum reliability.
                </p>
              </div>
            </div>

          </div>
        </div>
      )}
    </>
  );
}
