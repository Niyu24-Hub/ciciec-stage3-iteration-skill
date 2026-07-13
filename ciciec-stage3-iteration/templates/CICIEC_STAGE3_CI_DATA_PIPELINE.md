# CICIEC Stage 3 CI Data Pipeline

## Purpose

Keep GitLab CI facts, online-judge results, and curated project decisions in
separate files so generated evidence can be refreshed without overwriting human
interpretation.

## Generated Data

- `ci_data/ciciec_stage3_ci_runs.jsonl`: GitLab pipeline/job evidence.
- `ci_data/ciciec_stage3_ci_latest.md`: latest CI summary.
- `ci_data/ciciec_stage3_eval_results.jsonl`: online-judge results.
- `ci_data/ciciec_stage3_strategy_summaries.jsonl`: optional implementation notes.
- `ci_data/ciciec_stage3_score_winner_tree.json`: machine-readable winner tree.
- `ci_data/ciciec_stage3_score_winner_tree.md`: human-readable winner tree.

## Rules

- Treat JSONL, generated JSON, and generated Markdown as tool-owned outputs.
- Keep credentials in environment variables only.
- Update project memory only when evidence changes future decisions.
- Re-read generated data before relying on a previously recorded score.
