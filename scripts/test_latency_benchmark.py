import asyncio
import json
import time
import sys
import os
sys.path.insert(0, os.path.abspath("."))
import numpy as np

from app.data.database import managed_session
from app.data.models.platform import User
from app.data.models.chat import Conversation
from app.services.chat_orchestrator import chat_stream
from app.schemas.chat import ChatRequest

BENCHMARK_PROMPTS = [
    ("What is an acid?", "Science", 9),
    ("Can you briefly explain what photosynthesis is?", "Science", 10),
    ("What is refraction of light?", "Science", 10),
    ("Explain the difference between a metal and a non-metal.", "Science", 9),
    ("What happens during a neutralisation reaction?", "Science", 10),
]

class MockUser:
    def __init__(self, uid, class_num):
        self.id = uid
        self.class_num = class_num
        self.profile = None

async def run_benchmark():
    with managed_session() as db:
        u = db.query(User).first()
        conv = db.query(Conversation).filter(Conversation.user_id == u.id).first()
        uid = str(u.id)
        cid = str(conv.id) if conv else None

    print(f"=== Starting VishwAlpha V4 Real Latency & LLM Evaluation Benchmark ===")
    print(f"User ID: {uid} | Target Conversation: {cid}\n")

    results = []

    for idx, (question, subject, class_num) in enumerate(BENCHMARK_PROMPTS, 1):
        print(f"--- Instance {idx}/{len(BENCHMARK_PROMPTS)}: Class {class_num} '{question}' ---")
        user = MockUser(uid, class_num)
        req = ChatRequest(
            question=question,
            subject=subject,
            conversation_id=cid,
        )

        t_start = time.time()
        first_token_time = None
        turn_timings = {}
        token_count = 0
        answer_parts = []

        try:
            async for chunk in chat_stream(req, user):
                if chunk.startswith("data: "):
                    data_str = chunk[6:].strip()
                    if not data_str:
                        continue
                    try:
                        parsed = json.loads(data_str)
                        if parsed.get("type") == "token":
                            if first_token_time is None:
                                first_token_time = time.time()
                            token_count += 1
                            answer_parts.append(parsed.get("content", ""))
                        elif parsed.get("type") == "latency_update":
                            pass
                        elif parsed.get("type") == "done":
                            turn_timings = parsed.get("timings", {})
                    except Exception:
                        pass
        except Exception as e:
            print(f"Instance {idx} error: {e}")
            continue

        t_end = time.time()
        client_ttft_ms = int((first_token_time - t_start) * 1000) if first_token_time else turn_timings.get("total_ttft_ms", 0)
        client_total_ms = int((t_end - t_start) * 1000)
        tokens_per_sec = round(token_count / max(0.1, (t_end - (first_token_time or t_start))), 1)

        result = {
            "instance": idx,
            "question": question,
            "class_num": class_num,
            "tokens": token_count,
            "tokens_per_sec": tokens_per_sec,
            "client_ttft_ms": client_ttft_ms,
            "client_total_ms": client_total_ms,
            "db_prep_ms": turn_timings.get("db_prep_ms", 0),
            "syllabus_ms": turn_timings.get("syllabus_ms", 0),
            "topic_match_ms": turn_timings.get("topic_match_ms", 0),
            "save_msg_ms": turn_timings.get("save_msg_ms", 0),
            "llm_ttft_ms": turn_timings.get("llm_ttft_ms", 0),
            "llm_stream_ms": turn_timings.get("llm_stream_ms", 0),
            "total_turn_ms": turn_timings.get("total_turn_ms", 0),
        }
        results.append(result)

        print(f"  ✓ Perceived TTFT: {client_ttft_ms} ms (DB: {result['db_prep_ms']}ms, LLM TTFT: {result['llm_ttft_ms']}ms)")
        print(f"  ✓ Total Response: {client_total_ms} ms ({token_count} tokens @ {tokens_per_sec} tok/s)\n")

        # Brief 1s pacing between requests
        await asyncio.sleep(1.0)

    # Calculate percentiles
    ttfts = [r["client_ttft_ms"] for r in results]
    totals = [r["client_total_ms"] for r in results]
    db_preps = [r["db_prep_ms"] for r in results]
    llm_ttfts = [r["llm_ttft_ms"] for r in results]
    speeds = [r["tokens_per_sec"] for r in results]

    print("\n" + "="*60)
    print("                 BENCHMARK SUMMARY & EVALUATION")
    print("="*60)
    print(f"Instances Evaluated: {len(results)}")
    print(f"\n--- TIME TO FIRST TOKEN (TTFT) ---")
    print(f"  • P50 (Median) : {np.percentile(ttfts, 50):.1f} ms")
    print(f"  • P90          : {np.percentile(ttfts, 90):.1f} ms")
    print(f"  • P95          : {np.percentile(ttfts, 95):.1f} ms")
    print(f"  • Mean         : {np.mean(ttfts):.1f} ms")
    print(f"  • Min / Max    : {np.min(ttfts)} ms / {np.max(ttfts)} ms")

    print(f"\n--- TOTAL TURN DURATION ---")
    print(f"  • P50 (Median) : {np.percentile(totals, 50):.1f} ms")
    print(f"  • P90          : {np.percentile(totals, 90):.1f} ms")
    print(f"  • P95          : {np.percentile(totals, 95):.1f} ms")
    print(f"  • Mean         : {np.mean(totals):.1f} ms")

    print(f"\n--- DB PREPARATION & CONTEXT FETCH ---")
    print(f"  • P50 (Median) : {np.percentile(db_preps, 50):.1f} ms")
    print(f"  • P90          : {np.percentile(db_preps, 90):.1f} ms")

    print(f"\n--- GENERATION SPEED & THROUGHPUT ---")
    print(f"  • Average Speed: {np.mean(speeds):.1f} tokens/second")
    print("="*60)

    # Dump raw JSON for report generation
    with open("scripts/benchmark_results.json", "w") as f:
        json.dump({
            "instances": results,
            "metrics": {
                "ttft_p50": float(np.percentile(ttfts, 50)),
                "ttft_p90": float(np.percentile(ttfts, 90)),
                "ttft_p95": float(np.percentile(ttfts, 95)),
                "ttft_mean": float(np.mean(ttfts)),
                "total_p50": float(np.percentile(totals, 50)),
                "total_p90": float(np.percentile(totals, 90)),
                "total_p95": float(np.percentile(totals, 95)),
                "total_mean": float(np.mean(totals)),
                "db_prep_p50": float(np.percentile(db_preps, 50)),
                "db_prep_p90": float(np.percentile(db_preps, 90)),
                "avg_speed_tok_s": float(np.mean(speeds)),
            }
        }, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
