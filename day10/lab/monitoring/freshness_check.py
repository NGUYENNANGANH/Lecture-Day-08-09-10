"""
Kiểm tra freshness từ manifest pipeline (SLA đơn giản theo giờ).

Mở rộng bởi Mai Phi Hiếu (M5 — Monitoring / Docs Owner):
  - Đo freshness **2 boundary**: ingest (latest_exported_at) + publish (run_timestamp).
  - Log chi tiết: PASS / WARN / FAIL kèm delay_hours cho từng boundary.
  - WARN nếu SLA vượt 75% nhưng chưa FAIL.
  - Hỗ trợ gọi từ CLI (etl_pipeline.py freshness) và tích hợp trong pipeline run.

Dùng cho điều kiện Distinction (b) trong SCORING.md:
  "freshness đo 2 boundary (ingest + publish) có log"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

# Logger riêng cho monitoring — ghi vào console + có thể mở rộng file handler.
logger = logging.getLogger("monitoring.freshness")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


def parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        # Cho phép "2026-04-10T08:00:00" không có timezone
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _evaluate_boundary(
    label: str,
    ts_str: str | None,
    now: datetime,
    sla_hours: float,
) -> Dict[str, Any]:
    """Đánh giá freshness cho **một** boundary (ingest hoặc publish).

    Returns:
        dict chứa status (PASS/WARN/FAIL), age_hours, sla_hours, label.
    """
    if not ts_str:
        return {
            "boundary": label,
            "status": "FAIL",
            "reason": f"missing_{label}_timestamp",
            "timestamp": None,
            "age_hours": None,
            "sla_hours": sla_hours,
        }

    dt = parse_iso(str(ts_str))
    if dt is None:
        return {
            "boundary": label,
            "status": "FAIL",
            "reason": f"unparseable_{label}_timestamp",
            "timestamp": ts_str,
            "age_hours": None,
            "sla_hours": sla_hours,
        }

    age_hours = (now - dt).total_seconds() / 3600.0
    warn_threshold = sla_hours * 0.75  # WARN khi vượt 75% SLA

    if age_hours <= warn_threshold:
        status = "PASS"
    elif age_hours <= sla_hours:
        status = "WARN"
    else:
        status = "FAIL"

    result: Dict[str, Any] = {
        "boundary": label,
        "status": status,
        "timestamp": ts_str,
        "age_hours": round(age_hours, 3),
        "sla_hours": sla_hours,
    }
    if status == "WARN":
        result["reason"] = f"{label}_approaching_sla (>{int(warn_threshold)}h)"
    elif status == "FAIL":
        result["reason"] = f"{label}_sla_exceeded"

    return result


def check_manifest_freshness(
    manifest_path: Path,
    *,
    sla_hours: float = 24.0,
    now: datetime | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Trả về ("PASS" | "WARN" | "FAIL", detail dict).

    **Dual-boundary freshness (Distinction b):**
      - ingest boundary : `latest_exported_at` — thời điểm data được export từ nguồn.
      - publish boundary: `run_timestamp`      — thời điểm pipeline hoàn tất publish lên index.

    Tổng hợp: status = worst-case giữa 2 boundary.
    """
    now = now or datetime.now(timezone.utc)

    if not manifest_path.is_file():
        logger.error("Manifest not found: %s", manifest_path)
        return "FAIL", {"reason": "manifest_missing", "path": str(manifest_path)}

    data: Dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_id = data.get("run_id", "unknown")

    # ── Boundary 1: ingest (dữ liệu nguồn) ──
    ingest_ts = data.get("latest_exported_at") or None
    ingest_result = _evaluate_boundary("ingest", ingest_ts, now, sla_hours)

    # ── Boundary 2: publish (pipeline hoàn tất) ──
    publish_ts = data.get("run_timestamp") or None
    publish_result = _evaluate_boundary("publish", publish_ts, now, sla_hours)

    # ── Tổng hợp: worst-case ──
    priority = {"FAIL": 2, "WARN": 1, "PASS": 0}
    overall_status = max(
        ingest_result["status"],
        publish_result["status"],
        key=lambda s: priority[s],
    )

    # Tính delay giữa ingest → publish (thời gian pipeline xử lý)
    processing_delay_hours = None
    if ingest_ts and publish_ts:
        dt_ingest = parse_iso(str(ingest_ts))
        dt_publish = parse_iso(str(publish_ts))
        if dt_ingest and dt_publish:
            processing_delay_hours = round(
                (dt_publish - dt_ingest).total_seconds() / 3600.0, 3
            )

    detail: Dict[str, Any] = {
        "run_id": run_id,
        "overall_status": overall_status,
        "ingest_boundary": ingest_result,
        "publish_boundary": publish_result,
        "processing_delay_hours": processing_delay_hours,
        "sla_hours": sla_hours,
    }

    # ── Logging rõ ràng ──
    logger.info(
        "freshness_check run_id=%s | overall=%s | "
        "ingest=%s (age=%.1fh) | publish=%s (age=%.1fh) | "
        "processing_delay=%.1fh | sla=%.1fh",
        run_id,
        overall_status,
        ingest_result["status"],
        ingest_result.get("age_hours") or -1,
        publish_result["status"],
        publish_result.get("age_hours") or -1,
        processing_delay_hours or -1,
        sla_hours,
    )

    # Backward-compatible: trả về cả flat fields cho code gọi cũ
    detail["latest_exported_at"] = ingest_ts
    detail["age_hours"] = ingest_result.get("age_hours")
    if overall_status == "FAIL":
        reasons = []
        if ingest_result["status"] == "FAIL":
            reasons.append(ingest_result.get("reason", "ingest_fail"))
        if publish_result["status"] == "FAIL":
            reasons.append(publish_result.get("reason", "publish_fail"))
        detail["reason"] = "; ".join(reasons) if reasons else "freshness_sla_exceeded"

    return overall_status, detail
