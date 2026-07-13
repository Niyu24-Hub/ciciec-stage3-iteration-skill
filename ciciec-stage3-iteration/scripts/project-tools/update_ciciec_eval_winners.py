#!/usr/bin/env python3
"""Update CICIEC Stage 3 score winner data and best-code backup.

The script keeps evaluator scores separate from GitLab CI facts, then builds a
deterministic winner tree from rows that have both a finished score and
successful CI evidence. If requested, it downloads a GitLab repository archive
for the current highest-scoring commit using GITLAB_TOKEN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


DEFAULT_BASE = os.environ.get("CICIEC_GITLAB_API_URL", "")
DEFAULT_PROJECT = os.environ.get("CICIEC_GITLAB_PROJECT_ID", "")
DEFAULT_EVAL_JSONL = "ci_data/ciciec_stage3_eval_results.jsonl"
DEFAULT_STRATEGY_JSONL = "ci_data/ciciec_stage3_strategy_summaries.jsonl"
DEFAULT_CI_JSONL = "ci_data/ciciec_stage3_ci_runs.jsonl"
DEFAULT_CI_LEDGER = "CICIEC_STAGE3_CI_RESULTS.md"
DEFAULT_TREE_JSON = "ci_data/ciciec_stage3_score_winner_tree.json"
DEFAULT_TREE_MD = "ci_data/ciciec_stage3_score_winner_tree.md"
DEFAULT_BACKUP_DIR = "ci_data/code_backups"
SCHEMA_VERSION = 1
CN_TZ = timezone(timedelta(hours=8))
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def now_cn() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S %z")


def normalize_sha(value: Any) -> str:
    return str(value or "").strip().lower()


def parse_score(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def request_bytes(url: str, token: str, attempts: int = 4) -> tuple[int, bytes]:
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code in RETRYABLE_HTTP_STATUS and attempt < attempts:
                time.sleep(min(30, 2**attempt))
                continue
            return exc.code, body
        except urllib.error.URLError as exc:
            if attempt < attempts:
                time.sleep(min(30, 2**attempt))
                continue
            raise RuntimeError(f"request failed for {url}: {exc}") from exc
    raise RuntimeError(f"request failed for {url}")


def api_url(base: str, path: str, query: dict[str, str] | None = None) -> str:
    url = base.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda item: (str(item.get("submitted_at") or ""), int(item.get("task_id") or 0)))
    with path.open("w", encoding="utf-8") as fh:
        for row in ordered:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def upsert_eval_result(path: Path, args: argparse.Namespace) -> None:
    if args.task_id is None:
        return
    if not args.submitted_at or not args.version or not args.status or args.score is None:
        raise SystemExit("--task-id requires --submitted-at, --version, --status, and --score")

    rows = load_jsonl(path)
    record = {
        "schema_version": SCHEMA_VERSION,
        "task_id": int(args.task_id),
        "submitted_at": args.submitted_at,
        "version": args.version,
        "status": args.status,
        "score": float(args.score),
        "source": args.source,
    }
    replaced = False
    for idx, row in enumerate(rows):
        if int(row.get("task_id", -1)) == int(args.task_id):
            rows[idx] = record
            replaced = True
            break
    if not replaced:
        rows.append(record)
    write_jsonl(path, rows)


def add_success_evidence(target: dict[str, dict[str, Any]], key: str, evidence: dict[str, Any]) -> None:
    norm = normalize_sha(key)
    if not norm:
        return
    old = target.get(norm)
    if old and old.get("source_priority", 0) >= evidence.get("source_priority", 0):
        return
    target[norm] = evidence


def load_strategy_summaries(path: Path) -> list[dict[str, Any]]:
    rows = load_jsonl(path)
    return sorted(rows, key=lambda item: str(item.get("version") or ""))


def index_strategy_summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in (row.get("version"), row.get("full_sha")):
            norm = normalize_sha(key)
            if norm:
                indexed[norm] = row
    return indexed


def find_strategy(version: str, indexed: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    version_norm = normalize_sha(version)
    if not version_norm:
        return None
    if version_norm in indexed:
        return indexed[version_norm]
    for key, value in indexed.items():
        if key.startswith(version_norm) or version_norm.startswith(key):
            return value
    return None


def clean_strategy(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary:
        return None
    return {k: v for k, v in summary.items() if k != "schema_version"}


def load_ci_success_evidence(ci_jsonl: Path, ci_ledger: Path) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}

    for row in load_jsonl(ci_jsonl):
        if row.get("pipeline_status") != "success" or row.get("job_status") != "success":
            continue
        failure = row.get("failure") or {}
        if failure.get("class") not in {None, "", "none"}:
            continue
        item = {
            "source": "ci_jsonl",
            "source_priority": 100,
            "sha": row.get("sha"),
            "short_sha": row.get("short_sha"),
            "pipeline_id": row.get("pipeline_id"),
            "job_id": row.get("job_id"),
            "pipeline_status": row.get("pipeline_status"),
            "job_status": row.get("job_status"),
            "pipeline_created_at_cn": row.get("pipeline_created_at_cn"),
            "pipeline_web_url": row.get("pipeline_web_url"),
            "commit_title": row.get("commit_title"),
            "artifact_metrics": row.get("artifact_metrics") or {},
        }
        add_success_evidence(evidence, row.get("sha", ""), item)
        add_success_evidence(evidence, row.get("short_sha", ""), item)

    if ci_ledger.exists():
        for line in ci_ledger.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|") or "`" not in line:
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 9 or cells[4] != "success":
                continue
            commit_match = re.search(r"`([0-9a-fA-F]+)`", cells[2])
            if not commit_match:
                continue
            ids = re.findall(r"`([^`]+)`", cells[3])
            item = {
                "source": "ci_results_ledger",
                "source_priority": 50,
                "sha": None,
                "short_sha": commit_match.group(1),
                "pipeline_id": ids[0] if ids else "",
                "job_id": ids[1] if len(ids) > 1 else "",
                "pipeline_status": "success",
                "job_status": "success",
                "pipeline_created_at_cn": cells[0],
                "pipeline_web_url": "",
                "commit_title": re.sub(r"`[0-9a-fA-F]+`", "", cells[2]).strip(),
                "artifact_metrics": {},
            }
            add_success_evidence(evidence, commit_match.group(1), item)

    return evidence


def find_ci_evidence(version: str, evidence: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    version_norm = normalize_sha(version)
    if not version_norm:
        return None
    if version_norm in evidence:
        return evidence[version_norm]
    candidates = []
    for key, value in evidence.items():
        if key.startswith(version_norm) or version_norm.startswith(key):
            candidates.append(value)
    if not candidates:
        return None
    return max(candidates, key=lambda item: int(item.get("source_priority", 0)))


def candidate_key(item: dict[str, Any]) -> tuple[float, str, int]:
    return (float(item.get("score") or 0.0), str(item.get("submitted_at") or ""), -int(item.get("task_id") or 0))


def winner_between(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if float(right["score"]) > float(left["score"]):
        return right
    if float(right["score"]) < float(left["score"]):
        return left
    if str(right.get("submitted_at", "")) < str(left.get("submitted_at", "")):
        return right
    if str(right.get("submitted_at", "")) > str(left.get("submitted_at", "")):
        return left
    return right if int(right["task_id"]) < int(left["task_id"]) else left


def build_winner_tree(
    eval_rows: list[dict[str, Any]],
    ci_evidence: dict[str, dict[str, Any]],
    strategy_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    eligible: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []
    strategy_index = index_strategy_summaries(strategy_rows)
    evaluated_versions: set[str] = set()

    for row in sorted(eval_rows, key=lambda item: (str(item.get("submitted_at") or ""), int(item.get("task_id") or 0))):
        status = str(row.get("status") or "")
        score = row.get("score")
        version = str(row.get("version") or "")
        evaluated_versions.add(normalize_sha(version))
        evidence = find_ci_evidence(version, ci_evidence)
        strategy = clean_strategy(find_strategy(version, strategy_index))
        base = {
            "task_id": row.get("task_id"),
            "submitted_at": row.get("submitted_at"),
            "version": version,
            "status": status,
            "score": score,
            "source": row.get("source"),
        }
        if strategy:
            base["strategy"] = strategy
        if status != "Finished":
            base["reason"] = "evaluation_not_finished"
            ineligible.append(base)
            continue
        if score is None:
            base["reason"] = "score_missing"
            ineligible.append(base)
            continue
        if not evidence:
            base["reason"] = "success_ci_evidence_missing"
            ineligible.append(base)
            continue
        base["ci"] = {k: v for k, v in evidence.items() if k != "source_priority"}
        eligible.append(base)

    matches: list[dict[str, Any]] = []
    incumbent: dict[str, Any] | None = None
    for entrant in eligible:
        if incumbent is None:
            incumbent = entrant
            matches.append(
                {
                    "round": len(matches) + 1,
                    "incumbent_task_id": None,
                    "challenger_task_id": entrant["task_id"],
                    "winner_task_id": entrant["task_id"],
                    "winner_version": entrant["version"],
                    "reason": "first eligible result",
                }
            )
            continue
        winner = winner_between(incumbent, entrant)
        loser = entrant if winner is incumbent else incumbent
        reason = "higher score"
        if float(winner["score"]) == float(loser["score"]):
            reason = "score tie; earlier submission wins"
        matches.append(
            {
                "round": len(matches) + 1,
                "incumbent_task_id": incumbent["task_id"],
                "incumbent_score": incumbent["score"],
                "challenger_task_id": entrant["task_id"],
                "challenger_score": entrant["score"],
                "winner_task_id": winner["task_id"],
                "winner_version": winner["version"],
                "reason": reason,
            }
        )
        incumbent = winner

    leaderboard = sorted(eligible, key=candidate_key, reverse=True)
    unscored_strategy_candidates: list[dict[str, Any]] = []
    for summary in strategy_rows:
        version = str(summary.get("version") or "")
        full_sha = str(summary.get("full_sha") or "")
        strategy_keys = {normalize_sha(version), normalize_sha(full_sha)}
        has_score = False
        for strategy_key in {key for key in strategy_keys if key}:
            for evaluated_version in evaluated_versions:
                if evaluated_version.startswith(strategy_key) or strategy_key.startswith(evaluated_version):
                    has_score = True
                    break
            if has_score:
                break
        if has_score:
            continue
        ci = find_ci_evidence(version, ci_evidence) or find_ci_evidence(full_sha, ci_evidence)
        item = {"version": version, "strategy": clean_strategy(summary), "score": None}
        if ci:
            item["ci"] = {k: v for k, v in ci.items() if k != "source_priority"}
        item["reason"] = "score_missing"
        unscored_strategy_candidates.append(item)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_cn(),
        "policy": {
            "eligible": "Finished evaluator result with successful GitLab CI evidence",
            "winner": "highest score wins; score ties prefer earlier submission",
        },
        "current_winner": incumbent,
        "leaderboard": leaderboard,
        "winner_tree": matches,
        "ineligible_results": ineligible,
        "unscored_strategy_candidates": unscored_strategy_candidates,
    }


def md_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def join_items(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value)


def write_tree_outputs(tree: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(tree, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    winner = tree.get("current_winner") or {}
    lines = [
        "# CICIEC Stage 3 Score Winner Tree",
        "",
        f"Generated: {tree.get('generated_at')}",
        "",
        "This file is generated by `tools/update_ciciec_eval_winners.py`. It contains no access token.",
        "",
    ]
    if winner:
        ci = winner.get("ci") or {}
        strategy = winner.get("strategy") or {}
        lines.extend(
            [
                "## Current Winner",
                "",
                f"- Task: `{winner.get('task_id')}`",
                f"- Version: `{winner.get('version')}`",
                f"- Score: `{winner.get('score')}`",
                f"- CI: pipeline `{ci.get('pipeline_id')}`, job `{ci.get('job_id')}`, source `{ci.get('source')}`",
            ]
        )
        if strategy:
            lines.extend(
                [
                    f"- Idea: {strategy.get('implementation_idea')}",
                    f"- Strengths: {join_items(strategy.get('strengths'))}",
                    f"- Weaknesses: {join_items(strategy.get('weaknesses'))}",
                    f"- Next: {join_items(strategy.get('improvement_ideas'))}",
                ]
            )
        lines.append("")
    else:
        lines.extend(["## Current Winner", "", "No eligible scored CI result yet.", ""])

    lines.extend(
        [
            "## Leaderboard",
            "",
            "| Rank | Task | Submitted | Version | Score | CI Evidence | Idea |",
            "| ---: | ---: | --- | --- | ---: | --- | --- |",
        ]
    )
    for rank, item in enumerate(tree.get("leaderboard") or [], start=1):
        ci = item.get("ci") or {}
        strategy = item.get("strategy") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(rank),
                    md_cell(item.get("task_id")),
                    md_cell(item.get("submitted_at")),
                    md_cell(f"`{item.get('version')}`"),
                    md_cell(item.get("score")),
                    md_cell(f"{ci.get('source')} pipeline {ci.get('pipeline_id')} job {ci.get('job_id')}"),
                    md_cell(strategy.get("implementation_idea")),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Implementation Notes",
            "",
            "| Task | Version | Score | Strengths | Weaknesses | Improvement Ideas |",
            "| ---: | --- | ---: | --- | --- | --- |",
        ]
    )
    noted_items = list(tree.get("leaderboard") or []) + list(tree.get("ineligible_results") or [])
    for item in noted_items:
        strategy = item.get("strategy") or {}
        if not strategy:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(item.get("task_id")),
                    md_cell(f"`{item.get('version')}`"),
                    md_cell(item.get("score")),
                    md_cell(join_items(strategy.get("strengths"))),
                    md_cell(join_items(strategy.get("weaknesses"))),
                    md_cell(join_items(strategy.get("improvement_ideas"))),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Winner Tree",
            "",
            "| Round | Incumbent | Challenger | Winner | Reason |",
            "| ---: | --- | --- | --- | --- |",
        ]
    )
    for match in tree.get("winner_tree") or []:
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(match.get("round")),
                    md_cell(match.get("incumbent_task_id")),
                    md_cell(match.get("challenger_task_id")),
                    md_cell(f"{match.get('winner_task_id')} `{match.get('winner_version')}`"),
                    md_cell(match.get("reason")),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Excluded Results",
            "",
            "| Task | Submitted | Version | Score | Reason |",
            "| ---: | --- | --- | ---: | --- |",
        ]
    )
    for item in tree.get("ineligible_results") or []:
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(item.get("task_id")),
                    md_cell(item.get("submitted_at")),
                    md_cell(f"`{item.get('version')}`"),
                    md_cell(item.get("score")),
                    md_cell(item.get("reason")),
                ]
            )
            + " |"
        )

    candidates = tree.get("unscored_strategy_candidates") or []
    if candidates:
        lines.extend(
            [
                "",
                "## Unscored Strategy Candidates",
                "",
                "| Version | CI Evidence | Idea | Main Risk | Next Step |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in candidates:
            strategy = item.get("strategy") or {}
            ci = item.get("ci") or {}
            ci_text = ""
            if ci:
                ci_text = f"{ci.get('source')} pipeline {ci.get('pipeline_id')} job {ci.get('job_id')}"
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_cell(f"`{item.get('version')}`"),
                        md_cell(ci_text),
                        md_cell(strategy.get("implementation_idea")),
                        md_cell(join_items(strategy.get("weaknesses"))),
                        md_cell(join_items(strategy.get("improvement_ideas"))),
                    ]
                )
                + " |"
            )
    lines.append("")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_best_code(tree: dict[str, Any], base: str, project: str, backup_dir: Path) -> Path | None:
    winner = tree.get("current_winner")
    if not winner:
        return None
    ci = winner.get("ci") or {}
    sha = ci.get("sha") or winner.get("version")
    short_sha = normalize_sha(winner.get("version"))[:8]
    score_text = f"{float(winner['score']):.2f}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    archive_path = backup_dir / f"stage3_best_score_task{winner['task_id']}_{score_text}_{short_sha}.zip"
    manifest_path = backup_dir / "stage3_best_score_latest.json"

    if not archive_path.exists():
        token = os.environ.get("GITLAB_TOKEN")
        if not token:
            raise SystemExit("error: set GITLAB_TOKEN to download the best-scoring commit archive")
        url = api_url(base, f"/projects/{project}/repository/archive.zip", {"sha": str(sha)})
        status, body = request_bytes(url, token)
        if status < 200 or status >= 300:
            raise RuntimeError(f"HTTP {status} while downloading best-code archive for {sha}: {body[:200]!r}")
        archive_path.write_bytes(body)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_cn(),
        "backup_kind": "gitlab_repository_archive",
        "project_id": int(project),
        "source_api": f"{base.rstrip('/')}/projects/{project}/repository/archive.zip?sha=<winner_sha>",
        "winner": winner,
        "archive_path": str(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": sha256_file(archive_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--eval-jsonl", default=DEFAULT_EVAL_JSONL)
    parser.add_argument("--strategy-jsonl", default=DEFAULT_STRATEGY_JSONL)
    parser.add_argument("--ci-jsonl", default=DEFAULT_CI_JSONL)
    parser.add_argument("--ci-ledger", default=DEFAULT_CI_LEDGER)
    parser.add_argument("--tree-json", default=DEFAULT_TREE_JSON)
    parser.add_argument("--tree-md", default=DEFAULT_TREE_MD)
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--backup-best", action="store_true")
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--submitted-at")
    parser.add_argument("--version")
    parser.add_argument("--status")
    parser.add_argument("--score", type=parse_score)
    parser.add_argument("--source", default="manual")
    args = parser.parse_args()

    eval_path = Path(args.eval_jsonl)
    upsert_eval_result(eval_path, args)
    eval_rows = load_jsonl(eval_path)
    strategy_rows = load_strategy_summaries(Path(args.strategy_jsonl))
    ci_evidence = load_ci_success_evidence(Path(args.ci_jsonl), Path(args.ci_ledger))
    tree = build_winner_tree(eval_rows, ci_evidence, strategy_rows)
    write_tree_outputs(tree, Path(args.tree_json), Path(args.tree_md))

    winner = tree.get("current_winner") or {}
    if winner:
        print(f"winner task={winner.get('task_id')} version={winner.get('version')} score={winner.get('score')}")
    else:
        print("winner unavailable")

    if args.backup_best:
        if not args.base:
            raise SystemExit("error: set CICIEC_GITLAB_API_URL or pass --base for --backup-best")
        if not args.project:
            raise SystemExit("error: set CICIEC_GITLAB_PROJECT_ID or pass --project for --backup-best")
        archive = backup_best_code(tree, args.base, args.project, Path(args.backup_dir))
        if archive:
            print(f"best-code backup: {archive}")

    print(f"wrote {args.tree_json}")
    print(f"wrote {args.tree_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
