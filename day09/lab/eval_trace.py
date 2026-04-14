"""
eval_trace.py — Sprint 2: Production-Level Trace Evaluation (Day 09)
=====================================================================
Multi-Agent Orchestration — Supervisor-Worker pipeline.

Sprint 2 Upgrades:
  ✓ Full retrieved docs (text, source, score, ranking)
  ✓ Full prompt sent to LLM (synthesis context)
  ✓ Per-step latency (supervisor → worker → synthesis)
  ✓ Routing accuracy metrics (actual vs expected route)
  ✓ Answer quality scoring (Faithfulness, Relevance, Completeness)
  ✓ Ground truth comparison
  ✓ Failure mode classification with root-cause layer
  ✓ CSV export for spreadsheet analysis
  ✓ Single vs Multi comparison with Day 08 data

Cách chạy:
  python eval_trace.py                  # Chạy 15 test questions
  python eval_trace.py --grading        # Chạy grading questions (sau 17:00)
  python eval_trace.py --analyze        # Phân tích trace đã có
  python eval_trace.py --compare        # So sánh single vs multi
  python eval_trace.py --detail         # Show chi tiết từng câu (full doc, prompt)

Outputs:
    artifacts/traces/          — trace JSON cho từng câu
    artifacts/grading_run.jsonl — log grading (JSONL format)
    artifacts/eval_report.json  — báo cáo tổng kết
    artifacts/eval_summary.csv  — CSV cho phân tích

Author: Quality & Trace Analyst (M5) — Sprint 2
"""

import csv
import json
import os
import re
import sys
import time
import argparse
from dotenv import load_dotenv

load_dotenv()  # Load .env file (OPENAI_API_KEY, etc.)

from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(__file__))
from graph import run_graph, save_trace


# =============================================================================
# CONFIG
# =============================================================================

ARTIFACTS_DIR = "artifacts"
TRACES_DIR = "artifacts/traces"
TEST_FILE = "data/test_questions.json"
GRADING_FILE = "data/grading_questions.json"


# =============================================================================
# SCORING FUNCTIONS (rule-based — Day 09)
# =============================================================================


def score_faithfulness(answer: str, chunks: List[Dict]) -> Dict[str, Any]:
    """Faithfulness: answer bám context không?"""
    if not chunks or not answer:
        is_abstain = any(kw in answer.lower() for kw in ["không đủ", "không có trong", "khong du"]) if answer else True
        return {"score": 5 if is_abstain else 1, "notes": "No context / abstain check"}

    context_text = " ".join(c.get("text", "").lower() for c in chunks)
    answer_words = [w for w in answer.lower().split() if len(w) > 4]
    if not answer_words:
        return {"score": 3, "notes": "Short answer"}

    matches = sum(1 for w in answer_words if w in context_text)
    ratio = matches / len(answer_words)

    score = 5 if ratio > 0.7 else (4 if ratio > 0.5 else (3 if ratio > 0.3 else 1))
    return {"score": score, "grounding_ratio": round(ratio, 3), "notes": f"{matches}/{len(answer_words)} words grounded"}


def score_relevance(query: str, answer: str) -> Dict[str, Any]:
    """Answer Relevance: trả lời đúng câu hỏi không?"""
    if any(kw in answer.lower() for kw in ["không đủ", "không có trong", "khong du"]):
        return {"score": 5, "notes": "Valid abstain"}

    keywords = [w for w in query.lower().replace("?", "").split() if len(w) > 3]
    if not keywords:
        return {"score": 3, "notes": "No keywords to match"}

    matches = sum(1 for k in keywords if k in answer.lower())
    ratio = matches / len(keywords)

    score = 5 if ratio > 0.5 else (3 if ratio > 0.2 else 1)
    return {"score": score, "overlap": round(ratio, 3), "notes": f"{matches}/{len(keywords)} query keywords in answer"}


def score_completeness(answer: str, expected_answer: str) -> Dict[str, Any]:
    """Completeness: so với expected answer."""
    if not expected_answer:
        return {"score": None, "notes": "No expected answer"}

    expected_set = set(expected_answer.lower().replace(".", "").split())
    answer_set = set(answer.lower().replace(".", "").split())
    if not expected_set:
        return {"score": None, "notes": "Empty expected"}

    coverage = len(expected_set & answer_set) / len(expected_set)
    score = 5 if coverage > 0.5 else (3 if coverage > 0.2 else 1)
    return {"score": score, "coverage": round(coverage, 3), "notes": f"Coverage: {coverage:.1%}"}


def score_routing(actual_route: str, expected_route: str) -> Dict[str, Any]:
    """Routing accuracy: đúng worker chưa?"""
    if not expected_route:
        return {"correct": None, "notes": "No expected route"}
    correct = actual_route == expected_route
    return {"correct": correct, "actual": actual_route, "expected": expected_route}


def classify_failure(
    answer: str,
    chunks: List[Dict],
    faith: Dict,
    relev: Dict,
    compl: Dict,
    expected_answer: str,
    actual_route: str,
    expected_route: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Classify failure mode + root-cause layer.
    Layers: supervisor / retrieval / generation / system
    """
    is_abstain = any(kw in answer.lower() for kw in ["không đủ", "không có trong", "khong du"]) if answer else False
    f_s = faith.get("score") if faith else None
    c_s = compl.get("score") if compl else None
    r_s = relev.get("score") if relev else None

    # Wrong routing
    if expected_route and actual_route != expected_route:
        return "wrong_route", "supervisor"

    # False abstain
    if is_abstain and chunks and expected_answer:
        if "không" not in expected_answer.lower()[:30]:
            return "false_abstain", "generation"

    # Hallucination
    if f_s and f_s <= 2 and not is_abstain:
        return "hallucination", "generation"

    # Incomplete
    if c_s and c_s <= 2:
        return "incomplete", "generation"

    # Irrelevant
    if r_s and r_s <= 2:
        return "irrelevant", "generation"

    # Retrieval miss (no chunks)
    if not chunks and expected_answer and "không" not in expected_answer.lower()[:30]:
        return "retrieval_miss", "retrieval"

    return None, None


def compare_ground_truth(answer: str, expected: str, actual_sources: List[str], expected_sources: List[str]) -> Dict:
    """Compare answer with ground truth."""
    if not expected:
        return {"match_ratio": None, "sources_match": None, "key_facts_found": [], "key_facts_missing": []}

    answer_lower = answer.lower() if answer else ""
    expected_lower = expected.lower()

    # Extract key facts
    numbers = re.findall(r'\d+\s*(?:phút|giờ|ngày|lần|%|tháng|tuần)', expected_lower)
    phrases = re.findall(r'[A-Za-zÀ-ỹ]{3,}(?:\s+[A-Za-zÀ-ỹ]{3,}){1,2}', expected_lower)
    key_facts = list(set(numbers + phrases[:5]))

    found = [f for f in key_facts if f in answer_lower]
    missing = [f for f in key_facts if f not in answer_lower]

    # Source match
    exp_clean = {s.replace(".txt", "").lower() for s in expected_sources}
    act_clean = {s.replace(".txt", "").lower() for s in actual_sources if s}
    src_match = exp_clean.issubset(act_clean) if exp_clean else None

    return {
        "match_ratio": round(len(found) / len(key_facts), 3) if key_facts else None,
        "sources_match": src_match,
        "key_facts_found": found,
        "key_facts_missing": missing,
    }


# =============================================================================
# 1. ENHANCED RUN — Full trace with scoring
# =============================================================================


def run_test_questions(
    questions_file: str = TEST_FILE,
    verbose: bool = True,
    detail: bool = False,
) -> list:
    """
    Chạy pipeline với danh sách câu hỏi, ghi trace + scoring chi tiết.

    Sprint 2: Mỗi trace bao gồm:
    - Full retrieved docs (text, source, score)
    - Ranking order
    - Full prompt gửi cho LLM (từ synthesis)
    - Answer + ground truth comparison
    - Per-step latency
    - Failure mode classification
    """
    with open(questions_file, encoding="utf-8") as f:
        questions = json.load(f)

    print(f"\n{'='*70}")
    print(f"🔬 EVAL TRACE v2 — {len(questions)} questions")
    print(f"{'='*70}")

    results = []
    for i, q in enumerate(questions, 1):
        question_text = q["question"]
        q_id = q.get("id", f"q{i:02d}")
        expected_answer = q.get("expected_answer", "")
        expected_sources = q.get("expected_sources", [])
        expected_route = q.get("expected_route", "")
        difficulty = q.get("difficulty", "unknown")
        category = q.get("category", "unknown")

        if verbose:
            print(f"\n{'─'*70}")
            print(f"🔍 [{q_id}] {question_text}")

        try:
            # Run pipeline
            start = time.time()
            result = run_graph(question_text)
            total_ms = int((time.time() - start) * 1000)

            # Extract fields
            answer = result.get("final_answer", "")
            chunks = result.get("retrieved_chunks", [])
            sources = result.get("retrieved_sources", [])
            route = result.get("supervisor_route", "")
            route_reason = result.get("route_reason", "")
            workers = result.get("workers_called", [])
            mcp_tools = result.get("mcp_tools_used", [])
            confidence = result.get("confidence", 0.0)
            hitl = result.get("hitl_triggered", False)
            history = result.get("history", [])
            worker_io = result.get("worker_io_logs", [])

            # --- SCORING ---
            faith = score_faithfulness(answer, chunks)
            relev = score_relevance(question_text, answer)
            compl = score_completeness(answer, expected_answer)
            routing = score_routing(route, expected_route)
            fm, fl = classify_failure(answer, chunks, faith, relev, compl, expected_answer, route, expected_route)
            comparison = compare_ground_truth(answer, expected_answer, sources, expected_sources)

            # Overall score
            valid = [s for s in [faith.get("score"), relev.get("score"), compl.get("score")] if s is not None]
            avg_score = round(sum(valid) / len(valid), 2) if valid else 0
            passed = avg_score >= 3.5

            # Save individual trace
            trace_file = save_trace(result, TRACES_DIR)

            # Build enhanced record
            record = {
                "id": q_id,
                "question": question_text,
                "difficulty": difficulty,
                "category": category,
                "expected_answer": expected_answer,
                "expected_sources": expected_sources,
                "expected_route": expected_route,
                # --- Pipeline output ---
                "answer": answer,
                "supervisor_route": route,
                "route_reason": route_reason,
                "workers_called": workers,
                "mcp_tools_used": [t.get("tool", str(t)) if isinstance(t, dict) else str(t) for t in mcp_tools],
                "confidence": confidence,
                "hitl_triggered": hitl,
                # --- Retrieved docs (FULL) ---
                "retrieved_chunks": [
                    {
                        "rank": rank,
                        "text": c.get("text", ""),
                        "source": c.get("source", "unknown"),
                        "score": round(c.get("score", 0), 4),
                        "metadata": c.get("metadata", {}),
                    }
                    for rank, c in enumerate(chunks, 1)
                ],
                "retrieved_sources": sources,
                # --- Scoring ---
                "scoring": {
                    "faithfulness": faith,
                    "relevance": relev,
                    "completeness": compl,
                    "routing": routing,
                    "avg_score": avg_score,
                    "pass": passed,
                    "failure_mode": fm,
                    "failure_layer": fl,
                },
                "comparison": comparison,
                # --- Meta ---
                "latency_ms": total_ms,
                "history": history,
                "worker_io_logs": worker_io,
                "trace_file": trace_file,
                "timestamp": datetime.now().isoformat(),
            }

            results.append(record)

            # --- VERBOSE OUTPUT ---
            if verbose:
                route_ok = "✅" if routing.get("correct", True) else "❌"
                print(f"   ⚙️  Route: {route} {route_ok} | Workers: {workers}")
                print(f"   📄 Retrieved: {len(chunks)} chunks | Sources: {sources}")
                if detail and chunks:
                    for c in chunks:
                        print(f"      [{c.get('score',0):.3f}] {c.get('source','?')}: {c.get('text','')[:80]}...")
                print(f"   💬 Answer: {answer[:120]}...")
                print(f"   📊 F={faith.get('score','?')} R={relev.get('score','?')} C={compl.get('score','?')} | avg={avg_score:.1f} | conf={confidence:.2f}")
                if fm:
                    print(f"   ⚠️  Failure: {fm} (layer: {fl})")
                status = "✅ PASS" if passed else "❌ FAIL"
                print(f"   {status} | {total_ms}ms")

        except Exception as e:
            if verbose:
                print(f"   ❌ ERROR: {e}")
            results.append({
                "id": q_id,
                "question": question_text,
                "error": str(e),
                "answer": f"PIPELINE_ERROR: {e}",
                "scoring": {"failure_mode": "pipeline_error", "failure_layer": "system"},
                "latency_ms": 0,
                "timestamp": datetime.now().isoformat(),
            })

    # --- OUTPUT ---
    _print_results_table(results)
    _save_eval_csv(results)
    _save_eval_report(results)

    return results


# =============================================================================
# 2. GRADING QUESTIONS
# =============================================================================


def run_grading_questions(questions_file: str = GRADING_FILE) -> str:
    """Chạy grading questions và lưu JSONL log."""
    if not os.path.exists(questions_file):
        print(f"❌ {questions_file} chưa có (public lúc 17:00).")
        return ""

    with open(questions_file, encoding="utf-8") as f:
        questions = json.load(f)

    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    output_file = f"{ARTIFACTS_DIR}/grading_run.jsonl"

    print(f"\n🎯 GRADING — {len(questions)} câu → {output_file}")
    print("=" * 70)

    with open(output_file, "w", encoding="utf-8") as out:
        for i, q in enumerate(questions, 1):
            q_id = q.get("id", f"gq{i:02d}")
            question_text = q["question"]
            print(f"[{i:02d}/{len(questions)}] {q_id}: {question_text[:65]}...")

            try:
                result = run_graph(question_text)
                record = {
                    "id": q_id,
                    "question": question_text,
                    "answer": result.get("final_answer", "PIPELINE_ERROR: no answer"),
                    "sources": result.get("retrieved_sources", []),
                    "supervisor_route": result.get("supervisor_route", ""),
                    "route_reason": result.get("route_reason", ""),
                    "workers_called": result.get("workers_called", []),
                    "mcp_tools_used": [t.get("tool", str(t)) if isinstance(t, dict) else str(t) for t in result.get("mcp_tools_used", [])],
                    "confidence": result.get("confidence", 0.0),
                    "hitl_triggered": result.get("hitl_triggered", False),
                    "latency_ms": result.get("latency_ms"),
                    "timestamp": datetime.now().isoformat(),
                }
                print(f"  ✓ route={record['supervisor_route']}, conf={record['confidence']:.2f}, {record['latency_ms']}ms")
            except Exception as e:
                record = {
                    "id": q_id,
                    "question": question_text,
                    "answer": f"PIPELINE_ERROR: {e}",
                    "sources": [],
                    "supervisor_route": "error",
                    "route_reason": str(e),
                    "workers_called": [],
                    "mcp_tools_used": [],
                    "confidence": 0.0,
                    "hitl_triggered": False,
                    "latency_ms": None,
                    "timestamp": datetime.now().isoformat(),
                }
                print(f"  ✗ ERROR: {e}")

            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\n✅ Grading log → {output_file}")
    return output_file


# =============================================================================
# 3. ANALYZE TRACES
# =============================================================================


def analyze_traces(traces_dir: str = TRACES_DIR) -> dict:
    """Đọc trace files và tính metrics tổng hợp."""
    if not os.path.exists(traces_dir):
        print(f"⚠️  {traces_dir} không tồn tại.")
        return {}

    trace_files = [f for f in os.listdir(traces_dir) if f.endswith(".json")]
    if not trace_files:
        print(f"⚠️  Không có trace files.")
        return {}

    traces = []
    for fname in trace_files:
        with open(os.path.join(traces_dir, fname), encoding="utf-8") as f:
            traces.append(json.load(f))

    routing_counts = {}
    confidences = []
    latencies = []
    mcp_calls = 0
    hitl_triggers = 0
    source_counts = {}

    for t in traces:
        route = t.get("supervisor_route", "unknown")
        routing_counts[route] = routing_counts.get(route, 0) + 1

        conf = t.get("confidence", 0)
        if conf:
            confidences.append(conf)

        lat = t.get("latency_ms")
        if lat:
            latencies.append(lat)

        if t.get("mcp_tools_used"):
            mcp_calls += 1

        if t.get("hitl_triggered"):
            hitl_triggers += 1

        for src in t.get("retrieved_sources", []):
            source_counts[src] = source_counts.get(src, 0) + 1

    total = len(traces)
    metrics = {
        "total_traces": total,
        "routing_distribution": {k: f"{v}/{total} ({100*v//total}%)" for k, v in routing_counts.items()},
        "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0,
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "min_latency_ms": min(latencies) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
        "mcp_usage_rate": f"{mcp_calls}/{total} ({100*mcp_calls//total if total else 0}%)",
        "hitl_rate": f"{hitl_triggers}/{total} ({100*hitl_triggers//total if total else 0}%)",
        "top_sources": sorted(source_counts.items(), key=lambda x: -x[1])[:5],
    }

    return metrics


# =============================================================================
# 4. COMPARE SINGLE vs MULTI
# =============================================================================


def compare_single_vs_multi(
    multi_traces_dir: str = TRACES_DIR,
    day08_results_file: Optional[str] = None,
) -> dict:
    """So sánh Day 08 (single agent) vs Day 09 (multi-agent)."""
    multi_metrics = analyze_traces(multi_traces_dir)

    day08_baseline = {
        "total_questions": 10,
        "avg_faithfulness": 4.40,
        "avg_relevance": 5.00,
        "avg_context_recall": 5.00,
        "avg_completeness": 3.40,
        "avg_latency_ms": "~2000",
        "false_abstain_count": 2,
        "retrieval_mode": "dense",
        "notes": "Day 08 baseline results (from scorecard)",
    }

    if day08_results_file and os.path.exists(day08_results_file):
        with open(day08_results_file, encoding="utf-8") as f:
            day08_baseline = json.load(f)

    comparison = {
        "generated_at": datetime.now().isoformat(),
        "day08_single_agent": day08_baseline,
        "day09_multi_agent": multi_metrics,
        "analysis": {
            "routing": "Day 09: supervisor routes tasks to specialized workers. Day 08: single pipeline, no routing.",
            "debuggability": "Day 09: per-worker IO logs + route_reason → trace each decision. Day 08: monolithic, harder to isolate failures.",
            "mcp_tools": "Day 09: extensible via MCP server (policy checking, exception detection). Day 08: hard-coded logic.",
            "scalability": "Day 09: add new workers without modifying core. Day 08: must modify rag_answer.py.",
            "latency": f"Day 09 avg: {multi_metrics.get('avg_latency_ms', '?')}ms (multi-step overhead). Day 08: ~2000ms (single pipeline).",
            "accuracy": "Requires grading run comparison — pending grading_questions.json.",
        },
    }

    return comparison


# =============================================================================
# OUTPUT FUNCTIONS
# =============================================================================


def _print_results_table(results: list) -> None:
    """Rich console table."""
    print(f"\n{'='*90}")
    print(f"📊 RESULTS TABLE ({len(results)} queries)")
    print(f"{'='*90}")

    header = (
        f"{'ID':<5} {'Cat':<12} {'Diff':<5} "
        f"{'Route':<18} {'RteOK':>5} "
        f"{'F':>2} {'R':>2} {'C':>2} {'Avg':>4} {'Pass':>4} "
        f"{'Conf':>5} {'Failure':<16} {'ms':>5}"
    )
    print(header)
    print("─" * 90)

    pass_count = 0
    route_correct = 0
    route_total = 0

    for r in results:
        qid = r.get("id", "?")
        cat = r.get("category", "?")[:10]
        diff = r.get("difficulty", "?")[:4]
        sc = r.get("scoring", {})

        route = r.get("supervisor_route", "?")[:16]
        rte_ok = sc.get("routing", {}).get("correct")
        rte_str = "✅" if rte_ok else ("❌" if rte_ok is False else "—")
        if rte_ok is not None:
            route_total += 1
            if rte_ok:
                route_correct += 1

        f_s = sc.get("faithfulness", {}).get("score", "?")
        r_s = sc.get("relevance", {}).get("score", "?")
        c_s = sc.get("completeness", {}).get("score", "?")
        avg = sc.get("avg_score", 0)
        passed = "✅" if sc.get("pass") else "❌"
        if sc.get("pass"):
            pass_count += 1

        conf = r.get("confidence", 0)
        fm = (sc.get("failure_mode") or "—")[:14]
        lat = r.get("latency_ms", 0) or 0

        print(
            f"{qid:<5} {cat:<12} {diff:<5} "
            f"{route:<18} {rte_str:>5} "
            f"{str(f_s):>2} {str(r_s):>2} {str(c_s):>2} {avg:>4.1f} {passed:>4} "
            f"{conf:>5.2f} {fm:<16} {lat:>4}ms"
        )

    # Summary
    print("─" * 90)
    total = len(results)
    print(f"Pass: {pass_count}/{total} | Route accuracy: {route_correct}/{route_total}")

    # Failure distribution
    failures = [r.get("scoring", {}).get("failure_mode") for r in results if r.get("scoring", {}).get("failure_mode")]
    if failures:
        print(f"⚠️  Failures: {Counter(failures).most_common()}")

    latencies = [r.get("latency_ms", 0) for r in results if r.get("latency_ms")]
    if latencies:
        print(f"⏱️  Latency: avg={sum(latencies)//len(latencies)}ms | min={min(latencies)}ms | max={max(latencies)}ms")


def _save_eval_csv(results: list) -> str:
    """Export CSV cho spreadsheet analysis."""
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    filepath = f"{ARTIFACTS_DIR}/eval_summary.csv"

    headers = [
        "id", "category", "difficulty", "question",
        "answer", "expected_answer",
        "route", "expected_route", "route_correct",
        "workers_called", "mcp_tools",
        "chunks_count", "top1_source", "top1_score",
        "faithfulness", "relevance", "completeness", "avg_score", "pass",
        "failure_mode", "failure_layer",
        "confidence", "hitl",
        "sources_match", "facts_found", "facts_missing",
        "latency_ms",
    ]

    rows = []
    for r in results:
        sc = r.get("scoring", {})
        comp = r.get("comparison", {})
        chunks = r.get("retrieved_chunks", [])

        rows.append({
            "id": r.get("id", ""),
            "category": r.get("category", ""),
            "difficulty": r.get("difficulty", ""),
            "question": r.get("question", "")[:200],
            "answer": r.get("answer", "")[:300],
            "expected_answer": r.get("expected_answer", "")[:300],
            "route": r.get("supervisor_route", ""),
            "expected_route": r.get("expected_route", ""),
            "route_correct": sc.get("routing", {}).get("correct"),
            "workers_called": ",".join(r.get("workers_called", [])),
            "mcp_tools": ",".join(r.get("mcp_tools_used", [])),
            "chunks_count": len(chunks),
            "top1_source": chunks[0]["source"] if chunks else "",
            "top1_score": chunks[0]["score"] if chunks else "",
            "faithfulness": sc.get("faithfulness", {}).get("score"),
            "relevance": sc.get("relevance", {}).get("score"),
            "completeness": sc.get("completeness", {}).get("score"),
            "avg_score": sc.get("avg_score"),
            "pass": sc.get("pass"),
            "failure_mode": sc.get("failure_mode", ""),
            "failure_layer": sc.get("failure_layer", ""),
            "confidence": r.get("confidence", 0),
            "hitl": r.get("hitl_triggered", False),
            "sources_match": comp.get("sources_match"),
            "facts_found": len(comp.get("key_facts_found", [])),
            "facts_missing": len(comp.get("key_facts_missing", [])),
            "latency_ms": r.get("latency_ms", 0),
        })

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    print(f"📊 CSV → {filepath}")
    return filepath


def _save_eval_report(results: list) -> str:
    """Save full eval report JSON."""
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    filepath = f"{ARTIFACTS_DIR}/eval_report.json"

    # Aggregate metrics
    metrics = analyze_traces()

    report = {
        "generated_at": datetime.now().isoformat(),
        "sprint": 2,
        "total_questions": len(results),
        "pass_count": sum(1 for r in results if r.get("scoring", {}).get("pass")),
        "trace_metrics": metrics,
        "failure_modes": dict(Counter(
            r.get("scoring", {}).get("failure_mode")
            for r in results if r.get("scoring", {}).get("failure_mode")
        )),
        "results": results,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"📄 Report → {filepath}")
    return filepath


def print_metrics(metrics: dict):
    """Print metrics đẹp."""
    if not metrics:
        return
    print("\n📊 Trace Analysis:")
    for k, v in metrics.items():
        if isinstance(v, list):
            print(f"  {k}:")
            for item in v:
                print(f"    • {item}")
        elif isinstance(v, dict):
            print(f"  {k}:")
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")
        else:
            print(f"  {k}: {v}")


# =============================================================================
# MAIN
# =============================================================================


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Day 09 — Eval Trace v2 (M5 Sprint 2)")
    parser.add_argument("--grading", action="store_true", help="Run grading questions")
    parser.add_argument("--analyze", action="store_true", help="Analyze existing traces")
    parser.add_argument("--compare", action="store_true", help="Compare single vs multi")
    parser.add_argument("--detail", action="store_true", help="Show full chunk text per query")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-query output")
    parser.add_argument("--test-file", default=TEST_FILE, help="Test questions file")
    args = parser.parse_args()

    print("=" * 70)
    print("🔬 Day 09 — Eval Trace v2 (M5 Sprint 2)")
    print("=" * 70)

    if args.grading:
        log_file = run_grading_questions()
        if log_file:
            print(f"\n✅ Grading log: {log_file}")
            print("   Nộp file này trước 18:00!")

    elif args.analyze:
        metrics = analyze_traces()
        print_metrics(metrics)

    elif args.compare:
        comparison = compare_single_vs_multi()
        report_file = f"{ARTIFACTS_DIR}/eval_report.json"
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(comparison, f, ensure_ascii=False, indent=2)
        print(f"\n📊 Comparison → {report_file}")
        print("\n=== Day 08 vs Day 09 ===")
        for k, v in comparison.get("analysis", {}).items():
            print(f"  {k}: {v}")

    else:
        results = run_test_questions(
            args.test_file,
            verbose=not args.quiet,
            detail=args.detail,
        )

        print(f"\n{'='*70}")
        print("✅ Eval trace v2 complete!")
        print(f"📁 Traces: {TRACES_DIR}/")
        print(f"📊 CSV: {ARTIFACTS_DIR}/eval_summary.csv")
        print(f"📄 Report: {ARTIFACTS_DIR}/eval_report.json")
        print(f"{'='*70}")
