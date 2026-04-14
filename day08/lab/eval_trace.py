"""
eval_trace.py — Quality & Trace Analyst Module (M5)
=====================================================
Hệ thống tracing & evaluation cho RAG pipeline.

Mục tiêu:
  - Log chi tiết mỗi bước: retrieve → generate → evaluate
  - Ghi lại: input query, retrieved chunks, scores, answer, latency
  - Hỗ trợ debug: trace failure mode, so sánh A/B
  - Output: structured JSON traces + markdown summary

Cách chạy:
  python eval_trace.py                          # Chạy batch test 10 câu (dense)
  python eval_trace.py --mode hybrid            # Chạy batch test (hybrid)
  python eval_trace.py --query "SLA P1?"        # Chạy 1 câu
  python eval_trace.py --ab                     # A/B comparison traces
  python eval_trace.py --grading                # Trace grading questions

Author: Quality & Trace Analyst (M5)
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

# =============================================================================
# CẤU HÌNH
# =============================================================================

LAB_DIR = Path(__file__).parent
TEST_QUESTIONS_PATH = LAB_DIR / "data" / "test_questions.json"
GRADING_QUESTIONS_PATH = LAB_DIR / "data" / "grading.json"
TRACES_DIR = LAB_DIR / "logs" / "traces"

# Giới hạn preview text để trace không quá lớn
TEXT_PREVIEW_MAX = 200
PROMPT_PREVIEW_MAX = 500


# =============================================================================
# TRACE DATA STRUCTURES
# =============================================================================


def _now_iso() -> str:
    """Timestamp ISO format."""
    return datetime.now().isoformat()


def _generate_trace_id(query_id: str, mode: str) -> str:
    """Tạo trace ID unique."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"trace_{query_id}_{mode}_{ts}"


def _truncate(text: str, max_len: int) -> str:
    """Cắt text dài cho log gọn."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _estimate_tokens(text: str) -> int:
    """Ước lượng số tokens (1 token ~ 4 ký tự)."""
    return len(text) // 4 if text else 0


# =============================================================================
# CORE TRACE FUNCTION
# =============================================================================


def trace_single_query(
    query: str,
    query_id: str = "custom",
    retrieval_mode: str = "dense",
    top_k_search: int = 10,
    top_k_select: int = 3,
    use_rerank: bool = False,
    expected_answer: str = "",
    expected_sources: Optional[List[str]] = None,
    difficulty: str = "unknown",
    category: str = "unknown",
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Chạy 1 query qua RAG pipeline và ghi trace chi tiết.

    Returns:
        Dict trace hoàn chỉnh với tất cả thông tin debug.
    """
    from rag_answer import rag_answer, build_context_block, build_grounded_prompt

    if expected_sources is None:
        expected_sources = []

    trace = {
        "trace_id": _generate_trace_id(query_id, retrieval_mode),
        "timestamp": _now_iso(),
        "input": {
            "query": query,
            "query_id": query_id,
        },
        "config": {
            "retrieval_mode": retrieval_mode,
            "top_k_search": top_k_search,
            "top_k_select": top_k_select,
            "use_rerank": use_rerank,
            "llm_model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
            "embedding_model": "text-embedding-3-small",
            "temperature": 0,
        },
        "retrieval": {
            "candidates_count": 0,
            "selected_count": 0,
            "chunks": [],
        },
        "generation": {
            "prompt_preview": "",
            "prompt_tokens_est": 0,
            "answer": "",
            "sources_cited": [],
        },
        "evaluation": {
            "faithfulness": None,
            "relevance": None,
            "context_recall": None,
            "completeness": None,
            "overall_pass": None,
            "failure_mode": None,
        },
        "latency": {
            "retrieval_ms": 0,
            "generation_ms": 0,
            "scoring_ms": 0,
            "total_ms": 0,
        },
        "expected": {
            "answer": expected_answer,
            "sources": expected_sources,
            "difficulty": difficulty,
            "category": category,
        },
    }

    total_start = time.time()

    # ─── STEP 1: RETRIEVAL ───
    if verbose:
        print(f"\n{'─'*60}")
        print(f"🔍 [{query_id}] {query}")
        print(f"   Config: mode={retrieval_mode}, top_k={top_k_search}→{top_k_select}")

    retrieval_start = time.time()

    try:
        # Gọi pipeline
        result = rag_answer(
            query=query,
            retrieval_mode=retrieval_mode,
            top_k_search=top_k_search,
            top_k_select=top_k_select,
            use_rerank=use_rerank,
            verbose=False,
        )

        retrieval_end = time.time()
        retrieval_ms = (retrieval_end - retrieval_start) * 1000

        answer = result["answer"]
        chunks_used = result["chunks_used"]
        sources = result["sources"]

        # ─── TRACE: Retrieval Details ───
        trace["retrieval"]["candidates_count"] = top_k_search
        trace["retrieval"]["selected_count"] = len(chunks_used)

        for rank, chunk in enumerate(chunks_used, 1):
            meta = chunk.get("metadata", {})
            chunk_trace = {
                "rank": rank,
                "score": round(chunk.get("score", 0), 4),
                "text_preview": _truncate(chunk.get("text", ""), TEXT_PREVIEW_MAX),
                "text_length": len(chunk.get("text", "")),
                "metadata": {
                    "source": meta.get("source", "unknown"),
                    "section": meta.get("section", ""),
                    "department": meta.get("department", "unknown"),
                    "effective_date": meta.get("effective_date", "unknown"),
                    "access": meta.get("access", "internal"),
                },
            }
            trace["retrieval"]["chunks"].append(chunk_trace)

        # ─── TRACE: Generation Details ───
        # Rebuild prompt để trace (vì rag_answer() không return prompt)
        context_block = build_context_block(chunks_used)
        prompt = build_grounded_prompt(query, context_block)

        generation_start = time.time()
        # Generation đã xảy ra trong rag_answer(), ước tính thời gian
        generation_ms = retrieval_ms * 0.2  # rough estimate
        actual_gen_ms = (time.time() - retrieval_start) * 1000 - retrieval_ms

        trace["generation"]["prompt_preview"] = _truncate(prompt, PROMPT_PREVIEW_MAX)
        trace["generation"]["prompt_tokens_est"] = _estimate_tokens(prompt)
        trace["generation"]["answer"] = answer
        trace["generation"]["sources_cited"] = sources

        trace["latency"]["retrieval_ms"] = round(retrieval_ms, 1)
        trace["latency"]["generation_ms"] = round(
            max(actual_gen_ms, retrieval_ms), 1
        )

        if verbose:
            print(f"   📄 Retrieved: {len(chunks_used)} chunks")
            for i, c in enumerate(chunks_used):
                src = c.get("metadata", {}).get("source", "?")
                sec = c.get("metadata", {}).get("section", "?")
                score = c.get("score", 0)
                print(f"      [{i+1}] score={score:.4f} | {src} | {sec}")
            print(f"   💬 Answer: {_truncate(answer, 120)}")

    except Exception as e:
        retrieval_ms = (time.time() - retrieval_start) * 1000
        trace["generation"]["answer"] = f"PIPELINE_ERROR: {str(e)}"
        trace["evaluation"]["failure_mode"] = "pipeline_error"
        trace["latency"]["retrieval_ms"] = round(retrieval_ms, 1)

        if verbose:
            print(f"   ❌ Error: {e}")

        answer = ""
        chunks_used = []
        sources = []

    # ─── STEP 2: SCORING ───
    scoring_start = time.time()

    try:
        from eval import (
            score_faithfulness,
            score_answer_relevance,
            score_context_recall,
            score_completeness,
        )

        if answer and "PIPELINE_ERROR" not in answer:
            faith = score_faithfulness(answer, chunks_used)
            relev = score_answer_relevance(query, answer)
            recall = score_context_recall(chunks_used, expected_sources)
            compl = score_completeness(query, answer, expected_answer)

            trace["evaluation"]["faithfulness"] = faith
            trace["evaluation"]["relevance"] = relev
            trace["evaluation"]["context_recall"] = recall
            trace["evaluation"]["completeness"] = compl

            # Determine overall pass/fail
            scores = [
                faith.get("score"),
                relev.get("score"),
                recall.get("score"),
                compl.get("score"),
            ]
            valid_scores = [s for s in scores if s is not None]
            avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0
            trace["evaluation"]["overall_pass"] = avg_score >= 3.5

            # Classify failure mode
            trace["evaluation"]["failure_mode"] = _classify_failure_mode(
                answer, chunks_used, faith, relev, recall, compl, expected_answer
            )

            if verbose:
                print(
                    f"   📊 F={faith.get('score','?')} | R={relev.get('score','?')} "
                    f"| Rc={recall.get('score','?')} | C={compl.get('score','?')}"
                )
                fm = trace["evaluation"]["failure_mode"]
                if fm:
                    print(f"   ⚠️  Failure mode: {fm}")

    except Exception as e:
        if verbose:
            print(f"   ⚠️  Scoring error: {e}")

    scoring_ms = (time.time() - scoring_start) * 1000
    total_ms = (time.time() - total_start) * 1000

    trace["latency"]["scoring_ms"] = round(scoring_ms, 1)
    trace["latency"]["total_ms"] = round(total_ms, 1)

    if verbose:
        print(f"   ⏱️  Latency: {total_ms:.0f}ms total")

    return trace


# =============================================================================
# FAILURE MODE CLASSIFICATION
# =============================================================================


def _classify_failure_mode(
    answer: str,
    chunks_used: List[Dict],
    faith: Dict,
    relev: Dict,
    recall: Dict,
    compl: Dict,
    expected_answer: str,
) -> Optional[str]:
    """
    Phân loại failure mode dựa trên scores.

    Failure modes:
      - "false_abstain": Model abstain khi không nên
      - "hallucination": Model bịa thông tin
      - "incomplete": Thiếu thông tin quan trọng
      - "irrelevant": Trả lời lạc đề
      - "retrieval_miss": Không retrieve đúng source
      - None: Không có lỗi đáng kể
    """
    is_abstain = "không đủ dữ liệu" in answer.lower() if answer else False
    faith_score = faith.get("score") if faith else None
    recall_score = recall.get("score") if recall else None
    compl_score = compl.get("score") if compl else None
    relev_score = relev.get("score") if relev else None

    # Case 1: False abstain — abstain nhưng context recall cao
    if is_abstain and recall_score and recall_score >= 4:
        if expected_answer and "không" not in expected_answer.lower()[:30]:
            return "false_abstain"

    # Case 2: Retrieval miss — expected source không được retrieve
    if recall_score is not None and recall_score <= 2:
        return "retrieval_miss"

    # Case 3: Hallucination — faithfulness thấp
    if faith_score and faith_score <= 2 and not is_abstain:
        return "hallucination"

    # Case 4: Irrelevant — relevance thấp
    if relev_score and relev_score <= 2:
        return "irrelevant"

    # Case 5: Incomplete — completeness thấp
    if compl_score and compl_score <= 2:
        return "incomplete"

    return None


# =============================================================================
# BATCH TEST RUNNER
# =============================================================================


def run_batch_trace(
    retrieval_mode: str = "dense",
    test_questions_path: Optional[Path] = None,
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """
    Chạy batch test và tạo traces cho tất cả câu hỏi.

    Returns:
        List of trace dicts
    """
    if test_questions_path is None:
        test_questions_path = TEST_QUESTIONS_PATH

    with open(test_questions_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    print(f"\n{'='*60}")
    print(f"📋 BATCH TRACE: {len(questions)} questions")
    print(f"⚙️  Mode: {retrieval_mode}")
    print(f"{'='*60}")

    traces = []
    for q in questions:
        trace = trace_single_query(
            query=q["question"],
            query_id=q.get("id", "unknown"),
            retrieval_mode=retrieval_mode,
            expected_answer=q.get("expected_answer", ""),
            expected_sources=q.get("expected_sources", []),
            difficulty=q.get("difficulty", "unknown"),
            category=q.get("category", "unknown"),
            verbose=verbose,
        )
        traces.append(trace)

    # Save traces
    _save_traces(traces, f"batch_{retrieval_mode}")

    # Print summary
    _print_batch_summary(traces, retrieval_mode)

    return traces


def run_ab_trace(verbose: bool = True) -> Dict[str, List[Dict]]:
    """
    Chạy A/B comparison traces: baseline (dense) vs variant (hybrid).

    Returns:
        Dict với keys "baseline" và "variant", mỗi key là list traces.
    """
    print(f"\n{'='*60}")
    print("🔬 A/B TRACE COMPARISON: dense vs hybrid")
    print(f"{'='*60}")

    baseline_traces = run_batch_trace("dense", verbose=verbose)
    variant_traces = run_batch_trace("hybrid", verbose=verbose)

    # Print A/B comparison
    _print_ab_comparison(baseline_traces, variant_traces)

    return {"baseline": baseline_traces, "variant": variant_traces}


def run_grading_trace(verbose: bool = True) -> List[Dict[str, Any]]:
    """
    Chạy trace cho grading questions.
    """
    if not GRADING_QUESTIONS_PATH.exists():
        print(f"❌ Chưa có file: {GRADING_QUESTIONS_PATH}")
        print("   File grading_questions sẽ được cung cấp riêng.")
        return []

    return run_batch_trace(
        retrieval_mode="hybrid",  # Dùng config tốt nhất
        test_questions_path=GRADING_QUESTIONS_PATH,
        verbose=verbose,
    )


# =============================================================================
# OUTPUT: SAVE & REPORT
# =============================================================================


def _save_traces(traces: List[Dict], label: str) -> Path:
    """Lưu traces ra JSON file."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"traces_{label}_{ts}.json"
    filepath = TRACES_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(traces, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Traces saved to: {filepath}")
    return filepath


def _print_batch_summary(traces: List[Dict], label: str) -> None:
    """In bảng summary cho batch traces."""
    print(f"\n{'='*70}")
    print(f"📊 SUMMARY: {label} ({len(traces)} queries)")
    print(f"{'='*70}")

    # Header
    print(
        f"{'ID':<6} {'Category':<18} {'F':>3} {'R':>3} {'Rc':>3} {'C':>3} "
        f"{'Pass':>5} {'Failure Mode':<18} {'ms':>6}"
    )
    print("─" * 70)

    # Per-question rows
    total_pass = 0
    metric_sums = {"f": 0, "r": 0, "rc": 0, "c": 0}
    metric_counts = {"f": 0, "r": 0, "rc": 0, "c": 0}

    for t in traces:
        qid = t["input"]["query_id"]
        cat = t["expected"].get("category", "?")[:16]
        ev = t["evaluation"]

        f_score = ev.get("faithfulness", {}).get("score", "?") if ev.get("faithfulness") else "?"
        r_score = ev.get("relevance", {}).get("score", "?") if ev.get("relevance") else "?"
        rc_score = ev.get("context_recall", {}).get("score", "?") if ev.get("context_recall") else "?"
        c_score = ev.get("completeness", {}).get("score", "?") if ev.get("completeness") else "?"

        passed = "✅" if ev.get("overall_pass") else "❌"
        if ev.get("overall_pass"):
            total_pass += 1

        fm = ev.get("failure_mode", "") or ""
        latency = t["latency"].get("total_ms", 0)

        print(
            f"{qid:<6} {cat:<18} {str(f_score):>3} {str(r_score):>3} "
            f"{str(rc_score):>3} {str(c_score):>3} {passed:>5} "
            f"{fm:<18} {latency:>5.0f}ms"
        )

        # Accumulate for averages
        for key, val in [("f", f_score), ("r", r_score), ("rc", rc_score), ("c", c_score)]:
            if isinstance(val, (int, float)):
                metric_sums[key] += val
                metric_counts[key] += 1

    # Averages
    print("─" * 70)
    f_avg = metric_sums["f"] / metric_counts["f"] if metric_counts["f"] else 0
    r_avg = metric_sums["r"] / metric_counts["r"] if metric_counts["r"] else 0
    rc_avg = metric_sums["rc"] / metric_counts["rc"] if metric_counts["rc"] else 0
    c_avg = metric_sums["c"] / metric_counts["c"] if metric_counts["c"] else 0

    print(
        f"{'AVG':<6} {'':18} {f_avg:>3.1f} {r_avg:>3.1f} "
        f"{rc_avg:>3.1f} {c_avg:>3.1f} "
        f"{total_pass}/{len(traces)}"
    )

    # Failure mode distribution
    failure_modes = [t["evaluation"].get("failure_mode") for t in traces]
    failure_modes = [fm for fm in failure_modes if fm]
    if failure_modes:
        print(f"\n⚠️  Failure modes detected:")
        from collections import Counter
        for fm, count in Counter(failure_modes).most_common():
            print(f"   • {fm}: {count} queries")

    # Latency stats
    latencies = [t["latency"].get("total_ms", 0) for t in traces]
    if latencies:
        print(f"\n⏱️  Latency: avg={sum(latencies)/len(latencies):.0f}ms, "
              f"min={min(latencies):.0f}ms, max={max(latencies):.0f}ms")

    # Generate markdown summary
    _save_markdown_summary(traces, label)


def _print_ab_comparison(
    baseline_traces: List[Dict], variant_traces: List[Dict]
) -> None:
    """In A/B comparison table."""
    print(f"\n{'='*70}")
    print("🔬 A/B COMPARISON: Baseline (dense) vs Variant (hybrid)")
    print(f"{'='*70}")

    metrics = ["faithfulness", "relevance", "context_recall", "completeness"]

    def _avg_metric(traces, metric):
        scores = []
        for t in traces:
            ev = t.get("evaluation", {})
            m = ev.get(metric, {})
            if isinstance(m, dict) and m.get("score") is not None:
                scores.append(m["score"])
        return sum(scores) / len(scores) if scores else None

    print(f"{'Metric':<20} {'Baseline':>10} {'Variant':>10} {'Delta':>8}")
    print("─" * 55)

    for metric in metrics:
        b_avg = _avg_metric(baseline_traces, metric)
        v_avg = _avg_metric(variant_traces, metric)
        delta = (v_avg - b_avg) if (b_avg is not None and v_avg is not None) else None

        b_str = f"{b_avg:.2f}" if b_avg is not None else "N/A"
        v_str = f"{v_avg:.2f}" if v_avg is not None else "N/A"
        d_str = f"{delta:+.2f}" if delta is not None else "N/A"
        indicator = " 🔻" if (delta and delta < 0) else (" 🔺" if (delta and delta > 0) else "")

        print(f"{metric:<20} {b_str:>10} {v_str:>10} {d_str:>8}{indicator}")

    # Per-question comparison
    print(f"\n{'ID':<6} {'Baseline F/R/Rc/C':<22} {'Variant F/R/Rc/C':<22} {'Winner':<10}")
    print("─" * 65)

    b_by_id = {t["input"]["query_id"]: t for t in baseline_traces}

    for vt in variant_traces:
        qid = vt["input"]["query_id"]
        bt = b_by_id.get(qid)
        if not bt:
            continue

        def _scores_str(t):
            ev = t.get("evaluation", {})
            parts = []
            for m in metrics:
                s = ev.get(m, {}).get("score", "?") if isinstance(ev.get(m), dict) else "?"
                parts.append(str(s))
            return "/".join(parts)

        def _total(t):
            ev = t.get("evaluation", {})
            total = 0
            for m in metrics:
                s = ev.get(m, {}).get("score", 0) if isinstance(ev.get(m), dict) else 0
                total += (s or 0)
            return total

        b_str = _scores_str(bt)
        v_str = _scores_str(vt)
        b_total = _total(bt)
        v_total = _total(vt)
        winner = "Variant" if v_total > b_total else ("Baseline" if b_total > v_total else "Tie")

        print(f"{qid:<6} {b_str:<22} {v_str:<22} {winner:<10}")


def _save_markdown_summary(traces: List[Dict], label: str) -> None:
    """Tạo markdown summary report."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = TRACES_DIR / f"summary_{label}_{ts}.md"

    metrics = ["faithfulness", "relevance", "context_recall", "completeness"]

    md = f"# Trace Summary: {label}\n"
    md += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

    # Averages table
    md += "## Average Scores\n\n"
    md += "| Metric | Average |\n|--------|--------|\n"
    for metric in metrics:
        scores = []
        for t in traces:
            ev = t.get("evaluation", {})
            m = ev.get(metric, {})
            if isinstance(m, dict) and m.get("score") is not None:
                scores.append(m["score"])
        avg = sum(scores) / len(scores) if scores else None
        avg_str = f"{avg:.2f}/5" if avg else "N/A"
        md += f"| {metric.replace('_', ' ').title()} | {avg_str} |\n"

    # Per-question table
    md += "\n## Per-Question Results\n\n"
    md += "| ID | Category | F | R | Rc | C | Failure Mode | Latency |\n"
    md += "|----|----------|---|---|----|----|-------------|--------|\n"

    for t in traces:
        qid = t["input"]["query_id"]
        cat = t["expected"].get("category", "?")
        ev = t["evaluation"]

        f_s = ev.get("faithfulness", {}).get("score", "?") if isinstance(ev.get("faithfulness"), dict) else "?"
        r_s = ev.get("relevance", {}).get("score", "?") if isinstance(ev.get("relevance"), dict) else "?"
        rc_s = ev.get("context_recall", {}).get("score", "?") if isinstance(ev.get("context_recall"), dict) else "?"
        c_s = ev.get("completeness", {}).get("score", "?") if isinstance(ev.get("completeness"), dict) else "?"
        fm = ev.get("failure_mode", "") or ""
        lat = t["latency"].get("total_ms", 0)

        md += f"| {qid} | {cat} | {f_s} | {r_s} | {rc_s} | {c_s} | {fm} | {lat:.0f}ms |\n"

    # Failure analysis
    failure_modes = [t["evaluation"].get("failure_mode") for t in traces if t["evaluation"].get("failure_mode")]
    if failure_modes:
        md += "\n## Failure Analysis\n\n"
        from collections import Counter
        for fm, count in Counter(failure_modes).most_common():
            md += f"- **{fm}**: {count} query(s)\n"
            for t in traces:
                if t["evaluation"].get("failure_mode") == fm:
                    md += f"  - `{t['input']['query_id']}`: {t['input']['query'][:60]}...\n"

    filepath.write_text(md, encoding="utf-8")
    print(f"📝 Summary saved to: {filepath}")


# =============================================================================
# CONVENIENCE: Quick single query trace (for debugging)
# =============================================================================


def quick_trace(query: str, mode: str = "dense") -> Dict:
    """
    Quick trace cho 1 query — dùng khi debug nhanh.

    Usage:
        from eval_trace import quick_trace
        t = quick_trace("SLA P1 là bao lâu?")
        print(t["generation"]["answer"])
        print(t["retrieval"]["chunks"])
    """
    return trace_single_query(
        query=query,
        query_id="debug",
        retrieval_mode=mode,
        verbose=True,
    )


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="RAG Pipeline — Eval Trace (M5)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python eval_trace.py                          # Batch test (dense)
  python eval_trace.py --mode hybrid            # Batch test (hybrid)
  python eval_trace.py --query "SLA P1?"        # Single query
  python eval_trace.py --ab                     # A/B comparison
  python eval_trace.py --grading                # Grading questions
        """,
    )

    parser.add_argument(
        "--query", type=str, help="Chạy trace cho 1 query cụ thể"
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="dense",
        choices=["dense", "sparse", "hybrid"],
        help="Retrieval mode (default: dense)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        default=True,
        help="Chạy batch test với test_questions.json (default)",
    )
    parser.add_argument(
        "--ab", action="store_true", help="Chạy A/B comparison (dense vs hybrid)"
    )
    parser.add_argument(
        "--grading",
        action="store_true",
        help="Chạy trace cho grading questions",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Không in chi tiết từng query"
    )

    args = parser.parse_args()
    verbose = not args.quiet

    print("=" * 60)
    print("🔬 RAG Pipeline — Eval Trace System (M5)")
    print("=" * 60)

    if args.query:
        # Single query mode
        trace = trace_single_query(
            query=args.query,
            retrieval_mode=args.mode,
            verbose=verbose,
        )
        # Save single trace
        _save_traces([trace], f"single_{args.mode}")

    elif args.ab:
        # A/B comparison
        run_ab_trace(verbose=verbose)

    elif args.grading:
        # Grading questions
        run_grading_trace(verbose=verbose)

    else:
        # Default: batch test
        run_batch_trace(retrieval_mode=args.mode, verbose=verbose)

    print(f"\n{'='*60}")
    print("✅ Eval trace complete!")
    print(f"📁 Traces stored in: {TRACES_DIR}")
    print(f"{'='*60}")
