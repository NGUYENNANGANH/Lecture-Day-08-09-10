## Người 1 — Ingestion Owner
File chính: etl_pipeline.py (phần ingest), contracts/data_contract.yaml

Sprint 1: Đọc data/raw/policy_export_dirty.csv, map schema, viết log run_id / raw_records / cleaned_records / quarantine_records
Điền contracts/data_contract.yaml (owner, SLA, nguồn)
Điền docs/data_contract.md (source map ≥2 nguồn, failure mode, metric)
Đảm bảo python etl_pipeline.py run --run-id sprint1 chạy và log đúng
## Người 2 — Cleaning Owner
File chính: transform/cleaning_rules.py

Sprint 1–2: Hiểu baseline (allowlist doc_id, chuẩn hoá effective_date, quarantine HR cũ, fix refund 14→7, dedupe)
Viết thêm ≥3 rule mới có tác động đo được (ghi metric_impact trong group report)
Sprint 3: Phối hợp inject bằng --no-refund-fix để chứng minh rule hoạt động
Ghi bảng metric_impact trong reports/group_report.md
## Người 3 — Quality / Expectation Owner
File chính: quality/expectations.py

Sprint 2: Hiểu baseline expectations, thêm ≥2 expectation mới (phân biệt warn/halt)
Sprint 3: Chạy python etl_pipeline.py run --no-refund-fix --skip-validate, lưu 2 file eval để so sánh before/after
Hoàn thiện docs/quality_report_template.md → docs/quality_report.md (có run_id + interpret)
Chứng minh q_refund_window tệ hơn khi inject, tốt hơn sau fix
## Người 4 — Embed / Eval Owner
File chính: etl_pipeline.py (phần embed Chroma), eval_retrieval.py

Sprint 2: Đảm bảo embed idempotent (upsert chunk_id + prune id thừa), rerun 2 lần không phình
Sprint 2–3: Chạy python eval_retrieval.py, lưu artifacts/eval/before_after_eval.csv
Sprint 4: Chạy python grading_run.py --out artifacts/eval/grading_run.jsonl (3 câu gq_d10_01–gq_d10_03)
Kiểm tra embed_prune_removed trong log
## Người 5 — Monitoring / Docs Owner
File chính: monitoring/freshness_check.py, docs/pipeline_architecture.md, docs/runbook.md

Sprint 4: Chạy python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_<run-id>.json
Hoàn thiện docs/pipeline_architecture.md (sơ đồ + ranh giới ingest/clean/embed)
Hoàn thiện docs/runbook.md (5 mục: Symptom → Diagnosis → Mitigation → Fix → Prevention)
Tổng hợp reports/group_report.md, peer review 3 câu hỏi (slide Phần E)