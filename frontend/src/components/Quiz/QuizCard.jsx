import React, { useState, useEffect } from 'react';
import { quizApi } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { useSession } from '../../context/SessionContext';
import {
  CheckCircle2, XCircle, ChevronRight, Trophy, BookOpen,
  Loader2, Lightbulb, Target, X
} from 'lucide-react';

/**
 * QuizCard — full interactive quiz UI rendered inline in chat.
 *
 * Props:
 *   topic          (string)  — topic this quiz covers
 *   subject        (string)  — subject
 *   source         (string)  — 'mid_concept' | 'yesterday' | 'manual'
 *   sessionId      (string)  — current session ID
 *   numQuestions   (number)  — default 7
 *   onClose        (fn)      — called when student dismisses/finishes
 */
export default function QuizCard({ topic, subject, source = 'manual', sessionId = '', numQuestions = 7, onClose }) {
  const { student } = useAuth();
  const { refreshProfile, refreshMemory } = useSession();

  const [phase, setPhase] = useState('loading');   // loading | quiz | review | results
  const [questions, setQuestions] = useState([]);
  const [attemptId, setAttemptId] = useState('');
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedOption, setSelectedOption] = useState(null);
  const [theoryAnswer, setTheoryAnswer] = useState('');
  const [feedback, setFeedback] = useState(null);   // {is_correct, explanation, correct_index, correct_answer}
  const [answers, setAnswers] = useState([]);        // per-question {is_correct}
  const [results, setResults] = useState(null);     // FinishQuizResponse
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [resolvedTopic, setResolvedTopic] = useState(topic || '');

  // Generate quiz on mount
  useEffect(() => {
    (async () => {
      try {
        const studentId = student?.user_id || student?.id || student?.student_id || '';
        const data = await quizApi.generate({
          student_id: studentId,
          subject: subject || 'Science',
          topic: topic || '',
          source: source || 'manual',
          session_id: sessionId || '',
          num_questions: numQuestions || 7,
        });
        setAttemptId(data.attempt_id);
        setQuestions(data.questions || []);
        if (data.topic) setResolvedTopic(data.topic);
        setPhase('quiz');
      } catch (e) {
        console.error('Quiz generation failed:', e);
        setError(e.response?.data?.detail || 'Failed to load quiz. Please try again.');
        setPhase('error');
      }
    })();
  }, []);

  const currentQ = questions[currentIndex];
  const isMCQ = currentQ?.q_type === 'mcq';
  const isLast = currentIndex === questions.length - 1;

  const handleSubmitAnswer = async () => {
    if (submitting) return;
    if (isMCQ && selectedOption === null) return;
    if (!isMCQ && !theoryAnswer.trim()) return;

    setSubmitting(true);
    try {
      const payload = {
        question_id: currentQ.id,
        student_answer: isMCQ ? String(selectedOption) : theoryAnswer,
        student_answer_index: isMCQ ? selectedOption : null,
      };
      const res = await quizApi.submitAnswer(payload);
      setFeedback(res);
      setAnswers(prev => [...prev, { is_correct: res.is_correct }]);
      setPhase('review');
    } catch (e) {
      setError('Failed to submit answer.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleNext = () => {
    setFeedback(null);
    setSelectedOption(null);
    setTheoryAnswer('');
    if (isLast) {
      handleFinish();
    } else {
      setCurrentIndex(i => i + 1);
      setPhase('quiz');
    }
  };

  const handleFinish = async () => {
    setPhase('loading');
    try {
      const res = await quizApi.finish(attemptId, sessionId);
      setResults(res);
      setPhase('results');
      refreshProfile();
      refreshMemory();
    } catch (e) {
      setError('Failed to compute results.');
      setPhase('error');
    }
  };

  const correctCount = answers.filter(a => a.is_correct).length;
  const progress = questions.length > 0 ? ((currentIndex + (phase === 'results' ? 1 : 0)) / questions.length) * 100 : 0;

  // ── Loading / Error ───────────────────────────────────────────────────────
  if (phase === 'loading') {
    return (
      <div className="my-4 p-6 rounded-2xl bg-gradient-to-br from-indigo-900/60 to-purple-900/60 border border-indigo-500/30 backdrop-blur-sm flex items-center gap-4">
        <Loader2 className="animate-spin text-indigo-400 shrink-0" size={28} />
        <div>
          <p className="text-white font-semibold">Generating your personalised quiz…</p>
          <p className="text-gray-400 text-sm mt-0.5">Tailoring questions to your cognitive profile</p>
        </div>
      </div>
    );
  }

  if (phase === 'error') {
    return (
      <div className="my-4 p-5 rounded-2xl bg-red-900/30 border border-red-500/30 text-red-300">
        <p className="font-semibold">⚠️ {error}</p>
        <button onClick={onClose} className="mt-3 text-sm underline opacity-70 hover:opacity-100">Dismiss</button>
      </div>
    );
  }

  // ── Results Screen ─────────────────────────────────────────────────────────
  if (phase === 'results' && results) {
    const passed = results.passed;
    const scorePercent = Math.round(results.score);

    return (
      <div className="my-4 rounded-2xl bg-gradient-to-br from-slate-900/90 to-indigo-950/90 border border-white/10 overflow-hidden backdrop-blur-sm">
        {/* Score header */}
        <div className={`p-6 text-center ${passed ? 'bg-gradient-to-r from-emerald-600/30 to-teal-600/30' : 'bg-gradient-to-r from-orange-600/20 to-red-600/20'}`}>
          <div className="flex justify-center mb-3">
            <div className={`w-20 h-20 rounded-full flex items-center justify-center text-4xl font-black border-4 ${passed ? 'border-emerald-400 text-emerald-300 bg-emerald-900/40' : 'border-orange-400 text-orange-300 bg-orange-900/40'}`}>
              {scorePercent}%
            </div>
          </div>
          <div className="flex items-center justify-center gap-2 mb-1">
            <Trophy className={passed ? 'text-yellow-400' : 'text-gray-400'} size={20} />
            <h3 className="text-xl font-bold text-white">{passed ? 'Great job! You passed!' : 'Keep practising!'}</h3>
          </div>
          <p className="text-gray-300 text-sm">{results.correct} of {results.total} questions correct</p>
        </div>

        {/* Progress bar */}
        <div className="h-2 bg-gray-800">
          <div
            className={`h-2 transition-all duration-1000 ${passed ? 'bg-gradient-to-r from-emerald-500 to-teal-400' : 'bg-gradient-to-r from-orange-500 to-red-400'}`}
            style={{ width: `${scorePercent}%` }}
          />
        </div>

        {/* Stats */}
        <div className="p-5 grid grid-cols-2 gap-3">
          <div className="bg-white/5 rounded-xl p-3 text-center">
            <p className="text-2xl font-bold text-emerald-400">{results.correct}</p>
            <p className="text-xs text-gray-400 mt-0.5">Correct</p>
          </div>
          <div className="bg-white/5 rounded-xl p-3 text-center">
            <p className="text-2xl font-bold text-red-400">{results.total - results.correct}</p>
            <p className="text-xs text-gray-400 mt-0.5">Incorrect</p>
          </div>
        </div>

        {/* AI Feedback */}
        {results.ai_feedback && (
          <div className="mx-5 mb-4 p-4 rounded-xl bg-indigo-500/10 border border-indigo-500/20">
            <div className="flex items-center gap-2 mb-2">
              <Lightbulb size={16} className="text-indigo-400" />
              <span className="text-xs font-bold text-indigo-300 uppercase tracking-wider">AI Feedback</span>
            </div>
            <p className="text-gray-300 text-sm leading-relaxed">{results.ai_feedback}</p>
          </div>
        )}

        {/* Done button */}
        <div className="px-5 pb-5">
          <button
            onClick={onClose}
            className="w-full py-3 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 text-white font-semibold hover:from-indigo-500 hover:to-purple-500 transition-all"
          >
            Continue Learning
          </button>
        </div>
      </div>
    );
  }

  // ── Active Quiz ────────────────────────────────────────────────────────────
  return (
    <div className="my-4 rounded-2xl bg-gradient-to-br from-slate-900/90 to-indigo-950/90 border border-white/10 overflow-hidden backdrop-blur-sm">
      {/* Header */}
      <div className="px-5 pt-5 pb-3 border-b border-white/5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Target size={16} className="text-indigo-400" />
            <span className="text-xs font-bold text-indigo-300 uppercase tracking-wider">Quiz · {subject}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400">Q{currentIndex + 1} / {questions.length}</span>
            {onClose && (
              <button
                onClick={onClose}
                className="p-1 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-colors ml-1"
                title="Close Quiz"
              >
                <X size={15} />
              </button>
            )}
          </div>
        </div>
        {/* Progress bar */}
        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-1.5 bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500"
            style={{ width: `${((currentIndex) / questions.length) * 100}%` }}
          />
        </div>
        <p className="text-gray-400 text-xs mt-2 truncate">📚 {resolvedTopic || topic || (subject + ' Review')}</p>
      </div>

      {/* Question */}
      <div className="p-5">
        <div className="flex items-start gap-2 mb-1">
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wide ${isMCQ ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30' : 'bg-purple-500/20 text-purple-300 border border-purple-500/30'}`}>
            {isMCQ ? 'MCQ' : 'Theory'}
          </span>
        </div>
        <p className="text-white font-medium text-[15px] leading-relaxed mt-2 mb-4">{currentQ?.question}</p>

        {/* MCQ Options */}
        {isMCQ && phase === 'quiz' && (
          <div className="space-y-2.5">
            {currentQ.options.map((opt, idx) => (
              <button
                key={idx}
                onClick={() => setSelectedOption(idx)}
                className={`w-full flex items-center gap-3 p-3.5 rounded-xl text-left text-sm transition-all border ${
                  selectedOption === idx
                    ? 'border-indigo-500 bg-indigo-500/20 text-white'
                    : 'border-white/10 bg-white/5 text-gray-300 hover:border-white/20 hover:bg-white/10'
                }`}
              >
                <span className={`w-7 h-7 shrink-0 rounded-lg flex items-center justify-center text-xs font-bold border ${
                  selectedOption === idx ? 'border-indigo-400 bg-indigo-500 text-white' : 'border-white/20 bg-white/10 text-gray-300'
                }`}>
                  {['A','B','C','D'][idx]}
                </span>
                {opt}
              </button>
            ))}
          </div>
        )}

        {/* MCQ Review (after submit) */}
        {isMCQ && phase === 'review' && feedback && (
          <div className="space-y-2.5">
            {currentQ.options.map((opt, idx) => {
              const isCorrect = idx === feedback.correct_index;
              const isSelected = idx === parseInt(answers[answers.length - 1]?.is_correct !== undefined ? String(selectedOption) : '-1');
              let style = 'border-white/10 bg-white/5 text-gray-400 opacity-50';
              if (isCorrect) style = 'border-emerald-500 bg-emerald-500/20 text-emerald-200';
              else if (idx === selectedOption && !feedback.is_correct) style = 'border-red-500 bg-red-500/20 text-red-200';

              return (
                <div key={idx} className={`flex items-center gap-3 p-3.5 rounded-xl text-sm border ${style}`}>
                  <span className="w-7 h-7 shrink-0 rounded-lg flex items-center justify-center text-xs font-bold border border-current/30 bg-current/10">
                    {['A','B','C','D'][idx]}
                  </span>
                  {opt}
                  {isCorrect && <CheckCircle2 size={16} className="ml-auto text-emerald-400 shrink-0" />}
                  {idx === selectedOption && !isCorrect && <XCircle size={16} className="ml-auto text-red-400 shrink-0" />}
                </div>
              );
            })}
          </div>
        )}

        {/* Theory textarea */}
        {!isMCQ && phase === 'quiz' && (
          <textarea
            value={theoryAnswer}
            onChange={e => setTheoryAnswer(e.target.value)}
            rows={4}
            placeholder="Write your answer here…"
            className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-gray-200 text-sm placeholder-gray-500 focus:outline-none focus:border-indigo-500/60 resize-none leading-relaxed"
          />
        )}

        {/* Theory review */}
        {!isMCQ && phase === 'review' && feedback && (
          <div className="space-y-3">
            <div className="p-3 rounded-xl bg-white/5 border border-white/10">
              <p className="text-xs text-gray-500 mb-1">Your answer:</p>
              <p className="text-gray-300 text-sm">{theoryAnswer || '(no answer)'}</p>
            </div>
            <div className="p-3 rounded-xl bg-emerald-900/20 border border-emerald-500/20">
              <p className="text-xs text-emerald-400 mb-1 font-semibold">Model Answer:</p>
              <p className="text-gray-200 text-sm">{feedback.correct_answer}</p>
            </div>
          </div>
        )}

        {/* Feedback banner */}
        {phase === 'review' && feedback && (
          <div className={`mt-4 p-4 rounded-xl flex items-start gap-3 ${feedback.is_correct ? 'bg-emerald-900/30 border border-emerald-500/30' : 'bg-orange-900/30 border border-orange-500/30'}`}>
            {feedback.is_correct
              ? <CheckCircle2 size={20} className="text-emerald-400 shrink-0 mt-0.5" />
              : <XCircle size={20} className="text-orange-400 shrink-0 mt-0.5" />
            }
            <div>
              <p className={`font-semibold text-sm ${feedback.is_correct ? 'text-emerald-300' : 'text-orange-300'}`}>
                {feedback.is_correct ? 'Correct! ✨' : 'Not quite — keep going!'}
              </p>
              {feedback.explanation && (
                <p className="text-gray-400 text-sm mt-1 leading-relaxed">{feedback.explanation}</p>
              )}
            </div>
          </div>
        )}

        {/* Running score */}
        {answers.length > 0 && (
          <div className="mt-3 flex items-center gap-2">
            <div className="flex gap-1">
              {answers.map((a, i) => (
                <div key={i} className={`w-2 h-2 rounded-full ${a.is_correct ? 'bg-emerald-400' : 'bg-red-400'}`} />
              ))}
              {Array.from({ length: questions.length - answers.length }).map((_, i) => (
                <div key={`e-${i}`} className="w-2 h-2 rounded-full bg-white/10" />
              ))}
            </div>
            <span className="text-xs text-gray-500">{correctCount}/{answers.length} correct</span>
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="px-5 pb-5 flex gap-3">
        {phase === 'quiz' && (
          <>
            <button
              onClick={onClose}
              className="px-4 py-2.5 rounded-xl text-sm text-gray-400 border border-white/10 hover:bg-white/5 transition-all"
            >
              Skip Quiz
            </button>
            <button
              onClick={handleSubmitAnswer}
              disabled={submitting || (isMCQ ? selectedOption === null : !theoryAnswer.trim())}
              className="flex-1 py-2.5 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 text-white text-sm font-semibold hover:from-indigo-500 hover:to-purple-500 transition-all disabled:opacity-40 disabled:grayscale flex items-center justify-center gap-2"
            >
              {submitting ? <Loader2 size={16} className="animate-spin" /> : null}
              Submit Answer
            </button>
          </>
        )}
        {phase === 'review' && (
          <button
            onClick={handleNext}
            className="flex-1 py-2.5 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 text-white text-sm font-semibold hover:from-indigo-500 hover:to-purple-500 transition-all flex items-center justify-center gap-2"
          >
            {isLast ? 'Finish Quiz 🎯' : 'Next Question'}
            <ChevronRight size={16} />
          </button>
        )}
      </div>
    </div>
  );
}
